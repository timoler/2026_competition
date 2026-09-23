"""Final two-relay schedule from static set-cover positions.

The historical greedy set cover selects a set of
hover positions that jointly cover 100% of the blackout demand; the fleet holds
two relay drones (R01/R02), so the improved schedule places the two best
positions (best pair).  The residual is quantified and attributed.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from config import RESULTS, load_scenario
from relay import RelayProblem, COV_CACHE, write_csv


def _to_lonlat(terr, x, y):
    lo, la = terr.inverse.transform(x, y)
    return float(lo), float(la)


def _sortie_rows(rp, relays):
    k = rp.sc["official_relay"]
    prep = k["prep_s"]; link = k["link_build_s"]
    rows = []
    for rid in ["R01", "R02"]:
        for s in relays[rid]:
            fout = s["flight_out_s"]; fback = s["flight_back_s"]
            prep_start = s["service_start"] - link - fout - prep
            takeoff = prep_start + prep
            lon, lat = _to_lonlat(rp.terr, s["hover"][0], s["hover"][1])
            agl = s["hover"][2] - rp.terr.elevation(s["hover"][0], s["hover"][1])
            rows.append(dict(
                relay_id=rid, hover_x_m=round(s["hover"][0], 3),
                hover_y_m=round(s["hover"][1], 3), hover_lon=round(lon, 7),
                hover_lat=round(lat, 7), hover_altitude_m=round(s["hover"][2], 3),
                agl_m=round(agl, 2), prep_start_s=round(prep_start, 1),
                takeoff_s=round(takeoff, 1), service_start_s=round(s["service_start"], 1),
                service_end_s=round(s["service_end"], 1),
                return_s=round(s["service_end"] + fback, 1),
                flight_out_s=round(fout, 1), flight_back_s=round(fback, 1),
                service_duration_s=round(s["service_end"] - s["service_start"], 1),
                energy_kwh=round(s["energy_kwh"], 6),
                return_soc=round(1 - s["energy_kwh"] / k["energy_kwh"], 6)))
    rows.sort(key=lambda r: r["service_start_s"])
    for i, r in enumerate(rows, 1):
        r["sortie_id"] = f"S{i:02d}"
        r["energy_component_id"] = f"ERC-{(i - 1) % 6 + 1:02d}"
    cols = ["sortie_id", "relay_id", "energy_component_id", "hover_x_m", "hover_y_m",
            "hover_lon", "hover_lat", "hover_altitude_m", "agl_m", "prep_start_s",
            "takeoff_s", "service_start_s", "service_end_s", "return_s",
            "flight_out_s", "flight_back_s", "service_duration_s", "energy_kwh", "return_soc"]
    return [{k: r[k] for k in cols} for r in rows]


def verify_schedule(rp, sorties, step_s=1.0):
    """Canonical 1-second / 10m verification; legacy API retained."""
    if step_s != 1.0:
        raise ValueError('Formal verification requires step_s=1')
    from strict_feasibility import validate
    v, intervals, rows = validate(sorties, 10, len(set(r['relay_id'] for r in sorties)))
    samples = [str(r['trip_id'])+'@'+str(r['start_s']) for r in intervals[:20]]
    return rows, v['uncovered_samples'], v['total_samples'], samples


def run_schedule(scenario=None):
    """Strict search replaces the old 5-second best-pair pipeline."""
    if scenario is not None:
        raise ValueError('Strict search uses the versioned scenario.json')
    from strict_feasibility import main
    return main()


if __name__ == '__main__':
    run_schedule()
