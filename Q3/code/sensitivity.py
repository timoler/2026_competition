"""Sensitivity analysis for the key uncertain Q3 parameters.

For each perturbation we re-derive the blackout demand and the improved 2-relay
(best-pair) coverage.  To keep runtime tractable the sensitivity grid uses a
coarser demand step and candidate spacing than the production run; the metric is
the fraction of blackout samples covered by the best relay pair.

Parameters:
  relay_agl_m          hover height above ground (official: only an upper bound 300 m)
  los_clearance_m      terrain clearance for the sight-line test (not given in the topic)
  time_step_s          time-discretisation step used for the demand grid
  link_margin_db       additive link-budget margin (range sensitivity)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from config import RESULTS, load_scenario
from relay import RelayProblem, COV_CACHE, write_csv


def _improved_coverage(rp, cands, cov, nD):
    pair = rp.best_pair(cov)
    return pair[0] / nD


def _coverage_for(scenario, demand_step, cand_spacing):
    """Recompute demand + candidates + coverage + best-pair coverage for a scenario."""
    rp = RelayProblem(scenario)
    t_arr, pos_arr, meta = rp.demand(demand_step)
    cands = rp.candidates(cand_spacing)
    cov = rp.coverage(cands, pos_arr, use_cache=False)
    nD = len(pos_arr)
    pair = rp.best_pair(cov)
    return pair[0] / nD, nD


def main():
    base = load_scenario()
    results = []
    import copy

    # 1) relay AGL
    for agl in (150.0, 200.0, 250.0, 300.0):
        sc = copy.deepcopy(base)
        sc["model"]["relay_agl_m"] = agl
        cov, nD = _coverage_for(sc, 10.0, 500.0)
        results.append(dict(parameter="relay_agl_m", value=agl, improved_coverage=round(cov, 4),
                            demand_points=nD))

    # 2) LOS clearance
    for clr in (0.0, 10.0, 20.0):
        sc = copy.deepcopy(base)
        sc["model"]["los_clearance_m"] = clr
        cov, nD = _coverage_for(sc, 10.0, 500.0)
        results.append(dict(parameter="los_clearance_m", value=clr, improved_coverage=round(cov, 4),
                            demand_points=nD))

    # 3) time step
    for step in (2.0, 5.0, 10.0):
        sc = copy.deepcopy(base)
        cov, nD = _coverage_for(sc, step, 500.0)
        results.append(dict(parameter="time_step_s", value=step, improved_coverage=round(cov, 4),
                            demand_points=nD))

    # 4) link budget margin (range)
    for margin in (-3.0, 0.0, 3.0):
        sc = copy.deepcopy(base)
        sc["_link_margin_db"] = margin
        rp = RelayProblem(sc)
        # apply margin to thresholds
        rp.lb.th_direct += margin
        rp.lb.th_access += margin
        rp.lb.th_backhaul += margin
        t_arr, pos_arr, meta = rp.demand(10.0)
        cands = rp.candidates(500.0)
        cov = rp.coverage(cands, pos_arr, use_cache=False)
        pair = rp.best_pair(cov)
        results.append(dict(parameter="link_margin_db", value=margin,
                            improved_coverage=round(pair[0] / len(pos_arr), 4),
                            demand_points=len(pos_arr)))

    write_csv(RESULTS / "q3_sensitivity.csv", results)
    for r in results:
        print(r)


if __name__ == "__main__":
    main()
