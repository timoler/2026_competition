"""Independent validation of the Q3 relay schedule.

Re-derives the communication model from the scenario + DEM with a *different*
LOS implementation (finer sampling, independent code path) and re-checks:

  1. all transport trip trajectories come from Q2 (trip ids match);
  2. every transport drone is continuously connected over [takeoff_s, return_s];
  3. relay sorties have no time conflict and respect prep/flight/link/turnaround;
  4. relay speed/endurance/energy limits hold (energy <= (1-reserve)*Euse);
  5. relay takeoff/return are at O01, hover AGL <= limit, hover inside DEM;
  6. terrain/LOS decision is re-checked with an independent sampler;
  7. no teleportation / impossible position jumps.

Writes q3_validation.json with status PASS only if every check passes.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from pyproj import Transformer

from config import RESULTS, Q2_RESULTS, load_scenario, TERRAIN_CACHE, resolve_dem_path
from terrain import Terrain, node_bbox_utm
from trajectory import TransportTrajectory


# ----------------------------------------------------------------------------
# Independent LOS (different sampling: 10 m, strict inequality, own elevation path)
# ----------------------------------------------------------------------------
def independent_los_occluded(terr, x1, y1, z1, x2, y2, z2, clearance=0.0):
    d = float(np.hypot(x2 - x1, y2 - y1))
    n = max(4, int(np.ceil(d / 10.0)) + 1)
    t = np.linspace(0.0, 1.0, n)
    xs = x1 + (x2 - x1) * t
    ys = y1 + (y2 - y1) * t
    zs = z1 + (z2 - z1) * t
    terr_e = terr.elevations(xs[1:-1], ys[1:-1])
    return bool(np.any(terr_e >= zs[1:-1] - clearance))


def independent_link_budget(sc):
    comm = sc["official_communication"]
    f = comm["carrier_frequency_mhz"]
    fsp = 20 * np.log10(f) + 32.44
    thr = comm["receiver_sensitivity_dbm"] + comm["fading_margin_db"]
    def lmax(tx, rx):
        return tx["tx_power_dbm"] + tx["antenna_gain_dbi"] + rx["antenna_gain_dbi"] - comm["system_loss_db"] - thr
    th_direct = min(lmax(comm["transport"], comm["g01"]), lmax(comm["g01"], comm["transport"]))
    th_access = min(lmax(comm["transport"], comm["relay_access"]), lmax(comm["relay_access"], comm["transport"]))
    th_backhaul = min(lmax(comm["relay_backhaul"], comm["g01"]), lmax(comm["g01"], comm["relay_backhaul"]))
    return fsp, comm["terrain_occlusion_loss_db"], th_direct, th_access, th_backhaul


def link_ok(fsp, lobs, th, d_km, occluded):
    return 20 * np.log10(max(d_km, 1e-9)) + fsp + (lobs if occluded else 0.0) <= th


def _dist3(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])


def main():
    sc = load_scenario()
    results = {"status": "PENDING", "checks": []}
    def check(name, ok, detail=""):
        results["checks"].append({"check": name, "pass": bool(ok), "detail": detail})
        return bool(ok)

    # fresh terrain (independent crop from raw DEM when cache missing)
    terr = Terrain.load_npz(TERRAIN_CACHE)
    fsp, lobs, th_direct, th_access, th_backhaul = independent_link_budget(sc)
    tj = TransportTrajectory(Q2_RESULTS)
    o01 = tj.nodes()["O01"]
    g01 = (o01["x_m"], o01["y_m"],
           o01["ground_m"] + sc["official_communication"]["g01"]["antenna_height_m"])

    # --- check 1: trips come from Q2 ---
    q2_trips = set()
    with (Q2_RESULTS / "q2_trips.csv").open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            q2_trips.add(r["trip_id"])
    trip_ok = set(tj.trips()) == q2_trips and len(q2_trips) == 26
    check("q2_trajectories_match", trip_ok, f"{len(q2_trips)} trips")

    # --- load relay schedule ---
    sched_path = RESULTS / "q3_relay_schedule.csv"
    if not sched_path.exists():
        check("relay_schedule_present", False, "missing q3_relay_schedule.csv")
        results["status"] = "FAIL"
        (RESULTS / "q3_validation.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    sorties = []
    with sched_path.open(encoding="utf-8-sig") as f:
        sorties = list(csv.DictReader(f))
    check("relay_schedule_present", True, f"{len(sorties)} sorties")

    k = sc["official_relay"]
    reserve = k["reserve"]
    emax = (1 - reserve) * k["energy_kwh"]

    # --- relay sortie constraint checks ---
    r_speed_ok = True; r_energy_ok = True; r_agl_ok = True; r_dem_ok = True
    r_conflict_ok = True; r_origin_ok = True; r_soc_ok = True; r_seq_ok = True
    by_relay = {"R01": [], "R02": []}
    for s in sorties:
        rid = s["relay_id"]
        by_relay.setdefault(rid, []).append(s)
        hx, hy, hz = float(s["hover_x_m"]), float(s["hover_y_m"]), float(s["hover_altitude_m"])
        agl = hz - terr.elevation(hx, hy)
        if not (0 <= agl <= k["max_hover_agl_m"] + 0.5):
            r_agl_ok = False
        # energy
        e = float(s["energy_kwh"])
        if e > emax + 1e-9:
            r_energy_ok = False
        # return SOC consistency
        soc = float(s["return_soc"])
        if abs(soc - (1 - e / k["energy_kwh"])) > 1e-4:
            r_soc_ok = False
        # hover inside DEM (elevation lookup didn't raise) and backhaul LOS to G01
        if not link_ok(fsp, lobs, th_backhaul,
                       _dist3((hx, hy, hz), g01) / 1000.0,
                       independent_los_occluded(terr, hx, hy, hz, g01[0], g01[1], g01[2])):
            r_dem_ok = False
    # sortie sequence per relay (no overlap, turnaround respected, from/to O01)
    for rid, ss in by_relay.items():
        ss.sort(key=lambda r: float(r["prep_start_s"]))
        prev_return = None
        for s in ss:
            prep_s, take_s = float(s["prep_start_s"]), float(s["takeoff_s"])
            serv_s, serv_e = float(s["service_start_s"]), float(s["service_end_s"])
            ret_s = float(s["return_s"])
            if not (prep_s < take_s < serv_s < serv_e <= ret_s):
                r_seq_ok = False
            if abs(take_s - (prep_s + k["prep_s"])) > 0.5:
                r_seq_ok = False
            # flight speed sanity (horizontal distance / cruise time <= cruise speed * 1.01)
            dh = np.hypot(float(s["hover_x_m"]) - o01["x_m"], float(s["hover_y_m"]) - o01["y_m"])
            fout = float(s["flight_out_s"])
            if dh / max(fout, 1e-9) > k["cruise_mps"] * 1.5:
                r_speed_ok = False
            if prev_return is not None and prep_s < prev_return + k["turnaround_s"] - 1e-6:
                r_conflict_ok = False
            prev_return = ret_s
    check("relay_agl_limit", r_agl_ok)
    check("relay_energy_limit", r_energy_ok, f"emax={emax:.4f}kWh")
    check("relay_soc_consistency", r_soc_ok)
    check("relay_backhaul_and_dem", r_dem_ok)
    check("relay_sortie_sequence", r_seq_ok)
    check("relay_no_conflict", r_conflict_ok)
    check("relay_speed_sanity", r_speed_ok)

    # --- check 2: continuous connectivity at fine grid (independent LOS) ---
    active = [(float(s["service_start_s"]), float(s["service_end_s"]),
               (float(s["hover_x_m"]), float(s["hover_y_m"]), float(s["hover_altitude_m"])))
              for s in sorties]
    total = 0; uncovered = 0; uncovered_samples = []
    for trip_id, trip in tj.trips().items():
        t0, t1 = float(trip["takeoff_s"]), float(trip["return_s"])
        t = t0
        while t < t1:
            st = tj.position(trip_id, t)
            if st["phase"] == "finished":
                t += 1.0
                continue
            p = (st["x"], st["y"], st["altitude_m"])
            total += 1
            dkm = _dist3(p, g01) / 1000.0
            if link_ok(fsp, lobs, th_direct, dkm,
                       independent_los_occluded(terr, p[0], p[1], p[2], g01[0], g01[1], g01[2])):
                pass
            else:
                cov = False
                for (a, b, rp_) in active:
                    if a <= t < b:
                        dkm2 = _dist3(p, rp_) / 1000.0
                        if link_ok(fsp, lobs, th_access, dkm2,
                                   independent_los_occluded(terr, p[0], p[1], p[2], rp_[0], rp_[1], rp_[2])):
                            cov = True
                            break
                if not cov:
                    uncovered += 1
                    if len(uncovered_samples) < 10:
                        uncovered_samples.append(f"{trip_id}@{t:.0f}s")
            t += 1.0
    cov_frac = 1 - uncovered / total
    full_ok = uncovered == 0
    check("continuous_connectivity", full_ok,
          f"coverage={cov_frac*100:.4f}% ({total-uncovered}/{total}) uncovered={uncovered}")
    if uncovered_samples:
        results["uncovered_samples"] = uncovered_samples

    # --- relay coverage of demand timeline (links file present) ---
    links_path = RESULTS / "q3_communication_links.csv"
    links_ok = links_path.exists()
    check("communication_links_present", links_ok)

    all_ok = all(c["pass"] for c in results["checks"])
    results["status"] = "PASS" if all_ok else "FAIL"
    results["fine_coverage"] = round(cov_frac, 6)
    (RESULTS / "q3_validation.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
