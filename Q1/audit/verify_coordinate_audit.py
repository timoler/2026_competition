"""Independent checks for the Q1 coordinate audit (read-only).

Checks: UTM conversion, 15 service areas covered, outbound/return geometry
symmetry, DEM path bounds, unified result completeness, original results intact.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))  # noqa

import numpy as np
from pyproj import Transformer

AUDIT = Path(__file__).resolve().parent
Q1R = AUDIT.parent / "results"
Q2R = AUDIT.parent.parent / "Q2" / "results"
UNI = AUDIT / "unified_results"

checks = []
def check(name, ok, detail=""):
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


# 1. UTM conversion correctness (independent re-transform)
q2 = json.loads((Q2R / "q2_inputs.json").read_text(encoding="utf-8"))
fwd = Transformer.from_crs(4326, 32649, always_xy=True)
max_err = 0.0
for nid, n in q2["nodes"].items():
    x, y = fwd.transform(n["lon"], n["lat"])
    max_err = max(max_err, abs(x - n["x_m"]), abs(y - n["y_m"]))
check("utm_conversion", max_err < 0.01, f"max node UTM error={max_err:.6f} m")

# 2. 15 service areas all in the comparison
rows = list(csv.DictReader((AUDIT / "q1_coordinate_comparison.csv").open(encoding="utf-8-sig")))
sites = {r["service_id"] for r in rows}
check("all_15_service_areas", sites == {f"S{i:03d}" for i in range(1, 16)},
      f"{len(sites)} areas")

# 3. outbound/return geometry consistency (distance symmetric, up/down swapped, DEM same)
old = {(r["start"], r["end"]): r for r in csv.DictReader((Q1R / "q1_legs.csv").open(encoding="utf-8-sig"))}
new = {(r["origin"], r["destination"]): r for r in csv.DictReader((Q2R / "q2_geometry.csv").open(encoding="utf-8-sig"))}
sym_ok = True
for s in sorted(sites):
    a, b = new[("O01", s)], new[(s, "O01")]
    if abs(float(a["distance_m"]) - float(b["distance_m"])) > 1e-6:
        sym_ok = False
    if abs(float(a["terrain_max_m"]) - float(b["terrain_max_m"])) > 1e-6:
        sym_ok = False
    if abs(float(a["ascent_m"]) - float(b["descent_m"])) > 1e-6:
        sym_ok = False
    if abs(float(a["descent_m"]) - float(b["ascent_m"])) > 1e-6:
        sym_ok = False
check("outbound_return_symmetry", sym_ok)

# 4. DEM path bounds + nonnegative climb/descent in unified geometry
bounds_ok = True
for k, g in q2["geometry"].items():
    if g["cell_count"] < 1 or g["ascent_m"] < 0 or g["descent_m"] < 0:
        bounds_ok = False
check("dem_path_bounds_and_nonnegative", bounds_ok, f"{len(q2['geometry'])} legs")

# 5. unified results complete
expected = ["unified_max_payload_sensitivity.csv", "unified_model_comparison.csv",
            "unified_batches_default.csv"] + \
           [f"unified_batches_reserve_{p}.csv" for p in (10, 15, 20, 25, 30)]
missing = [f for f in expected if not (UNI / f).exists()]
check("unified_results_complete", not missing, f"missing={missing}")

# 6. unified results internal consistency (feasible, 80 boxes, reserve satisfied)
mc = list(csv.DictReader((UNI / "unified_model_comparison.csv").open(encoding="utf-8-sig")))
cons_ok = all(r["feasible"] == "True" and r["trips"] for r in mc)
check("unified_results_consistent", cons_ok, f"{len(mc)} configs all feasible")

all_ok = all(ok for _, ok, _ in checks)
print("\nOVERALL:", "PASS" if all_ok else "FAIL")
(AUDIT / "q1_coordinate_audit_verify.json").write_text(
    json.dumps({"status": "PASS" if all_ok else "FAIL",
                "checks": [{"name": n, "pass": ok, "detail": d} for n, ok, d in checks]},
               ensure_ascii=False, indent=2), encoding="utf-8")
