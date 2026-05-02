"""
批量生成 non-B × non-B 二聚体 EDA 计算的火山引擎任务 YAML。

覆盖范围：19 个已有分子之间所有 unique pair（含同分子对），共 190 对。
SMILES 自动从 data/existing_monomers/*.xyz 的 mapped_smiles 注释行解析。
EDA 结果写入 data/dimer_eda_nonb/（与 B 分子结果分开存放）。

用法:
    # 生成所有 190 对的任务
    python data/volc_yamls/generate_nonb_eda_yamls.py

    # 跳过已完成的切片
    python data/volc_yamls/generate_nonb_eda_yamls.py --skip-done

    # 自定义每任务构型数
    python data/volc_yamls/generate_nonb_eda_yamls.py --confs-per-task 10

    # 只生成特定分子对（两个分子名之一包含在列表里的）
    python data/volc_yamls/generate_nonb_eda_yamls.py --include EC DMC LI PF6
"""
import argparse
import os
import re
from itertools import combinations_with_replacement
from pathlib import Path

from rdkit import Chem

MONOMER_DIR = "data/existing_monomers"
OUTPUT_DIR_EDA = "data/dimer_eda_nonb"

EXISTING_MOLS = [
    'AN', 'DEC', 'DEGDM', 'DMC', 'DMET', 'DOL', 'EA', 'EC', 'EFA', 'EMC',
    'FEA', 'FEC', 'FSI', 'GBL', 'LI', 'MA', 'PC', 'PF6', 'TFSI',
]

TEMPLATE = """\
# volc ml_task submit 配置文件
# 提交: volc ml_task submit -c {yaml_path}

TaskName: "byteff2-nonb-eda-{mol1_name}-{mol2_name}-c{conf_start:03d}"
Description: "GPU4PySCF ALMO-EDA (non-B): {mol1_name} + {mol2_name} conf {conf_start}-{conf_end_display}"
Tags:
    - "byteff2"
    - "eda"
    - "non-boron"

UserCodePath: ""
RemoteMountCodePath: ""

Entrypoint: |
    cd /vepfs-mlp/project-battery/lianyi/byteff2

    source /root/miniconda3/etc/profile.d/conda.sh
    conda activate byteff

    echo "=== EDA (non-B): {mol1_name} + {mol2_name} (conf {conf_start}-{conf_end_display}) ==="
    echo "Start: $(date)"

    python data/run_single_pair_eda.py \\
        --mol1_xyz data/existing_monomers/{mol1_name}.xyz \\
        --mol1_smi "{mol1_smi}" \\
        --mol1_name {mol1_name} \\
        --mol2_xyz data/existing_monomers/{mol2_name}.xyz \\
        --mol2_name {mol2_name} \\
        --nconfs {nconfs_total} \\
        --conf-start {conf_start} \\
        --conf-end {conf_end} \\
        --output_dir {output_dir}

    echo "End: $(date)"

Envs: []

ImageUrl: "cr-mlp-cn-beijing.cr.volces.com/public/lianyi:260320"
ResourceQueueName: "queue004"
Framework: "Custom"

TaskRoleSpecs:
    - RoleName: "worker"
      RoleReplicas: 1
      Flavor: "ml.pni2.3xlarge"

ActiveDeadlineSeconds: "24h"

Preemptible: true

Storages:
    - Type: "Vepfs"
      MountPath: "/vepfs-mlp/project-battery/lianyi"
      FsName: "vepfs-mlp2"
      SubPath: "/project-battery/lianyi"

AccessType: "Private"

Priority: 4

EnableIdleResource: true
"""


def parse_smiles_from_xyz(xyz_path: str) -> str:
    """从 XYZ 文件第二行的 mapped_smiles 注释中解析 canonical SMILES。"""
    with open(xyz_path) as f:
        lines = f.readlines()
    comment = lines[1] if len(lines) > 1 else ''
    m = re.search(r'mapped_smiles="([^"]+)"', comment)
    if not m:
        raise ValueError(f"No mapped_smiles found in {xyz_path}")
    mapped = m.group(1)
    mol = Chem.MolFromSmiles(mapped)
    if mol is None:
        raise ValueError(f"RDKit failed to parse mapped_smiles in {xyz_path}: {mapped}")
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    return Chem.MolToSmiles(mol)


def count_completed_confs(eda_dir: str, mol1_name: str, mol2_name: str,
                          conf_start: int, conf_end: int) -> int:
    """检查某个切片中已完成的构型数。"""
    conf_dir = os.path.join(eda_dir, f'{mol1_name}_{mol2_name}', 'confs')
    if not os.path.exists(conf_dir):
        return 0
    return sum(
        1 for ci in range(conf_start, conf_end)
        if os.path.exists(os.path.join(conf_dir, f'conf_{ci:03d}.json'))
    )


def main():
    parser = argparse.ArgumentParser(description="生成 non-B × non-B EDA 任务 YAML")
    parser.add_argument("--nconfs", type=int, default=100,
                        help="每 pair 总构型数 (default: 100)")
    parser.add_argument("--confs-per-task", type=int, default=20,
                        help="每个任务算多少构型 (default: 20)")
    parser.add_argument("--outdir", type=str, default="data/volc_jobs/nonb_eda",
                        help="YAML 输出目录")
    parser.add_argument("--eda-dir", type=str, default=OUTPUT_DIR_EDA,
                        help="EDA 结果目录（用于检查断点）")
    parser.add_argument("--skip-done", action="store_true",
                        help="跳过已全部完成的切片")
    parser.add_argument("--include", nargs="+", metavar="MOL",
                        help="只生成包含指定分子名的 pair（白名单过滤）")
    args = parser.parse_args()

    monomer_dir = Path(MONOMER_DIR)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 解析所有 19 个分子的 SMILES
    smiles_map = {}
    for name in EXISTING_MOLS:
        xyz_path = monomer_dir / f"{name}.xyz"
        smiles_map[name] = parse_smiles_from_xyz(str(xyz_path))
    print(f"Loaded SMILES for {len(smiles_map)} molecules.")

    # 生成所有 unique pair（mol1 ≤ mol2，按 EXISTING_MOLS 顺序）
    all_pairs = list(combinations_with_replacement(EXISTING_MOLS, 2))

    # 白名单过滤
    if args.include:
    	include_set = set(args.include)
    	all_pairs = [(m1, m2) for m1, m2 in all_pairs
                     if m1 in include_set or m2 in include_set]
    	print(f"Filtered to {len(all_pairs)} pairs involving: {sorted(include_set)}")
    else:
        print(f"Total unique pairs: {len(all_pairs)}")

    # 构型切片
    slices = [(s, min(s + args.confs_per_task, args.nconfs))
              for s in range(0, args.nconfs, args.confs_per_task)]

    n_generated = 0
    n_skipped = 0
    files = []

    for mol1_name, mol2_name in all_pairs:
        mol1_smi = smiles_map[mol1_name]

        for conf_start, conf_end in slices:
            if args.skip_done:
                n_done = count_completed_confs(
                    args.eda_dir, mol1_name, mol2_name, conf_start, conf_end)
                if n_done >= conf_end - conf_start:
                    n_skipped += 1
                    continue

            yaml_filename = f"nonb_eda_{mol1_name}_{mol2_name}_c{conf_start:03d}.yaml"
            yaml_path = f"{args.outdir}/{yaml_filename}"

            content = TEMPLATE.format(
                yaml_path=yaml_path,
                mol1_name=mol1_name,
                mol2_name=mol2_name,
                mol1_smi=mol1_smi,
                nconfs_total=args.nconfs,
                conf_start=conf_start,
                conf_end=conf_end,
                conf_end_display=conf_end - 1,
                output_dir=args.eda_dir,
            )

            filepath = outdir / yaml_filename
            filepath.write_text(content)
            files.append(filepath)
            n_generated += 1

    print(f"\nGenerated {n_generated} YAML files → {outdir}/")
    if n_skipped:
        print(f"Skipped (already done): {n_skipped} slices")
    print(f"\nEstimated GPU tasks if all run: "
          f"{len(all_pairs)} pairs × {len(slices)} slices = "
          f"{len(all_pairs) * len(slices)} tasks")

    if files:
        print("\nExamples:")
        for f in files[:5]:
            print(f"  {f.name}")
        if len(files) > 5:
            print(f"  ... ({len(files) - 5} more)")


if __name__ == "__main__":
    main()
