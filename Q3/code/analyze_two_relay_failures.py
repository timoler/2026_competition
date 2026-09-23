"""Analyse the 407 uncovered samples of the current best 2-relay schedule.

Rebuilds the 1 s demand grid via the strict Engine, re-derives the uncovered
samples after R01/R02 coverage, and for each failure records which link is
missing (direct / R01 access / R01 backhaul / R02 access / R02 backhaul) plus
the flight phase and position. Outputs per-sample, per-interval, per-trip and
cluster tables, and a JSON categorising the failures.

Does NOT modify any formal result. Only writes two_relay_failure_* files.
"""
from __future__ import annotations
import csv, json, sys
from collections import defaultdict, Counter
from pathlib import Path
import numpy as np

CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE))
from strict_feasibility import Engine, validate, table
from config import RESULTS

OUT = RESULTS


def read_csv(p):
    with Path(p).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    rows = read_csv(OUT / "q3_schedule_2relay.csv")
    relays = []
    for r in rows:
        relays.append(dict(
            relay_id=r["relay_id"],
            p=(float(r["hover_x_m"]), float(r["hover_y_m"]), float(r["hover_altitude_m"])),
            a=float(r["service_start_s"]), b=float(r["service_end_s"])))

    e = Engine(10)
    rp = e.rp
    g01 = rp.g01

    # --- replicate coverage to find the uncovered samples -------------------
    cover = np.ones(len(e.pts), bool)
    cover[e.di] = False
    for r in relays:
        ix = e.di[(e.dt >= r["a"]) & (e.dt < r["b"])]
        back = bool(e.links(r["p"], np.array([g01]), e.b[4])[0])
        if back:
            ok = e.links(r["p"], e.pts[ix], e.b[3])
            cover[ix[ok]] = True
    bad = np.where(~cover)[0]
    print(f"uncovered samples: {len(bad)}")

    # --- per-sample detail --------------------------------------------------
    sample_rows = []
    by_trip = Counter()
    intervals = []
    concurrent = Counter()  # wall-clock second -> how many drones in outage

    for ix in bad:
        tid, t, drone = e.meta[ix]
        x, y, z = e.pts[ix]
        st = rp.tj.position(tid, t)
        phase = st["phase"]
        fphase = st["flight_phase"]

        direct_ok = bool(e.links(g01, e.pts[ix:ix + 1], e.b[2])[0])
        per_relay = {}
        for r in relays:
            serving = r["a"] <= t < r["b"]
            access = bool(e.links(r["p"], e.pts[ix:ix + 1], e.b[3])[0]) if serving else False
            backhaul = bool(e.links(r["p"], np.array([g01]), e.b[4])[0])
            per_relay[r["relay_id"]] = dict(serving=serving, access=access,
                                            backhaul=backhaul)

        # classify the failure reason
        reasons = []
        if not direct_ok:
            reasons.append("direct_fail")
        for r in relays:
            rid = r["relay_id"]
            pr = per_relay[rid]
            if not pr["serving"]:
                reasons.append(f"{rid}_not_serving")
            elif not pr["backhaul"]:
                reasons.append(f"{rid}_backhaul_fail")
            elif not pr["access"]:
                reasons.append(f"{rid}_access_fail")

        sample_rows.append(dict(
            time_s=t, trip_id=tid, drone_id=drone,
            x_m=round(x, 1), y_m=round(y, 1), z_m=round(z, 1),
            phase=phase, flight_phase=fphase,
            direct_ok=direct_ok,
            R01_serving=per_relay["R01"]["serving"], R01_access=per_relay["R01"]["access"],
            R01_backhaul=per_relay["R01"]["backhaul"],
            R02_serving=per_relay["R02"]["serving"], R02_access=per_relay["R02"]["access"],
            R02_backhaul=per_relay["R02"]["backhaul"],
            reason=";".join(reasons)))

        by_trip[tid] += 1
        concurrent[t] += 1
        if intervals and intervals[-1]["trip_id"] == tid and abs(intervals[-1]["last_sample_s"] + 1 - t) < 1e-6:
            intervals[-1]["last_sample_s"] = t
            intervals[-1]["end_exclusive_s"] = t + 1
            intervals[-1]["uncovered_samples"] += 1
        else:
            intervals.append(dict(trip_id=tid, start_s=t, last_sample_s=t,
                                  end_exclusive_s=t + 1, uncovered_samples=1))

    table(OUT / "two_relay_failure_samples.csv", sample_rows)
    table(OUT / "two_relay_failure_intervals.csv", intervals,
          ["trip_id", "start_s", "last_sample_s", "end_exclusive_s", "uncovered_samples"])

    trip_rows = [dict(trip_id=tid, uncovered_samples=n) for tid, n in sorted(by_trip.items())]
    table(OUT / "two_relay_failure_by_trip.csv", trip_rows,
          ["trip_id", "uncovered_samples"])

    # --- spatial clustering (round to 100 m cell) --------------------------
    pos = e.pts[bad]
    key = np.round(pos[:, :2] / 100.0).astype(int)
    clusters = defaultdict(list)
    for i, k in enumerate(key):
        clusters[(int(k[0]), int(k[1]))].append(i)
    cluster_rows = []
    for (cx, cy), idx in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        xs = pos[idx, 0]; ys = pos[idx, 1]; zs = pos[idx, 2]
        cluster_rows.append(dict(
            cluster_x100m=cx * 100, cluster_y100m=cy * 100, n_samples=len(idx),
            x_min=round(float(xs.min()), 1), x_max=round(float(xs.max()), 1),
            y_min=round(float(ys.min()), 1), y_max=round(float(ys.max()), 1),
            z_min=round(float(zs.min()), 1), z_max=round(float(zs.max()), 1),
            trips=";".join(sorted({e.meta[bad[j]][0] for j in idx}))))
    table(OUT / "two_relay_failure_clusters.csv", cluster_rows)

    # --- categorisation summary --------------------------------------------
    reason_counter = Counter()
    for r in sample_rows:
        reason_counter[r["reason"]] += 1
    max_concurrent = max(concurrent.values()) if concurrent else 0
    n_trips = len(by_trip)
    analysis = dict(
        uncovered_samples=len(bad),
        n_failure_trips=n_trips,
        by_trip={k: v for k, v in sorted(by_trip.items())},
        n_intervals=len(intervals),
        max_continuous_outage=max(r["uncovered_samples"] for r in intervals),
        max_concurrent_drones_in_outage=max_concurrent,
        reason_counts={k: v for k, v in sorted(reason_counter.items(), key=lambda kv: -kv[1])},
        spatial_clusters=len(cluster_rows),
        top_spatial_clusters=cluster_rows[:5],
        relay_positions=[{r["relay_id"]: r["p"]} for r in relays],
    )
    (OUT / "two_relay_failure_analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
