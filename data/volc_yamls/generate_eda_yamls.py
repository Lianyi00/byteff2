"""
批量生成二聚体 EDA 计算的火山引擎任务 YAML。
每个含硼分子 × 19 个已有分子 × 5 个切片 = 95 个任务/含硼分子。
每个任务算 20 个构型 (~10h)。

用法:
    # 为 mol_000 ~ mol_029 生成
    python data/volc_jobs/generate_eda_yamls.py --start 0 --end 30

    # 跳过已完成的构型
    python data/volc_jobs/generate_eda_yamls.py --start 0 --end 30 --skip-done

    # 自定义切片大小
    python data/volc_jobs/generate_eda_yamls.py --start 0 --end 5 --confs-per-task 50
"""
import argparse
import csv
import os
from pathlib import Path

EXISTING_MOLS = [
    'AN', 'DEC', 'DEGDM', 'DMC', 'DMET', 'DOL', 'EA', 'EC', 'EFA', 'EMC',
    'FEA', 'FEC', 'FSI', 'GBL', 'LI', 'MA', 'PC', 'PF6', 'TFSI',
]

TEMPLATE = """\
# volc ml_task submit 配置文件
# 提交: volc ml_task submit -c {yaml_path}

TaskName: "byteff2-eda-{mol1_name}-{mol2_name}-c{conf_start:03d}"
Description: "GPU4PySCF ALMO-EDA: {mol1_name} + {mol2_name} conf {conf_start}-{conf_end_display}"
Tags:
    - "byteff2"
    - "eda"
    - "boron"

UserCodePath: ""
RemoteMountCodePath: ""

Entrypoint: |
    cd /vepfs-mlp/project-battery/lianyi/byteff2

    source /root/miniconda3/etc/profile.d/conda.sh
    conda activate byteff

    echo "=== EDA: {mol1_name} + {mol2_name} (conf {conf_start}-{conf_end_display}) ==="
    echo "Start: $(date)"

    python data/run_single_pair_eda.py \\
        --mol1_xyz data/monomer_opt/{mol1_name}/{mol1_name}.xyz \\
        --mol1_smi "{mol1_smi}" \\
        --mol1_name {mol1_name} \\
        --mol2_xyz data/existing_monomers/{mol2_name}.xyz \\
        --mol2_name {mol2_name} \\
        --nconfs {nconfs_total} \\
        --conf-start {conf_start} \\
        --conf-end {conf_end}

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

Preemptible: false

Storages:
    - Type: "Vepfs"
      MountPath: "/vepfs-mlp/project-battery/lianyi"
      FsName: "vepfs-mlp2"
      SubPath: "/project-battery/lianyi"

AccessType: "Private"

Priority: 4

EnableIdleResource: true
"""


def load_manifest(manifest_path):
    """读取 manifest.tsv，返回 {{mol_name: smiles}}"""
    mapping = {}
    with open(manifest_path) as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            mapping[row['mol_name']] = row['smiles']
    return mapping


def count_completed_confs(eda_dir, mol1_name, mol2_name, conf_start, conf_end):
    """检查某个切片中已完成的构型数"""
    conf_dir = os.path.join(eda_dir, f'{mol1_name}_{mol2_name}', 'confs')
    if not os.path.exists(conf_dir):
        return 0
    count = 0
    for ci in range(conf_start, conf_end):
        if os.path.exists(os.path.join(conf_dir, f'conf_{ci:03d}.json')):
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="批量生成 EDA 任务 YAML")
    parser.add_argument("--start", type=int, required=True, help="起始含硼分子编号 (inclusive)")
    parser.add_argument("--end", type=int, required=True, help="结束含硼分子编号 (exclusive)")
    parser.add_argument("--nconfs", type=int, default=100, help="每 pair 总构型数 (default: 100)")
    parser.add_argument("--confs-per-task", type=int, default=20, help="每个任务算多少构型 (default: 20)")
    parser.add_argument("--outdir", type=str, default="data/volc_jobs/eda", help="输出目录")
    parser.add_argument("--skip-done", action="store_true", help="跳过已全部完成的切片")
    parser.add_argument("--manifest", type=str, default="data/monomer_opt/manifest.tsv")
    parser.add_argument("--eda-dir", type=str, default="data/dimer_eda", help="EDA 结果目录")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 计算切片
    slices = []
    for s in range(0, args.nconfs, args.confs_per_task):
        slices.append((s, min(s + args.confs_per_task, args.nconfs)))

    n_generated = 0
    n_skipped_mol = 0
    n_skipped_done = 0
    files = []

    for mol_idx in range(args.start, args.end):
        mol1_name = f'mol_{mol_idx:03d}'
        if mol1_name not in manifest:
            continue

        mol1_smi = manifest[mol1_name]

        # 检查 ORCA 优化是否完成
        mol1_xyz = f'data/monomer_opt/{mol1_name}/{mol1_name}.xyz'
        mol1_out = f'data/monomer_opt/{mol1_name}/{mol1_name}.out'
        if not os.path.exists(mol1_xyz):
            print(f"  SKIP: {mol1_name} (no optimized xyz)")
            n_skipped_mol += 1
            continue

        for mol2_name in EXISTING_MOLS:
            for conf_start, conf_end in slices:
                # 检查是否已完成
                if args.skip_done:
                    n_done = count_completed_confs(
                        args.eda_dir, mol1_name, mol2_name, conf_start, conf_end)
                    if n_done >= conf_end - conf_start:
                        n_skipped_done += 1
                        continue

                yaml_filename = f'eda_{mol1_name}_{mol2_name}_c{conf_start:03d}.yaml'
                yaml_path = f'data/volc_jobs/eda/{yaml_filename}'

                content = TEMPLATE.format(
                    yaml_path=yaml_path,
                    mol1_name=mol1_name,
                    mol2_name=mol2_name,
                    mol1_smi=mol1_smi,
                    nconfs_total=args.nconfs,
                    conf_start=conf_start,
                    conf_end=conf_end,
                    conf_end_display=conf_end - 1,
                )

                filepath = outdir / yaml_filename
                filepath.write_text(content)
                files.append(filepath)
                n_generated += 1

    print(f"\nGenerated {n_generated} YAML files")
    print(f"  Skipped (no xyz): {n_skipped_mol} molecules")
    print(f"  Skipped (done):   {n_skipped_done} slices")
    print(f"  Output: {outdir}/")

    n_mols = args.end - args.start - n_skipped_mol
    n_slices = len(slices)
    print(f"\n  {n_mols} molecules × 19 partners × {n_slices} slices "
          f"= {n_mols * 19 * n_slices} max tasks")

    if files:
        print(f"\nExamples:")
        for f in files[:5]:
            print(f"  {f.name}")
        if len(files) > 5:
            print(f"  ... ({len(files) - 5} more)")


if __name__ == "__main__":
    main()
