"""
批量提交火山引擎任务 YAML。

用法:
    # 预览（不实际提交）
    python data/volc_jobs/submit_all.py --dry-run

    # 正式提交所有 monomer_opt_*.yaml
    python data/volc_jobs/submit_all.py

    # 只提交指定范围
    python data/volc_jobs/submit_all.py --pattern "monomer_opt_0*.yaml"

    # 提交间隔（秒），避免过快
    python data/volc_jobs/submit_all.py --interval 3
"""
import argparse
import glob
import subprocess
import time
import sys
from pathlib import Path


def submit_task(yaml_path: str, dry_run: bool = False) -> bool:
    """提交单个任务，返回是否成功"""
    cmd = ["volc", "ml_task", "submit", "-c", yaml_path]
    if dry_run:
        print(f"  [DRY-RUN] {' '.join(cmd)}")
        return True

    print(f"  Submitting {yaml_path} ... ", end="", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print("OK")
        # 打印任务ID等关键信息
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                print(f"    {line.strip()}")
        return True
    else:
        print("FAILED")
        print(f"    stderr: {result.stderr.strip()}")
        return False


def main():
    parser = argparse.ArgumentParser(description="批量提交火山引擎任务")
    parser.add_argument("--pattern", type=str, default="monomer_opt_*.yaml",
                        help="YAML 文件 glob 模式 (default: monomer_opt_*.yaml)")
    parser.add_argument("--dir", type=str, default="data/volc_jobs",
                        help="YAML 文件目录")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅预览，不实际提交")
    parser.add_argument("--interval", type=float, default=2,
                        help="两次提交之间的间隔秒数 (default: 2)")
    args = parser.parse_args()

    yaml_files = sorted(glob.glob(str(Path(args.dir) / args.pattern)))

    if not yaml_files:
        print(f"No YAML files found matching {args.dir}/{args.pattern}")
        sys.exit(1)

    print(f"Found {len(yaml_files)} tasks to submit:")
    for f in yaml_files:
        print(f"  {f}")
    print()

    if not args.dry_run:
        answer = input(f"Confirm submit {len(yaml_files)} tasks? [y/N] ")
        if answer.lower() != "y":
            print("Aborted.")
            sys.exit(0)

    n_ok = 0
    n_fail = 0
    for i, yaml_file in enumerate(yaml_files):
        success = submit_task(yaml_file, dry_run=args.dry_run)
        if success:
            n_ok += 1
        else:
            n_fail += 1
        # 非最后一个任务时等待
        if i < len(yaml_files) - 1 and not args.dry_run:
            time.sleep(args.interval)

    print(f"\nDone: {n_ok} submitted, {n_fail} failed (of {len(yaml_files)} total)")


if __name__ == "__main__":
    main()
