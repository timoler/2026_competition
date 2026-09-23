"""No-relay baseline: detect where the Q2 transport plan loses communication.

For every trip, samples its [takeoff_s, return_s] window at a fine step and
checks direct G01 connectivity.  Consecutive outage samples are merged into
blackout intervals.  Also emits a readable per-sample connectivity table.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Q2_RESULTS, RESULTS, load_scenario, TERRAIN_CACHE, resolve_dem_path
from terrain import Terrain, node_bbox_utm
from communication import LinkBudget, Connectivity
from trajectory import TransportTrajectory


def write_csv(path, records):
    if not records:
        raise ValueError(f"Refusing empty table {path}")
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)


def load_terrain_and_connectivity(sc):
    if TERRAIN_CACHE.exists():
        terr = Terrain.load_npz(TERRAIN_CACHE)
    else:
        terr = Terrain.load_mat(resolve_dem_path(sc))
        m = sc["model"]["terrain_margin_m"]
        tj = TransportTrajectory(Q2_RESULTS)
        xmin, xmax, ymin, ymax = node_bbox_utm(tj.nodes())
        terr = terr.crop(xmin - m, xmax + m, ymin - m, ymax + m)
        terr.save_npz(TERRAIN_CACHE)
    lb = LinkBudget(sc["official_communication"], sc["official_relay"])
    tj = TransportTrajectory(Q2_RESULTS)
    o01 = tj.nodes()["O01"]
    g01 = (o01["x_m"], o01["y_m"],
           o01["ground_m"] + sc["official_communication"]["g01"]["antenna_height_m"])
    conn = Connectivity(terr, lb, g01, sc["model"]["los_clearance_m"],
                        sc["model"]["cruise_sample_spacing_m"])
    return terr, conn


def detect_blackouts(step_s: float = 1.0) -> tuple[list[dict], dict]:
    sc = load_scenario()
    terr, conn = load_terrain_and_connectivity(sc)
    tj = TransportTrajectory(Q2_RESULTS)

    intervals = []
    per_trip = {}
    for trip_id, trip in tj.trips().items():
        drone = trip["drone_id"]
        t0 = float(trip["takeoff_s"])
        t1 = float(trip["return_s"])
        t = t0
        run_start = None
        run_end = None
        run_pos_start = None
        run_reason = None
        total_outage = 0.0
        while t < t1 + 1e-9:
            s = tj.position(trip_id, t)
            if s["phase"] == "finished":
                t += step_s
                continue
            p = (s["x"], s["y"], s["altitude_m"])
            det = conn.direct_detail(p)
            if not det["ok"]:
                reason = "link_budget" if not det["occluded"] else "terrain_occlusion"
                if run_start is None:
                    run_start = t
                    run_pos_start = f"{s['lon']:.7f},{s['lat']:.7f},{s['altitude_m']:.2f}"
                    run_reason = reason
                run_end = t
                run_pos_end = f"{s['lon']:.7f},{s['lat']:.7f},{s['altitude_m']:.2f}"
            else:
                if run_start is not None:
                    dur = (run_end - run_start) + step_s
                    intervals.append(dict(trip_id=trip_id, drone_id=drone,
                                          start_s=round(run_start, 3), end_s=round(run_end + step_s, 3),
                                          duration_s=round(dur, 3),
                                          start_position=run_pos_start, end_position=run_pos_end,
                                          reason=run_reason))
                    total_outage += dur
                    run_start = run_end = None
            t += step_s
        if run_start is not None:
            dur = (run_end - run_start) + step_s
            intervals.append(dict(trip_id=trip_id, drone_id=drone,
                                  start_s=round(run_start, 3), end_s=round(run_end + step_s, 3),
                                  duration_s=round(dur, 3),
                                  start_position=run_pos_start, end_position=run_pos_end,
                                  reason=run_reason))
            total_outage += dur
        per_trip[trip_id] = dict(drone_id=drone, window_s=round(t1 - t0, 3),
                                 outage_s=round(total_outage, 3),
                                 coverage=round(1 - total_outage / (t1 - t0), 6))

    total_window = sum(v["window_s"] for v in per_trip.values())
    total_outage = sum(v["outage_s"] for v in per_trip.values())
    summary = dict(total_window_s=round(total_window, 3),
                   total_outage_s=round(total_outage, 3),
                   coverage=round(1 - total_outage / total_window, 6),
                   blackout_interval_count=len(intervals),
                   affected_trips=sum(1 for v in per_trip.values() if v["outage_s"] > 0))
    return intervals, per_trip, summary


def build_baseline_table(step_s: float = 5.0) -> list[dict]:
    sc = load_scenario()
    terr, conn = load_terrain_and_connectivity(sc)
    tj = TransportTrajectory(Q2_RESULTS)
    rows = []
    for trip_id, trip in tj.trips().items():
        t0 = float(trip["takeoff_s"])
        t1 = float(trip["return_s"])
        t = t0
        while t < t1 + 1e-9:
            s = tj.position(trip_id, t)
            if s["phase"] == "finished":
                t += step_s
                continue
            det = conn.direct_detail((s["x"], s["y"], s["altitude_m"]))
            mode = "direct" if det["ok"] else "outage"
            reason = "" if det["ok"] else ("link_budget" if not det["occluded"] else "terrain_occlusion")
            rows.append(dict(time_s=round(t, 3), trip_id=trip_id, drone_id=trip["drone_id"],
                             x=round(s["x"], 3), y=round(s["y"], 3),
                             altitude_m=round(s["altitude_m"], 3), phase=s["phase"],
                             connected=int(det["ok"]), mode=mode, reason=reason))
            t += step_s
    rows.sort(key=lambda r: (r["time_s"], r["trip_id"]))
    return rows


if __name__ == "__main__":
    sc = load_scenario()
    intervals, per_trip, summary = detect_blackouts(step_s=1.0)
    write_csv(RESULTS / "q3_blackout_intervals.csv", intervals)
    table = build_baseline_table(step_s=sc["model"]["time_step_s"])
    write_csv(RESULTS / "q3_baseline_communication.csv", table)
    per_trip_rows = [dict(trip_id=k, **v) for k, v in sorted(per_trip.items())]
    write_csv(RESULTS / "q3_baseline_per_trip.csv", per_trip_rows)
    (RESULTS / "q3_baseline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("baseline summary:", json.dumps(summary, ensure_ascii=False))
    print("blackout intervals:", len(intervals))
    for it in intervals[:15]:
        print("  ", it["trip_id"], it["drone_id"], f"{it['start_s']}-{it['end_s']}s",
              f"{it['duration_s']}s", it["reason"])
