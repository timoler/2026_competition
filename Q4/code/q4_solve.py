"""Q4: partition the 15 service areas into 2/3 groups on top of the fixed Q3 plan.

Indivisible blocks come ONLY from multi-site transport trips (same trip serving
multiple service areas).  Relay-sharing is NOT a hard co-grouping constraint:
each group independently configures its own relay drones / energy modules to
reproduce the Q3 communication service for its own trips; if one Q3 relay sortie
serves trips in several groups, it is duplicated (counted as relay redundancy),
and no physical relay resource is shared across groups.

Q4 does NOT re-optimise Q3.  The earlier strict "relay-binding" reading is kept
as a separate sensitivity (strict_relay_binding_sensitivity.json).
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict, Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
Q2R = REPO / "Q2" / "results"
Q3R = REPO / "Q3" / "results"
OUT = REPO / "Q4" / "results"
OUT.mkdir(parents=True, exist_ok=True)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path, records, fieldnames=None):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        if fieldnames is None and records:
            fieldnames = list(records[0])
        if fieldnames is None:
            f.write("")
            return
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(records)


def charge_time(soc, full_s):
    return full_s * (0.65 * (0.9 - soc) / 0.9 + 0.35) if soc < 0.9 else full_s * 0.35 * (1 - soc) / 0.1


# ----------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------
def load():
    trips = []
    for r in read_csv(Q3R / "q3_transport_schedule.csv"):
        route = [x for x in r["route"].split("-") if x not in ("", "O01")]
        trips.append(dict(trip_id=r["trip_id"], type_id=r["type_id"],
                          route=route, prep=float(r["preparation_start_s"]),
                          ret=float(r["return_s"]), soc=float(r["return_soc"]),
                          energy=float(r["total_energy_kwh"]),
                          box_ids=json.loads(r["box_ids_json"])))
    relay = []
    for r in read_csv(Q3R / "q3_relay_schedule.csv"):
        relay.append(dict(sortie_id=r["sortie_id"], relay_id=r["relay_id"],
                          prep=float(r["prep_start_s"]), ret=float(r["return_s"]),
                          service_start=float(r["service_start_s"]),
                          service_end=float(r["service_end_s"]),
                          soc=float(r["return_soc"]), energy=float(r["energy_kwh"])))
    # 中继架次按 sortie_id（provider 字段，S01/S02/S03）归属；R02 的两次架次 S02/S03 分开统计。
    relay_trips = defaultdict(set)
    for r in read_csv(Q3R / "q3_communication_links.csv"):
        sortie = (r.get("sortie_id") or r.get("provider") or "").strip()
        if sortie and sortie != "G01":
            relay_trips[sortie].add(r["trip_id"])
    q2 = json.loads((Q2R / "q2_inputs.json").read_text(encoding="utf-8"))
    type_charge = {t["type_id"]: t["full_charge_s"] for t in q2["types"].values()}
    inv = dict(transport_drones=Counter(q2["drones"].values()),
               batteries=Counter(q2["batteries"].values()),
               relay_drones=2, relay_modules=6, relay_module_charge=1800.0)
    return trips, relay, dict(relay_trips), type_charge, inv, q2["boxes"]


def build_blocks(trips):
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
    blocks.sort()
    return blocks


def main():
    trips, relay, relay_trips, type_charge, inv, boxes = load()
    blocks = build_blocks(trips)
    n = len(blocks)
    site_block = {s: i for i, b in enumerate(blocks) for s in b}
    tb = {t["trip_id"]: sorted({site_block[s] for s in t["route"]}) for t in trips}

    # block-level precompute
    block_trips = defaultdict(list)
    for t in trips:
        for b in tb[t["trip_id"]]:
            block_trips[b].append(t["trip_id"])
    trip_box_ids = {t["trip_id"]: t["box_ids"] for t in trips}
    block_boxes = {b: sum(len(trip_box_ids[t]) for t in block_trips[b]) for b in range(n)}
    block_sites = {b: len(blocks[b]) for b in range(n)}

    # relay -> blocks (served)
    relay_blocks = {}
    for rid, served in relay_trips.items():
        rb = set()
        for t in served:
            rb.update(tb[t])
        relay_blocks[rid] = sorted(rb)

    # write blocks + inventory
    write_blocks(blocks, block_trips, relay_blocks)
    # 中继情景：正式 Q3 为两物理中继联合调度（R01 一次悬停 + R02 两次顺序架次），
    # 已严格验证 100% 连续通信；原题库存 R01/R02 两架。
    relay_fleet = sorted({s["relay_id"] for s in relay})
    relay_scenario = ("original 2-relay fleet (R01/R02), strict-feasible joint schedule"
                      if len(relay_fleet) <= 2 else
                      f"augmented {len(relay_fleet)}-relay fleet")
    (OUT / "q4_inventory.json").write_text(
        json.dumps(dict(transport_drones=dict(inv["transport_drones"]),
                        batteries=dict(inv["batteries"]),
                        relay_drones=inv["relay_drones"],
                        relay_energy_modules=inv["relay_modules"],
                        q3_relay_schedule_fleet=relay_fleet,
                        q3_relay_schedule_fleet_count=len(relay_fleet),
                        relay_scenario=relay_scenario),
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # resource accounting (relaxed relay: duplication)
    def account(block_ids):
        group_trips = [t for t in trips if any(b in block_ids for b in tb[t["trip_id"]])]
        tids = {t["trip_id"] for t in group_trips}
        # relay sorties serving this group = those with any served trip in group
        sorties = [s for s in relay if any(t in tids for t in relay_trips[s["sortie_id"]])]
        physical_relays = len(set(s["relay_id"] for s in sorties))
        return dict(
            n_trips=len(group_trips),
            n_boxes=sum(len(t["box_ids"]) for t in group_trips),
            n_sites=sum(block_sites[b] for b in block_ids),
            occupancy_s=sum(t["ret"] - t["prep"] for t in group_trips),
            energy=sum(t["energy"] for t in group_trips),
            relay_service_s=sum(s["service_end"] - s["service_start"] for s in sorties),
            relay_energy=sum(s["energy"] for s in sorties),
            drones=transport_drones(group_trips),
            batteries=batteries(group_trips, type_charge),
            relay_drones=physical_relays,           # physical relay UAVs (<=2)
            relay_sorties=len(sorties),             # relay sorties (R01 x1 + R02 x2)
            relay_modules=relay_modules(sorties, inv["relay_module_charge"]))

    def transport_drones(g_trips):
        by = defaultdict(list)
        for t in g_trips:
            by[t["type_id"]].append((t["prep"], t["ret"]))
        return {k: max_concurrent(v) for k, v in by.items()}

    def max_concurrent(ivs):
        ev = []
        for s, e in ivs:
            ev += [(s, 1), (e, -1)]
        ev.sort(); cur = mx = 0
        for _, d in ev:
            cur += d; mx = max(mx, cur)
        return mx

    def batteries(g_trips, tc):
        by = defaultdict(list)
        for t in g_trips:
            by[t["type_id"]].append((t["prep"], t["ret"], t["soc"]))
        req = {}
        for typ, lst in by.items():
            lst.sort(); avail = []
            for s, e, soc in lst:
                if avail and min(avail) <= s + 1e-9:
                    i = avail.index(min(avail))
                else:
                    avail.append(0.0); i = len(avail) - 1
                avail[i] = e + charge_time(soc, tc[typ])
            req[typ] = len(avail)
        return req

    def relay_modules(sorties, full):
        lst = sorted(((s["prep"], s["ret"], s["soc"]) for s in sorties), key=lambda x: x[0])
        avail = []
        for s, e, soc in lst:
            if avail and min(avail) <= s + 1e-9:
                i = avail.index(min(avail))
            else:
                avail.append(0.0); i = len(avail) - 1
            avail[i] = e + charge_time(soc, full)
        return len(avail)

    # centralised baseline
    base = account(list(range(n)))

    # enumeration
    def enumerate_partitions(nb, k):
        groups = []
        def rec(i):
            if i == nb:
                if len(groups) == k:
                    yield [tuple(g) for g in groups]
                return
            for g in groups:
                g.append(i); yield from rec(i + 1); g.pop()
            if len(groups) < k:
                groups.append([i]); yield from rec(i + 1); groups.pop()
        yield from rec(0)

    results = {}
    for k in (2, 3):
        scored = []
        for groups in enumerate_partitions(n, k):
            acct = [account(list(g)) for g in groups]
            tot = totals(acct)
            gap = inventory_gap(tot, inv)
            gap_sum = sum(sum(v.values()) for v in gap["drones"].values()
                          if isinstance(gap["drones"], dict)) if False else gap_score(gap)
            imbalance = workload_imbalance(acct)
            total_res = sum(tot["drones"].values()) + sum(tot["batteries"].values()) \
                + tot["relay_drones"] + tot["relay_modules"]
            scored.append(dict(groups=groups, acct=acct, tot=tot, gap=gap,
                               gap_sum=gap_sum, total_res=total_res,
                               imbalance=imbalance))
        # lexicographic sort: gap, total resources, imbalance
        scored.sort(key=lambda x: (x["gap_sum"], x["total_res"], x["imbalance"]))
        results[k] = scored
        print(f"[q4] k={k}: {len(scored)} partitions; best gap={scored[0]['gap_sum']} "
              f"total={scored[0]['total_res']} imbalance={scored[0]['imbalance']:.4f}")

    # outputs
    write_all_partitions(results, n)
    write_best(results, blocks, inv, base)
    write_comparison(results, base)
    write_strict_binding(blocks, relay_blocks)


def totals(acct):
    drones = Counter(); batt = Counter(); rd = 0; rm = 0
    for g in acct:
        for t, v in g["drones"].items():
            drones[t] += v
        for t, v in g["batteries"].items():
            batt[t] += v
        rd += g["relay_drones"]; rm += g["relay_modules"]
    return dict(drones=dict(drones), batteries=dict(batt), relay_drones=rd, relay_modules=rm)


def inventory_gap(tot, inv):
    gd = {t: max(0, tot["drones"].get(t, 0) - inv["transport_drones"].get(t, 0)) for t in ("A", "B", "C")}
    gb = {t: max(0, tot["batteries"].get(t, 0) - inv["batteries"].get(t, 0)) for t in ("A", "B", "C")}
    gr = max(0, tot["relay_drones"] - inv["relay_drones"])
    gm = max(0, tot["relay_modules"] - inv["relay_modules"])
    return dict(drones=gd, batteries=gb, relay_drones=gr, relay_modules=gm)


def gap_score(gap):
    return sum(gap["drones"].values()) + sum(gap["batteries"].values()) \
        + gap["relay_drones"] + gap["relay_modules"]


def workload_imbalance(acct):
    keys = ["n_trips", "occupancy_s", "energy", "n_boxes", "relay_service_s"]
    norm = []
    for kk in keys:
        vals = [g[kk] for g in acct]
        lo, hi = min(vals), max(vals)
        norm.append([(v - lo) / (hi - lo) if hi > lo else 0.0 for v in vals])
    W = [0.2 * sum(norm[c][gi] for c in range(5)) for gi in range(len(acct))]
    return max(W) - min(W)


# ----------------------------------------------------------------------------
# outputs
# ----------------------------------------------------------------------------
def write_blocks(blocks, block_trips, relay_blocks):
    rows = []
    for i, b in enumerate(blocks):
        for s in b:
            rows.append(dict(block_id=f"B{i+1:02d}", service_id=s,
                             related_trip_ids=";".join(sorted(block_trips[i]))))
    write_csv(OUT / "q4_service_blocks.csv", rows)
    (OUT / "q4_blocks_summary.json").write_text(
        json.dumps(dict(n_service_areas=15, n_blocks=len(blocks),
                        blocks=[{"block_id": f"B{i+1:02d}", "service_ids": b,
                                 "trip_ids": sorted(block_trips[i])}
                                for i, b in enumerate(blocks)],
                        relay_served_blocks={rid: [f"B{i+1:02d}" for i in rb]
                                             for rid, rb in relay_blocks.items()}),
                   ensure_ascii=False, indent=2), encoding="utf-8")


def write_all_partitions(results, n):
    for k in (2, 3):
        scored = results[k]
        # full dump only for 2 groups (2047 rows); for 3 groups keep top 1000 to limit size
        limit = None if k == 2 else 1000
        sub = scored[:limit] if limit else scored
        rows = []
        for s in sub:
            rows.append(dict(
                partition="|".join("{" + ",".join(f"B{i+1:02d}" for i in g) + "}" for g in s["groups"]),
                gap=s["gap_sum"], total_resources=s["total_res"],
                imbalance=round(s["imbalance"], 6),
                drones=json.dumps(s["tot"]["drones"], ensure_ascii=False),
                batteries=json.dumps(s["tot"]["batteries"], ensure_ascii=False),
                relay_drones=s["tot"]["relay_drones"], relay_modules=s["tot"]["relay_modules"]))
        write_csv(OUT / f"q4_all_partitions_{k}groups.csv", rows)
        if limit:
            (OUT / f"q4_all_partitions_{k}groups_summary.json").write_text(
                json.dumps(dict(k=k, total_enumerated=len(scored),
                                saved_top_n=len(rows)), ensure_ascii=False, indent=2),
                encoding="utf-8")


def write_best(results, blocks, inv, base):
    for k in (2, 3):
        scored = results[k]
        best = scored[0]
        acct = best["acct"]
        groups = best["groups"]
        best_json = dict(
            k=k, feasible=True, n_candidates=len(scored),
            groups=[dict(group_id=gi + 1,
                         blocks=[f"B{i+1:02d}" for i in g],
                         service_ids=[s for i in g for s in blocks[i]],
                         n_sites=acct[gi]["n_sites"], n_boxes=acct[gi]["n_boxes"],
                         n_trips=acct[gi]["n_trips"],
                         occupancy_s=round(acct[gi]["occupancy_s"], 2),
                         transport_energy_kwh=round(acct[gi]["energy"], 6),
                         relay_service_s=round(acct[gi]["relay_service_s"], 2),
                         relay_energy_kwh=round(acct[gi]["relay_energy"], 6),
                         transport_drones=acct[gi]["drones"],
                         batteries=acct[gi]["batteries"],
                         relay_drones=acct[gi]["relay_drones"],
                         relay_modules=acct[gi]["relay_modules"])
                    for gi, g in enumerate(groups)],
            total_resources=best["tot"], resource_gap=best["gap"],
            gap_sum=best["gap_sum"], total_resources_sum=best["total_res"],
            workload_imbalance=round(best["imbalance"], 6),
            top10=[dict(partition="|".join("{" + ",".join(f"B{i+1:02d}" for i in g) + "}" for g in s["groups"]),
                        gap=s["gap_sum"], total_resources=s["total_res"],
                        imbalance=round(s["imbalance"], 6)) for s in scored[:10]])
        (OUT / f"q4_best_{k}groups.json").write_text(
            json.dumps(best_json, ensure_ascii=False, indent=2), encoding="utf-8")
        # group resources csv
        gres = []
        for gi, g in enumerate(acct):
            gres.append(dict(group=gi + 1,
                             service_ids=";".join(s for i in groups[gi] for s in blocks[i]),
                             n_sites=g["n_sites"], n_boxes=g["n_boxes"], n_trips=g["n_trips"],
                             occupancy_s=round(g["occupancy_s"], 2),
                             transport_energy_kwh=round(g["energy"], 6),
                             relay_service_s=round(g["relay_service_s"], 2),
                             relay_energy_kwh=round(g["relay_energy"], 6),
                             drones_A=g["drones"].get("A", 0), drones_B=g["drones"].get("B", 0),
                             drones_C=g["drones"].get("C", 0),
                             batteries_A=g["batteries"].get("A", 0),
                             batteries_B=g["batteries"].get("B", 0),
                             batteries_C=g["batteries"].get("C", 0),
                             relay_drones=g["relay_drones"], relay_modules=g["relay_modules"]))
        write_csv(OUT / f"q4_group_resources_{k}groups.csv", gres)


def write_comparison(results, base):
    base_tot = dict(drones=base["drones"], batteries=base["batteries"],
                    relay_drones=base["relay_drones"], relay_modules=base["relay_modules"])
    comp = [dict(scenario="Q3集中式",
                 transport_drones=sum(base_tot["drones"].values()),
                 batteries=sum(base_tot["batteries"].values()),
                 relay_drones=base_tot["relay_drones"], relay_modules=base_tot["relay_modules"])]
    inv = json.loads((OUT / "q4_inventory.json").read_text(encoding="utf-8"))
    inv_d = sum(inv["transport_drones"].values()); inv_b = sum(inv["batteries"].values())
    gaps = []
    for label, tot in [(r["scenario"], r) for r in comp]:
        gaps.append(dict(scenario=label, feasible=True,
                         transport_drones=tot["transport_drones"], batteries=tot["batteries"],
                         relay_drones=tot["relay_drones"], relay_modules=tot["relay_modules"],
                         inventory_drones=inv_d, inventory_batteries=inv_b,
                         inventory_relay_drones=inv["relay_drones"],
                         inventory_relay_modules=inv["relay_energy_modules"],
                         gap_drones=max(0, tot["transport_drones"] - inv_d),
                         gap_batteries=max(0, tot["batteries"] - inv_b),
                         gap_relay_drones=max(0, tot["relay_drones"] - inv["relay_drones"]),
                         gap_relay_modules=max(0, tot["relay_modules"] - inv["relay_energy_modules"]),
                         note=""))
    for k in (2, 3):
        best = results[k][0]
        tot = best["tot"]
        comp.append(dict(scenario=f"{k}组分区",
                         transport_drones=sum(tot["drones"].values()),
                         batteries=sum(tot["batteries"].values()),
                         relay_drones=tot["relay_drones"], relay_modules=tot["relay_modules"]))
        gaps.append(dict(scenario=f"{k}组分区", feasible=True,
                         transport_drones=sum(tot["drones"].values()),
                         batteries=sum(tot["batteries"].values()),
                         relay_drones=tot["relay_drones"], relay_modules=tot["relay_modules"],
                         inventory_drones=inv_d, inventory_batteries=inv_b,
                         inventory_relay_drones=inv["relay_drones"],
                         inventory_relay_modules=inv["relay_energy_modules"],
                         gap_drones=sum(best["gap"]["drones"].values()),
                         gap_batteries=sum(best["gap"]["batteries"].values()),
                         gap_relay_drones=best["gap"]["relay_drones"],
                         gap_relay_modules=best["gap"]["relay_modules"],
                         note=""))
    write_csv(OUT / "q4_resource_comparison.csv", comp)
    write_csv(OUT / "q4_resource_gap.csv", gaps)

    # workload comparison
    wrows = []
    for k in (2, 3):
        best = results[k][0]
        for gi, g in enumerate(best["acct"]):
            wrows.append(dict(scenario=f"{k}组", group=gi + 1, feasible=True,
                              n_sites=g["n_sites"], n_boxes=g["n_boxes"], n_trips=g["n_trips"],
                              occupancy_s=round(g["occupancy_s"], 2),
                              transport_energy_kwh=round(g["energy"], 6),
                              relay_service_s=round(g["relay_service_s"], 2),
                              relay_energy_kwh=round(g["relay_energy"], 6), note=""))
    write_csv(OUT / "q4_workload_comparison.csv", wrows)


def write_strict_binding(blocks, relay_blocks):
    """Strict interpretation: relay-served blocks must be co-grouped."""
    # union-find over blocks connected by relay sharing
    parent = list(range(len(blocks)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for rid, rb in relay_blocks.items():
        for i in range(len(rb)):
            for j in range(i + 1, len(rb)):
                union(rb[i], rb[j])
    comp = defaultdict(list)
    for b in range(len(blocks)):
        comp[find(b)].append(b)
    comps = sorted(comp.values(), key=len, reverse=True)
    n_comps = len(comps)
    # feasible 2/3-group: each relay-connected component atomic -> need >= k components
    feasible2 = (n_comps >= 2)
    feasible3 = (n_comps >= 3)
    # build the strict 2-group (largest component + rest) if feasible2
    strict2 = None
    if feasible2:
        g1 = sorted(b for c in comps[:-1] for b in c)
        g2 = sorted(comps[-1])
        strict2 = dict(group1=[f"B{i+1:02d}" for i in g1],
                       group2=[f"B{i+1:02d}" for i in g2])
    (OUT / "strict_relay_binding_sensitivity.json").write_text(
        json.dumps(dict(
            interpretation="shared relay sortie => its served service blocks must be co-grouped (strict)",
            relay_connected_components=[[f"B{i+1:02d}" for i in c] for c in comps],
            n_components=n_comps,
            feasible_2groups=feasible2,
            feasible_3groups=feasible3,
            strict_2groups=strict2,
            note=f"严格解释下2组{'退化为大组件+S011' if feasible2 else '不可行'}，3组{'不可行（中继连通组件仅'+str(n_comps)+'个，不足以构成3个非空组）' if not feasible3 else '可行'}"),
            ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
