"""Compare OLD_Q1 (local-affine) vs UNIFIED_UTM geometry and Q1 results.

Writes Q1/audit/q1_coordinate_comparison.csv, q1_coordinate_audit.json, .md.
Read-only against Q1/results and Q2; outputs only under Q1/audit/.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
Q1R = AUDIT.parent / "results"
Q2R = AUDIT.parent.parent / "Q2" / "results"
UNI = AUDIT / "unified_results"


def read(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---- 1. geometry comparison (O01 -> Si) ------------------------------------
old_legs = {(r["start"], r["end"]): r for r in read(Q1R / "q1_legs.csv")}
new_legs = {(r["origin"], r["destination"]): r for r in read(Q2R / "q2_geometry.csv")}
sites = [f"S{i:03d}" for i in range(1, 16)]

comp_rows = []
max_d = max_dp = max_dem = 0.0
max_d_site = max_dem_site = ""
for s in sites:
    o, n = old_legs[("O01", s)], new_legs[("O01", s)]
    do, dn = float(o["distance_m"]), float(n["distance_m"])
    demo, demn = float(o["terrain_max_m"]), float(n["terrain_max_m"])
    dd, dp = dn - do, (dn - do) / do * 100
    demd = demn - demo
    if abs(dd) > abs(max_d):
        max_d, max_d_site = dd, s
    if abs(dp) > abs(max_dp):
        max_dp = dp
    if abs(demd) > abs(max_dem):
        max_dem, max_dem_site = demd, s
    comp_rows.append(dict(
        service_id=s, old_distance_m=round(do, 3), utm_distance_m=round(dn, 3),
        distance_diff_m=round(dd, 3), distance_diff_pct=round(dp, 4),
        old_max_dem_m=demo, utm_max_dem_m=demn, dem_diff_m=round(demd, 3),
        old_cruise_alt_m=float(o["cruise_m"]), utm_cruise_alt_m=float(n["cruise_altitude_m"]),
        old_climb_m=float(o["up_m"]), utm_climb_m=float(n["ascent_m"]),
        old_descent_m=float(o["down_m"]), utm_descent_m=float(n["descent_m"])))
with (AUDIT / "q1_coordinate_comparison.csv").open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(comp_rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(comp_rows)

# ---- 2. model comparison ---------------------------------------------------
old_mc = {(r["reserve"], r["priority"]): r for r in read(Q1R / "q1_model_comparison.csv")}
new_mc = {(r["reserve"], r["priority"]): r for r in read(UNI / "unified_model_comparison.csv")}

mc_diffs = []
for k in sorted(old_mc):
    o, n = old_mc[k], new_mc[k]
    de = float(n["energy_kwh"]) - float(o["energy_kwh"])
    dt = float(n["operation_s"]) - float(o["operation_s"])
    mc_diffs.append(dict(reserve=k[0], priority=k[1],
                         old_trips=o["trips"], new_trips=n["trips"],
                         old_energy_kwh=float(o["energy_kwh"]), new_energy_kwh=float(n["energy_kwh"]),
                         energy_diff_kwh=round(de, 6), energy_diff_pct=round(de / float(o["energy_kwh"]) * 100, 4),
                         old_operation_s=float(o["operation_s"]), new_operation_s=float(n["operation_s"]),
                         operation_diff_s=round(dt, 3)))

trips_changed = any(d["old_trips"] != d["new_trips"] for d in mc_diffs)
max_energy_diff_pct = max(abs(d["energy_diff_pct"]) for d in mc_diffs)
max_operation_diff = max(abs(d["operation_diff_s"]) for d in mc_diffs)

# ---- 3. max payload sensitivity -------------------------------------------
old_cap = {(r["reserve"], r["site"], r["model"]): r for r in read(Q1R / "q1_max_payload_sensitivity.csv")}
new_cap = {(r["reserve"], r["site"], r["model"]): r for r in read(UNI / "unified_max_payload_sensitivity.csv")}

reachability_flips = []
max_cap_diff = 0.0
cap_diff_site = ""
for k in sorted(old_cap):
    o, n = old_cap[k], new_cap[k]
    ro, rn = o["reachable"], n["reachable"]
    if ro != rn:
        reachability_flips.append(k)
    if ro == "True" and rn == "True":
        d = float(n["max_payload_kg"]) - float(o["max_payload_kg"])
        if abs(d) > abs(max_cap_diff):
            max_cap_diff, cap_diff_site = d, f"{k[1]}/{k[2]}@{k[0]}"

# ---- 4. default batch comparison (20% reserve) -----------------------------
old_b = sorted(read(Q1R / "q1_batches_default.csv"), key=lambda r: sorted(r["box_ids"].split(";")))
new_b = sorted(read(UNI / "unified_batches_default.csv"), key=lambda r: sorted(r["box_ids"].split(";")))

batch_identical = len(old_b) == len(new_b)
if batch_identical:
    for a, b in zip(old_b, new_b):
        if (sorted(a["box_ids"].split(";")) != sorted(b["box_ids"].split(";"))
                or a["model"] != b["model"]):
            batch_identical = False
            break

# ---- CASE determination ----------------------------------------------------
case_b = (bool(reachability_flips) or trips_changed or not batch_identical)
verdict = ("CASE B" if case_b else "CASE A")

audit = dict(
    geometry=dict(max_distance_diff_m=round(max_d, 3), max_distance_diff_site=max_d_site,
                  max_distance_diff_pct=round(max_dp, 4),
                  max_dem_diff_m=round(max_dem, 3), max_dem_diff_site=max_dem_site),
    model_comparison=mc_diffs,
    trips_changed=trips_changed,
    max_energy_diff_pct=round(max_energy_diff_pct, 4),
    max_operation_diff_s=round(max_operation_diff, 3),
    max_payload=dict(reachability_flips=[list(k) for k in reachability_flips],
                     max_payload_diff_kg=round(max_cap_diff, 6),
                     max_payload_diff_site=cap_diff_site),
    batch_identical=batch_identical,
    verdict=verdict)

(AUDIT / "q1_coordinate_audit.json").write_text(
    json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(audit, ensure_ascii=False, indent=2))
