"""Reproducible multi-start insertion heuristic; no global optimality claim."""
import argparse
import csv
import datetime
import hashlib
import itertools
import json
import platform
import random
import subprocess
import time
from pathlib import Path

from transport_core import Model, DEFAULT_RESULTS, DEFAULT_CONFIG, charge_time, write_csv


def write_csv_allow_empty(path, records, fieldnames):
    """Write a table with its header even when there are no rows (no stale leftovers)."""
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(records)


def objective(trips):
    soft = sum(d["priority"] * d["lateness_s"] for t in trips
               for d in t["deliveries"] if d["hard_due_s"] is None)
    return (soft, max(t["return_s"] for t in trips),
            sum(t["total_energy_kwh"] for t in trips), len(trips))


def resources(model):
    return {u: 0. for u in model.drones}, {b: 0. for b in model.batteries}


def assign(model, trip, drone, battery, drone_free, battery_free):
    trip["drone_id"], trip["battery_id"] = drone, battery
    drone_free[drone] = trip["return_s"] + model.config["turnaround_s"]
    battery_free[battery] = trip["return_s"] + charge_time(
        trip["return_soc"], model.types[trip["type_id"]]["full_charge_s"])


def construct(model, seed, max_stops):
    rng = random.Random(seed)
    remaining = set(model.boxes)
    drone_free, battery_free = resources(model)
    trips = []
    # Randomness changes tie breaks and packing preferences, never constraints.
    noise = {b: rng.uniform(.7, 1.3) for b in sorted(remaining)}
    pack_power = rng.uniform(.85, 1.5)
    while remaining:
        anchor = min(remaining, key=lambda b: (
            model.boxes[b]["hard_due_s"] is None,
            model.boxes[b]["hard_due_s"] or model.boxes[b]["desired_due_s"],
            noise[b], b))
        candidates = []
        for typ in sorted(model.types):
            drone = min((u for u in model.drones if model.drones[u] == typ),
                        key=lambda u: (drone_free[u], u))
            battery = min((b for b in model.batteries if model.batteries[b] == typ),
                          key=lambda b: (battery_free[b], b))
            start = max(drone_free[drone], battery_free[battery])
            ids = [anchor]
            route = [model.boxes[anchor]["destination"]]
            try:
                current = model.trip(typ, ids, route, start)
            except ValueError:
                continue
            while True:
                insertions = []
                for box_id in sorted(remaining - set(ids)):
                    b = model.boxes[box_id]
                    dest = b["destination"]
                    if dest in route:
                        routes = [route]
                    elif len(route) < max_stops:
                        routes = [route[:p] + [dest] + route[p:] for p in range(len(route)+1)]
                    else:
                        continue
                    for proposed in routes:
                        try:
                            trial = model.trip(typ, ids + [box_id], proposed, start)
                        except ValueError:
                            continue
                        extra = trial["return_s"] - current["return_s"]
                        urgency = 3. if b["hard_due_s"] is not None else 1.
                        # Favors same-stop packing, urgent boxes and earlier wishes.
                        gain = urgency * noise[box_id] * (3600 / b["desired_due_s"]) ** .3
                        insertions.append((extra / gain, box_id, proposed, trial))
                if not insertions:
                    break
                _, box_id, route, current = min(insertions, key=lambda v: (v[0], v[1], v[2]))
                ids.append(box_id)
            value = sum((3 if model.boxes[b]["hard_due_s"] is not None else 1) * noise[b] for b in ids)
            score = (current["return_s"] - start + .65 * start) / value ** pack_power
            score += sum(d["lateness_s"] * d["priority"] for d in current["deliveries"]) / 20
            candidates.append((score, typ, current, drone, battery))
        if not candidates:
            raise ValueError(f"No feasible insertion for {anchor}")
        _, _, chosen, drone, battery = min(candidates, key=lambda v: (v[0], v[1]))
        assign(model, chosen, drone, battery, drone_free, battery_free)
        remaining.difference_update(chosen["box_ids"])
        trips.append(chosen)
    return trips


def recompute(model, entries):
    """Respect explicit IDs/resources/start times; reject rather than repair conflicts."""
    trips = []
    for item in entries:
        drone, battery = item["drone_id"], item["battery_id"]
        typ = model.drones[drone]
        if model.batteries[battery] != typ:
            raise ValueError("Battery type mismatch")
        trip = model.trip(typ, item["box_ids"], item["route"], float(item["preparation_start_s"]))
        trip.update(drone_id=drone, battery_id=battery, trip_id=item["trip_id"])
        trips.append(trip)
    ids = [b for t in trips for b in t["box_ids"]]
    if len(ids) != len(set(ids)) or set(ids) != set(model.boxes):
        raise ValueError("Incomplete/duplicated box coverage")
    if len({t["trip_id"] for t in trips}) != len(trips):
        raise ValueError("Duplicate trip identifiers")
    for resource, inventory in [("drone_id", model.drones), ("battery_id", model.batteries)]:
        for ident in inventory:
            free = 0.
            for trip in sorted((t for t in trips if t[resource] == ident), key=lambda t: t["start_s"]):
                if trip["start_s"] < free - 1e-8:
                    raise ValueError(f"Resource conflict: {ident}")
                free = trip["return_s"] + (model.config["turnaround_s"] if resource == "drone_id"
                       else charge_time(trip["return_soc"], model.types[trip["type_id"]]["full_charge_s"]))
    return trips


def schedule_groups(model, groups):
    drone_free, battery_free = resources(model)
    trips = []
    for group in groups:
        typ, ids = group["type_id"], group["box_ids"]
        drone = min((u for u in model.drones if model.drones[u] == typ),
                    key=lambda u: (drone_free[u], u))
        battery = min((b for b in model.batteries if model.batteries[b] == typ),
                      key=lambda b: (battery_free[b], b))
        start = max(drone_free[drone], battery_free[battery])
        routes = itertools.permutations(sorted({model.boxes[b]["destination"] for b in ids}))
        feasible = []
        for route in routes:
            try:
                trip = model.trip(typ, ids, list(route), start)
            except ValueError:
                continue
            feasible.append(trip)
        if not feasible:
            raise ValueError("Group cannot be scheduled")
        trip = min(feasible, key=lambda t: objective([t]))
        assign(model, trip, drone, battery, drone_free, battery_free)
        trips.append(trip)
    return trips


def improve(model, initial, iterations, max_stops):
    rng = random.Random(20260923)
    best = initial
    groups = [dict(type_id=t["type_id"], box_ids=t["box_ids"][:]) for t in best]
    history = []
    for step in range(iterations):
        proposed = [dict(type_id=g["type_id"], box_ids=g["box_ids"][:]) for g in groups]
        a, b = rng.sample(range(len(proposed)), 2)
        move = rng.randrange(4)
        if move == 0:
            box = rng.choice(proposed[a]["box_ids"])
            proposed[a]["box_ids"].remove(box)
            proposed[b]["box_ids"].append(box)
            proposed = [g for g in proposed if g["box_ids"]]
        elif move == 1:
            proposed[a], proposed[b] = proposed[b], proposed[a]
        elif move == 2:
            proposed[a]["type_id"] = rng.choice(sorted(model.types))
        else:
            x, y = rng.randrange(len(proposed[a]["box_ids"])), rng.randrange(len(proposed[b]["box_ids"]))
            proposed[a]["box_ids"][x], proposed[b]["box_ids"][y] = proposed[b]["box_ids"][y], proposed[a]["box_ids"][x]
        if any(len({model.boxes[b]["destination"] for b in g["box_ids"]}) > max_stops for g in proposed):
            continue
        try:
            candidate = schedule_groups(model, proposed)
        except ValueError:
            continue
        if objective(candidate) < objective(best):
            best, groups = candidate, proposed
            obj = objective(best)
            history.append(dict(iteration=step, weighted_soft_lateness_s=obj[0],
                                makespan_s=obj[1], energy_kwh=obj[2], trips=obj[3]))
    return best, history


def export(model, trips, out, run_info):
    out.mkdir(parents=True, exist_ok=True)
    tables = {k: [] for k in ("trips", "deliveries", "segments", "drone_schedule", "battery_schedule")}
    plan = []
    for n, trip in enumerate(trips, 1):
        tid = trip.get("trip_id", f"T{n:03d}")
        common = dict(trip_id=tid, drone_id=trip["drone_id"], type_id=trip["type_id"],
                      battery_id=trip["battery_id"])
        tables["trips"].append(dict(
            **common, box_ids_json=json.dumps(trip["box_ids"]), route="-".join(trip["route"]),
            preparation_start_s=trip["start_s"], takeoff_s=trip["departure_s"],
            return_s=trip["return_s"], preparation_s=trip["preparation_s"],
            loading_s=trip["loading_s"],
            flight_s=sum(s["ascent_duration_s"]+s["cruise_duration_s"]+s["descent_duration_s"] for s in trip["segments"]),
            handover_s=sum(s["handover_end_s"]-s["handover_start_s"] for s in trip["segments"]),
            turnaround_s=trip["turnaround_s"], total_energy_kwh=trip["total_energy_kwh"],
            return_soc=trip["return_soc"], takeoff_mass_kg=trip["mass_kg"],
            takeoff_volume_m3=trip["volume_m3"], scenario_status=model.config["status"]))
        for s in trip["segments"]:
            a, b = model.nodes[s["origin"]], model.nodes[s["destination"]]
            tables["segments"].append(dict(**common, **s,
                origin_x_m=a["x_m"], origin_y_m=a["y_m"], origin_work_altitude_m=a["work_m"],
                destination_x_m=b["x_m"], destination_y_m=b["y_m"], destination_work_altitude_m=b["work_m"]))
        tables["deliveries"].extend(dict(**common, **d) for d in trip["deliveries"])
        tables["drone_schedule"].append(dict(
            **common, occupancy_start_s=trip["start_s"], return_s=trip["return_s"],
            occupancy_end_s=trip["return_s"] + trip["turnaround_s"],
            next_available_s=trip["return_s"] + trip["turnaround_s"]))
        full = model.types[trip["type_id"]]["full_charge_s"]
        charged = trip["return_s"] + charge_time(trip["return_soc"], full)
        tables["battery_schedule"].append(dict(
            **common, occupancy_start_s=trip["start_s"], use_end_s=trip["return_s"],
            initial_soc=1., task_end_soc=trip["return_soc"], charge_start_s=trip["return_s"],
            charge_end_s=charged, next_available_s=charged, charged_soc=1.))
        plan.append(dict(trip_id=tid, drone_id=trip["drone_id"], battery_id=trip["battery_id"],
                         box_ids=trip["box_ids"], route=trip["route"][1:-1],
                         preparation_start_s=trip["start_s"]))
    for name, records in tables.items():
        write_csv(out / f"q2_{name}.csv", records)
    obj = objective(trips)
    metrics = dict(scenario_status=model.config["status"], total_boxes=len(model.boxes),
                   hard_deadline_boxes=sum(b["hard_due_s"] is not None for b in model.boxes.values()),
                   total_trips=len(trips), multipoint_trips=sum(len(t["route"]) > 3 for t in trips),
                   total_energy_kwh=obj[2], makespan_s=obj[1], weighted_soft_lateness_s=obj[0],
                   late_boxes=sum(d["lateness_s"] > 1e-8 for t in trips for d in t["deliveries"]),
                   min_return_soc=min(t["return_soc"] for t in trips),
                   total_operation_s=sum(t["return_s"]-t["start_s"]+t["turnaround_s"] for t in trips))
    write_csv(out / "q2_summary.csv", [dict(metric=k, value=v) for k, v in metrics.items()])
    (out / "q2_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (out / "q2_scenario.json").write_text(json.dumps(model.config, indent=2), encoding="utf-8")
    (out / "q2_inputs.json").write_text(json.dumps(model.data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "q2_run.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", type=Path, default=DEFAULT_RESULTS / "q2_inputs.json")
    p.add_argument("--config", type=Path, required=True,
                   help="formal scenario config (Q2/code/scenario.json); explicit binding required, no silent default")
    p.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    p.add_argument("--seeds", type=int, default=256)
    p.add_argument("--max-stops", type=int, default=4)
    p.add_argument("--improve-iterations", type=int, default=5000)
    p.add_argument("--plan", type=Path)
    args = p.parse_args()
    begin = time.perf_counter()
    model = Model(args.inputs, args.config)
    run = dict(python=platform.python_version(),
               inputs_sha256=hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
               config_path=str(args.config.resolve()),
               config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),
               timestamp=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               algorithm="multi-start greedy insertion", seed_start=20260923,
               attempts_per_method=args.seeds, max_stops=args.max_stops,
               improvement_iterations=args.improve_iterations)
    try:
        run["base_commit_at_run"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        run["base_commit_at_run"] = "unavailable"
    if args.plan:
        trips = recompute(model, json.loads(args.plan.read_text(encoding="utf-8")))
        run["algorithm"] = "explicit plan recalculation"
        run["plan_sha256"] = hashlib.sha256(args.plan.read_bytes()).hexdigest()
    else:
        best, history = None, []
        for stops, label in [(1, "single_stop_baseline"), (args.max_stops, "multipoint")]:
            for i in range(args.seeds):
                seed = 20260923 + i
                record = dict(method=label, seed=seed, feasible=False,
                              weighted_soft_lateness_s="", makespan_s="", energy_kwh="", trips="", error="")
                try:
                    candidate = construct(model, seed, stops)
                    obj = objective(candidate)
                    record.update(feasible=True, weighted_soft_lateness_s=obj[0],
                                  makespan_s=obj[1], energy_kwh=obj[2], trips=obj[3])
                    if best is None or obj < objective(best):
                        best = candidate
                        run["selected_method"], run["selected_seed"] = label, seed
                except ValueError as exc:
                    record["error"] = str(exc)
                history.append(record)
                if i % 32 == 0 or i == args.seeds-1:
                    print(label, i, record["feasible"], record["makespan_s"], flush=True)
        args.output.mkdir(parents=True, exist_ok=True)
        write_csv(args.output / "q2_search_history.csv", history)
        if best is None:
            raise RuntimeError("No feasible schedule found; not proof of infeasibility")
        run["before_improvement_objective"] = objective(best)
        trips, improvements = improve(model, best, args.improve_iterations, args.max_stops)
        # Always (re)write the improvement log, even when empty, so a fresh run
        # cannot leave a stale q2_improvement.csv from a previous run behind.
        write_csv_allow_empty(args.output / "q2_improvement.csv", improvements,
                              ["iteration", "weighted_soft_lateness_s", "makespan_s",
                               "energy_kwh", "trips"])
        run["accepted_improvements"] = len(improvements)
    run["elapsed_s"] = time.perf_counter() - begin
    run["code_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(Path(__file__).parent.glob("*.py"))}
    export(model, trips, args.output, run)
    from validate import validate
    validate(args.output)


if __name__ == "__main__":
    main()
