"""Reconstruct the Q2 transport timeline (unified time axis) for Q3.

Samples every active trip at a uniform step over its [takeoff_s, return_s]
window and emits the position/phase table.  This is the *visualization / paper*
timeline; the exact blackout detection in baseline.py uses a finer step.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Q2_RESULTS, RESULTS, load_scenario
from trajectory import TransportTrajectory


def write_csv(path, records):
    if not records:
        raise ValueError(f"Refusing empty table {path}")
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)


def build_timeline(step_s: float, out_path: Path | None = None) -> list[dict]:
    tj = TransportTrajectory(Q2_RESULTS)
    rows = []
    for trip_id, trip in tj.trips().items():
        t0 = float(trip["takeoff_s"])
        t1 = float(trip["return_s"])
        t = t0
        while t < t1 + 1e-9:
            s = tj.position(trip_id, t)
            if s["phase"] != "finished":
                rows.append(dict(
                    time_s=round(t, 3), trip_id=trip_id, drone_id=trip["drone_id"],
                    x=round(s["x"], 3), y=round(s["y"], 3),
                    lon=round(s["lon"], 7), lat=round(s["lat"], 7),
                    altitude_m=round(s["altitude_m"], 3), phase=s["phase"]))
            t += step_s
    rows.sort(key=lambda r: (r["time_s"], r["trip_id"]))
    if out_path is not None:
        write_csv(out_path, rows)
    return rows


if __name__ == "__main__":
    sc = load_scenario()
    step = sc["model"]["time_step_s"]
    rows = build_timeline(step, RESULTS / "q3_transport_timeline.csv")
    print(f"timeline rows={len(rows)} step={step}s")
