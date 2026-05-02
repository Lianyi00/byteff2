# ByteFF2 添加 B 元素：方案与实施记录

## 核心约束

ByteFF2 基于离散元素索引工作（`SUPPORTED_ELEMENTS` → `atom_embedding` + 元素查表），B 不在元素表里时含硼样本在数据编码阶段就会 `KeyError`，不能靠直接微调解决，必须先扩容。

---

## 代码修改

### 1. `byteff2/utils/definitions.py`

在 `SUPPORTED_ELEMENTS` 末尾追加 `5`（B 的原子序数）：

```python
SUPPORTED_ELEMENTS = [1, 6, 7, 8, 9, 15, 16, 17, 35, 53, 3, 5]
#                    H  C  N  O  F  P   S  Cl  Br   I  Li  B
```

**必须追加到末尾**：旧元素索引 0..10 保持不变，Li 仍是 index 10，B 新增为 index 11。

同时在 `V_FREE / ALPHA_FREE / C6_FREE / RVDW_FREE` 末尾追加 B 的值，注意与数组现有单位保持一致（`definitions.py` 内部会做单位换算，不要把已换算值重复追加）。

`ATOMIC_ENERGY` 是死代码，无需修改。

### 2. checkpoint 扩容

发生 `[11, x] → [12, x]` 维度变化的参数共 6 组：

| 参数键 | B 行初始化方式 |
|--------|----------------|
| `graph_block.feature_layer.atom_embedding.weight` | C/N/O 三行均值 |
| `preff_block.pre_layers.PreExp6Pol.v_free.weight` | `definitions.py` 中 B 的 `V_FREE` 初值 |
| `preff_block.pre_layers.PreExp6Pol.c6_free.weight` | 同上 |
| `preff_block.pre_layers.PreExp6Pol.rvdw_free.weight` | 同上 |
| `preff_block.pre_layers.PreExp6Pol.alpha_free.weight` | 同上 |
| `ff_block.ff_layers.Exp6Pol.nuclear_charge.weight` | 原子序数 `5` |

不能依赖 trainer 的 `strict=False` 默认加载——shape 不匹配的参数会被整块跳过，不会做"旧行复制 + 新行初始化"。扩容脚本：`scripts/expand_checkpoint_add_boron.py`。

输出：`byteff2/trained_models/optimal_with_b_init.pt`

### 3. Li 硬编码索引（`mm_tspol.py` 第 422、441 行）

当前写的是 `== 10`，B 追加到末尾后 Li 仍是 10，暂时不会出错。后续再加元素时建议改为 `== ELEMENT_MAP[3]`。

---

## 训练策略

### 探索性路线：仅 B 数据（stage1_v2，已完成）

- 冻结 `Graph` / `MMBondedConj`，只训练 `ChargeVolume` + `Exp6Pol`
- 结论：B 有改善，但旧分布有退化；**不作为正式路线**

### 正式路线：mixed full finetune（已完成）

- 从 `optimal_with_b_init.pt` 重新开始，全量解冻
- B 数据走完整 EDA supervision
- public non-B anchor（来自公开 `valid_data` 的 90% 切分）只做 `TOTAL` 锚定
- 配置：`data/finetune_configs/full_finetune_boron_mixed_v1.yaml`

**为什么不用分阶段冻结 Graph**：B 是新元素，若只调头部，主干对 B 的表示学不充分，后续解冻主干还会反过来扰动头部。从统一 init 做 mixed 全量训练更合理。

**关于 `sample_weight` 的注意事项**：trainer 的匹配逻辑是 `d.name.split('_')[:2]`，如果 dimer 命名是 `mol_000_AN` 这类格式，`sample_keys` 无法按预期命中。正式混合训练建议改用多数据集 `loss_weight`，不依赖 `sample_weight`。

---

## 数据准备

### 原始数据格式

`data/dimer_eda/` 下每条 dimer 目录：

```
mol_000_AN/
├── EDA.json      # 字段：TOTAL, FROZEN, ELEC_PAULI, DISP, POLARIZATION,
│                 #       CHARGE TRANSFER, ELEC, CLS ELEC, PREPARATION
├── coords.npy    # shape [n_confs, n_atoms, 3]
└── info.json     # SMILES、原子数等
```

### HDF5 字段映射

| EDA.json | HDF5 字段名 |
|----------|------------|
| `TOTAL` | `total_int_energy` |
| `FROZEN` | `frozen_int_energy` |
| `ELEC_PAULI` | `elec_pauli_int_energy` |
| `DISP` | `disp_int_energy` |
| `POLARIZATION` | `polarization_int_energy` |
| `CHARGE TRANSFER` | `charge_transfer_int_energy` |
| `ELEC` | `elec_int_energy` |
| `CLS ELEC` | `cls_elec_int_energy` |
| `PREPARATION` | `preparation_int_energy` |

### QC 筛选

脚本 `data/screen_boron_dataset.py`，结果在 `data/boron_screened/`：

- `keep`（5349 条）：无明显几何或能量预警，用于第一轮训练
- `review`（318 条）：偏离主分布，第二阶段酌情加入
- `drop`（20 条）：暂不进入训练，不删除

**筛选阈值：**

| 参数 | review | drop |
|------|--------|------|
| `min_dist` | `< 1.60 Å` | `< 1.45 Å` |
| `TOTAL` | `> 84.94 kcal/mol` | `> 200 kcal/mol` |
| `FROZEN` | `> 100 kcal/mol` | `> 250 kcal/mol` |
| `POLARIZATION` | `< -40 kcal/mol` | — |
| `CHARGE TRANSFER` | `< -40 kcal/mol` | — |
| `TOTAL`（非离子 partner） | `< -25 kcal/mol` | — |

### 数据切分

组装脚本：`scripts/assemble_boron_finetune_dataset.py`
- 只取每个 dimer 的第一个构象（`conf_index = 0`）
- 按 `mol2_name` 分层、检查 `mol1_name` 覆盖，固定随机种子，`90 / 5 / 5` 切分

结果：`train=4819 / valid=265 / test=265`，输出至 `data/boron_finetune/`

---

## 实施顺序（已全部完成）

1. 修改 `definitions.py`，追加 B 元素定义
2. 运行 `scripts/expand_checkpoint_add_boron.py`，产出 `optimal_with_b_init.pt`
3. 运行 `scripts/assemble_boron_finetune_dataset.py`，组装训练数据
4. 运行基线评测（`optimal_with_b_init.pt` before 指标）
5. stage1_v2 探索性训练（仅 B，冻结 Graph）
6. mixed full finetune（B + public non-B anchor，全量解冻）

---

## 待解决问题

- `ELEC` 分量仍然很差，是当前最薄弱环节
- 是否需要对 B 的 `alpha` 加类似 Li 的 `fix_alpha` 约束，还没确认
- 严格 non-B 泛化（`public_valid_anchor/test`）结论尚未最终确认
- 液相 MD 宏观性质（density / viscosity / conductivity）验证尚未做
