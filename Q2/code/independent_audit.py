"""Read-only, reproducible second-review checks; stdout is a JSON report.

Run from repository root:
    python -B Q2/code/independent_audit.py
Optional: --dem PATH --step-m 0.25 --skip-improve-replay
Requires numpy, scipy, pyproj, mpmath and the production modules' dependencies.
All mutation fixtures and frozen inputs live in a disposable temporary directory.
No Model.trip/leg or validate calls are used for independent schedule arithmetic.
Dense DEM samples are a reference only, never a cell-enumeration certificate.
"""
import argparse
import csv
import hashlib
import io
import itertools
import json
import math
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from pathlib import Path

sys.dont_write_bytecode = True

import mpmath as mp
import numpy as np
from pyproj import Transformer
from scipy.io import loadmat

CODE = Path(__file__).resolve().parent
REPO = CODE.parents[1]
CODE_FILES = (
    "prepare_data.py", "transport_core.py", "solve.py", "validate.py",
    "utm_interval.py", "scenario.json",
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(root, name):
    with (root / ("q2_" + name + ".csv")).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def close(actual, expected, label, errors=None):
    error = abs(float(actual) - float(expected))
    require(math.isfinite(error) and error <= 1e-7, "Mismatch: " + label)
    if errors is not None:
        errors[label] = max(errors.get(label, 0.), error)


def independent_schedule(root):
    data, cfg = read_json(root / "q2_inputs.json"), read_json(root / "q2_scenario.json")
    plan = read_json(root / "q2_plan.json")
    trips, delivery, segments = rows(root, "trips"), rows(root, "deliveries"), rows(root, "segments")
    coverage = Counter(b for p in plan for b in p["box_ids"])
    require(coverage == Counter({b: 1 for b in data["boxes"]}), "Plan box coverage")
    require(Counter(d["box_id"] for d in delivery) == coverage, "Delivery coverage")
    require(len({p["trip_id"] for p in plan}) == len(plan), "Duplicate plan trip")
    require(Counter(r["trip_id"] for r in trips) == Counter(p["trip_id"] for p in plan), "Trip coverage")
    tids = {p["trip_id"] for p in plan}
    require(all(s["trip_id"] in tids for s in segments), "Unknown segment trip")
    errors, hard_slacks, soft_slacks = {}, [], []
    energies, ends, socs, reserve_margins, operations = [], [], [], [], []
    intervals = {"drone": defaultdict(list), "battery": defaultdict(list)}
    soft_late, late_count, multipoint = 0., 0, []
    trip_map = {r["trip_id"]: r for r in trips}
    delivery_map = {r["box_id"]: r for r in delivery}
    for p in plan:
        tid = p["trip_id"]
        r = trip_map[tid]
        typ = data["drones"][p["drone_id"]]
        require(data["batteries"][p["battery_id"]] == typ, "Battery type")
        require(all(r[key] == p[key] for key in ("drone_id", "battery_id")), "Plan resources")
        require(r["type_id"] == typ, "Trip type")
        require(Counter(json.loads(r["box_ids_json"])) == Counter(p["box_ids"]), "Plan cargo")
        boxes = [data["boxes"][b] for b in p["box_ids"]]
        mass, volume = sum(b["mass_kg"] for b in boxes), sum(b["volume_m3"] for b in boxes)
        k = data["types"][typ]
        require(mass <= k["capacity_kg"] and volume <= k["capacity_m3"], "Capacity")
        close(r["takeoff_mass_kg"], mass, "takeoff_mass", errors)
        close(r["takeoff_volume_m3"], volume, "takeoff_volume", errors)
        route = ["O01"] + p["route"] + ["O01"]
        require(r["route"] == "-".join(route), "Plan route")
        require(len(set(p["route"])) == len(p["route"]), "Repeated stop")
        require(set(p["route"]) == {b["destination"] for b in boxes}, "Route destinations")
        if len(p["route"]) > 1:
            multipoint.append({"trip_id": tid, "route": route, "loads_kg": []})
        start = float(p["preparation_start_s"])
        require(math.isfinite(start) and start >= 0, "Start time")
        close(r["preparation_start_s"], start, "preparation_start", errors)
        clock = start + k["prep_s"] + len(boxes) * k["load_box_s"]
        close(r["takeoff_s"], clock, "takeoff", errors)
        legs = sorted((s for s in segments if s["trip_id"] == tid), key=lambda s: int(s["segment_id"]))
        require([int(s["segment_id"]) for s in legs] == list(range(1, len(route))), "Segment sequence")
        energy, flight, handover = 0., 0., 0.
        for s, a, b in zip(legs, route, route[1:]):
            require((s["origin"], s["destination"]) == (a, b), "Segment endpoints")
            require(all(s[key] == r[key] for key in ("drone_id", "battery_id", "type_id")), "Segment resources")
            na, nb = data["nodes"][a], data["nodes"][b]
            g = data["geometry"][a + "|" + b]
            distance = math.hypot(nb["x_m"] - na["x_m"], nb["y_m"] - na["y_m"])
            height = g["terrain_max_m"] + 50
            up, down = height - na["work_m"], height - nb["work_m"]
            require(min(up, down) >= 0, "Negative vertical stage")
            for field, value in (("distance_m", distance), ("ascent_m", up), ("descent_m", down),
                                 ("cruise_altitude_m", height), ("terrain_max_m", g["terrain_max_m"])):
                close(g[field], value, "geometry_" + field, errors)
                close(s[field], value, "segment_" + field, errors)
            close(s["remaining_cargo_kg"], mass, "remaining_cargo", errors)
            if len(p["route"]) > 1:
                multipoint[-1]["loads_kg"].append(mass)
            for phase, duration in (("ascent", up / k["ascent_mps"]),
                                    ("cruise", distance / k["cruise_mps"]),
                                    ("descent", down / k["descent_mps"])):
                close(s[phase + "_start_s"], clock, phase + "_start", errors)
                clock += duration
                flight += duration
                close(s[phase + "_end_s"], clock, phase + "_end", errors)
            arrival = clock
            unloaded = [box for box in boxes if box["destination"] == b]
            duration = k["handover_base_s"] + len(unloaded) * k["handover_box_s"] if unloaded else 0.
            clock += duration
            handover += duration
            close(s["handover_start_s"], arrival, "handover_start", errors)
            close(s["handover_end_s"], clock, "handover_end", errors)
            for box in unloaded:
                d = delivery_map[box["box_id"]]
                require(d["trip_id"] == tid and d["destination"] == b, "Delivery trip/stop")
                close(d["delivery_complete_s"], clock, "delivery_complete", errors)
                close(d["arrival_s"], arrival, "delivery_arrival", errors)
                lateness = max(0., clock - box["desired_due_s"])
                close(d["lateness_s"], lateness, "lateness", errors)
                late_count += lateness > 1e-8
                if box["hard_due_s"] is not None:
                    slack = box["hard_due_s"] - clock
                    require(slack >= -1e-8, "Hard deadline")
                    hard_slacks.append((slack, box["box_id"]))
                else:
                    soft_slacks.append((box["desired_due_s"] - clock, box["box_id"]))
                    soft_late += box["priority"] * lateness
            fraction = (mass / k["capacity_kg"]) ** 1.5
            effective_range = k["empty_range_m"] * (1 - fraction) + k["full_range_m"] * fraction
            horizontal = k["energy_kwh"] * distance / effective_range * cfg["horizontal_multiplier"]
            vertical = (k["empty_kg"] + mass) * cfg["gravity_mps2"] * up * cfg["climb_multiplier"] / (3600000 * k["ascent_efficiency"])
            close(s["total_energy_kwh"], horizontal + vertical, "segment_energy", errors)
            energy += horizontal + vertical
            mass -= sum(box["mass_kg"] for box in unloaded)
        close(mass, 0, "return_cargo", errors)
        close(r["return_s"], clock, "return_time", errors)
        close(r["flight_s"], flight, "flight_time", errors)
        close(r["handover_s"], handover, "handover_time", errors)
        close(r["total_energy_kwh"], energy, "trip_energy", errors)
        soc = 1 - energy / k["energy_kwh"]
        close(r["return_soc"], soc, "return_soc", errors)
        reserve = k["reserve"] if cfg["reserve_override"] is None else cfg["reserve_override"]
        require(soc >= reserve - 1e-10, "Reserve")
        reserve_margins.append(((soc - reserve) * k["energy_kwh"], tid))
        # Integrate remaining SOC at the two specified constant charge rates.
        recharge = k["full_charge_s"] * (max(0., .9 - soc) / (.9 / .65) + (1 - max(.9, soc)) / (.1 / .35))
        intervals["drone"][p["drone_id"]].append((start, clock + cfg["turnaround_s"], tid, p["drone_id"]))
        intervals["battery"][p["battery_id"]].append((start, clock + recharge, tid, p["drone_id"]))
        energies.append(energy)
        ends.append(clock)
        socs.append(soc)
        operations.append(clock - start + cfg["turnaround_s"])
    resource_checks = {}
    for kind, schedule in intervals.items():
        gaps, switches = [], 0
        exported = rows(root, kind + "_schedule")
        require(Counter(r["trip_id"] for r in exported) == Counter(tids), "Schedule coverage")
        by_tid = {r["trip_id"]: r for r in exported}
        for resource, events in schedule.items():
            events.sort()
            for event in events:
                r = by_tid[event[2]]
                require(r[kind + "_id"] == resource, "Schedule resource")
                close(r["occupancy_start_s"], event[0], kind + "_occupancy", errors)
                close(r["next_available_s"], event[1], kind + "_available", errors)
            for first, second in zip(events, events[1:]):
                gap = second[0] - first[1]
                require(gap >= -1e-8, kind + " conflict")
                gaps.append(gap)
                switches += first[3] != second[3]
        resource_checks[kind] = dict(resources=len(schedule), reuse_pairs=len(gaps),
                                    minimum_gap_s=min(gaps, default=None), cross_drone_reuses=switches)
    metrics = dict(scenario_status=cfg["status"], total_boxes=len(coverage), hard_deadline_boxes=len(hard_slacks),
                   total_trips=len(plan), multipoint_trips=len(multipoint), total_energy_kwh=sum(energies),
                   makespan_s=max(ends), weighted_soft_lateness_s=soft_late, late_boxes=late_count,
                   min_return_soc=min(socs), total_operation_s=sum(operations))
    summary = {r["metric"]: r["value"] for r in rows(root, "summary")}
    require(set(summary) == set(metrics), "Summary schema")
    for key, value in metrics.items():
        if isinstance(value, str):
            require(summary[key] == value, "Summary status")
        else:
            close(summary[key], value, "summary_" + key, errors)
    return dict(metrics=metrics, segments=len(segments), hard_minimum_slack=min(hard_slacks),
                soft_minimum_slack=min(soft_slacks), reserve_minimum_margin_kwh=min(reserve_margins),
                resources=resource_checks, multipoint_routes=multipoint, max_errors=errors)


def trajectories(root, trajectory_class):
    trajectory = trajectory_class(root)
    forward = Transformer.from_crs(4326, 32649, always_xy=True)
    boundary_count, midpoint_count, max_jump, max_mid_error = 0, 0, 0., 0.
    for tid, trip in trajectory.trips.items():
        boundaries = {float(trip[k]) for k in ("preparation_start_s", "takeoff_s", "return_s")}
        for s in (s for s in trajectory.segments if s["trip_id"] == tid):
            a, b = trajectory.nodes[s["origin"]], trajectory.nodes[s["destination"]]
            h = float(s["cruise_altitude_m"])
            expected = {
                "ascent": (a["x_m"], a["y_m"], (a["work_m"] + h) / 2),
                "cruise": ((a["x_m"] + b["x_m"]) / 2, (a["y_m"] + b["y_m"]) / 2, h),
                "descent": (b["x_m"], b["y_m"], (b["work_m"] + h) / 2),
                "handover": (b["x_m"], b["y_m"], b["work_m"]),
            }
            for phase in expected:
                t0, t1 = float(s[phase + "_start_s"]), float(s[phase + "_end_s"])
                boundaries.update((t0, t1))
                if t1 > t0:
                    point = trajectory.position(tid, (t0 + t1) / 2)
                    x, y = forward.transform(point["lon"], point["lat"])
                    error = math.dist((x, y, point["altitude_m"]), expected[phase])
                    require(error < 1e-5, "Trajectory midpoint")
                    require(point["flight_phase"] == phase, "Trajectory phase")
                    require(point["is_return"] == (s["destination"] == "O01"), "Return phase")
                    max_mid_error = max(max_mid_error, error)
                    midpoint_count += 1
        for t in boundaries:
            points = [trajectory.position(tid, t + offset) for offset in (-1e-6, 0, 1e-6)]
            xyz = [(*forward.transform(p["lon"], p["lat"]), p["altitude_m"]) for p in points]
            jump = max(math.dist(xyz[0], xyz[1]), math.dist(xyz[1], xyz[2]), math.dist(xyz[0], xyz[2]))
            require(jump < 1e-3, "Trajectory boundary discontinuity")
            max_jump = max(max_jump, jump)
            boundary_count += 1
    return dict(boundaries=boundary_count, midpoint_checks=midpoint_count,
                maximum_boundary_change_m=max_jump, maximum_midpoint_error_m=max_mid_error)


def interface_checks(root, scratch, model_class, validator):
    inputs, config = root / "q2_inputs.json", root / "q2_scenario.json"
    cfg = read_json(config)
    fixture = scratch / "config.json"
    modified = dict(cfg, reserve_override=.99)
    fixture.write_text(json.dumps(modified), encoding="utf-8")
    model = model_class(inputs, fixture)
    inherited, explicit = model.max_payload("A", "S001"), model.max_payload("A", "S001", .99)
    require(inherited == explicit and not inherited["reachable"], "Reserve override regression")
    require(model.max_payload("A", "S001", .2)["reachable"], "Explicit reserve precedence")
    rejected = []
    for key in ("horizontal_model", "climb_model", "delivery_event", "battery_occupancy_from", "charging", "objective"):
        modified = dict(cfg)
        modified[key] = "unsupported"
        fixture.write_text(json.dumps(modified), encoding="utf-8")
        try:
            model_class(inputs, fixture)
        except ValueError:
            rejected.append(key)
        else:
            raise AssertionError("Semantic configuration accepted: " + key)
    mutant = scratch / "mutation"
    shutil.copytree(root, mutant)
    with redirect_stdout(io.StringIO()):
        validator(root, save=False)
    original = rows(root, "summary")
    detected = []
    for target in original:
        altered = [dict(r) for r in original]
        for r in altered:
            if r["metric"] == target["metric"]:
                r["value"] = "WRONG_STATUS" if r["metric"] == "scenario_status" else str(float(r["value"]) + 1)
        with (mutant / "q2_summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["metric", "value"])
            writer.writeheader()
            writer.writerows(altered)
        try:
            with redirect_stdout(io.StringIO()):
                validator(mutant, save=False)
        except AssertionError:
            detected.append(target["metric"])
        else:
            raise AssertionError("Summary mutation accepted: " + target["metric"])
    return dict(reserve_override=inherited, semantics_rejected=rejected, summary_mutations_rejected=detected)


def scalar_inverse(a, b, t):
    """Independent scalar series, using GeographicLib's integer polynomials.

    Source: GeographicLib src/TransverseMercator.cpp, order-six b1coeff/betcoeff.
    These polynomial tables differ in representation from the audited module.
    Return xi', eta', relative longitude and conformal latitude, in radians.
    """
    f = 1 / mp.mpf("298.257223563")
    n = f / (2 - f)
    scale = mp.mpf("0.9996") * 6378137 * mp.polyval([1, 4, 64, 256], n * n) / (256 * (1 + n))
    polynomials = [
        ([384796, -382725, -6720, 932400, -1612800, 1209600], 2419200),
        ([-1118711, 1695744, -1174656, 258048, 80640], 3870720),
        ([22276, -16929, -15984, 12852], 362880),
        ([-830251, -158400, 197865], 7257600),
        ([-435388, 453717], 15966720),
        ([20648693], 638668800),
    ]
    beta = [n ** j * mp.polyval(coef, n) / denominator
            for j, (coef, denominator) in enumerate(polynomials, 1)]
    x = mp.mpf(a[0]) + (mp.mpf(b[0]) - mp.mpf(a[0])) * t
    y = mp.mpf(a[1]) + (mp.mpf(b[1]) - mp.mpf(a[1])) * t
    xi, eta = y / scale, (x - 500000) / scale
    xp = xi - sum(v * mp.sin(2 * j * xi) * mp.cosh(2 * j * eta) for j, v in enumerate(beta, 1))
    ep = eta - sum(v * mp.cos(2 * j * xi) * mp.sinh(2 * j * eta) for j, v in enumerate(beta, 1))
    return xp, ep, mp.atan2(mp.sinh(ep), mp.cos(xp)), mp.asin(mp.sin(xp) / mp.cosh(ep))


def terrain_checks(data, dem, step, terrain_class, sign_function):
    raw = loadmat(dem)
    z = raw["dem"]
    dx, rx, west, ry, dy, north = raw["transform"].ravel()
    require(rx == 0 and ry == 0, "Rotated DEM not supported by reference")
    nodata = float(raw["nodata"].item())
    inverse = Transformer.from_crs(32649, 4326, always_xy=True)
    terrain = terrain_class(dem)
    source_hashes = {r["sha256"] for r in data["source_manifest"] if r["file_name"].endswith(".mat")}
    require(digest(dem) in source_hashes, "DEM differs from input manifest")
    mp.mp.dps = 60
    derivative_points, samples, paths, max_peak_diff = 0, 0, 0, 0.
    min_interval_margin, max_lon_error = math.inf, 0.
    peak_differences = []
    derivative_disagreements = []
    for aid, bid in itertools.combinations(sorted(data["nodes"]), 2):
        na, nb = data["nodes"][aid], data["nodes"][bid]
        a, b = (na["x_m"], na["y_m"]), (nb["x_m"], nb["y_m"])
        captured = {}

        def capture(frame, event, arg):
            if frame.f_code is sign_function.__code__ and event == "return":
                captured.update(frame.f_locals)

        previous_profile = sys.getprofile()
        try:
            sys.setprofile(capture)
            signs = sign_function(a, b)
        finally:
            sys.setprofile(previous_profile)
        require(sign_function(b, a) == [-v for v in signs], "Reverse derivative signs")
        for name in ("longitude", "latitude"):
            interval = captured[name]
            min_interval_margin = min(min_interval_margin, abs(float(interval.a)), abs(float(interval.b)))
        # High-precision numerical differentiation, not reuse of derivative expressions.
        for t in (mp.mpf(0), mp.mpf(".25"), mp.mpf(".5"), mp.mpf(".75"), mp.mpf(1)):
            values = scalar_inverse(a, b, t)
            deriv = [mp.diff(lambda u, index=i: scalar_inverse(a, b, u)[index], t) for i in range(4)]
            for name, value in zip(("dxp", "dep"), deriv[:2]):
                interval = captured[name]
                require(float(interval.a) <= float(value) <= float(interval.b), "Series derivative enclosure: " + name)
            xp, ep = values[:2]
            # Undo positive denominators to compare the actual signed numerators.
            lon_num = deriv[2] * (mp.sinh(ep) ** 2 + mp.cos(xp) ** 2)
            lat_num = deriv[3] * mp.cosh(ep) ** 2 * mp.sqrt(mp.cosh(ep) ** 2 - mp.sin(xp) ** 2)
            for name, value, sign in zip(("longitude", "latitude"), (lon_num, lat_num), signs):
                interval = captured[name]
                require(float(interval.a) <= float(value) <= float(interval.b), "Geographic derivative enclosure: " + name)
                require(int(mp.sign(value)) == sign, "Scalar derivative sign")
            x, y = a[0] + float(t) * (b[0] - a[0]), a[1] + float(t) * (b[1] - a[1])
            lon, lat = inverse.transform(x, y)
            max_lon_error = max(max_lon_error, abs(lon - (111 + float(mp.degrees(values[2])))))
            h = mp.mpf(".001")
            tt = float(t)
            l0, p0 = inverse.transform(a[0] + (tt - float(h)) * (b[0] - a[0]),
                                       a[1] + (tt - float(h)) * (b[1] - a[1]))
            l1, p1 = inverse.transform(a[0] + (tt + float(h)) * (b[0] - a[0]),
                                       a[1] + (tt + float(h)) * (b[1] - a[1]))
            if [int(np.sign(l1 - l0)), int(np.sign(p1 - p0))] != signs:
                derivative_disagreements.append(aid + "|" + bid)
            derivative_points += 1
        distance = math.dist(a, b)
        count = int(math.ceil(distance / step)) + 1
        dense_peak = -math.inf
        for begin in range(0, count, 200000):
            t = np.arange(begin, min(count, begin + 200000), dtype=float) / (count - 1)
            lon, lat = inverse.transform(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            col, row = (lon - west) / dx, (lat - north) / dy
            cc, rr = np.floor(col).astype(int), np.floor(row).astype(int)
            require(np.all((cc >= 0) & (cc < z.shape[1]) & (rr >= 0) & (rr < z.shape[0])), "Dense coverage")
            elev = z[rr, cc]
            require(np.all(np.isfinite(elev)) and np.all(elev != nodata), "Dense nodata")
            dense_peak = max(dense_peak, float(np.max(elev)))
        peak, cell_count = terrain.maximum(a, b)
        g = data["geometry"][aid + "|" + bid]
        close(peak, g["terrain_max_m"], "Re-enumerated DEM maximum")
        require(cell_count == g["cell_count"], "Re-enumerated cell count")
        reverse = data["geometry"][bid + "|" + aid]
        close(peak, reverse["terrain_max_m"], "Reverse DEM maximum")
        difference = peak - dense_peak
        require(difference >= -1e-8, "Dense reference found terrain above production maximum")
        max_peak_diff = max(max_peak_diff, abs(difference))
        if difference != 0:
            peak_differences.append(dict(path=aid + "|" + bid, enumerated_m=peak, dense_m=dense_peak))
        paths += 1
        samples += count
    require(not derivative_disagreements, "PROJ derivative sign disagreement")
    return dict(paths=paths, step_m=step, sample_count=samples, maximum_peak_difference_m=max_peak_diff,
                differing_paths=peak_differences, derivative_points=derivative_points,
                reverse_sign_checks=paths, minimum_signed_numerator_interval_margin=min_interval_margin,
                maximum_scalar_vs_proj_longitude_error_deg=max_lon_error,
                dem_sha256=digest(dem),
                limitation="Dense samples are not a supercover proof. Sixth-order truncation derivative bounds are not supplied.")


def replay_improvement(root, model_class, solver, skip):
    run = read_json(root / "q2_run.json")
    history = rows(root, "improvement") if (root / "q2_improvement.csv").exists() else []
    previous = tuple(run["before_improvement_objective"])
    for r in history:
        current = (float(r["weighted_soft_lateness_s"]), float(r["makespan_s"]), float(r["energy_kwh"]), int(r["trips"]))
        require(current < previous, "Non-improving accepted step")
        previous = current
    require(len(history) == run["accepted_improvements"], "Improvement count")
    if skip:
        return dict(replayed=False, accepted_steps=len(history), history_lexicographically_decreases=True)
    model = model_class(root / "q2_inputs.json", root / "q2_scenario.json")
    stops = 1 if run["selected_method"] == "single_stop_baseline" else run["max_stops"]
    baseline = solver.construct(model, run["selected_seed"], stops)
    for actual, expected in zip(solver.objective(baseline), run["before_improvement_objective"]):
        close(actual, expected, "Replay baseline")
    improved, replay_history = solver.improve(model, baseline, run["improvement_iterations"], run["max_stops"])
    require(len(replay_history) == len(history), "Replay accepted count")
    for actual, expected in zip(replay_history, history):
        for key, value in actual.items():
            close(expected[key], value, "Replay history " + key)
    plan = read_json(root / "q2_plan.json")
    require(len(improved) == len(plan), "Replay trip count")
    for trip, p in zip(improved, plan):
        require(trip["box_ids"] == p["box_ids"] and trip["route"][1:-1] == p["route"], "Replay cargo/route")
        require(all(trip[key] == p[key] for key in ("drone_id", "battery_id")), "Replay resources")
        close(p["preparation_start_s"], trip["start_s"], "Replay start")
    return dict(replayed=True, iterations=run["improvement_iterations"], accepted_steps=len(history),
                exact_plan_reproduced=True, objective=list(solver.objective(improved)),
                limitation="Strict local descent, no global optimality or neighborhood exhaustion claim.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", type=Path)
    parser.add_argument("--step-m", type=float, default=.25)
    parser.add_argument("--skip-improve-replay", action="store_true")
    args = parser.parse_args()
    require(__debug__, "Do not run under Python -O")
    require(math.isfinite(args.step_m) and args.step_m > 0, "Positive DEM reference step required")
    dem = args.dem or REPO / "data/raw/q2_source/dem.mat"
    if not dem.exists():
        alternatives = sorted((REPO.parent / "\u0044\u9898").rglob("*DEM.mat"))
        require(len(alternatives) == 1, "Provide original DEM with --dem")
        dem = alternatives[0]
    tracked = [CODE / name for name in CODE_FILES]
    tracked += sorted(p for p in (REPO / "Q2/results").glob("q2_*") if p.suffix in (".csv", ".json"))
    before = {p.relative_to(REPO).as_posix(): digest(p) for p in tracked}
    with tempfile.TemporaryDirectory(prefix="q2-independent-") as temp:
        scratch = Path(temp)
        source, root = scratch / "code", scratch / "results"
        source.mkdir()
        root.mkdir()
        for path in tracked:
            shutil.copy2(path, (source if path.parent == CODE else root) / path.name)
        require(all(digest((source if p.parent == CODE else root) / p.name) == before[p.relative_to(REPO).as_posix()]
                    for p in tracked), "Source changed while snapshotting; rerun")
        sys.path.insert(0, str(source))
        from transport_core import Model, Trajectory
        from prepare_data import Terrain
        from utm_interval import monotonic_signs
        from validate import validate
        import solve

        data, run = read_json(root / "q2_inputs.json"), read_json(root / "q2_run.json")
        report = {"scope": "Independent review of frozen Q2 files; provisional scenario only"}
        report["snapshot_sha256"] = before
        report["run_code_hash_mismatches"] = [
            name for name in CODE_FILES if name.endswith(".py")
            and run.get("code_sha256", {}).get(name) != digest(source / name)]
        report["run_inputs_hash_matches"] = run["inputs_sha256"] == digest(root / "q2_inputs.json")
        report["schedule"] = independent_schedule(root)
        report["trajectory"] = trajectories(root, Trajectory)
        report["interfaces"] = interface_checks(root, scratch, Model, validate)
        report["terrain"] = terrain_checks(data, dem, args.step_m, Terrain, monotonic_signs)
        report["local_search"] = replay_improvement(root, Model, solve, args.skip_improve_replay)
        report["files_changed_during_audit"] = [
            p.relative_to(REPO).as_posix() for p in tracked
            if digest(p) != before[p.relative_to(REPO).as_posix()]]
        report["status"] = "PASS_UNDER_DECLARED_SCENARIO_WITH_DOCUMENTED_LIMITATIONS"
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
