"""
批量生成 ORCA 单体优化的火山引擎任务 YAML（只为未完成的分子生成）。

用法:
    # 默认每 2 个分子一组，只生成未完成的
    python data/volc_jobs/generate_yamls.py

    # 自定义 batch size
    python data/volc_jobs/generate_yamls.py --batch 3

    # 强制为所有 300 个分子生成（忽略已完成状态）
    python data/volc_jobs/generate_yamls.py --all
"""
import argparse
import os
from pathlib import Path

TEMPLATE = """\
# volc ml_task submit 配置文件
# 提交: volc ml_task submit -c {yaml_path}

TaskName: "byteff2-monomer-opt-{tag}"
Description: "ORCA B3LYP-D3BJ/def2-SVPD monomer optimization for boron molecules"
Tags:
    - "byteff2"
    - "orca"
    - "monomer-opt"

UserCodePath: ""
RemoteMountCodePath: ""

Entrypoint: |
    cd /vepfs-mlp/project-battery/lianyi/byteff2

    source /root/miniconda3/etc/profile.d/conda.sh
    conda activate orca
    export LD_LIBRARY_PATH=/root/miniconda3/envs/orca/lib:$LD_LIBRARY_PATH
    export OMPI_ALLOW_RUN_AS_ROOT=1
    export OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
    export OMPI_MCA_btl_vader_single_copy_mechanism=none

    ORCA_PATH="/vepfs-mlp/project-battery/lianyi/orca/orca"
    WORK_DIR="/vepfs-mlp/project-battery/lianyi/byteff2/data/monomer_opt"
    NPROCS=12

    echo "=== Monomer Optimization: {mol_list_display} ==="
    echo "Start: $(date)"

    N_DONE=0
    N_FAIL=0

    for i in {seq_expr}; do
        mol_name=$(printf "mol_%03d" $i)
        mol_dir="$WORK_DIR/$mol_name"
        inp_file="$mol_dir/${{mol_name}}.inp"
        out_file="$mol_dir/${{mol_name}}.out"
        opt_xyz="$mol_dir/${{mol_name}}.xyz"

        if [ ! -f "$inp_file" ]; then
            echo "  SKIP: $mol_name (no input file)"
            continue
        fi

        # 跳过已完成的
        if [ -f "$opt_xyz" ] && grep -q "ORCA TERMINATED NORMALLY" "$out_file" 2>/dev/null; then
            echo "  SKIP: $mol_name (already done)"
            N_DONE=$((N_DONE + 1))
            continue
        fi

        # 清理之前中断的临时文件
        rm -f "$mol_dir/${{mol_name}}.gbw" "$mol_dir/${{mol_name}}.prop" "$mol_dir/${{mol_name}}.opt"

        echo -n "  OPT:  $mol_name ... "
        cd "$mol_dir"
        "$ORCA_PATH" "${{mol_name}}.inp" > "${{mol_name}}.out" 2>&1
        orca_exit=$?
        cd /vepfs-mlp/project-battery/lianyi/byteff2

        if [ $orca_exit -eq 0 ] && [ -f "$opt_xyz" ]; then
            energy=$(grep "FINAL SINGLE POINT ENERGY" "$out_file" | tail -1 | awk '{{print $NF}}')
            echo "OK (E = $energy)"
            N_DONE=$((N_DONE + 1))
        else
            echo "FAILED"
            N_FAIL=$((N_FAIL + 1))
        fi
    done

    echo ""
    echo "=== Done: $N_DONE succeeded, $N_FAIL failed ==="
    echo "End: $(date)"

Envs: []

ImageUrl: "cr-mlp-cn-beijing.cr.volces.com/public/lianyi:260320"
ResourceQueueName: "queue004"
Framework: "Custom"

TaskRoleSpecs:
    - RoleName: "worker"
      RoleReplicas: 1
      Flavor: "ml.pni2.3xlarge"

ActiveDeadlineSeconds: "72h"

Storages:
    - Type: "Vepfs"
      MountPath: "/vepfs-mlp/project-battery/lianyi"
      FsName: "vepfs-mlp2"
      SubPath: "/project-battery/lianyi"

AccessType: "Private"

Priority: 4

EnableIdleResource: true
"""


def is_done(mol_idx, work_dir):
    """检查分子是否已完成优化"""
    mol_name = f"mol_{mol_idx:03d}"
    mol_dir = os.path.join(work_dir, mol_name)
    out_file = os.path.join(mol_dir, f"{mol_name}.out")
    xyz_file = os.path.join(mol_dir, f"{mol_name}.xyz")

    if not os.path.exists(out_file) or not os.path.exists(xyz_file):
        return False
    with open(out_file) as f:
        content = f.read()
        return "ORCA TERMINATED NORMALLY" in content


def main():
    parser = argparse.ArgumentParser(description="批量生成 monomer opt YAML（只为未完成分子）")
    parser.add_argument("--total", type=int, default=300, help="总分子数")
    parser.add_argument("--batch", type=int, default=1, help="每个任务的分子数")
    parser.add_argument("--outdir", type=str, default="data/volc_jobs", help="输出目录")
    parser.add_argument("--all", action="store_true", help="为所有分子生成（忽略已完成状态）")
    args = parser.parse_args()

    work_dir = "data/monomer_opt"
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 找出未完成的分子
    if args.all:
        todo = list(range(args.total))
    else:
        done = [i for i in range(args.total) if is_done(i, work_dir)]
        todo = [i for i in range(args.total) if not is_done(i, work_dir)]
        print(f"Already done ({len(done)}): {', '.join(f'mol_{i:03d}' for i in done[:10])}{'...' if len(done) > 10 else ''}")

    print(f"To compute: {len(todo)} molecules, batch size: {args.batch}")

    if not todo:
        print("All done! No YAML files generated.")
        return

    # 按 batch 分组
    batches = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]

    files = []
    for batch in batches:
        tag = f"{batch[0]:03d}-{batch[-1]:03d}"
        filename = f"monomer_opt_{tag}.yaml"
        yaml_path = f"data/volc_jobs/{filename}"

        # 连续序列用 $(seq a b)，非连续用空格列表
        if batch == list(range(batch[0], batch[-1] + 1)):
            seq_expr = f"$(seq {batch[0]} {batch[-1]})"
        else:
            seq_expr = " ".join(str(x) for x in batch)

        mol_list_display = " ".join(f"mol_{x:03d}" for x in batch)

        content = TEMPLATE.format(
            tag=tag,
            yaml_path=yaml_path,
            mol_list_display=mol_list_display,
            seq_expr=seq_expr,
        )
        filepath = outdir / filename
        filepath.write_text(content)
        files.append(filepath)

    print(f"\nGenerated {len(files)} YAML files in {outdir}/")
    for f in files[:5]:
        print(f"  {f.name}")
    if len(files) > 5:
        print(f"  ... ({len(files) - 5} more)")


if __name__ == "__main__":
    main()
