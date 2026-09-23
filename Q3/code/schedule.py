"""Final two-relay schedule from static set-cover positions.

The greedy set cover over candidate hover positions finds the minimum number of
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
    active = [(r["service_start_s"], r["service_end_s"],
               (r["hover_x_m"], r["hover_y_m"], r["hover_altitude_m"]), r["relay_id"])
              for r in sorties]
    tj = rp.tj
    rows = []
    uncovered = 0; total = 0
    uncovered_samples = []
    for trip_id, trip in tj.trips().items():
        t0, t1 = float(trip["takeoff_s"]), float(trip["return_s"])
        t = t0
        while t < t1:
            st = tj.position(trip_id, t)
            if st["phase"] == "finished":
                t += step_s; continue
            p = (st["x"], st["y"], st["altitude_m"])
            total += 1
            if rp.conn.direct_ok(p):
                rows.append(dict(time_s=round(t, 1), trip_id=trip_id, drone_id=trip["drone_id"],
                                 mode="direct", relay_id=""))
            else:
                rid = ""
                for (a, b, rp_, rrid) in active:
                    if a <= t < b and rp.conn.access_ok(p, rp_):
                        rid = rrid; break
                if rid:
                    rows.append(dict(time_s=round(t, 1), trip_id=trip_id, drone_id=trip["drone_id"],
                                     mode="relay", relay_id=rid))
                else:
                    uncovered += 1
                    if len(uncovered_samples) < 20:
                        uncovered_samples.append(f"{trip_id}@{t:.0f}s")
                    rows.append(dict(time_s=round(t, 1), trip_id=trip_id, drone_id=trip["drone_id"],
                                     mode="outage", relay_id=""))
            t += step_s
    rows.sort(key=lambda r: (r["time_s"], r["trip_id"]))
    return rows, uncovered, total, uncovered_samples


def run_schedule(scenario=None):
    rp = RelayProblem(scenario)
    sc = rp.sc
    t_arr, pos_arr, meta = rp.demand(sc["model"]["time_step_s"])
    cands = rp.candidates()
    cov = rp.coverage(cands, pos_arr)
    nD = cov.shape[1]
    k = rp.sc["official_relay"]
    prep = k["prep_s"]; link = k["link_build_s"]

    # greedy set cover (positions for 100%)
    chosen = rp.greedy_set_cover(cov)
    # best pair (2 positions) and best single (1 position)
    pair = rp.best_pair(cov)
    best_single = int(np.argmax(cov.sum(axis=1)))

    # ---- improved schedule: 2 relays at best pair ----
    pair_idx = [pair[1], pair[2]]
    # assignment: each demand point -> first covering position of the pair
    assignment = np.full(nD, -1, dtype=int)
    for c in pair_idx:
        m = cov[c] & (assignment < 0)
        assignment[m] = c
    relays = {"R01": [], "R02": []}
    for rid, c in zip(["R01", "R02"], pair_idx):
        idx = np.where(assignment == c)[0]
        s = float(t_arr[idx].min()) if len(idx) else 0.0
        e = float(t_arr[idx].max()) if len(idx) else 0.0
        sort0 = rp.relay_sortie(cands[c], 0.0)
        # earliest feasible service start from O01 at t=0
        fout, fback = sort0["flight_out_s"], sort0["flight_back_s"]
        arrive = prep + fout + link
        ss = max(s, arrive)
        if ss > s + 1e-6:
            # first blackout too early; still serve (arrive late)
            pass
        dur = e - ss
        sort = rp.relay_sortie(cands[c], max(dur, 0.0))
        relays[rid].append(dict(hover=cands[c], service_start=ss, service_end=e,
                                flight_out_s=fout, flight_back_s=fback,
                                energy_kwh=sort["energy_kwh"]))
    sorties = _sortie_rows(rp, relays)
    write_csv(RESULTS / "q3_relay_schedule.csv", sorties)

    rows, uncovered, total, samples = verify_schedule(rp, sorties, step_s=1.0)
    write_csv(RESULTS / "q3_communication_links.csv", rows)
    cov_frac = 1 - uncovered / total

    # ---- 3-position reference (for the 100% note) ----
    three_cov = int(np.logical_or.reduce(cov[chosen], axis=0).sum())

    summary = dict(
        n_relays_used=2, n_positions_improved=2, n_positions_full=len(chosen),
        improved_pair=[cands[pair[1]], cands[pair[2]]],
        full_set_cover_positions=[cands[c] for c in chosen],
        best_single_coverage=int(cov[best_single].sum()),
        best_pair_coverage=pair[0],
        full_set_cover_coverage=three_cov,
        total_demand=nD, fine_total=total, fine_uncovered=uncovered,
        fine_coverage=round(cov_frac, 6),
        uncovered_samples=samples)
    (RESULTS / "q3_schedule_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[schedule] improved 2-relay fine coverage={cov_frac*100:.4f}% "
          f"({total-uncovered}/{total}) uncov={uncovered}")
    print(f"[schedule] set cover: {len(chosen)} positions -> {three_cov}/{nD} (5s grid); "
          f"best pair={pair[0]}/{nD}; best single={int(cov[best_single].sum())}/{nD}")
    for s in sorties:
        print(f"    {s['sortie_id']} {s['relay_id']} "
              f"x={s['hover_x_m']:.0f} y={s['hover_y_m']:.0f} z={s['hover_altitude_m']:.0f} "
              f"serve=[{s['service_start_s']},{s['service_end_s']}] energy={s['energy_kwh']:.4f}kWh")
    return summary


if __name__ == "__main__":
    run_schedule()
