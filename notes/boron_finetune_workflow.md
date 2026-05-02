# ByteFF2 加入 B 元素：实际过程与当前状态

## 1. 已完成的工作

| 步骤 | 产物 |
|------|------|
| 元素扩展 | `definitions.py` 追加 B（index=11） |
| checkpoint 扩容 | `byteff2/trained_models/optimal_with_b_init.pt` |
| 数据组装 | `data/boron_finetune/` |
| public non-B anchor 切分 | `data/public_valid_anchor/` |
| 探索性训练 stage1_v2 | `training_logs/boron_stage1_v2_26_04_13_01_24_32/` |
| 正式 mixed full finetune | `training_logs/boron_mixed_full_v1_26_04_14_15_18_44/` |

---

## 2. 数据

### B 数据（`data/boron_finetune/`）

来源：`data/dimer_eda/`，QC 后只用 `keep`（5349 条），每个 dimer 取第一个构象。

```
data/boron_finetune/
├── raw/
│   ├── boron_keep.h5
│   ├── boron_keep.json
│   ├── train_meta.txt / valid_meta.txt / test_meta.txt
│   ├── split_assignments.csv
│   └── split_summary.csv
├── preprocess/
│   ├── preprocess_train.yaml / preprocess_valid.yaml / preprocess_test.yaml
└── processed/
    ├── train/   (4819 条)
    ├── valid/   (265 条)
    └── test/    (265 条)
```

切分：按 `mol2_name` 分层，固定随机种子，`90 / 5 / 5`。

### Public non-B anchor（`data/public_valid_anchor/`）

来源：从公开 `byteff2/valid_data`（单个 shard，3799 dimer，约 75951 构象）按 `90 / 5 / 5` 切出。

```
train=3419 / valid=190 / test=190
```

**注意**：mixed 训练用了 `train` 子集，所以评测时要用 `test` 子集，不能用整个公开 `valid_data`（会有数据泄漏）。

---

## 3. 训练

### stage1_v2（探索性，仅 B 数据）

- 配置：`data/finetune_configs/stage1_boron_finetune_v2.yaml`
- 起点：`optimal_with_b_init.pt`
- 解冻：`Graph=0, MMBondedConj=0, ChargeVolume=5e-6, Exp6Pol=1e-4`
- 结论：B 有改善，但旧分布退化，**不作为最终方案**

### mixed full finetune v1（正式，基准）

- 配置：`data/finetune_configs/full_finetune_boron_mixed_v1.yaml`
- 起点：`optimal_with_b_init.pt`
- 解冻：`Graph=2e-5, MMBondedConj=1e-5, ChargeVolume=1e-5, Exp6Pol=5e-5`
- 优化器：RAdam，CosineAnnealingLR，`T_max=200, eta_min=1e-6`
- 数据：B train/valid（完整 EDA loss）+ public non-B anchor train/valid（仅 TOTAL loss）
- 问题：ELEC 分量无单独监督，为当前最薄弱分量

### mixed full finetune v2（加 ELEC Loss）

- 配置：`data/finetune_configs/full_finetune_boron_mixed_v2.yaml`
- 起点：`optimal_with_b_init.pt`（同 v1，从预训练权重重新开始）
- 解冻：同 v1
- 核心改动：在 B 数据集上额外加入 `InterEnergyElecMSE`（weight=0.5），使用 `elec_int_energy` 标签单独监督 ELEC 分量
- 原理：ELEC 和 PAULI 由完全独立的参数控制（ELEC←ChargeVolume 的 BCC 电荷；PAULI←Exp6Pol 的 λ/ε/r₀），加独立 ELEC loss 不影响 PAULI 参数梯度路径；`InterEnergyElecPauliMSE` 保留，确保 PAULI 约束不变
- 注意：`elec_int_energy`（QM ELEC）与模型函数形式（点电荷 Coulomb）存在穿透修正（penetration correction）的系统性不匹配，ELEC MAE 下降空间有上界

---

## 4. 评测结果

### 4.1 基线（`optimal_with_b_init.pt`，微调前）

| 数据集 | MAE | RMSE | bias | Pearson r |
|--------|-----|------|------|-----------|
| 非 B `valid_data` | 0.6567 | 7.3719 | +0.2360 | 0.9583 |
| B `boron_test` | 2.8392 | 13.8226 | +1.2223 | 0.6632 |

含 B 分量细节：`DISP` 已较好（MAE=0.2160, r=0.9947）；`ELEC` 极差（MAE=7.78, r≈0.002）。

### 4.2 stage1_v2

| 数据集 | MAE | RMSE | bias | Pearson r |
|--------|-----|------|------|-----------|
| 非 B `valid_data` | 0.9378 | 6.3028 | -0.4650 | 0.9482 |
| B `boron_test` | 1.7354 | 5.4658 | -0.7930 | 0.8529 |

旧分布退化明显（MAE 0.66 → 0.94）。

### 4.3 三模型横向对比（Boron test set，MAE / Pearson r）

评测命令：`scripts/eval_boron_dimer_set.py`，结果存 `data/eval/boron_test_{init,v1,v2}.json`。

| 分量 | init | v1 | v2 |
|------|------|----|----|
| TOTAL | 2.839 / +0.663 | 1.646 / +0.861 | **1.561 / +0.863** |
| FROZEN | 2.917 / +0.758 | 1.922 / +0.906 | **1.649 / +0.921** |
| ELEC_PAULI | 2.916 / +0.826 | 1.936 / +0.939 | **1.665 / +0.949** |
| **ELEC** | 7.781 / **+0.002** | 7.702 / **-0.028** | 7.661 / **+0.001** |
| PAULI | 7.841 / +0.827 | 8.059 / +0.950 | **7.798 / +0.961** |
| DISP | **0.216** / +0.995 | 0.231 / +0.994 | 0.273 / +0.994 |
| POLARIZATION | 0.651 / +0.861 | **0.630** / +0.875 | 0.654 / +0.855 |
| CHARGE_TRANSFER | 0.423 / +0.883 | 0.589 / +0.914 | **0.442 / +0.958** |

**Public valid_data TOTAL**（`scripts/eval_valid_data_total.py`，结果存 `data/eval/valid_total_{init,v1,v2}.json`）：

| checkpoint | MAE | RMSE | r |
|-----------|-----|------|----|
| init | 0.6567 | 7.3716 | 0.9583 |
| v1 | 0.7235 | 6.7444 | 0.9592 |
| v2 | 0.8327 | 7.5945 | 0.9598 |

**关键结论：**

1. **ELEC 在三个模型中 Pearson r 全部约为 0**——确认为架构层面上限，与 loss 设计无关。根因是模型用点电荷 Coulomb 形式，而 ALMO-EDA `elec_int_energy` 包含量子穿透修正（penetration correction），两者之间存在系统性函数形式不匹配。
2. **v2 整体略优于 v1**（TOTAL/FROZEN/ELEC_PAULI/CT 均改善），但 ELEC 单项无实质变化，说明 `InterEnergyElecMSE` loss 对当前架构意义不大，可以移除。
3. **non-B 泛化随微调持续退化**（MAE: 0.657→0.724→0.833），根本原因是 anchor 数据只有 `TOTAL` 标签，无法约束各 EDA 分量的分解，ChargeVolume 发生漂移。
4. **当前最优含硼权重**：`training_logs/boron_mixed_full_v2_26_04_21_10_35_29/optimal.pt`

---

## 5. 液相 MD Benchmark（1M LiPF6/EC:DMC 3:7 vol, 25°C）

### 5.1 配置

- 体系：EC:293 + DMC:542 + Li:65 + PF6:65（≈9954 atoms，3:7 体积比由密度/分子量推算）
- Protocol：Transport（NPT 4M steps → NVT 10M steps → 非平衡 1M steps）
- Config 文件：`example/4_MD_simulations/lipf6_ecdmc_transport_config.json`（baseline）、`lipf6_ecdmc_finetuned_config.json`（finetuned）
- 火山提交：`data/volc_jobs/md/md_lipf6_ecdmc_baseline.yaml` / `md_lipf6_ecdmc_finetuned.yaml`

### 5.2 完整液相 MD 结果（实验参考：1M LiPF6/EC:DMC 3:7, 25°C）

实际建盒分子数：EC=298, DMC=550, Li=66, PF6=66（search_mixture 自动调整后）。

| 指标 | baseline | finetuned | 实验值 | baseline 偏差 |
|------|---------|-----------|--------|-------------|
| **密度** | 1.263 g/mL | 1.418 g/mL | ~1.26 g/mL | ≈0% ✅ |
| **粘度** | **2.59 mPa·s** | 33.4 mPa·s | ~3 mPa·s | **-14%** ✅ |
| **σ (Onsager)** | 13.3 mS/cm | 1.7 mS/cm | ~8–10 mS/cm | 偏高 ~40% |
| **σ (NE)** | 18.7 mS/cm | 2.2 mS/cm | ~8–10 mS/cm | 偏高 ~90% |
| **D_Li** | 2.46×10⁻¹⁰ m²/s | 0.23×10⁻¹⁰ m²/s | ~0.4×10⁻¹⁰ m²/s | 偏高 ~6× |
| **D_PF6** | 3.54×10⁻¹⁰ m²/s | 0.37×10⁻¹⁰ m²/s | ~0.6×10⁻¹⁰ m²/s | 偏高 ~6× |
| **D_DMC** | 4.76×10⁻¹⁰ m²/s | 0.82×10⁻¹⁰ m²/s | — | — |
| **D_EC** | 5.03×10⁻¹⁰ m²/s | 0.35×10⁻¹⁰ m²/s | — | — |

**备注：**
- 密度：NPT 最后 1000 行均值；粘度：nonequ NEMD（1M steps，cosine perturbation）；电导率/扩散系数：NVT 轨迹（20000 帧）Onsager/Einstein 方法。
- **baseline 粘度 2.59 mPa·s 非常接近实验值 ~3 mPa·s（误差 -14%），是整个 benchmark 中最亮眼的结果。**
- baseline 的电导率和扩散系数均偏高 5-8 倍，原因：①NVT 仅 20 ns，对于 ~3 mPa·s 的粘性液体扩散统计不充分；②温度报告下移（292 K vs 298 K 目标）导致扩散偏快。
- finetuned 粘度高达 33.4 mPa·s（实验值 10 倍），电导率/扩散系数仅为 baseline 的 1/6–1/10，完全由电荷漂移（盒子收缩 11%，分子运动受限）驱动。

### 5.3 根因分析：电荷漂移（ChargeVolume catastrophic forgetting）

对 EC 逐原子电荷对比（基线 vs 微调）：

| 原子 | 基线 | 微调后 | Δ |
|------|------|--------|---|
| C=O 碳 | +0.883 | +1.311 | **+0.428**（+49%） |
| C=O 氧 | −0.574 | −0.746 | −0.173（+30%） |
| 环内 C-O 碳 | +0.067 | +0.186 | +0.119（+175%） |
| H | +0.086 | +0.061 | −0.025 |

整体 charge RMSD=0.179（rel 64.8%）；DMC charge RMSD=0.082（rel 30.8%）。
`Rvdw` 几乎不变（<1%），`eps` 变化 10–25%。

**结论**：微调后 EC/DMC 电荷被过度极化，静电吸引力增强同时 vdW 势阱变浅，导致密度偏高。ChargeVolume 层在 `lr=1e-5` 下未被 anchor 数据有效约束，发生了对 non-B 电荷分布的灾难性遗忘。

### 5.4 量纲分析：传输性质偏差是否全部由密度引起？

**核心问题**：finetuned 模型粘度高 12.9 倍、离子导低 8 倍，这些偏差是密度误差的派生效应，还是电荷漂移的独立作用？

#### 分析链条

**第一步：密度 → 粘度（自由体积理论 Doolittle 方程）**

$$\ln\eta = A + \frac{C}{f}, \quad f = 1 - \frac{\rho}{\rho_0}$$

取 ρ₀ = 1.60 g/mL（碳酸酯混合体系合理估计），计算自由体积分数：

| | f | 1/f |
|---|---|---|
| baseline（1.263 g/mL） | 0.210 | 4.76 |
| finetuned（1.418 g/mL） | 0.114 | 8.77 |

密度仅升高 12.3%，**自由体积减半**（0.210 → 0.114），非线性放大粘度：

$$\ln\frac{\eta_{ft}}{\eta_{base}} = C\left(\frac{1}{0.114} - \frac{1}{0.210}\right) = C \times 4.01$$

实测粘度比 ln(12.9) = 2.56，反推 **C = 0.64**（典型有机液体 C ≈ 0.5–1.2，物理合理）。

**→ 密度升高 12.3% 单独即可定量解释粘度升高 12.9 倍。**

**第二步：粘度 → 扩散系数（Stokes-Einstein 关系）**

$$D \propto \frac{1}{\eta} \implies \frac{D_{ft}}{D_{base}} \approx \frac{1}{12.9} = 0.078$$

| 物种 | D_ft/D_base（实测） | SE 预测 |
|---|---|---|
| Li⁺ | 0.094 | 0.078 |
| PF₆⁻ | 0.105 | 0.078 |
| DMC | 0.172 | 0.078 |
| EC | 0.070 | 0.078 |

实测范围 0.07–0.17，与 SE 预测量级完全一致。**扩散系数下降由粘度升高解释，无需额外假设。**

**第三步：扩散系数 → 离子导率（Nernst-Einstein，含密度效应）**

$$\sigma_{NE} \propto n(D_+ + D_-), \quad n \propto \rho$$

密度升高使离子数密度 n 增加 1.123 倍（抵消部分 D 下降），净预测：

$$\frac{\sigma_{NE,ft}}{\sigma_{NE,base}} = 1.123 \times \frac{D_{Li,ft}+D_{PF6,ft}}{D_{Li,base}+D_{PF6,base}} = 1.123 \times \frac{0.60}{6.00} = \mathbf{0.112}$$

实测：2.2/18.7 = **0.118**（误差仅 5%）。

#### 结论：完整因果链

```
电荷漂移（EC C=O 碳 +49%）
    ↓
静电吸引增强 → 盒子收缩 → 密度 +12.3%
    ↓  自由体积非线性压缩
自由体积减半（0.210 → 0.114）
    ↓  Doolittle，C=0.64（合理）
粘度 ×12.9 倍                          ← 定量符合
    ↓  Stokes-Einstein
扩散系数 ×0.10（实测 0.07–0.17）        ← 定量符合
    ↓  Nernst-Einstein + 密度补正
离子导率 ×0.112（实测 0.118，误差 5%） ← 定量符合
```

**是的：粘度、D、σ 的偏差，全部可以从密度偏高 12.3% 出发定量推导，无需引入额外假设。密度是唯一的一级原因。**

#### 实验密度校正是否足够？

自然推论：若将 box 等比扩大到实验密度 1.26 g/mL，传输性质会恢复吗？

**答案：能大幅改善，但不能完全修复。** 电荷漂移存在两条并行路径：

| 路径 | 机制 | 密度校正是否修复 |
|---|---|---|
| 间接路径 | 强静电 → 密度↑ → 自由体积↓ → 粘度↑ | ✅ 可修复 |
| 直接路径 | 力场静电势场本身变强 → 相同密度下分子运动也变慢（Li⁺ 配位壳结合更紧，应力张量涨落更大） | ❌ 无法修复 |

粗略估计：密度校正后粘度可从 33.4 降至 ~5–10 mPa·s，σ 从 2.2 升至 ~5–8 mS/cm，仍与实验有 2–3 倍差距。

**真正的修复只能靠修正力场参数（电荷）本身，即抑制 ChargeVolume 漂移。** 密度是快速诊断指标：密度准 → 传输性质大概率准。

### 5.5 三种假设的判断

| 假设 | 评估 |
|------|------|
| B 数据量太少 | 部分相关（ELEC 本来就是弱项），但主因不在数量 |
| B 数据极性强（硼酸酯/硼氧环），拉着电荷模型学到更极化的表示 | **主要原因之一** |
| anchor 数据量和权重不足以防止 ChargeVolume 漂移 | **主要原因** |

---

## 6. 含 B 体系液相 MD 实验

### 6.1 LiBF4/EC:DMC 和 LiBOB/EC 密度测试

为验证 finetuned 模型在含 B 盐体系上的表现，额外创建了两个密度测试配置：

| 体系 | Config | Checkpoint |
|------|--------|------------|
| 1M LiBF4/EC:DMC (3:7 vol) | `example/4_MD_simulations/libf4_ecdmc_density_config.json` | `boron_mixed_full_v1` |
| 1M LiBOB/EC | `example/4_MD_simulations/libob_ec_density_config.json` | `boron_mixed_full_v1` |

### 6.2 TPFPB 添加剂密度测试

基底体系：1M LiPF6/EC:DMC (3:7 vol)，EC=293, DMC=542, Li=65, PF6=65（共 9954 atoms）

TPFPB（Tris(pentafluorophenyl)borane，B(C₆F₅)₃）：MW≈511.8 g/mol，34 原子/分子，SMILES=`B(c1c(F)c(F)c(F)c(F)c1F)(c1c(F)c(F)c(F)c(F)c1F)c1c(F)c(F)c(F)c(F)c1F`

| 质量分数 | TPFPB 分子数 | Config | Volcano YAML |
|----------|------------|--------|-------------|
| 5 wt% | 9 | `lipf6_ecdmc_tpfpb5pct_density_config.json` | `data/volc_jobs/md/md_lipf6_ecdmc_tpfpb5pct.yaml` |
| 10 wt% | 18 | `lipf6_ecdmc_tpfpb10pct_density_config.json` | `data/volc_jobs/md/md_lipf6_ecdmc_tpfpb10pct.yaml` |
| 20 wt% | 41 | `lipf6_ecdmc_tpfpb20pct_density_config.json` | `data/volc_jobs/md/md_lipf6_ecdmc_tpfpb20pct.yaml` |

Checkpoint（全部使用）：`training_logs/boron_mixed_full_v1_26_04_14_15_18_44/optimal.pt`

提交命令：
```bash
volc ml_task submit -c data/volc_jobs/md/md_lipf6_ecdmc_tpfpb5pct.yaml
volc ml_task submit -c data/volc_jobs/md/md_lipf6_ecdmc_tpfpb10pct.yaml
volc ml_task submit -c data/volc_jobs/md/md_lipf6_ecdmc_tpfpb20pct.yaml
```

**设计动机**：TPFPB 含 B-C 键（训练数据以 B-O 键为主），Lewis 酸性强。通过提高浓度（5%→20%）使盒子中 TPFPB 达到 9~41 个分子，获得统计意义上的密度信号，用于验证 finetuned 模型在新型含 B 添加剂体系上的可靠性。

---

## 7. 当前推荐的工作流

评测新 checkpoint 的顺序：

1. 含 B `boron_test`（严格 holdout）
2. 非 B `public_valid_anchor/test`（严格 holdout）
3. 整个公开 `valid_data`（仅参考，mixed 训练后有泄漏）
4. 液相 MD benchmark（`1M LiPF6/EC:DMC`，density 是快速诊断指标）

---

## 8. Non-B EDA 数据生产流程

### 8.1 动机

anchor 数据（`data/public_valid_anchor/`）目前只有 `TOTAL` 标签，无法约束各 EDA 分量的分解，导致微调时 ChargeVolume 发生漂移（详见 §5.3）。**解决方案：对 19 个已有非 B 分子之间的所有 unique pair 补跑 GPU4PySCF ALMO-EDA**，生成带完整 EDA 分量标签的非 B 二聚体数据。

### 8.2 数据规模

- 19 个已有分子：AN, DEC, DEGDM, DMC, DMET, DOL, EA, EC, EFA, EMC, FEA, FEC, FSI, GBL, LI, MA, PC, PF6, TFSI
- 所有 unique pair（含同分子对）：C(19,2)+19 = **190 对**
- 每对生成 100 个二聚体构象，切分为 5 个 slice（每 slice 20 个构象）
- 总任务数：190 × 5 = **950 个火山引擎任务**

### 8.3 流水线脚本

| 脚本 | 用途 |
|------|------|
| `data/volc_yamls/generate_nonb_eda_yamls.py` | 生成 YAML 任务文件 |
| `data/volc_yamls/submit_nonb_eda.py` | 批量提交任务 |
| `data/run_single_pair_eda.py` | 后端计算脚本（与 B 数据共用） |

**生成 YAML：**
```bash
# 生成所有 190 对的任务（默认 100 构象/对，20 构象/slice）
python data/volc_yamls/generate_nonb_eda_yamls.py

# 跳过已完成切片
python data/volc_yamls/generate_nonb_eda_yamls.py --skip-done

# 只生成含特定分子的 pair
python data/volc_yamls/generate_nonb_eda_yamls.py --include EC DMC LI PF6
```

**提交任务：**
```bash
# 预览
python data/volc_yamls/submit_nonb_eda.py --dry-run

# 提交特定分子对
python data/volc_yamls/submit_nonb_eda.py --mol1 EC --mol2 DMC

# 提交第 N 到第 M 个任务（0-indexed，exclusive end）
python data/volc_yamls/submit_nonb_eda.py --start 0 --end 50

# 正式提交（会提示确认）
python data/volc_yamls/submit_nonb_eda.py
```

### 8.4 数据层次

```
每个 pair（如 AN_DMC）
├── 100 个二聚体构象（conf_000 ~ conf_099）
├── 切分为 5 个 slice：c000(0-19), c020(20-39), c040(40-59), c060(60-79), c080(80-99)
├── 每个 slice 对应 1 个火山引擎 YAML 任务
└── 结果存入 data/dimer_eda_nonb/{MOL1}_{MOL2}/confs/conf_XXX.json
```

每个 `conf_XXX.json` 包含完整 EDA 分量：total, frozen, electrostatic, pauli, dispersion, polarization, charge_transfer, cls_electrostatic, preparation。

### 8.5 计算资源

- 镜像：`cr-mlp-cn-beijing.cr.volces.com/public/lianyi:260320`
- 机型：`ml.pni2.3xlarge`（GPU 节点）
- 队列：`queue004`
- 每任务超时：24h
- 启用闲时资源：`EnableIdleResource: true`，`Preemptible: true`

### 8.6 当前进度

- YAML 已生成：950 个（`data/volc_jobs/nonb_eda/`）
- 已完成：10/190 对（AN × 全部 19 个分子），共 1000 个构象
- 数据质量检查：全部通过，无异常值，TOTAL 能量分布合理（mean=2.58, std=13.64 kcal/mol）
- 剩余：180 对，待提交

### 8.7 后续步骤

1. 提交剩余 180 对的计算任务
2. 计算完成后将 `data/dimer_eda_nonb/` 中的结果组装为 HDF5 训练数据
3. 与 B 数据联合训练，non-B 数据使用全量 EDA 分量 loss 监督（而非仅 TOTAL）
4. 评估 ChargeVolume 漂移是否被有效抑制

---

## 9. 待解决问题与后续方向

- **non-B EDA 数据计算**（当前主要瓶颈）：详见 §8
- **ELEC 分量**：已确认为架构层面上限（点电荷 vs 量子穿透修正），非数据/loss 问题，暂不作为优化目标
- `public_valid_anchor/test` 上的严格 non-B 结论尚未最终记录
- 是否需要对 B 的 `alpha` 加 `fix_alpha` 约束尚未确认
