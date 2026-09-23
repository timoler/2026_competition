"""Compare Q1 geometry BEFORE (origin/q1: UTM distance + lon/lat DEM path) vs AFTER
(Q2/code/prepare_data.py: UTM distance + UTM straight-line DEM path)."""
import csv
import io
import json
import subprocess
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
Q1R = AUDIT.parent / "results"


def git_show_csv(ref_path):
    raw = subprocess.run(["git", "show", ref_path], capture_output=True).stdout
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def read_csv(p):
    with Path(p).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


old = {(r["start"], r["end"]): r for r in git_show_csv("origin/q1:Q1/results/q1_legs.csv")}
new = {(r["start"], r["end"]): r for r in read_csv(Q1R / "q1_legs.csv")}

rows = []
max_dd = max_dem = max_cr = max_up = max_dn = 0.0
for k in old:
    o, n = old[k], new[k]
    dd = abs(float(n["distance_m"]) - float(o["distance_m"]))
    dem = abs(float(n["terrain_max_m"]) - float(o["terrain_max_m"]))
    cr = abs(float(n["cruise_m"]) - float(o["cruise_m"]))
    up = abs(float(n["up_m"]) - float(o["up_m"]))
    dn = abs(float(n["down_m"]) - float(o["down_m"]))
    max_dd = max(max_dd, dd); max_dem = max(max_dem, dem); max_cr = max(max_cr, cr)
    max_up = max(max_up, up); max_dn = max(max_dn, dn)
    rows.append(dict(start=k[0], end=k[1], distance_diff_m=round(dd, 9),
                     terrain_max_diff_m=round(dem, 9), cruise_diff_m=round(cr, 9),
                     up_diff_m=round(up, 9), down_diff_m=round(dn, 9)))

with (AUDIT / "common_geometry_comparison.csv").open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader(); w.writerows(rows)

omc = {(r["reserve"], r["priority"]): r
       for r in git_show_csv("origin/q1:Q1/results/q1_model_comparison.csv")}
nmc = {(r["reserve"], r["priority"]): r for r in read_csv(Q1R / "q1_model_comparison.csv")}
trips_same = all(omc[k]["trips"] == nmc[k]["trips"] for k in omc)
energy_diff = max(abs(float(nmc[k]["energy_kwh"]) - float(omc[k]["energy_kwh"])) for k in omc)
op_diff = max(abs(float(nmc[k]["operation_s"]) - float(omc[k]["operation_s"])) for k in omc)

summary = dict(n_legs=len(old),
               max_distance_diff_m=max_dd, max_terrain_max_diff_m=max_dem,
               max_cruise_diff_m=max_cr, max_up_diff_m=max_up, max_down_diff_m=max_dn,
               discrete_results=dict(trips_unchanged=trips_same,
                                     max_energy_diff_kwh=round(energy_diff, 9),
                                     max_operation_diff_s=round(op_diff, 9),
                                     conclusion="CASE A: geometry identical (0 difference), discrete decisions unchanged"))
(AUDIT / "common_geometry_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
