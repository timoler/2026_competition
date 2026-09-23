"""Aggregate the three scenarios (no relay / simple / improved) into q3_summary.csv.

Metrics are computed on the fine (1 s) connectivity grid:
  coverage, total outage, longest continuous outage, affected trips,
  relay count, relay flight time, relay work time, relay energy.
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
from schedule import verify_schedule, _sortie_rows


def outage_metrics(rp, sorties, step_s=1.0):
    """Return (coverage, outage_total_s, longest_s, affected_trips, samples)."""
    active = [(r["service_start_s"], r["service_end_s"],
               (r["hover_x_m"], r["hover_y_m"], r["hover_altitude_m"]))
              for r in sorties]
    tj = rp.tj
    # per trip outage tracking
    per_trip = {}
    for trip_id, trip in tj.trips().items():
        t0, t1 = float(trip["takeoff_s"]), float(trip["return_s"])
        t = t0
        run = 0.0
        longest = 0.0
        total = 0.0
        cur = 0.0
        while t < t1:
            st = tj.position(trip_id, t)
            if st["phase"] == "finished":
                t += step_s; continue
            p = (st["x"], st["y"], st["altitude_m"])
            ok = rp.conn.direct_ok(p) or any(
                a <= t < b and rp.conn.access_ok(p, (x, y, z)) for (a, b, (x, y, z)) in active)
            if not ok:
                cur += step_s
                total += step_s
                longest = max(longest, cur)
            else:
                cur = 0.0
            t += step_s
        per_trip[trip_id] = (total, longest, t1 - t0)
    tot_outage = sum(v[0] for v in per_trip.values())
    tot_window = sum(v[2] for v in per_trip.values())
    longest = max(v[1] for v in per_trip.values())
    affected = sum(1 for v in per_trip.values() if v[0] > 0)
    return (1 - tot_outage / tot_window), tot_outage, longest, affected, tot_window


def relay_metrics(sorties):
    flight = sum(r["flight_out_s"] + r["flight_back_s"] for r in sorties)
    work = sum((r["return_s"] - r["prep_start_s"]) for r in sorties)
    energy = sum(r["energy_kwh"] for r in sorties)
    return flight, work, energy


def _num_rows(sorties):
    out = []
    for r in sorties:
        rr = dict(r)
        for f in ("service_start_s", "service_end_s", "hover_x_m", "hover_y_m",
                  "hover_altitude_m", "flight_out_s", "flight_back_s",
                  "return_s", "prep_start_s", "energy_kwh"):
            if f in rr:
                rr[f] = float(rr[f])
        out.append(rr)
    return out


def main():
    sc = load_scenario()
    rp = RelayProblem(sc)
    cov = np.load(COV_CACHE)["cov"]
    cands = rp.candidates()

    # A: no relay
    cov_a, out_a, long_a, aff_a, win_a = outage_metrics(rp, [])

    # B: simple 1 relay at best single position
    best_single = int(np.argmax(cov.sum(axis=1)))
    # build a sortie for B
    t_arr, pos_arr, meta = rp.demand(sc["model"]["time_step_s"])
    idx = np.where(cov[best_single])[0]
    s = float(t_arr[idx].min()); e = float(t_arr[idx].max())
    k = sc["official_relay"]
    arrive = k["prep_s"] + rp.relay_sortie(cands[best_single], 0)["flight_out_s"] + k["link_build_s"]
    ss = max(s, arrive)
    sortB = rp.relay_sortie(cands[best_single], max(e - ss, 0.0))
    rowsB = _sortie_rows(rp, {"R01": [dict(hover=cands[best_single], service_start=ss,
                                            service_end=e, flight_out_s=sortB["flight_out_s"],
                                            flight_back_s=sortB["flight_back_s"],
                                            energy_kwh=sortB["energy_kwh"])], "R02": []})
    cov_b, out_b, long_b, aff_b, _ = outage_metrics(rp, rowsB)
    fl_b, wk_b, en_b = relay_metrics(rowsB)

    # C: improved 2 relays (from schedule)
    with (RESULTS / "q3_relay_schedule.csv").open(encoding="utf-8-sig") as f:
        sortiesC = _num_rows(list(csv.DictReader(f)))
    cov_c, out_c, long_c, aff_c, _ = outage_metrics(rp, sortiesC)
    fl_c, wk_c, en_c = relay_metrics(sortiesC)

    table = [
        dict(scenario="A_无中继baseline", relays=0,
             coverage=round(cov_a, 6), outage_s=round(out_a, 1),
             longest_outage_s=round(long_a, 1), affected_trips=aff_a,
             relay_flight_s=0.0, relay_work_s=0.0, relay_energy_kwh=0.0),
        dict(scenario="B_简单中继(1架)", relays=1,
             coverage=round(cov_b, 6), outage_s=round(out_b, 1),
             longest_outage_s=round(long_b, 1), affected_trips=aff_b,
             relay_flight_s=round(fl_b, 1), relay_work_s=round(wk_b, 1),
             relay_energy_kwh=round(en_b, 6)),
        dict(scenario="C_优化中继(2架)", relays=2,
             coverage=round(cov_c, 6), outage_s=round(out_c, 1),
             longest_outage_s=round(long_c, 1), affected_trips=aff_c,
             relay_flight_s=round(fl_c, 1), relay_work_s=round(wk_c, 1),
             relay_energy_kwh=round(en_c, 6)),
    ]
    write_csv(RESULTS / "q3_summary.csv", table)
    print(json.dumps(table, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
