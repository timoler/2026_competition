"""Reproducible Q4 re-run on top of the Q3 strict-feasibility (3-relay) schedule.

Q4 does NOT re-optimise Q3 and does not change any Q2/Q3 spatio-temporal
arrangement: it only partitions the 15 service areas (built from multi-site
transport trips) and re-accounts resources.  This wrapper pins the Q3 source
commit and the exact input files (SHA-256), then invokes the real entry points
`q4_solve.py` and `validate.py` — it does not re-implement or guess them.

Usage (from the repository root):
    python Q4/code/rerun_from_q3.py

Outputs (all under Q4/results/):
    q4_rerun_manifest.json      Q3 commit + input hashes + run status
    (plus everything q4_solve.py / validate.py normally emit)
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
Q2R = REPO / "Q2" / "results"
Q3R = REPO / "Q3" / "results"
OUT = REPO / "Q4" / "results"
CODE = REPO / "Q4" / "code"

# Q3 严格可行性复算的正式提交：三架增配中继(R01/R02/R03)达 100% 连续通信。
Q3_SOURCE_COMMIT = "274c67789d50c52ed58121c256f65b4598d5629d"

# Q4 的真实输入依赖（只读，不得改动）。
INPUT_FILES = [
    Q2R / "q2_trips.csv",
    Q2R / "q2_inputs.json",
    Q3R / "q3_relay_schedule.csv",
    Q3R / "q3_communication_links.csv",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_py(args):
    print("\n>", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=REPO, check=True)


def main() -> int:
    t0 = time.perf_counter()
    manifest = {
        "q3_source_commit": Q3_SOURCE_COMMIT,
        "input_files_sha256": {
            p.relative_to(REPO).as_posix(): sha256(p) for p in INPUT_FILES
        },
    }

    # 当前分支 HEAD（本轮在 q4 分支，含已合并的 Q3 提交）。
    try:
        manifest["q4_head_at_run"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip()
    except Exception:  # pragma: no cover - git absent
        manifest["q4_head_at_run"] = "unavailable"

    # 确认 Q3 来源提交确在当前历史中（避免基于旧 Q3 结果重跑）。
    try:
        subprocess.check_call(
            ["git", "merge-base", "--is-ancestor", Q3_SOURCE_COMMIT, "HEAD"],
            cwd=REPO,
        )
        manifest["q3_commit_in_history"] = True
    except subprocess.CalledProcessError:
        manifest["q3_commit_in_history"] = False

    # 1) 实际入口：分区枚举 + 资源核算 + 输出全部结果。
    run_py([sys.executable, "-X", "utf8", str(CODE / "q4_solve.py")])
    # 2) 实际入口：独立复核（从 Q2/Q3 原始文件重算资源占用）。
    run_py([sys.executable, "-X", "utf8", str(CODE / "validate.py")])

    val = json.loads((OUT / "q4_validation.json").read_text(encoding="utf-8"))
    manifest["q4_validation_status"] = val["status"]
    manifest["elapsed_s"] = round(time.perf_counter() - t0, 3)

    (OUT / "q4_rerun_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if val["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
