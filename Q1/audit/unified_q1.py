"""Re-run Q1's exact grouped-count DP under the UNIFIED UTM geometry.

Replicates Q1/code/main.py optimisation verbatim (same models/boxes/energy/DP),
but replaces the local-affine geometry with the UTM 49N geometry already
validated by Q2 (Q2/results/q2_inputs.json).  Original Q1/results are NOT
overwritten; outputs go to Q1/audit/unified_results/.
"""
from __future__ import annotations

import csv
import itertools
import json
import sys
from functools import lru_cache
from pathlib import Path

import openpyxl

AUDIT = Path(__file__).resolve().parent
OUT = AUDIT / "unified_results"
REPO = AUDIT.parent.parent
BASE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("E:/GitHub_Project/2026_comp") / "数据/无人机应急物资运输基础数据"
OUT.mkdir(parents=True, exist_ok=True)


def rows(name, sheet=0):
    w = openpyxl.load_workbook(BASE / name, data_only=True)
    return list((w.worksheets[sheet] if isinstance(sheet, int) else w[sheet]).values)


def save(name, data):
    if not data:
        return
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(data)


# --- models / boxes (identical parsing to Q1 main.py) -----------------------
nr = rows("调度中心与服务区.xlsx")
nodes = {r[0]: dict(lon=r[2], lat=r[3], z=r[4]) for r in [nr[2]] + nr[6:] if r[0]}
assert len(nodes) == 16

mr = rows("运输无人机数据.xlsx")
keys = ["id", "name", "mass", "Q", "V", "speed", "L0", "LF", "battery",
        "reserve_pct", "prep", "load", "handover", "perbox", "up", "down", "eta", "downeta"]
models = {r[0]: dict(zip(keys, r)) for r in mr[2:5]}

boxes = [dict(zip(["id", "site", "kind", "mass", "volume", "first", "deadline",
                   "expected", "priority"], r))
         for r in rows("物资需求与配送时限.xlsx", 1)[1:] if r[0]]
assert len(boxes) == 80 and len({b["id"] for b in boxes}) == 80

# --- UNIFIED UTM geometry from Q2's validated inputs ------------------------
q2 = json.loads((REPO / "Q2/results/q2_inputs.json").read_text(encoding="utf-8"))
legs = {}
for key, g in q2["geometry"].items():
    a, b = key.split("|")
    legs[a, b] = dict(start=a, end=b, distance_m=g["distance_m"],
                      terrain_max_m=g["terrain_max_m"], cruise_m=g["cruise_altitude_m"],
                      up_m=g["ascent_m"], down_m=g["descent_m"], cells=g["cell_count"])


# --- Q1 energy + DP (verbatim formulas) -------------------------------------
def leg_perf(i, j, k, q):
    g = models[k]
    l = legs[i, j]
    assert -1e-9 <= q <= g["Q"] + 1e-9
    L = g["L0"] - (g["L0"] - g["LF"]) * (q / g["Q"]) ** 1.5
    eh = g["battery"] * l["distance_m"] / L
    eu = (g["mass"] + q) * 9.80665 * l["up_m"] / (g["eta"] * 3.6e6)
    t = l["up_m"] / g["up"] + l["distance_m"] / g["speed"] + l["down_m"] / g["down"]
    return t, eh + eu


def trip(site, k, q, count):
    g = models[k]
    t1, e1 = leg_perf("O01", site, k, q)
    t2, e2 = leg_perf(site, "O01", k, 0)
    prep = g["prep"] + g["load"] * count
    handover = g["handover"] + g["perbox"] * count
    return dict(flight_s=t1 + t2, preparation_s=prep, handover_s=handover,
                operation_s=t1 + t2 + prep + handover, energy_kwh=e1 + e2,
                soc_pct=100 * (1 - (e1 + e2) / g["battery"]))


def capacity(site, k, r):
    g = models[k]
    limit = (1 - r) * g["battery"]
    if trip(site, k, 0, 0)["energy_kwh"] > limit:
        return None
    if trip(site, k, g["Q"], 0)["energy_kwh"] <= limit:
        return float(g["Q"])
    lo, hi = 0.0, float(g["Q"])
    for _ in range(65):
        mid = (lo + hi) / 2
        if trip(site, k, mid, 0)["energy_kwh"] <= limit:
            lo = mid
        else:
            hi = mid
    return lo


def solve_site(site, r, order):
    bs = [b for b in boxes if b["site"] == site]
    groups = {}
    for b in bs:
        groups.setdefault((b["mass"], b["volume"]), []).append(b)
    types = list(groups)
    target = tuple(len(groups[t]) for t in types)
    patterns = []
    for counts in itertools.product(*(range(n + 1) for n in target)):
        if not any(counts):
            continue
        mass = sum(c * t[0] for c, t in zip(counts, types))
        vol = sum(c * t[1] for c, t in zip(counts, types))
        for k, g in models.items():
            if mass > g["Q"] + 1e-9 or vol > g["V"] + 1e-12:
                continue
            p = trip(site, k, mass, sum(counts))
            if p["energy_kwh"] > (1 - r) * g["battery"] + 1e-10:
                continue
            patterns.append((counts, k, mass, vol, p))

    @lru_cache(None)
    def dp(state):
        if not any(state):
            return (0, 0.0, 0.0), None
        first = next(i for i, v in enumerate(state) if v)
        best = None
        chosen = None
        for ix, (counts, k, m, v, p) in enumerate(patterns):
            if not counts[first] or any(c > s for c, s in zip(counts, state)):
                continue
            sub = tuple(s - c for c, s in zip(counts, state))
            base, _ = dp(sub)
            if base is None:
                continue
            value = (base[0] + 1, base[1] + p["energy_kwh"], base[2] + p["operation_s"])
            key = tuple(value[i] for i in order)
            if best is None or key < tuple(best[i] for i in order):
                best, chosen = value, ix
        return best, chosen

    score, _ = dp(target)
    if score is None:
        return None, []
    state = target
    used = [0] * len(types)
    result = []
    while any(state):
        _, ix = dp(state)
        counts, k, m, v, p = patterns[ix]
        ids = []
        for a, c in enumerate(counts):
            ids += [b["id"] for b in groups[types[a]][used[a]:used[a] + c]]
            used[a] += c
        result.append(dict(site=site, model=k, box_ids=";".join(ids),
                           mass_kg=m, volume_m3=v, **p))
        state = tuple(s - c for s, c in zip(state, counts))
    return score, result


# --- run same sweep as Q1 ---------------------------------------------------
sites = sorted(set(b["site"] for b in boxes))

# max payload sensitivity
caps = []
for r in [0.1, 0.15, 0.2, 0.25, 0.3]:
    for site, k in itertools.product(sites, models):
        c = capacity(site, k, r)
        caps.append(dict(reserve=r, site=site, model=k, max_payload_kg=c,
                         reachable=c is not None))
save("unified_max_payload_sensitivity.csv", caps)

summary = []
baseline = []
for r, order, label in [(r, (2, 0, 1), "时间_架次_能耗") for r in [0.1, 0.15, 0.2, 0.25, 0.3]] + \
                       [(0.2, (0, 1, 2), "架次_能耗_时间"), (0.2, (0, 2, 1), "架次_时间_能耗"),
                        (0.2, (1, 0, 2), "能耗_架次_时间")]:
    result = []
    bad = []
    for site in sites:
        score, res = solve_site(site, r, order)
        if score is None:
            bad.append(site)
        result.extend(res)
    for idx, row in enumerate(result, 1):
        row["trip_id"] = f"Q1-{idx:03d}"
    if not bad:
        assigned = [i for x in result for i in x["box_ids"].split(";")]
        assert sorted(assigned) == sorted(b["id"] for b in boxes)
        lookup = {b["id"]: b for b in boxes}
        for row in result:
            cargo = [lookup[i] for i in row["box_ids"].split(";")]
            g = models[row["model"]]
            assert all(b["site"] == row["site"] for b in cargo)
            assert sum(b["mass"] for b in cargo) <= g["Q"] + 1e-9
            assert sum(b["volume"] for b in cargo) <= g["V"] + 1e-12
            assert row["soc_pct"] >= 100 * r - 1e-7
        if label == "时间_架次_能耗":
            save(f"unified_batches_reserve_{int(r * 100)}.csv", result)
        else:
            save(f"unified_batches_priority_{label}.csv", result)
    summary.append(dict(reserve=r, priority=label, feasible=not bad,
                        infeasible_sites=";".join(bad),
                        trips=len(result) if not bad else None,
                        energy_kwh=sum(x["energy_kwh"] for x in result) if not bad else None,
                        operation_s=sum(x["operation_s"] for x in result) if not bad else None,
                        flight_s=sum(x["flight_s"] for x in result) if not bad else None))
    if r == 0.2 and label == "时间_架次_能耗":
        baseline = result
save("unified_model_comparison.csv", summary)
save("unified_batches_default.csv", baseline)
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("Baseline models:", {k: sum(x["model"] == k for x in baseline) for k in models})
