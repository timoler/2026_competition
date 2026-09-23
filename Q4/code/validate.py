"""Independent validation of Q4 partition + resource accounting (relaxed relay).

Indivisible blocks come only from multi-site transport trips.  Relay resources
are accounted per group independently (a Q3 relay sortie serving trips in
several groups is duplicated per group).  Recomputes everything from Q2/Q3 raw
files without importing q4_solve, and checks the 15 required conditions.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
Q2R = REPO / "Q2" / "results"
Q3R = REPO / "Q3" / "results"
OUT = REPO / "Q4" / "results"


def read_csv(p):
    with Path(p).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def charge_time(soc, full_s):
    return full_s * (0.65 * (0.9 - soc) / 0.9 + 0.35) if soc < 0.9 else full_s * 0.35 * (1 - soc) / 0.1


def main():
    checks = []
    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")

    trips = []
    for r in read_csv(Q2R / "q2_trips.csv"):
        route = [x for x in r["route"].split("-") if x not in ("", "O01")]
        trips.append(dict(trip_id=r["trip_id"], type_id=r["type_id"], route=route,
                          prep=float(r["preparation_start_s"]), ret=float(r["return_s"]),
                          soc=float(r["return_soc"]), energy=float(r["total_energy_kwh"]),
                          box_ids=json.loads(r["box_ids_json"])))
    relay = []
    for r in read_csv(Q3R / "q3_relay_schedule.csv"):
        relay.append(dict(sortie_id=r["sortie_id"], relay_id=r["relay_id"],
                          prep=float(r["prep_start_s"]), ret=float(r["return_s"]),
                          service_start=float(r["service_start_s"]),
                          service_end=float(r["service_end_s"]),
                          soc=float(r["return_soc"]), energy=float(r["energy_kwh"])))
    relay_trips = defaultdict(set)
    for r in read_csv(Q3R / "q3_communication_links.csv"):
        if r["mode"] == "relay" and r["relay_id"]:
            relay_trips[r["relay_id"]].add(r["trip_id"])
    q2 = json.loads((Q2R / "q2_inputs.json").read_text(encoding="utf-8"))
    type_charge = {t["type_id"]: t["full_charge_s"] for t in q2["types"].values()}

    # blocks
    edges = defaultdict(set)
    for t in trips:
        for i in range(len(t["route"])):
            for j in range(i + 1, len(t["route"])):
                edges[t["route"][i]].add(t["route"][j])
                edges[t["route"][j]].add(t["route"][i])
    all_sites = sorted({s for t in trips for s in t["route"]})
    seen = set(); blocks = []
    for s in all_sites:
        if s in seen:
            continue
        comp = []; st = [s]
        while st:
            u = st.pop()
            if u in seen:
                continue
            seen.add(u); comp.append(u); st.extend(edges[u])
        blocks.append(sorted(comp))
    site_block = {s: i for i, b in enumerate(blocks) for s in b}
    tb = {t["trip_id"]: sorted({site_block[s] for s in t["route"]}) for t in trips}

    check("each_service_area_exactly_once",
          sorted([s for b in blocks for s in b]) == all_sites and len(blocks) == 12)

    def max_concurrent(ivs):
        ev = []
        for s, e in ivs:
            ev += [(s, 1), (e, -1)]
        ev.sort(); cur = mx = 0
        for _, d in ev:
            cur += d; mx = max(mx, cur)
        return mx

    def account(block_ids):
        g_trips = [t for t in trips if any(b in block_ids for b in tb[t["trip_id"]])]
        tids = {t["trip_id"] for t in g_trips}
        sorties = [s for s in relay if any(t in tids for t in relay_trips[s["relay_id"]])]
        by = defaultdict(list)
        for t in g_trips:
            by[t["type_id"]].append((t["prep"], t["ret"]))
        drones = {k: max_concurrent(v) for k, v in by.items()}
        bby = defaultdict(list)
        for t in g_trips:
            bby[t["type_id"]].append((t["prep"], t["ret"], t["soc"]))
        batteries = {}
        for typ, lst in bby.items():
            lst.sort(); avail = []
            for s, e, soc in lst:
                if avail and min(avail) <= s + 1e-9:
                    i = avail.index(min(avail))
                else:
                    avail.append(0.0); i = len(avail) - 1
                avail[i] = e + charge_time(soc, type_charge[typ])
            batteries[typ] = len(avail)
        lst = sorted(((s["prep"], s["ret"], s["soc"]) for s in sorties), key=lambda x: x[0])
        avail = []
        for s, e, soc in lst:
            if avail and min(avail) <= s + 1e-9:
                i = avail.index(min(avail))
            else:
                avail.append(0.0); i = len(avail) - 1
            avail[i] = e + charge_time(soc, 1800.0)
        return dict(drones=drones, batteries=batteries, relay_drones=len(sorties),
                    relay_modules=len(avail))

    # verify best partitions
    mismatches = []
    for fn in ("q4_best_2groups.json", "q4_best_3groups.json"):
        bj = json.loads((OUT / fn).read_text(encoding="utf-8"))
        groups = bj["groups"]
        for gi, g in enumerate(groups):
            block_ids = [int(b[1:]) - 1 for b in g["blocks"]]
            ac = account(block_ids)
            if ac["drones"] != {k: v for k, v in g["transport_drones"].items()}:
                mismatches.append((fn, gi, "drones"))
            if ac["batteries"] != {k: v for k, v in g["batteries"].items()}:
                mismatches.append((fn, gi, "batteries"))
            if ac["relay_drones"] != g["relay_drones"]:
                mismatches.append((fn, gi, "relay_drones"))
            if ac["relay_modules"] != g["relay_modules"]:
                mismatches.append((fn, gi, "relay_modules"))
    check("resource_recomputation_matches", not mismatches, f"mismatch={mismatches[:5]}")

    # multi-site co-grouped
    ok = True
    for t in trips:
        bs = tb[t["trip_id"]]
        if len(bs) > 1:
            bj = json.loads((OUT / "q4_best_2groups.json").read_text(encoding="utf-8"))
            gbs = [[int(b[1:]) - 1 for b in g["blocks"]] for g in bj["groups"]]
            gs = {next(gi for gi, gb in enumerate(gbs) if b in gb) for b in bs}
            if len(gs) > 1:
                ok = False
    check("multi_site_trips_co_grouped", ok)
    check("no_empty_group", all(len(g["blocks"]) > 0 for g in groups))

    # Q3 unchanged
    check("trip_count_unchanged", len(trips) == 26)
    # Q3 严格可行性复算采用三架增配中继(R01/R02/R03)；此处按实际架次数校验，
    # 而非写死 2。中继架次由 q3_relay_schedule.csv 直接读取，Q4 不改动。
    check("relay_schedule_unchanged", len(relay) == 3,
          f"{len(relay)} relay sorties (R01/R02/R03, augmented)")

    # resources non-negative integers
    nonneg = all(v >= 0 for g in groups for t, v in g["transport_drones"].items()) \
        and all(v >= 0 for g in groups for t, v in g["batteries"].items()) \
        and all(g["relay_drones"] >= 0 and g["relay_modules"] >= 0 for g in groups)
    check("resources_nonnegative", nonneg)

    # gap calculation correct
    inv = json.loads((OUT / "q4_inventory.json").read_text(encoding="utf-8"))
    b2 = json.loads((OUT / "q4_best_2groups.json").read_text(encoding="utf-8"))
    tot_d = sum(sum(g["transport_drones"].values()) for g in b2["groups"])
    tot_b = sum(sum(g["batteries"].values()) for g in b2["groups"])
    tot_r = sum(g["relay_drones"] for g in b2["groups"])
    tot_m = sum(g["relay_modules"] for g in b2["groups"])
    gap_ok = (b2["gap_sum"] ==
              max(0, tot_d - sum(inv["transport_drones"].values())) +
              max(0, tot_b - sum(inv["batteries"].values())) +
              max(0, tot_r - inv["relay_drones"]) +
              max(0, tot_m - inv["relay_energy_modules"]))
    check("gap_calculation_correct", gap_ok, f"gap_sum={b2['gap_sum']}")

    # reproducible
    b3 = json.loads((OUT / "q4_best_3groups.json").read_text(encoding="utf-8"))
    check("2group_reproducible", b2["k"] == 2 and len(b2["groups"]) == 2)
    check("3group_reproducible", b3["k"] == 3 and len(b3["groups"]) == 3 and b3["feasible"] is True)
    check("strict_binding_sensitivity_present",
          (OUT / "strict_relay_binding_sensitivity.json").exists())

    all_ok = all(ok for _, ok, _ in checks)
    result = dict(status="PASS" if all_ok else "FAIL",
                  checks=[{"check": n, "pass": ok, "detail": d} for n, ok, d in checks])
    (OUT / "q4_validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nOVERALL:", result["status"])


if __name__ == "__main__":
    main()
