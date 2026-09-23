"""Q4: partition the 15 service areas into 2/3 groups on top of the fixed Q3 plan.

Steps:
  1. build indivisible service blocks from multi-site transport trips;
  2. build relay-sharing association (relay sortie -> trips -> blocks);
  3. enumerate all block partitions into 2/3 groups and check relay compatibility;
  4. for each feasible partition compute minimum resources (transport drones,
     shared batteries, relay drones, relay energy modules);
  5. compute redundancy / gap / workload and select best per k.

Q4 does NOT re-optimise Q3; it only re-accounts resources under independent
per-group execution of the fixed Q3 tasks.  No Q1/Q2/Q3 file is modified.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict, Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
Q2R = REPO / "Q2" / "results"
Q3R = REPO / "Q3" / "results"
OUT = REPO / "Q4" / "results"
OUT.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------
# data loading
# ----------------------------------------------------------------------------
def read_csv(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_trips():
    rows = read_csv(Q2R / "q2_trips.csv")
    trips = []
    for r in rows:
        route = [x for x in r["route"].split("-") if x not in ("", "O01")]
        trips.append(dict(
            trip_id=r["trip_id"], drone_id=r["drone_id"], type_id=r["type_id"],
            battery_id=r["battery_id"], route=route,
            preparation_start_s=float(r["preparation_start_s"]),
            takeoff_s=float(r["takeoff_s"]), return_s=float(r["return_s"]),
            total_energy_kwh=float(r["total_energy_kwh"]),
            return_soc=float(r["return_soc"]),
            box_ids=json.loads(r["box_ids_json"])))
    return trips


def load_relay_sorties():
    rows = read_csv(Q3R / "q3_relay_schedule.csv")
    out = []
    for r in rows:
        out.append(dict(sortie_id=r["sortie_id"], relay_id=r["relay_id"],
                        energy_component_id=r["energy_component_id"],
                        prep_start_s=float(r["prep_start_s"]),
                        takeoff_s=float(r["takeoff_s"]),
                        service_start_s=float(r["service_start_s"]),
                        service_end_s=float(r["service_end_s"]),
                        return_s=float(r["return_s"]),
                        energy_kwh=float(r["energy_kwh"]),
                        return_soc=float(r["return_soc"])))
    return out


def load_communication_relay_trips():
    """relay_id -> set(trip_id) served."""
    rt = defaultdict(set)
    for r in read_csv(Q3R / "q3_communication_links.csv"):
        if r["mode"] == "relay" and r["relay_id"]:
            rt[r["relay_id"]].add(r["trip_id"])
    return dict(rt)


def load_inventory():
    """Read inventory from Q2/Q3 official inputs (never hand-written)."""
    q2 = json.loads((Q2R / "q2_inputs.json").read_text(encoding="utf-8"))
    drone_types = Counter(q2["drones"].values())          # type -> count
    batt_types = Counter(q2["batteries"].values())        # type -> count
    # full charge time per type
    type_charge = {t["type_id"]: t["full_charge_s"] for t in q2["types"].values()}
    boxes = q2["boxes"]
    inv = dict(
        transport_drones=dict(drone_types),
        batteries=dict(batt_types),
        relay_drones=2,              # R01, R02 from 中继无人机数据.xlsx
        relay_energy_modules=6,      # from 中继无人机数据.xlsx
        relay_module_full_charge_s=1800.0,
        type_charge_s=type_charge,
        boxes=boxes)
    return inv


def charge_time(soc, full_s):
    if soc < 0.9:
        return full_s * (0.65 * (0.9 - soc) / 0.9 + 0.35)
    return full_s * 0.35 * (1 - soc) / 0.1


# ----------------------------------------------------------------------------
# step 1: indivisible service blocks
# ----------------------------------------------------------------------------
def build_blocks(trips):
    edges = defaultdict(set)
    for t in trips:
        sites = t["route"]
        for i in range(len(sites)):
            for j in range(i + 1, len(sites)):
                edges[sites[i]].add(sites[j])
                edges[sites[j]].add(sites[i])
    # all 15 service areas
    all_sites = sorted({s for t in trips for s in t["route"]})
    seen = set()
    blocks = []
    for s in all_sites:
        if s in seen:
            continue
        comp = []
        stack = [s]
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            comp.append(u)
            stack.extend(edges[u])
        blocks.append(sorted(comp))
    blocks.sort()
    return blocks


def trip_to_blocks(trips, blocks):
    site_to_block = {}
    for i, b in enumerate(blocks):
        for s in b:
            site_to_block[s] = i
    tb = {}
    for t in trips:
        tb[t["trip_id"]] = sorted({site_to_block[s] for s in t["route"]})
    return tb, site_to_block


# ----------------------------------------------------------------------------
# resource accounting (identical algorithm used for centralised baseline too)
# ----------------------------------------------------------------------------
def transport_drones_required(group_trips):
    """max concurrent occupancy per drone type."""
    by_type = defaultdict(list)
    for t in group_trips:
        by_type[t["type_id"]].append((t["preparation_start_s"], t["return_s"]))
    req = {}
    for typ, ivs in by_type.items():
        events = []
        for s, e in ivs:
            events.append((s, 1))
            events.append((e, -1))
        events.sort()
        cur = mx = 0
        for _, d in events:
            cur += d
            mx = max(mx, cur)
        req[typ] = mx
    return req


def batteries_required(group_trips, type_charge):
    """greedy min shared batteries per type (two-stage charging)."""
    by_type = defaultdict(list)
    for t in group_trips:
        by_type[t["type_id"]].append(
            (t["preparation_start_s"], t["return_s"], t["return_soc"]))
    req = {}
    for typ, trips in by_type.items():
        full = type_charge[typ]
        trips = sorted(trips, key=lambda x: x[0])
        avail = []
        for start, end, soc in trips:
            if avail and min(avail) <= start + 1e-9:
                i = avail.index(min(avail))
            else:
                avail.append(0.0)
                i = len(avail) - 1
            avail[i] = end + charge_time(soc, full)
        req[typ] = len(avail)
    return req


def relay_drones_required(group_sortie_ids):
    return len(group_sortie_ids)


def relay_modules_required(group_sorties, full_charge_s):
    trips = sorted(((s["prep_start_s"], s["return_s"], s["return_soc"])
                    for s in group_sorties), key=lambda x: x[0])
    avail = []
    for start, end, soc in trips:
        if avail and min(avail) <= start + 1e-9:
            i = avail.index(min(avail))
        else:
            avail.append(0.0)
            i = len(avail) - 1
        avail[i] = end + charge_time(soc, full_charge_s)
    return len(avail)


# ----------------------------------------------------------------------------
# partition enumeration (set partitions into k non-empty groups, canonical)
# ----------------------------------------------------------------------------
def enumerate_partitions(n, k):
    groups = []
    def rec(i):
        if i == n:
            if len(groups) == k:
                yield [tuple(g) for g in groups]
            return
        for g in groups:
            g.append(i)
            yield from rec(i + 1)
            g.pop()
        if len(groups) < k:
            groups.append([i])
            yield from rec(i + 1)
            groups.pop()
    yield from rec(0)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    trips = load_trips()
    relay_sorties = load_relay_sorties()
    relay_trips = load_communication_relay_trips()
    inv = load_inventory()

    # step 1: blocks
    blocks = build_blocks(trips)
    tb, site_to_block = trip_to_blocks(trips, blocks)
    n_blocks = len(blocks)

    block_trips = defaultdict(list)
    for t in trips:
        for b in tb[t["trip_id"]]:
            block_trips[b].append(t["trip_id"])
    trip_boxes = {t["trip_id"]: t["box_ids"] for t in trips}
    block_boxes = {b: sum(len(trip_boxes[t]) for t in block_trips[b]) for b in range(n_blocks)}
    block_sites = {b: len(blocks[b]) for b in range(n_blocks)}
    block_energy = {b: sum(t["total_energy_kwh"] for t in trips if t["trip_id"] in block_trips[b])
                    for b in range(n_blocks)}
    block_occ = {b: sum(t["return_s"] - t["preparation_start_s"]
                        for t in trips if t["trip_id"] in block_trips[b])
                 for b in range(n_blocks)}

    # relay -> blocks
    relay_blocks = {}
    for sortie in relay_sorties:
        rid = sortie["relay_id"]
        served_trips = relay_trips.get(rid, set())
        rb = set()
        for t in served_trips:
            rb.update(tb[t])
        relay_blocks[rid] = sorted(rb)
    # sortie->relay id mapping
    sortie_relay = {s["sortie_id"]: s["relay_id"] for s in relay_sorties}

    # write blocks outputs
    block_rows = []
    for i, b in enumerate(blocks):
        for s in b:
            block_rows.append(dict(block_id=f"B{i+1:02d}", service_id=s,
                                   related_trip_ids=";".join(sorted(block_trips[i]))))
    write_csv(OUT / "q4_service_blocks.csv", block_rows)
    blocks_summary = dict(n_service_areas=15, n_blocks=n_blocks,
                          blocks=[{"block_id": f"B{i+1:02d}", "service_ids": b,
                                   "trip_ids": sorted(block_trips[i])}
                                  for i, b in enumerate(blocks)],
                          relay_sharing={rid: [f"B{i+1:02d}" for i in rb]
                                         for rid, rb in relay_blocks.items()})
    (OUT / "q4_blocks_summary.json").write_text(
        json.dumps(blocks_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # inventory
    (OUT / "q4_inventory.json").write_text(
        json.dumps(dict(transport_drones=inv["transport_drones"],
                        batteries=inv["batteries"],
                        relay_drones=inv["relay_drones"],
                        relay_energy_modules=inv["relay_energy_modules"]),
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # centralised baseline (same algorithm on full task)
    def account(groups):
        out = []
        for gi, block_ids in enumerate(groups):
            trips_g = [t for t in trips if any(b in block_ids for b in tb[t["trip_id"]])]
            # relay sorties assigned to this group (all served blocks in group)
            sorties_g = [s for s in relay_sorties
                         if all(b in block_ids for b in relay_blocks[s["relay_id"]])]
            td = transport_drones_required(trips_g)
            bt = batteries_required(trips_g, inv["type_charge_s"])
            rd = relay_drones_required([s["sortie_id"] for s in sorties_g])
            rm = relay_modules_required(sorties_g, inv["relay_module_full_charge_s"])
            out.append(dict(
                group=gi, blocks=block_ids,
                trips=[t["trip_id"] for t in trips_g],
                n_sites=sum(block_sites[b] for b in block_ids),
                n_boxes=sum(block_boxes[b] for b in block_ids),
                n_trips=len(trips_g),
                occupancy_s=sum(t["return_s"] - t["preparation_start_s"] for t in trips_g),
                transport_energy_kwh=sum(t["total_energy_kwh"] for t in trips_g),
                relay_service_s=sum(s["service_end_s"] - s["service_start_s"] for s in sorties_g),
                relay_energy_kwh=sum(s["energy_kwh"] for s in sorties_g),
                transport_drones=td, batteries=bt,
                relay_drones=rd, relay_modules=rm))
        return out

    base_groups = account([list(range(n_blocks))])
    base = base_groups[0]

    # enumerate partitions and check relay compatibility (strict: each relay's
    # blocks must be in a single group)
    def relay_compatible(groups):
        for rid, rb in relay_blocks.items():
            gs = {next(g for g, ids in enumerate(groups) if b in ids) for b in rb}
            if len(gs) > 1:
                return False
        return True

    results = {}
    for k in (2, 3):
        feasible = []
        infeasible_count = 0
        for groups in enumerate_partitions(n_blocks, k):
            if not relay_compatible(groups):
                infeasible_count += 1
                continue
            acct = account(groups)
            feasible.append(dict(groups=groups, acct=acct))
        results[k] = dict(feasible=feasible, infeasible_count=infeasible_count)
        print(f"[q4] k={k}: feasible={len(feasible)}, infeasible={infeasible_count}")

    # resource totals + metrics for feasible partitions
    def summarize(groups, acct):
        td = Counter()
        bt = Counter()
        rd = 0
        rm = 0
        for g in acct:
            for typ, v in g["transport_drones"].items():
                td[typ] += v
            for typ, v in g["batteries"].items():
                bt[typ] += v
            rd += g["relay_drones"]
            rm += g["relay_modules"]
        return dict(transport_drones=dict(td), batteries=dict(bt),
                    relay_drones=rd, relay_modules=rm)

    # store feasible partitions into CSVs (with metrics)
    for k in (2, 3):
        rows = []
        for fp in results[k]["feasible"]:
            groups = fp["groups"]
            acct = fp["acct"]
            tot = summarize(groups, acct)
            # workload W (5 equal weights)
            norm = []
            for col in range(5):
                vals = [g[["n_trips", "occupancy_s", "transport_energy_kwh",
                           "n_boxes", "relay_service_s"][col]] for g in acct]
                lo, hi = min(vals), max(vals)
                norm.append([(v - lo) / (hi - lo) if hi > lo else 0.0 for v in vals])
            W = [0.2 * sum(norm[c][gi] for c in range(5)) for gi in range(len(acct))]
            rows.append(dict(k=k, groups="|".join(
                "{" + ",".join(f"B{i+1:02d}" for i in g) + "}" for g in groups),
                n_trips_per_group=";".join(str(g["n_trips"]) for g in acct),
                transport_drones=json.dumps(tot["transport_drones"], ensure_ascii=False),
                batteries=json.dumps(tot["batteries"], ensure_ascii=False),
                relay_drones=tot["relay_drones"], relay_modules=tot["relay_modules"],
                workload_W=";".join(f"{w:.4f}" for w in W),
                workload_range=max(W) - min(W),
                workload_cv=(__import__("statistics").stdev(W) / __import__("statistics").mean(W)
                             if len(W) > 1 else 0.0)))
        write_csv(OUT / f"q4_all_partitions_{k}groups.csv", rows)

    print("[q4] done enumeration; writing best/compare files")
    write_best_and_compare(results, blocks, block_sites, block_boxes, inv, account, trips, relay_sorties, relay_blocks)


def trips_by_id(tid, trips):
    return next(t for t in trips if t["trip_id"] == tid)


def write_best_and_compare(results, blocks, block_sites, block_boxes, inv, account, trips, relay_sorties, relay_blocks):
    # baseline centralised
    base = account([list(range(len(blocks)))])[0]

    def totals(acct):
        td = Counter(); bt = Counter(); rd = 0; rm = 0
        for g in acct:
            for typ, v in g["transport_drones"].items(): td[typ] += v
            for typ, v in g["batteries"].items(): bt[typ] += v
            rd += g["relay_drones"]; rm += g["relay_modules"]
        return dict(td), dict(bt), rd, rm

    def gaps(tot):
        inv_td = inv["transport_drones"]; inv_bt = inv["batteries"]
        gap = dict(transport_drones={t: max(0, tot[0].get(t, 0) - inv_td.get(t, 0)) for t in ("A", "B", "C")},
                   batteries={t: max(0, tot[1].get(t, 0) - inv_bt.get(t, 0)) for t in ("A", "B", "C")},
                   relay_drones=max(0, tot[2] - inv["relay_drones"]),
                   relay_modules=max(0, tot[3] - inv["relay_energy_modules"]))
        surplus = dict(transport_drones={t: max(0, inv_td.get(t, 0) - tot[0].get(t, 0)) for t in ("A", "B", "C")},
                       batteries={t: max(0, inv_bt.get(t, 0) - tot[1].get(t, 0)) for t in ("A", "B", "C")},
                       relay_drones=max(0, inv["relay_drones"] - tot[2]),
                       relay_modules=max(0, inv["relay_energy_modules"] - tot[3]))
        return gap, surplus

    for k in (2, 3):
        feas = results[k]["feasible"]
        best = None
        for fp in feas:
            tot = totals(fp["acct"])
            gap, _ = gaps(tot)
            gap_score = sum(gap["transport_drones"].values()) + sum(gap["batteries"].values()) \
                + gap["relay_drones"] + gap["relay_modules"]
            # workload imbalance (CV of trips per group)
            import statistics
            cv = (statistics.stdev([g["n_trips"] for g in fp["acct"]]) /
                  statistics.mean([g["n_trips"] for g in fp["acct"]])) if len(fp["acct"]) > 1 else 0
            score = (gap_score, sum(tot[0].values()) + sum(tot[1].values()) + tot[2] + tot[3], cv)
            if best is None or score < best[0]:
                best = (score, fp)
        if best is not None:
            fp = best[1]
            acct = fp["acct"]
            tot = totals(acct)
            gap, surplus = gaps(tot)
            best_json = dict(
                k=k, groups=[{"group_id": gi + 1,
                              "blocks": [f"B{i+1:02d}" for i in g],
                              "service_ids": [s for i in g for s in blocks[i]],
                              "n_sites": acct[gi]["n_sites"], "n_boxes": acct[gi]["n_boxes"],
                              "n_trips": acct[gi]["n_trips"],
                              "occupancy_s": acct[gi]["occupancy_s"],
                              "transport_energy_kwh": round(acct[gi]["transport_energy_kwh"], 6),
                              "relay_service_s": acct[gi]["relay_service_s"],
                              "relay_energy_kwh": round(acct[gi]["relay_energy_kwh"], 6),
                              "transport_drones": acct[gi]["transport_drones"],
                              "batteries": acct[gi]["batteries"],
                              "relay_drones": acct[gi]["relay_drones"],
                              "relay_modules": acct[gi]["relay_modules"]}
                             for gi, g in enumerate(fp["groups"])],
                total_resources=tot, resource_gap=gap, resource_surplus=surplus)
            (OUT / f"q4_best_{k}groups.json").write_text(
                json.dumps(best_json, ensure_ascii=False, indent=2), encoding="utf-8")
            # group resources csv
            gres = []
            for gi, g in enumerate(acct):
                gres.append(dict(group=gi + 1,
                                 service_ids=";".join(s for i in fp["groups"][gi] for s in blocks[i]),
                                 n_sites=g["n_sites"], n_boxes=g["n_boxes"], n_trips=g["n_trips"],
                                 occupancy_s=round(g["occupancy_s"], 2),
                                 transport_energy_kwh=round(g["transport_energy_kwh"], 6),
                                 relay_service_s=round(g["relay_service_s"], 2),
                                 relay_energy_kwh=round(g["relay_energy_kwh"], 6),
                                 drones_A=g["transport_drones"].get("A", 0),
                                 drones_B=g["transport_drones"].get("B", 0),
                                 drones_C=g["transport_drones"].get("C", 0),
                                 batteries_A=g["batteries"].get("A", 0),
                                 batteries_B=g["batteries"].get("B", 0),
                                 batteries_C=g["batteries"].get("C", 0),
                                 relay_drones=g["relay_drones"], relay_modules=g["relay_modules"]))
            write_csv(OUT / f"q4_group_resources_{k}groups.csv", gres)

    # resource comparison (centralised vs 2 vs 3)
    base_tot = totals([base])
    comp_rows = [dict(scenario="Q3集中式",
                      transport_drones=sum(base_tot[0].values()),
                      batteries=sum(base_tot[1].values()),
                      relay_drones=base_tot[2], relay_modules=base_tot[3])]
    for k in (2, 3):
        feas = results[k]["feasible"]
        if feas:
            best = min(feas, key=lambda fp: (sum(totals(fp["acct"])[0].values()) + sum(totals(fp["acct"])[1].values()) + totals(fp["acct"])[2] + totals(fp["acct"])[3]))
            tot = totals(best["acct"])
            comp_rows.append(dict(scenario=f"{k}组分区",
                                  transport_drones=sum(tot[0].values()),
                                  batteries=sum(tot[1].values()),
                                  relay_drones=tot[2], relay_modules=tot[3]))
        else:
            comp_rows.append(dict(scenario=f"{k}组分区", transport_drones=None,
                                  batteries=None, relay_drones=None, relay_modules=None))
    write_csv(OUT / "q4_resource_comparison.csv", comp_rows)

    # workload comparison (per group raw metrics + composite W)
    wrows = []
    for k in (2, 3):
        feas = results[k]["feasible"]
        if not feas:
            wrows.append(dict(scenario=f"{k}组", group=None, feasible=False,
                              n_sites=None, n_boxes=None, n_trips=None, occupancy_s=None,
                              transport_energy_kwh=None, relay_service_s=None,
                              relay_energy_kwh=None, note="relay_sharing_infeasible"))
            continue
        best = feas[0]
        for gi, g in enumerate(best["acct"]):
            wrows.append(dict(scenario=f"{k}组", group=gi + 1, feasible=True,
                              n_sites=g["n_sites"], n_boxes=g["n_boxes"], n_trips=g["n_trips"],
                              occupancy_s=round(g["occupancy_s"], 2),
                              transport_energy_kwh=round(g["transport_energy_kwh"], 6),
                              relay_service_s=round(g["relay_service_s"], 2),
                              relay_energy_kwh=round(g["relay_energy_kwh"], 6), note=""))
    write_csv(OUT / "q4_workload_comparison.csv", wrows)

    # resource gap / surplus (centralised vs partition)
    inv_td = inv["transport_drones"]; inv_bt = inv["batteries"]
    gaps = []
    for label, tot in [(r["scenario"], r) for r in comp_rows]:
        td = tot["transport_drones"]; bt = tot["batteries"]; rd = tot["relay_drones"]
        rm = tot["relay_modules"]
        if td is None:
            gaps.append(dict(scenario=label, feasible=False, transport_drones=None,
                             batteries=None, relay_drones=None, relay_modules=None,
                             inventory_drones=sum(inv_td.values()),
                             inventory_batteries=sum(inv_bt.values()),
                             inventory_relay_drones=inv["relay_drones"],
                             inventory_relay_modules=inv["relay_energy_modules"],
                             gap_drones=None, gap_batteries=None,
                             gap_relay_drones=None, gap_relay_modules=None,
                             surplus_relay_modules=None, note="relay_sharing_infeasible"))
            continue
        total_drone = td; total_batt = bt
        gap_drone = max(0, total_drone - sum(inv_td.values()))
        gap_batt = max(0, total_batt - sum(inv_bt.values()))
        gap_rd = max(0, rd - inv["relay_drones"])
        gap_rm = max(0, rm - inv["relay_energy_modules"])
        gaps.append(dict(scenario=label, feasible=True,
                         transport_drones=td, batteries=bt, relay_drones=rd, relay_modules=rm,
                         inventory_drones=sum(inv_td.values()), inventory_batteries=sum(inv_bt.values()),
                         inventory_relay_drones=inv["relay_drones"],
                         inventory_relay_modules=inv["relay_energy_modules"],
                         gap_drones=gap_drone, gap_batteries=gap_batt,
                         gap_relay_drones=gap_rd, gap_relay_modules=gap_rm,
                         surplus_relay_modules=max(0, inv["relay_energy_modules"] - rm),
                         note=""))
    write_csv(OUT / "q4_resource_gap.csv", gaps)

    # best 3 groups (infeasible marker)
    if not results[3]["feasible"]:
        (OUT / "q4_best_3groups.json").write_text(
            json.dumps(dict(k=3, feasible=False,
                            reason="relay_sharing_constraint_infeasible",
                            detail="中继R01/R02共享关联把11个不可拆块强制同组，剩余仅1个块无法构成3个非空组"),
                       ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(comp_rows, ensure_ascii=False, indent=2))


def write_csv(path, records):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        if not records:
            f.write("")
            return
        w = csv.DictWriter(f, fieldnames=list(records[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(records)


if __name__ == "__main__":
    main()
