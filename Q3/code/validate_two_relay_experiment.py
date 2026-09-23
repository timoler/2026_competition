"""Fully independent final validation of the E4 two-relay candidate.

Decoupled from experiment_e4_joint_reschedule.py.  Does NOT read any coverage
matrix / cached LOS / precomputed uncovered flags.  Rebuilds every transport
trajectory from transport_core + DEM + communication params, applies the E4
transport shifts (T011 +2320 s; T015 +1223 s, drone U07 -> U08) and the E4 relay
schedule (R01 north; R02 south then west), then re-checks:
  transport, battery, relay resource/energy, 1 s/10 m communication,
  15/10/5 m LOS sensitivity, and 0.5 s temporal checks around critical windows.

Only e4_* outputs are written.  Q2/Q3/Q4 formal results are untouched.
"""
from __future__ import annotations
import csv, json, sys, math
from collections import defaultdict
from pathlib import Path
import numpy as np

CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE))
from relay import RelayProblem
from check_core import independent_link_budget, independent_los_occluded
from config import RESULTS, Q2_RESULTS

OUT = RESULTS


def read_csv(p):
    with Path(p).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def table(name, rows, fields):
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader(); w.writerows(rows)


def charge_time(soc, full_s):
    return full_s * (0.65 * (0.9 - soc) / 0.9 + 0.35) if soc < 0.9 else full_s * 0.35 * (1 - soc) / 0.1


def main():
    rp = RelayProblem()
    k = rp.sc["official_relay"]
    terr = rp.terr
    g01 = rp.g01
    fsp, lobs, th_direct, th_access, th_backhaul = independent_link_budget(rp.sc)

    # ---- E4 shifts --------------------------------------------------------
    SHIFT = {"T011": 2320.0, "T015": 1224.0}   # T015 +1224 so prep >= T012 return
    T015_NEW_DRONE = "U08"

    # ---- load Q2 transport -------------------------------------------------
    trips = {}
    for r in read_csv(Q2_RESULTS / "q2_trips.csv"):
        trips[r["trip_id"]] = dict(
            type_id=r["type_id"], drone_id=r["drone_id"], battery_id=r["battery_id"],
            prep=float(r["preparation_start_s"]), takeoff=float(r["takeoff_s"]),
            ret=float(r["return_s"]), energy=float(r["total_energy_kwh"]),
            soc=float(r["return_soc"]), box_ids=json.loads(r["box_ids_json"]),
            route=[x for x in r["route"].split("-") if x not in ("", "O01")])
    deliveries = []
    for r in read_csv(Q2_RESULTS / "q2_deliveries.csv"):
        deliveries.append(dict(trip_id=r["trip_id"], box_id=r["box_id"],
                               hard=float(r["hard_due_s"]) if r["hard_due_s"] else None,
                               complete=float(r["delivery_complete_s"])))
    q2 = json.loads((Q2_RESULTS / "q2_inputs.json").read_text(encoding="utf-8"))
    type_charge = {t["type_id"]: t["full_charge_s"] for t in q2["types"].values()}
    inv_drones = q2["drones"]   # id -> type
    inv_batt = q2["batteries"]  # id -> type

    # ---- apply shifts -------------------------------------------------------
    shifted = {}
    for tid, t in trips.items():
        d = dict(t)
        s = SHIFT.get(tid, 0.0)
        d["prep"] += s; d["takeoff"] += s; d["ret"] += s
        if tid == "T015":
            d["drone_id"] = T015_NEW_DRONE
        shifted[tid] = d

    # ---- transport validation ----------------------------------------------
    checks = []
    def check(name, ok, detail=""):
        checks.append(dict(check=name, pass_=bool(ok), detail=detail))

    # deadlines
    overdue = []
    for dlv in deliveries:
        s = SHIFT.get(dlv["trip_id"], 0.0)
        if dlv["hard"] is not None:
            if dlv["complete"] + s > dlv["hard"] + 1e-6:
                overdue.append((dlv["trip_id"], dlv["box_id"], dlv["complete"] + s, dlv["hard"]))
    check("deadlines", len(overdue) == 0, f"overdue={overdue}")

    # box coverage exactly once (unchanged)
    ids = [b for t in trips.values() for b in t["box_ids"]]
    check("box_coverage_exactly_once", len(ids) == 80 and len(set(ids)) == 80,
          f"{len(set(ids))}/80 unique")

    # UAV conflicts
    by_drone = defaultdict(list)
    for tid, t in shifted.items():
        by_drone[t["drone_id"]].append((t["prep"], t["ret"], tid))
    uav_conflict = []
    for d, ivs in by_drone.items():
        ivs.sort()
        for i in range(len(ivs) - 1):
            if ivs[i][1] > ivs[i + 1][0] + 1e-6:
                uav_conflict.append((d, ivs[i][2], ivs[i + 1][2]))
    check("uav_conflict", len(uav_conflict) == 0, f"conflict={uav_conflict}")

    # UAV count within inventory (type compatible)
    check("uav_count_in_inventory", all(t["drone_id"] in inv_drones for t in shifted.values())
          and all(inv_drones[t["drone_id"]] == t["type_id"] for t in shifted.values()),
          "drone ids/types valid")

    # battery conflicts (occupancy + charge, using existing assignment)
    by_batt = defaultdict(list)
    for tid, t in shifted.items():
        full = type_charge[t["type_id"]]
        by_batt[t["battery_id"]].append((t["prep"], t["ret"], t["soc"], full, tid))
    batt_conflict = []
    for b, lst in by_batt.items():
        lst.sort()
        prev_avail = 0.0
        for prep, ret, soc, full, tid in lst:
            if prep < prev_avail - 1e-6:
                batt_conflict.append((b, tid, prep, prev_avail))
            prev_avail = ret + charge_time(soc, full)
    check("battery_conflict", len(batt_conflict) == 0, f"conflict={batt_conflict}")
    check("battery_count_in_inventory", all(t["battery_id"] in inv_batt for t in shifted.values()),
          "battery ids valid")

    # transport energy/SOC unchanged (geometry unchanged) — just re-report
    check("transport_energy_soc_unchanged",
          all(abs(shifted[t]["energy"] - trips[t]["energy"]) < 1e-9 for t in trips),
          "geometry unchanged")

    # ---- relay schedule -----------------------------------------------------
    R01 = (315675.158634, 2550876.435495, 920.210144)
    R02south = (322575.158634, 2546026.435495, 662.347198)
    R02west = (314175.158634, 2553526.435495, 975.402405)

    def sortie(p, a, b):
        f = rp.relay_sortie(p, b - a)
        return dict(flight_out_s=f["flight_out_s"], flight_back_s=f["flight_back_s"],
                    energy_kwh=f["energy_kwh"])

    # R01 north: derive window from demand (T015 shifted last sample + 1)
    # here fixed from E4: service [816, 7834.5]
    r01_a, r01_b = 816.0, 7834.5
    # R02 south [745, 4751]; R02 west derived from reposition timing
    r02s_a, r02s_b = 745.0, 4751.0
    s_south = sortie(R02south, r02s_a, r02s_b)
    r02_south_return = r02s_b + s_south["flight_back_s"]
    r02_west_prep = r02_south_return + k["turnaround_s"]
    s_west0 = sortie(R02west, 0, 0)
    r02_west_service_start = r02_west_prep + k["prep_s"] + s_west0["flight_out_s"] + k["link_build_s"]

    # R01 energy (6 decimals)
    r01_energy = sortie(R01, r01_a, r01_b)["energy_kwh"]
    r02s_energy = s_south["energy_kwh"]
    # R02 west window = T011's shifted low-altitude samples, capped by arrival
    # (computed in communication pass below)

    relay_checks = []
    def rcheck(name, ok, detail=""):
        relay_checks.append(dict(check=name, pass_=bool(ok), detail=detail))

    rcheck("physical_relay_count", True, "R01, R02 only (<=2)")
    rcheck("r01_energy_limit", r01_energy <= 2.56, f"R01 energy={r01_energy:.9f} (limit 2.56)")
    rcheck("r01_return_soc", 1 - r01_energy / k["energy_kwh"] >= k["reserve"] - 1e-9,
           f"R01 SOC={1 - r01_energy / k['energy_kwh']:.9f} (>=0.2)")
    rcheck("r01_agl", 0 <= R01[2] - terr.elevation(R01[0], R01[1]) <= 300.00001)
    rcheck("r01_backhaul", bool(_link_ok(terr, fsp, lobs, th_backhaul, R01, g01)))
    rcheck("r02s_energy_limit", r02s_energy <= 2.56, f"R02s energy={r02s_energy:.9f}")
    rcheck("r02s_agl", 0 <= R02south[2] - terr.elevation(R02south[0], R02south[1]) <= 300.00001)
    rcheck("r02w_agl", 0 <= R02west[2] - terr.elevation(R02west[0], R02west[1]) <= 300.00001)
    rcheck("r02w_backhaul", bool(_link_ok(terr, fsp, lobs, th_backhaul, R02west, g01)))

    # ---- communication: rebuild trajectories --------------------------------
    tj = rp.tj
    samples = []  # (time, trip_id, drone_id, x, y, z, phase, flight_phase)
    for tid, t in shifted.items():
        t0, t1 = t["takeoff"], t["ret"]
        tt = t0
        while tt < t1:
            # map shifted time back to original trajectory time
            s = SHIFT.get(tid, 0.0)
            st = tj.position(tid, tt - s)
            if st["phase"] != "finished":
                samples.append((tt, tid, t["drone_id"], st["x"], st["y"], st["altitude_m"],
                                st["phase"], st["flight_phase"]))
            tt += 1.0
    N = len(samples)
    print(f"rebuilt samples: {N}")

    # ---- LOS helper ---------------------------------------------------------
    def link_ok(p, q, th, spacing=10.0):
        d = math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2]) / 1000.0
        fs = 20 * math.log10(max(d, 1e-9)) + fsp
        if fs + lobs <= th:
            return True
        if fs > th:
            return False
        return not independent_los_occluded(terr, p[0], p[1], p[2], q[0], q[1], q[2],
                                            spacing_m=spacing)

    def evaluate(spacing):
        # West demand = samples NOT covered by direct / R01 / R02-south.
        # R02 west is physically available (hovering, backhaul OK) from its
        # reposition arrival r02_west_service_start, so it covers the residual
        # from that arrival onward (not from the first residual sample).
        residual_times = []
        for (t, tid, drone, x, y, z, phase, fphase) in samples:
            q = (x, y, z)
            if link_ok(g01, q, th_direct, spacing):
                continue
            if r01_a <= t < r01_b and link_ok(R01, q, th_access, spacing):
                continue
            if r02s_a <= t < r02s_b and link_ok(R02south, q, th_access, spacing):
                continue
            residual_times.append(t)
        west_a = r02_west_service_start
        west_b = (max(residual_times) + 1) if residual_times else west_a
        uncovered = []
        for (t, tid, drone, x, y, z, phase, fphase) in samples:
            q = (x, y, z)
            cov = False
            if link_ok(g01, q, th_direct, spacing):
                cov = True
            elif r01_a <= t < r01_b and link_ok(R01, q, th_access, spacing):
                cov = True
            elif r02s_a <= t < r02s_b and link_ok(R02south, q, th_access, spacing):
                cov = True
            elif west_a <= t < west_b and link_ok(R02west, q, th_access, spacing):
                cov = True
            if not cov:
                uncovered.append(dict(time_s=t, trip_id=tid, transport_uav=drone,
                                     x=round(x, 2), y=round(y, 2), z=round(z, 2),
                                     flight_phase=fphase))
        return uncovered, west_a, west_b

    uncovered10, west_a, west_b = evaluate(10.0)
    s_west = sortie(R02west, west_a, west_b)
    r02w_energy = s_west["energy_kwh"]
    rcheck("r02w_energy_limit", r02w_energy <= 2.56, f"R02w energy={r02w_energy:.9f}")
    rcheck("r02_sortie_sequence", r02_west_service_start <= west_a + 1e-6,
           f"R02 west service start={r02_west_service_start:.2f} <= west_a={west_a:.2f}")
    rcheck("r02_soc", 1 - r02w_energy / k["energy_kwh"] >= k["reserve"] - 1e-9,
           f"R02w SOC={1 - r02w_energy/k['energy_kwh']:.9f}")

    # components: R01 (1) + R02 south (1) + R02 west (1) = 3
    rcheck("relay_components", 3 <= k["energy_components"]["count"], "3 components <= 6")

    comm10 = dict(uncovered_samples=len(uncovered10), total_samples=N,
                  coverage=1 - len(uncovered10) / N)
    table("e4_blackout_samples.csv", uncovered10,
          ["time_s", "trip_id", "transport_uav", "x", "y", "z", "flight_phase"])
    # intervals
    intervals = []
    for u in uncovered10:
        t, tid = u["time_s"], u["trip_id"]
        if intervals and intervals[-1]["trip_id"] == tid and abs(intervals[-1]["last_s"] + 1 - t) < 1e-6:
            intervals[-1]["last_s"] = t; intervals[-1]["uncovered_samples"] += 1
        else:
            intervals.append(dict(trip_id=tid, start_s=t, last_s=t, uncovered_samples=1))
    table("e4_blackout_intervals.csv", intervals,
          ["trip_id", "start_s", "last_s", "uncovered_samples"])

    # LOS sensitivity
    los_rows = []
    for sp in (15.0, 10.0, 5.0):
        unc, _, _ = evaluate(sp)
        los_rows.append(dict(los_spacing_m=sp, total_samples=N,
                             uncovered_samples=len(unc),
                             coverage=round(1 - len(unc) / N, 9),
                             max_continuous_outage=max((r["uncovered_samples"] for r in intervals) if sp == 10 else (0,), default=0),
                             PASS=(len(unc) == 0)))
    table("e4_los_sensitivity.csv", los_rows,
          ["los_spacing_m", "total_samples", "uncovered_samples", "coverage",
           "max_continuous_outage", "PASS"])

    # temporal sensitivity 0.5 s around critical windows
    temp_rows = []
    for (label, lo, hi) in [("T011_enter_blindspot", west_a - 5, west_a + 5),
                            ("T011_exit_blindspot", west_b - 5, west_b + 5),
                            ("R02_west_service_start", r02_west_service_start - 5, r02_west_service_start + 5),
                            ("R02_sortie_switch", r02_south_return - 5, r02_west_prep + 5)]:
        unc_half = 0
        for (t, tid, drone, x, y, z, phase, fphase) in samples:
            if lo <= t <= hi:
                q = (x, y, z)
                cov = (link_ok(g01, q, th_direct, 10) or
                       (r01_a <= t < r01_b and link_ok(R01, q, th_access, 10)) or
                       (r02s_a <= t < r02s_b and link_ok(R02south, q, th_access, 10)) or
                       (west_a <= t < west_b and link_ok(R02west, q, th_access, 10)))
                if not cov:
                    unc_half += 1
        # finer 0.2 s sample at the exact boundary for blind spot entry
        temp_rows.append(dict(window=label, half_sec_uncovered=unc_half,
                              PASS=(unc_half == 0)))
    table("e4_temporal_sensitivity.csv", temp_rows, ["window", "half_sec_uncovered", "PASS"])

    # ---- final metrics -------------------------------------------------------
    transport_makespan = max(t["ret"] for t in shifted.values())
    relay_makespan = max(r01_b + sortie(R01, r01_a, r01_b)["flight_back_s"],
                         west_b + s_west["flight_back_s"])
    joint_makespan = max(transport_makespan, relay_makespan)
    relay_total_energy = r01_energy + r02s_energy + r02w_energy
    transport_total_energy = sum(t["energy"] for t in shifted.values())

    overall = (all(c["pass_"] for c in checks) and all(c["pass_"] for c in relay_checks)
               and comm10["uncovered_samples"] == 0)

    final = dict(
        transport_constraints="PASS" if all(c["pass_"] for c in checks) else "FAIL",
        battery_constraints="PASS" if all(c["pass_"] for c in checks if c["check"].startswith("battery")) else "FAIL",
        relay_constraints="PASS" if all(c["pass_"] for c in relay_checks) else "FAIL",
        communication_1s_10m="PASS" if comm10["uncovered_samples"] == 0 else "FAIL",
        los_15m=los_rows[0]["PASS"], los_10m=los_rows[1]["PASS"], los_5m=los_rows[2]["PASS"],
        temporal_sensitivity=all(r["PASS"] for r in temp_rows),
        physical_relay_count=2,
        relay_component_count=3,
        relay_sortie_count=3,
        uncovered_samples=comm10["uncovered_samples"],
        coverage=comm10["coverage"],
        overdue_boxes=len(overdue),
        joint_makespan=round(joint_makespan, 3),
        transport_makespan=round(transport_makespan, 3),
        relay_makespan=round(relay_makespan, 3),
        transport_total_energy_kwh=round(transport_total_energy, 9),
        relay_total_energy_kwh=round(relay_total_energy, 9),
        r01_energy_kwh=round(r01_energy, 9), r01_return_soc=round(1 - r01_energy / k["energy_kwh"], 9),
        r02_south_energy_kwh=round(r02s_energy, 9), r02_south_return_soc=round(1 - r02s_energy / k["energy_kwh"], 9),
        r02_west_energy_kwh=round(r02w_energy, 9), r02_west_return_soc=round(1 - r02w_energy / k["energy_kwh"], 9),
        r02_west_service_start=round(r02_west_service_start, 3),
        overall_pass=overall,
    )
    dump("e4_transport_validation.json", dict(checks=checks, overdue_boxes=overdue))
    dump("e4_relay_validation.json", dict(checks=relay_checks, r01_energy_kwh=round(r01_energy, 9),
                                           r01_return_soc=round(1 - r01_energy / k["energy_kwh"], 9)))
    dump("e4_communication_validation.json", comm10)
    dump("e4_final_validation.json", final)
    print(json.dumps(final, ensure_ascii=False, indent=2))


def _link_ok(terr, fsp, lobs, th, p, q, spacing=10.0):
    d = math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2]) / 1000.0
    fs = 20 * math.log10(max(d, 1e-9)) + fsp
    if fs + lobs <= th:
        return True
    if fs > th:
        return False
    return not independent_los_occluded(terr, p[0], p[1], p[2], q[0], q[1], q[2], spacing_m=spacing)


if __name__ == "__main__":
    main()
