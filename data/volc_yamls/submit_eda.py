"""
批量提交 EDA 任务 YAML。支持按含硼分子编号范围筛选。

用法:
    # 预览所有任务
    python data/volc_jobs/submit_eda.py --dry-run

    # 只提交 mol_000 ~ mol_029 的任务
    python data/volc_jobs/submit_eda.py --mol-start 0 --mol-end 30

    # 只提交 mol_000 与 AN 的任务
    python data/volc_jobs/submit_eda.py --mol-start 0 --mol-end 1 --mol2 AN

    # 正式提交（需确认）
    python data/volc_jobs/submit_eda.py --mol-start 0 --mol-end 30
"""
import argparse
import glob
import re
import subprocess
import sys
import time
from pathlib import Path


def parse_yaml_name(filename):
    """从文件名解析 mol1, mol2, conf_start。
    格式: eda_mol_XXX_MOL2_cYYY.yaml
    """
    m = re.match(r'eda_(mol_\d+)_(\w+)_c(\d+)\.yaml$', filename)
    if not m:
        return None, None, None
    mol1 = m.group(1)
    mol2 = m.group(2)
    conf_start = int(m.group(3))
    return mol1, mol2, conf_start


def mol_idx(mol_name):
    """mol_000 -> 0"""
    return int(mol_name.split('_')[1])


def submit_task(yaml_path, dry_run=False):
    """提交单个任务，返回是否成功"""
    cmd = ["volc", "ml_task", "submit", "-c", yaml_path]
    if dry_run:
        print(f"  [DRY-RUN] {' '.join(cmd)}")
        return True

    print(f"  Submitting {Path(yaml_path).name} ... ", end="", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print("OK")
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                print(f"    {line.strip()}")
        return True
    else:
        print("FAILED")
        print(f"    stderr: {result.stderr.strip()}")
        return False


def main():
    parser = argparse.ArgumentParser(description="批量提交 EDA 任务")
    parser.add_argument("--dir", type=str, default="data/volc_jobs/eda", help="YAML 目录")
    parser.add_argument("--mol-start", type=int, default=None, help="起始含硼分子编号 (inclusive)")
    parser.add_argument("--mol-end", type=int, default=None, help="结束含硼分子编号 (exclusive)")
    parser.add_argument("--mol2", type=str, default=None, help="只提交与指定已有分子配对的任务")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际提交")
    parser.add_argument("--interval", type=float, default=2, help="提交间隔秒数 (default: 2)")
    args = parser.parse_args()

    # 扫描所有 YAML 文件
    all_files = sorted(glob.glob(str(Path(args.dir) / "eda_*.yaml")))
    if not all_files:
        print(f"No YAML files found in {args.dir}/")
        sys.exit(1)

    # 过滤
    selected = []
    for f in all_files:
        mol1, mol2, _ = parse_yaml_name(Path(f).name)
        if mol1 is None:
            continue
        idx = mol_idx(mol1)
        if args.mol_start is not None and idx < args.mol_start:
            continue
        if args.mol_end is not None and idx >= args.mol_end:
            continue
        if args.mol2 is not None and mol2 != args.mol2:
            continue
        selected.append(f)

    if not selected:
        print("No tasks match the filter criteria.")
        sys.exit(1)

    print(f"Found {len(selected)} tasks to submit:")
    # 按 mol1 分组统计
    mol1_counts = {}
    for f in selected:
        mol1, _, _ = parse_yaml_name(Path(f).name)
        mol1_counts[mol1] = mol1_counts.get(mol1, 0) + 1
    for mol1 in sorted(mol1_counts):
        print(f"  {mol1}: {mol1_counts[mol1]} tasks")
    print()

    if not args.dry_run:
        answer = input(f"Confirm submit {len(selected)} tasks? [y/N] ")
        if answer.lower() != "y":
            print("Aborted.")
            sys.exit(0)

    n_ok = 0
    n_fail = 0
    for i, yaml_file in enumerate(selected):
        success = submit_task(yaml_file, dry_run=args.dry_run)
        if success:
            n_ok += 1
        else:
            n_fail += 1
        if i < len(selected) - 1 and not args.dry_run:
            time.sleep(args.interval)

    print(f"\nDone: {n_ok} submitted, {n_fail} failed (of {len(selected)} total)")


if __name__ == "__main__":
    main()
