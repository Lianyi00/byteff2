# ByteFF2 Benchmark 方法

## 1. 评测集与可靠性

| 评测集 | 路径 | 可靠性 |
|--------|------|--------|
| B `boron_test` | `data/boron_finetune/processed/test/` | 严格 holdout，训练未用 |
| 非 B `public_valid_anchor/test` | `data/public_valid_anchor/test/` | mixed 训练后的严格 non-B holdout |
| 公开 `valid_data` | `byteff2/valid_data/` | mixed 训练后有泄漏，仅作参考 |

**关于 `byteff2/valid_data`**：它不是论文中完整的 0.6M 验证集，只是其中一个公开 shard（3799 dimer，约 75951 构象）。mixed 训练用了其中 90% 作为 non-B anchor，所以用整个 `valid_data` 评测时有数据泄漏。

---

## 2. Benchmark 命令

以下命令均在仓库根目录执行，使用 `byteff` conda 环境。

### 基线模型（微调前）

```bash
# 非 B
conda run --no-capture-output -n byteff python scripts/eval_valid_data_total.py \
  --checkpoint byteff2/trained_models/optimal_with_b_init.pt

# 含 B
conda run --no-capture-output -n byteff python scripts/eval_boron_dimer_set.py \
  --checkpoint byteff2/trained_models/optimal_with_b_init.pt \
  --dataset-config data/boron_finetune/processed/test/dataset_config.yaml
```

### stage1_v2（仅 B 数据探索性训练）

```bash
# 非 B
conda run --no-capture-output -n byteff python scripts/eval_valid_data_total.py \
  --checkpoint training_logs/boron_stage1_v2_26_04_13_01_24_32/optimal.pt

# 含 B
conda run --no-capture-output -n byteff python scripts/eval_boron_dimer_set.py \
  --checkpoint training_logs/boron_stage1_v2_26_04_13_01_24_32/optimal.pt \
  --dataset-config data/boron_finetune/processed/test/dataset_config.yaml
```

### mixed full finetune（正式方案）

```bash
# 含 B（严格 holdout）
conda run --no-capture-output -n byteff python scripts/eval_boron_dimer_set.py \
  --checkpoint training_logs/boron_mixed_full_v1_26_04_14_15_18_44/optimal.pt \
  --dataset-config data/boron_finetune/processed/test/dataset_config.yaml

# 非 B（严格 holdout，推荐用这条）
conda run --no-capture-output -n byteff python scripts/eval_valid_data_total.py \
  --checkpoint training_logs/boron_mixed_full_v1_26_04_14_15_18_44/optimal.pt \
  --dataset-config data/public_valid_anchor/test/dataset_config.yaml

# 非 B（整个公开 valid_data，有泄漏，仅参考）
conda run --no-capture-output -n byteff python scripts/eval_valid_data_total.py \
  --checkpoint training_logs/boron_mixed_full_v1_26_04_14_15_18_44/optimal.pt
```

---

## 3. 当前结果

| 模型 | 数据集 | MAE | RMSE | Pearson r |
|------|--------|-----|------|-----------|
| `optimal_with_b_init.pt` | 非 B `valid_data` | 0.6567 | 7.3719 | 0.9583 |
| `optimal_with_b_init.pt` | B `boron_test` | 2.8392 | 13.8226 | 0.6632 |
| stage1_v2 | 非 B `valid_data` | 0.9378 | 6.3028 | 0.9482 |
| stage1_v2 | B `boron_test` | 1.7354 | 5.4658 | 0.8529 |
| mixed full | 非 B `valid_data`（含泄漏） | 0.7235 | 6.7444 | 0.9592 |
| mixed full | B `boron_test` | 1.6461 | 5.2072 | 0.8614 |

---

## 4. 结论分级

| 档次 | 条件 |
|------|------|
| Accept | B 数据显著改善，旧数据无明显退化 |
| Borderline | B 改善有限，或旧数据略有退化但仍可接受 |
| Reject | B 改善不明显，或旧数据显著下降 |

**当前状态**：mixed full finetune 在 B 上有效改善（MAE 2.84 → 1.65），非 B 基本保持。但 `ELEC` 分量仍然很差，且严格 non-B holdout（`public_valid_anchor/test`）的结论尚未最终记录。

---

## 5. 当前 benchmark 的局限性

当前评测是 dimer/cluster 级别的能量分量，是液相 MD 宏观性质（density / viscosity / conductivity）的**代理指标**，不能直接证明溶剂化结构或宏观性质一定更准。

后续进入 MD benchmark 的推荐路线：
1. 先选 BAMBOO benchmark 中与 ByteFF2 共享的非 B 体系
2. 同时跑原始 `optimal.pt` 和微调后模型，用 BAMBOO 公开实验值做 GT
3. 含 B 新体系的实验 GT 通常没有公开，需要单独整理
