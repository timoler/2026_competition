"""Reproducible Q4 re-run on top of the Q3 two-relay (3-sortie) schedule.

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

# Q4 的真实输入依赖（只读，不得改动）。
INPUT_FILES = [
    Q3R / "q3_transport_schedule.csv",
    Q2R / "q2_inputs.json",
    Q3R / "q3_relay_schedule.csv",
    Q3R / "q3_communication_links.csv",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def q3_source_commit() -> str:
    """Last commit that touched the Q3 relay schedule (Q4's relay input)."""
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", "Q3/results/q3_relay_schedule.csv"],
            cwd=REPO, text=True,
        ).strip()
        return out or "unavailable"
    except Exception:  # pragma: no cover - git absent
        return "unavailable"


def run_py(args):
    print("\n>", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=REPO, check=True)


def main() -> int:
    t0 = time.perf_counter()
    q3_commit = q3_source_commit()
    manifest = {
        "q3_source_commit": q3_commit,
        "input_files_sha256": {
            p.relative_to(REPO).as_posix(): sha256(p) for p in INPUT_FILES
        },
    }

    # 当前分支 HEAD。
    try:
        manifest["q4_head_at_run"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip()
    except Exception:  # pragma: no cover - git absent
        manifest["q4_head_at_run"] = "unavailable"

    # 确认 Q3 来源提交确在当前历史中（避免基于旧 Q3 结果重跑）。
    if q3_commit != "unavailable":
        try:
            subprocess.check_call(
                ["git", "merge-base", "--is-ancestor", q3_commit, "HEAD"],
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
