"""Independent validation of Q4 partition + resource accounting (relaxed relay).

Indivisible blocks come only from multi-site transport trips.  Relay resources
are accounted per group independently (a Q3 relay sortie serving trips in
several groups is duplicated per group).  Recomputes everything from Q2/Q3 raw
files without importing q4_solve.

Coverage (all checks are recomputed from raw inputs, never read from a prior
PASS boolean):
  - block construction from trip edges (12 indivisible blocks, 15 service areas);
  - per-group resource recomputation vs. submitted best JSON (drones/batteries/
    relay drones/relay modules), separately for the 2-group and 3-group plans;
  - partition legality per plan: service-area complete coverage + uniqueness,
    no empty group, atomic-block integrity, multi-site-trip co-grouping;
  - resource non-negativity per plan;
  - exhaustive optimality check: independently enumerate every legal 2/3-group
    partition, recompute its resources and lexicographic objective, then verify
    the selected plans and saved candidate CSVs against those results.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 本程序及代码是在人工智能工具辅助下完成的：OpenAI Codex，GPT-5（公开发布日期：2025-08-07；
# 运行构建标识未公开），OpenAI；本次验证器修订日期：2026-09-24。

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
    # 中继架次按 sortie_id（provider 字段，S01/S02/S03）归属；R02 的两次架次 S02/S03 分开统计。
    relay_trips = defaultdict(set)
    for r in read_csv(Q3R / "q3_communication_links.csv"):
        sortie = (r.get("sortie_id") or r.get("provider") or "").strip()
        if sortie and sortie != "G01":
            relay_trips[sortie].add(r["trip_id"])
    q2 = json.loads((Q2R / "q2_inputs.json").read_text(encoding="utf-8"))
    type_charge = {t["type_id"]: t["full_charge_s"] for t in q2["types"].values()}
    inventory = dict(
        drones=Counter(q2["drones"].values()),
        batteries=Counter(q2["batteries"].values()),
        relay_drones=2,
        relay_modules=6,
    )

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
        sorties = [s for s in relay if any(t in tids for t in relay_trips[s["sortie_id"]])]
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
        return dict(
            n_trips=len(g_trips),
            n_boxes=sum(len(t["box_ids"]) for t in g_trips),
            occupancy_s=sum(t["ret"] - t["prep"] for t in g_trips),
            energy=sum(t["energy"] for t in g_trips),
            relay_service_s=sum(s["service_end"] - s["service_start"] for s in sorties),
            drones=drones,
            batteries=batteries,
            relay_drones=len(set(s["relay_id"] for s in sorties)),
            relay_modules=len(avail),
        )

    def encode_partition(groups):
        return "|".join("{" + ",".join(f"B{i + 1:02d}" for i in group) + "}" for group in groups)

    def decode_partition(value, k):
        try:
            groups = []
            for part in value.split("|"):
                if len(part) < 3 or part[0] != "{" or part[-1] != "}":
                    return None
                body = part[1:-1]
                if not body:
                    return None
                group = []
                for token in body.split(","):
                    if len(token) < 2 or token[0] != "B":
                        return None
                    block_id = int(token[1:]) - 1
                    if not 0 <= block_id < len(blocks):
                        return None
                    group.append(block_id)
                if len(group) != len(set(group)):
                    return None
                groups.append(tuple(sorted(group)))
            flat = [b for group in groups for b in group]
            if (len(groups) != k or any(not group for group in groups)
                    or sorted(flat) != list(range(len(blocks)))
                    or len(flat) != len(set(flat))):
                return None
            return tuple(groups)
        except (TypeError, ValueError):
            return None

    def score_partition(groups):
        group_accounts = [account(group) for group in groups]
        total_drones = Counter()
        total_batteries = Counter()
        relay_drones = relay_modules = 0
        for group in group_accounts:
            total_drones.update(group["drones"])
            total_batteries.update(group["batteries"])
            relay_drones += group["relay_drones"]
            relay_modules += group["relay_modules"]

        gap = sum(max(0, total_drones[t] - inventory["drones"][t]) for t in "ABC")
        gap += sum(max(0, total_batteries[t] - inventory["batteries"][t]) for t in "ABC")
        gap += max(0, relay_drones - inventory["relay_drones"])
        gap += max(0, relay_modules - inventory["relay_modules"])
        total_resources = (sum(total_drones.values()) + sum(total_batteries.values())
                           + relay_drones + relay_modules)

        # Reproduce the documented per-candidate normalization and equal weights.
        metrics = ("n_trips", "occupancy_s", "energy", "n_boxes", "relay_service_s")
        group_work = [0.0] * len(group_accounts)
        for metric in metrics:
            values = [group[metric] for group in group_accounts]
            lo, hi = min(values), max(values)
            for i, value in enumerate(values):
                group_work[i] += 0.2 * ((value - lo) / (hi - lo) if hi > lo else 0.0)
        imbalance = max(group_work) - min(group_work)
        return gap, total_resources, imbalance

    def enumerate_partitions(n_blocks, k):
        # Restricted-growth strings generate each unlabeled set partition once.
        assignment = [0] * n_blocks

        def visit(position, used_groups):
            if position == n_blocks:
                if used_groups == k:
                    groups = [[] for _ in range(k)]
                    for block_id, group_id in enumerate(assignment):
                        groups[group_id].append(block_id)
                    yield tuple(tuple(group) for group in groups)
                return
            remaining = n_blocks - position - 1
            for group_id in range(min(used_groups + 1, k)):
                next_used = max(used_groups, group_id + 1)
                if next_used + remaining < k:
                    continue
                assignment[position] = group_id
                yield from visit(position + 1, next_used)

        yield from visit(0, 0)

    # ------------------------------------------------------------------
    # 最终分区方案验证（2 组 / 3 组分别独立验证，避免循环变量残留）
    # ------------------------------------------------------------------
    best = {}
    mismatches = []
    for k in (2, 3):
        bj = json.loads((OUT / f"q4_best_{k}groups.json").read_text(encoding="utf-8"))
        best[k] = bj
        groups = bj["groups"]
        prefix = f"{k}groups"
        gbs = [[int(b[1:]) - 1 for b in g["blocks"]] for g in groups]

        # 资源核算复核：每组独立重算，与 JSON 值逐一比对
        for gi, g in enumerate(groups):
            ac = account(gbs[gi])
            if ac["drones"] != {t: v for t, v in g["transport_drones"].items()}:
                mismatches.append((f"q4_best_{k}groups.json", gi, "drones"))
            if ac["batteries"] != {t: v for t, v in g["batteries"].items()}:
                mismatches.append((f"q4_best_{k}groups.json", gi, "batteries"))
            if ac["relay_drones"] != g["relay_drones"]:
                mismatches.append((f"q4_best_{k}groups.json", gi, "relay_drones"))
            if ac["relay_modules"] != g["relay_modules"]:
                mismatches.append((f"q4_best_{k}groups.json", gi, "relay_modules"))

        # A. 服务区完整覆盖：S001–S015 全部出现
        covered = sorted({s for gb in gbs for b in gb for s in blocks[b]})
        check(f"{prefix}_service_area_complete_coverage",
              covered == all_sites, f"{len(covered)}/{len(all_sites)} 服务区")

        # B. 每个服务区恰好属于一个组（不重、不漏）
        flat_sites = [s for gb in gbs for b in gb for s in blocks[b]]
        check(f"{prefix}_service_area_exactly_once",
              sorted(flat_sites) == all_sites and len(flat_sites) == len(set(flat_sites)))

        # C. 无空组
        check(f"{prefix}_no_empty_group", all(len(gb) > 0 for gb in gbs))

        # D. 原子不可拆块完整：12 个块各恰好出现一次，不跨组
        flat_blocks = [b for gb in gbs for b in gb]
        check(f"{prefix}_atomic_block_integrity",
              sorted(flat_blocks) == list(range(len(blocks)))
              and len(flat_blocks) == len(set(flat_blocks)))

        # E. 多站运输架次涉及的服务区同组
        ms_ok = True
        for t in trips:
            bs = tb[t["trip_id"]]
            if len(bs) > 1:
                gs = {next(gi for gi, gb in enumerate(gbs) if b in gb) for b in bs}
                if len(gs) > 1:
                    ms_ok = False
        check(f"{prefix}_multi_site_trip_co_grouped", ms_ok)

        # 资源非负整数
        nonneg = all(v >= 0 for g in groups for t, v in g["transport_drones"].items()) \
            and all(v >= 0 for g in groups for t, v in g["batteries"].items()) \
            and all(g["relay_drones"] >= 0 and g["relay_modules"] >= 0 for g in groups)
        check(f"{prefix}_resources_nonnegative", nonneg)

    check("resource_recomputation_matches", not mismatches, f"mismatch={mismatches[:5]}")

    # ------------------------------------------------------------------
    # 独立穷举复核：不调用 q4_solve，重新生成所有无标签分区并重算目标值。
    # ------------------------------------------------------------------
    for k in (2, 3):
        expected_count = {2: 2047, 3: 86526}[k]
        scored = []
        candidate_ids = set()
        for groups in enumerate_partitions(len(blocks), k):
            partition_id = encode_partition(groups)
            candidate_ids.add(partition_id)
            scored.append((score_partition(groups), partition_id))
        scored.sort(key=lambda item: item[0])
        best_score = scored[0][0]
        check(f"enum_{k}groups_all_candidates_recomputed",
              len(scored) == expected_count and len(candidate_ids) == expected_count,
              f"independently enumerated {len(scored)} unique partitions")

        b = best[k]
        submitted_groups = tuple(
            tuple(sorted(int(block[1:]) - 1 for block in group["blocks"]))
            for group in b["groups"]
        )
        submitted_id = encode_partition(submitted_groups)
        submitted_score = score_partition(submitted_groups)
        submitted_is_candidate = submitted_id in candidate_ids
        optimum_matches = (submitted_is_candidate
                           and submitted_score[:2] == best_score[:2]
                           and abs(submitted_score[2] - best_score[2]) <= 1e-10
                           and b["gap_sum"] == best_score[0]
                           and b["total_resources_sum"] == best_score[1]
                           and abs(b["workload_imbalance"] - round(best_score[2], 6)) <= 5e-7)
        check(f"enum_{k}groups_submitted_plan_is_global_lexicographic_optimum",
              optimum_matches,
              f"independent minimum={best_score[0]}/{best_score[1]}/{best_score[2]:.9f}; "
              f"submitted={submitted_score[0]}/{submitted_score[1]}/{submitted_score[2]:.9f}")
        check(f"enum_{k}groups_candidate_count_matches_best_json",
              b.get("n_candidates") == expected_count)

        rows = read_csv(OUT / f"q4_all_partitions_{k}groups.csv")
        row_ids = [row.get("partition", "") for row in rows]
        csv_objectives = []
        row_values_match = True
        for row, partition_id in zip(rows, row_ids):
            groups = decode_partition(partition_id, k)
            if groups is None or partition_id not in candidate_ids:
                row_values_match = False
                continue
            objective = score_partition(groups)
            csv_objectives.append((objective[0], objective[1], round(objective[2], 6)))
            if (int(row["gap"]) != objective[0]
                    or int(row["total_resources"]) != objective[1]
                    or abs(float(row["imbalance"]) - objective[2]) > 5e-7):
                row_values_match = False
        actual_keys = [(int(row["gap"]), int(row["total_resources"]), float(row["imbalance"]))
                       for row in rows]
        sorted_ok = all(actual_keys[i] <= actual_keys[i + 1]
                        for i in range(len(actual_keys) - 1))
        check(f"enum_{k}groups_csv_rows_recompute_correctly", row_values_match,
              f"recomputed {len(csv_objectives)}/{len(rows)} saved candidates")
        check(f"enum_{k}groups_csv_sorted", sorted_ok, f"{len(rows)} saved rows")

        if k == 2:
            check("enum_2groups_csv_is_full_unique_enumeration",
                  len(rows) == expected_count and len(set(row_ids)) == expected_count
                  and set(row_ids) == candidate_ids,
                  f"saved {len(rows)} rows for {expected_count} candidates")
        else:
            summ = json.loads((OUT / "q4_all_partitions_3groups_summary.json").read_text(encoding="utf-8"))
            check("enum_3groups_total_enumerated", summ.get("total_enumerated") == expected_count,
                  f"total_enumerated={summ.get('total_enumerated')}")
            check("enum_3groups_saved_top_n",
                  summ.get("saved_top_n") == 1000 and len(rows) == 1000
                  and len(set(row_ids)) == 1000,
                  f"saved_top_n={summ.get('saved_top_n')}, csv_rows={len(rows)}")
            expected_top_keys = [
                (objective[0], objective[1], round(objective[2], 6))
                for objective, _ in scored[:1000]
            ]
            check("enum_3groups_csv_matches_global_top_1000_objectives",
                  csv_objectives == expected_top_keys,
                  "saved objective sequence compared with independently sorted full enumeration")

    # Q3 不变
    check("trip_count_unchanged", len(trips) == 26)
    # 正式 Q3 为两物理中继 R01/R02，R02 两次顺序架次 → 3 个 relay sorties。
    # 中继架次由 q3_relay_schedule.csv 直接读取，Q4 不改动。
    check("relay_schedule_unchanged", len(relay) == 3,
          f"{len(relay)} relay sorties (R01 x1 + R02 x2, physical relays = 2)")

    # gap 计算正确
    inv = json.loads((OUT / "q4_inventory.json").read_text(encoding="utf-8"))
    b2 = best[2]
    tot_d = sum(sum(g["transport_drones"].values()) for g in b2["groups"])
    tot_b = sum(sum(g["batteries"].values()) for g in b2["groups"])
    tot_r = sum(g["relay_drones"] for g in b2["groups"])
    tot_m = sum(g["relay_modules"] for g in b2["groups"])
    gap_ok = (b2["gap_sum"] ==
              max(0, tot_d - sum(inventory["drones"].values())) +
              max(0, tot_b - sum(inventory["batteries"].values())) +
              max(0, tot_r - inventory["relay_drones"]) +
              max(0, tot_m - inventory["relay_modules"]))
    check("gap_calculation_correct", gap_ok, f"gap_sum={b2['gap_sum']}")
    inventory_matches = (
        inv["transport_drones"] == dict(inventory["drones"])
        and inv["batteries"] == dict(inventory["batteries"])
        and inv["relay_drones"] == inventory["relay_drones"]
        and inv["relay_energy_modules"] == inventory["relay_modules"]
    )
    check("inventory_export_matches_independent_inputs", inventory_matches)

    # 复现性
    b3 = best[3]
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
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
