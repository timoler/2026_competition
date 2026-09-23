"""Experiment: can 2 relays (R01/R02 only) reach 100% continuous comms?

Stages (run in order, no formal results are overwritten — all outputs use
e0_/e1_/e2_/e3_/two_relay_ prefixes):
  E0  reproduce the 407-sample 2-relay baseline
  E1  finer continuous x/y/AGL search for a static 2-position cover
  E2  dynamic repositioning (each relay may fly multiple sequential sorties)
  E3  stagger transport start times (fixed routes/types/batches) + 2 relays

Formal conventions are unchanged: 1 s grid, 10 m LOS, access+backhaul both
required, AGL<=300, only R01/R02, <=6 energy components (3.2 kWh each, usable
<=2.56 kWh, return SOC>=20%). uncovered_samples==0 is required to PASS.
"""
from __future__ import annotations
import csv, json, math, sys, time
from collections import defaultdict
from pathlib import Path
import numpy as np

CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE))
from strict_feasibility import Engine, validate, table
from config import RESULTS

OUT = RESULTS
K = None  # scenario relay params, filled after first Engine


def read_csv(p):
    with Path(p).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def baseline_rows():
    return read_csv(OUT / "q3_schedule_2relay.csv")


# ---------------------------------------------------------------------------
# E0: reproduce baseline
# ---------------------------------------------------------------------------
def stage_e0():
    rows = baseline_rows()
    v, intervals, _ = validate(rows, 10, 2)
    dump("e0_baseline.json", dict(
        uncovered_samples=v["uncovered_samples"], coverage=v["coverage"],
        status=v["status"], intervals=intervals))
    print("E0", v["uncovered_samples"], v["coverage"], v["status"])
    return v


# ---------------------------------------------------------------------------
# E1: finer static position/AGL search
# ---------------------------------------------------------------------------
def _cover(e, p):
    """coverage bool array over direct-outage samples for position p."""
    c, _ = e.candidate(p)
    return c


def stage_e1():
    global K
    e = Engine(10)
    K = e.k
    rp = e.rp
    di = e.di  # indices of direct-outage samples (into pts/meta)
    # current best + failure region centre
    cur = [(float(r["hover_x_m"]), float(r["hover_y_m"]), float(r["hover_altitude_m"]))
           for r in baseline_rows()]
    # failure region: S004 low-altitude (from failure analysis)
    fx, fy = 319529.0, 2553224.7

    # identify the 407 failure sample indices (the uncovered ones of baseline)
    rows = baseline_rows()
    cover = np.ones(len(e.pts), bool); cover[di] = False
    for r in rows:
        p = (float(r["hover_x_m"]), float(r["hover_y_m"]), float(r["hover_altitude_m"]))
        a, b = float(r["service_start_s"]), float(r["service_end_s"])
        ix = di[(e.dt >= a) & (e.dt < b)]
        if e.links(p, np.array([rp.g01]), e.b[4])[0]:
            ok = e.links(p, e.pts[ix], e.b[3]); cover[ix[ok]] = True
    bad = np.where(~cover)[0]  # 407 samples

    # Fast pre-filter: a candidate covers ALL 407 failure samples iff it can
    # see the LOWEST failure point (LOS is monotonic in z for fixed x/y).  Then
    # full coverage is computed only for that (small) survivor set.
    z_lo = float(np.min(e.pts[bad, 2]))
    fail_pt = np.array([[fx, fy, z_lo]])
    print(f"failure column z range: {float(np.min(e.pts[bad,2]))}..{float(np.max(e.pts[bad,2]))}")

    cands = set()
    for agl in (300, 280, 260, 240, 220, 200):
        for dx in range(-5000, 5001, 150):
            for dy in range(-5000, 5001, 150):
                x, y = fx + dx, fy + dy
                try:
                    z = rp.terr.elevation(x, y) + agl
                except ValueError:
                    continue
                cands.add((round(x, 1), round(y, 1), round(z, 1)))
    cands = sorted(cands)
    print(f"E1 raw candidate positions: {len(cands)}")

    survivors = []
    t0 = time.time()
    for i, p in enumerate(cands):
        if not e.links(p, np.array([rp.g01]), e.b[4])[0]:  # backhaul
            continue
        if not e.links(p, fail_pt, e.b[3])[0]:             # sees lowest failure point
            continue
        survivors.append(p)
    print(f"E1 survivors (cover all 407 failures): {len(survivors)} in {round(time.time()-t0,1)}s")

    # Full coverage only for survivors; pair with R01/R02 current coverage.
    cov_r1 = _cover(e, cur[0]); cov_r2 = _cover(e, cur[1])
    best_pair_uncovered = None
    best_single_failure_coverage = len(bad) if survivors else 0
    winning = None
    t0 = time.time()
    for i, p in enumerate(survivors):
        c = _cover(e, p)
        if c is None:
            continue
        for other_cov in (cov_r1, cov_r2):
            union = np.logical_or(c, other_cov)
            uncovered = int((~union).sum())
            if best_pair_uncovered is None or uncovered < best_pair_uncovered:
                best_pair_uncovered = uncovered
            if uncovered == 0:
                winning = p
                break
        if winning is not None:
            break
        if i % 200 == 0:
            print("  ", i, "/", len(survivors), "sec", round(time.time() - t0), flush=True)

    result = dict(best_single_failure_coverage=best_single_failure_coverage,
                  n_positions_covering_all_failures=len(survivors),
                  two_position_reaches_zero=(winning is not None),
                  best_pair_uncovered=best_pair_uncovered,
                  winning_position=winning,
                  baseline_uncovered=len(bad))
    dump("e1_best.json", result)
    print("E1", json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--stage", default="all", choices=["E0", "E1", "E2", "E3", "all"])
    args = p.parse_args()
    if args.stage in ("E0", "all"):
        stage_e0()
    if args.stage in ("E1", "all"):
        stage_e1()
    # E2/E3 implemented in follow-up stages.
    if args.stage in ("E2", "E3"):
        print(f"{args.stage}: not yet implemented in this pass", file=sys.stderr)
