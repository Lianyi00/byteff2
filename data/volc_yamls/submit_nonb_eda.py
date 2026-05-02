"""
批量提交 non-B EDA 任务 YAML。支持按分子名过滤。

用法:
    # 预览所有任务
    python data/volc_yamls/submit_nonb_eda.py --dry-run

    # 只提交 EC 参与的所有任务（mol1 或 mol2 为 EC）
    python data/volc_yamls/submit_nonb_eda.py --mol1 EC --dry-run

    # 只提交 EC + DMC 这一对
    python data/volc_yamls/submit_nonb_eda.py --mol1 EC --mol2 DMC --dry-run

    # 正式提交（会提示确认）
    python data/volc_yamls/submit_nonb_eda.py --mol1 EC --mol2 DMC
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
    格式: nonb_eda_MOL1_MOL2_cXXX.yaml
    """
    m = re.match(r'nonb_eda_(\w+)_(\w+)_c(\d+)\.yaml$', filename)
    if not m:
        return None, None, None
    return m.group(1), m.group(2), int(m.group(3))


def submit_task(yaml_path, dry_run=False):
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
    parser = argparse.ArgumentParser(description="批量提交 non-B EDA 任务")
    parser.add_argument("--dir", type=str, default="/vepfs-mlp/project-battery/lianyi/byteff2/data/volc_jobs/nonb_eda",
                        help="YAML 目录")
    parser.add_argument("--mol1", type=str, default=None,
                        help="只提交 mol1 为指定分子的任务")
    parser.add_argument("--mol2", type=str, default=None,
                        help="只提交 mol2 为指定分子的任务")
    parser.add_argument("--start", type=int, default=0,
                        help="从第 N 个任务开始提交（0-indexed，default: 0）")
    parser.add_argument("--end", type=int, default=None,
                        help="提交到第 M 个任务（exclusive，default: 全部）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅预览，不实际提交")
    parser.add_argument("--interval", type=float, default=2,
                        help="提交间隔秒数 (default: 2)")
    args = parser.parse_args()

    all_files = sorted(glob.glob(str(Path(args.dir) / "nonb_eda_*.yaml")))
    if not all_files:
        print(f"No YAML files found in {args.dir}/")
        sys.exit(1)

    selected = []
    for f in all_files:
        mol1, mol2, _ = parse_yaml_name(Path(f).name)
        if mol1 is None:
            continue
        if args.mol1 is not None and mol1 != args.mol1:
            continue
        if args.mol2 is not None and mol2 != args.mol2:
            continue
        selected.append(f)

    if not selected:
        print("No tasks match the filter criteria.")
        sys.exit(1)

    # 索引范围截取
    end = args.end if args.end is not None else len(selected)
    selected = selected[args.start:end]
    if not selected:
        print(f"No tasks in range [{args.start}, {end}).")
        sys.exit(1)

    # 按 pair 分组统计
    pair_counts = {}
    for f in selected:
        mol1, mol2, _ = parse_yaml_name(Path(f).name)
        pair = f"{mol1}_{mol2}"
        pair_counts[pair] = pair_counts.get(pair, 0) + 1

    print(f"Found {len(selected)} tasks ({len(pair_counts)} pairs):")
    for pair in sorted(pair_counts):
        print(f"  {pair}: {pair_counts[pair]} slices")
    print()

    if not args.dry_run:
        answer = input(f"Confirm submit {len(selected)} tasks? [y/N] ")
        if answer.lower() != "y":
            print("Aborted.")
            sys.exit(0)

    n_ok, n_fail = 0, 0
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
