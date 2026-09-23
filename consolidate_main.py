#!/usr/bin/env python3
"""Consolidate timoler/2026_competition: unify main, archive & delete q1..q4.

Fail-fast and idempotent. Runs in a fresh temporary clone so no teammate
worktree is touched. Phases (run in order; each re-reads the remote state):

    python consolidate_main.py prepare       # clone + fetch + record SHAs + verify ancestry
    python consolidate_main.py archive       # create archive/consolidation tags + push
    python consolidate_main.py fast-forward  # fast-forward local main to q4
    #  [manual: edit root README.md / BRANCHES.md / 上传规范.md, commit to main, push]
    python consolidate_main.py delete        # re-verify remote tips, delete q1..q4

Every destructive step re-verifies the remote before acting. Archive tags are
only created when they do not already point at the recorded tip (no re-creation
on re-run). Branch deletion is skipped for any branch whose remote tip moved,
is not an ancestor of main, or whose archive tag is missing on the remote.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_URL = "https://github.com/timoler/2026_competition.git"
BRANCHES = ["main", "q1", "q2", "q3", "q4"]
DELETE_BRANCHES = ["q1", "q2", "q3", "q4"]
TAG_PREFIX = "archive/consolidation"

WORK = Path(tempfile.gettempdir()) / "competition_consolidation"
STATE = WORK / "state.json"
CLONE = WORK / "repo"


def sh(*args, cwd=None, check=True):
    return subprocess.run(list(map(str, args)), cwd=str(cwd), check=check,
                         text=True, capture_output=True)


def sh_out(*args, cwd=None):
    return sh(*args, cwd=cwd).stdout.strip()


def now_stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8"))


def save_state(d: dict):
    WORK.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_clone():
    if (CLONE / ".git").exists():
        return
    WORK.mkdir(parents=True, exist_ok=True)
    sh("git", "clone", "--no-local", REPO_URL, str(CLONE))
    sh("git", "fetch", "--all", "--tags", "--prune", cwd=CLONE)


def git_refs():
    out = sh_out("git", "for-each-ref", "--format=%(refname:short) %(objectname)",
                 "refs/remotes/origin", cwd=CLONE)
    refs = {}
    for line in out.splitlines():
        name, sha = line.split()
        if name.startswith("origin/"):
            refs[name[len("origin/"):]] = sha
    return refs


def phase_prepare():
    ensure_clone()
    refs = git_refs()
    for b in BRANCHES:
        if b not in refs:
            sys.exit(f"FAIL: origin/{b} missing")
    q4 = refs["q4"]
    for b in ["main", "q1", "q2", "q3"]:
        r = subprocess.run(
            ["git", "merge-base", "--is-ancestor", refs[b], q4],
            cwd=str(CLONE), capture_output=True)
        if r.returncode != 0:
            sys.exit(f"FAIL: origin/{b} ({refs[b]}) is not an ancestor of "
                     f"origin/q4 ({q4}); abort, no overwrite")
    save_state({
        "recorded_at": now_stamp(),
        "branch_tips": {b: refs[b] for b in BRANCHES},
        "q4": q4,
    })
    print(json.dumps(load_state(), ensure_ascii=False, indent=2))


def phase_archive():
    st = load_state()
    sh("git", "fetch", "--all", "--tags", "--prune", cwd=CLONE)
    refs = git_refs()
    stamp = now_stamp()
    created = []
    for b in BRANCHES:
        tip = refs.get(b)
        if tip != st["branch_tips"][b]:
            sys.exit(f"FAIL: origin/{b} moved ({st['branch_tips'][b]} -> {tip}); "
                     f"refusing to tag stale tip")
        tag = f"{TAG_PREFIX}/{b}-{stamp}"
        existing = sh_out("git", "tag", "--list", "--points-at", tip,
                          f"{TAG_PREFIX}/{b}-*", cwd=CLONE)
        if existing:
            print(f"SKIP {b}: already archived at {existing}")
            continue
        sh("git", "tag", "-a", tag, "-m",
           f"archive/consolidation of {b} @ {tip} ({stamp})", tip, cwd=CLONE)
        created.append((b, tag, tip))
    if created:
        sh("git", "push", "origin", *[t for _, t, _ in created], cwd=CLONE)
        for b, tag, tip in created:
            print(f"TAG {tag} -> {tip}")
    else:
        print("no new tags created (already archived)")
    sh("git", "fetch", "--all", "--tags", "--prune", cwd=CLONE)


def phase_fast_forward():
    st = load_state()
    sh("git", "fetch", "--all", "--tags", "--prune", cwd=CLONE)
    q4_now = git_refs().get("q4")
    if q4_now != st["q4"]:
        sys.exit(f"FAIL: origin/q4 moved ({st['q4']} -> {q4_now}); abort")
    sh("git", "checkout", "main", cwd=CLONE)
    sh("git", "merge", "--ff-only", st["q4"], cwd=CLONE)
    head = sh_out("git", "rev-parse", "HEAD", cwd=CLONE)
    if head != st["q4"]:
        sys.exit(f"FAIL: fast-forward did not land on q4 ({head} != {st['q4']})")
    print(f"main fast-forwarded to {head}")
    print("NEXT: edit root README.md / BRANCHES.md / 上传规范.md, "
          "commit to main (do NOT touch Q1/Q2/Q3/Q4), then push.")


def phase_delete():
    st = load_state()
    sh("git", "fetch", "--all", "--tags", "--prune", cwd=CLONE)
    refs = git_refs()
    main_sha = refs.get("main")
    if main_sha is None:
        sys.exit("FAIL: origin/main missing")
    for b in DELETE_BRANCHES:
        tip = refs.get(b)
        if tip is None:
            print(f"SKIP {b}: already absent on remote")
            continue
        if tip != st["branch_tips"][b]:
            print(f"SKIP {b}: remote moved ({st['branch_tips'][b]} -> {tip}); NOT deleting")
            continue
        r = subprocess.run(["git", "merge-base", "--is-ancestor", tip, main_sha],
                           cwd=str(CLONE), capture_output=True)
        if r.returncode != 0:
            print(f"SKIP {b}: {tip} is not an ancestor of main {main_sha}; NOT deleting")
            continue
        tags = sh_out("git", "ls-remote", "--tags", "origin",
                      f"{TAG_PREFIX}/{b}-*", cwd=CLONE)
        if not tags or tip not in tags:
            print(f"SKIP {b}: no archive tag pointing at {tip} on remote; NOT deleting")
            continue
        sh("git", "push", "origin", "--delete", b, cwd=CLONE)
        print(f"DELETED origin/{b} ({tip})")
    sh("git", "fetch", "--all", "--tags", "--prune", cwd=CLONE)
    final = git_refs()
    print("\nremote branches now:", sorted(final))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["prepare", "archive", "fast-forward", "delete"])
    args = p.parse_args()
    globals()[f"phase_{args.phase.replace('-', '_')}"]()


if __name__ == "__main__":
    main()
