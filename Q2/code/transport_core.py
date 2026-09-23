"""Single transport physics and event implementation for Q1/Q2/Q3 reuse."""
import csv
import json
import math
from pathlib import Path

from pyproj import Transformer
from scipy.optimize import brentq

DEFAULT_RESULTS = Path(__file__).resolve().parents[1] / "results"
DEFAULT_CONFIG = Path(__file__).with_name("scenario.json")


def write_csv(path, records):
    if not records:
        raise ValueError(f"Refusing empty table {path}")
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def charge_time(soc, full_s):
    if not 0 <= soc <= 1:
        raise ValueError("SOC outside [0,1]")
    return full_s * (.65 * (.9 - soc) / .9 + .35) if soc < .9 else full_s * .35 * (1 - soc) / .1


class Model:
    def __init__(self, inputs=None, config=None):
        self.data = json.loads(Path(inputs or DEFAULT_RESULTS / "q2_inputs.json").read_text(encoding="utf-8"))
        self.config = json.loads(Path(config or DEFAULT_CONFIG).read_text(encoding="utf-8"))
        supported = {
            "horizontal_model": "Euse*d/(L0-(L0-LF)*(cargo/Q)^1.5)",
            "climb_model": "(empty_mass_including_battery+cargo)*g*h/(eta*3.6e6)",
            "delivery_event": "handover_complete",
            "battery_occupancy_from": "preparation_start",
            "charging": "unlimited_parallel_same_type_full_before_reuse",
            "objective": ["hard_feasibility", "weighted_soft_lateness", "makespan_s", "energy_kwh", "trip_count"]}
        for key, value in supported.items():
            if self.config.get(key) != value:
                raise ValueError(f"Unsupported semantics: {key}")
        for key in ("horizontal_multiplier", "climb_multiplier", "gravity_mps2"):
            if not math.isfinite(self.config[key]) or self.config[key] <= 0:
                raise ValueError(f"Invalid scenario parameter {key}")
        if not math.isfinite(self.config["turnaround_s"]) or self.config["turnaround_s"] < 0:
            raise ValueError("Invalid turnaround")
        reserve = self.config["reserve_override"]
        if reserve is not None and not 0 <= reserve < 1:
            raise ValueError("Invalid reserve")
        for name in ("nodes", "types", "boxes", "drones", "batteries", "geometry"):
            setattr(self, name, self.data[name])

    def leg(self, origin, dest, typ, cargo):
        k = self.types[typ]
        if not 0 <= cargo <= k["capacity_kg"] + 1e-10:
            raise ValueError("Invalid cargo mass")
        g = self.geometry[origin + "|" + dest]
        eq_range = k["empty_range_m"] - (k["empty_range_m"] - k["full_range_m"]) * (cargo / k["capacity_kg"]) ** 1.5
        horizontal = k["energy_kwh"] * g["distance_m"] / eq_range * self.config["horizontal_multiplier"]
        climb = ((k["empty_kg"] + cargo) * self.config["gravity_mps2"] * g["ascent_m"]
                 / k["ascent_efficiency"] / 3.6e6 * self.config["climb_multiplier"])
        return dict(g, remaining_cargo_kg=cargo,
                    ascent_duration_s=g["ascent_m"] / k["ascent_mps"],
                    cruise_duration_s=g["distance_m"] / k["cruise_mps"],
                    descent_duration_s=g["descent_m"] / k["descent_mps"],
                    ascent_energy_kwh=climb, cruise_energy_kwh=horizontal,
                    descent_energy_kwh=0., handover_energy_kwh=0.,
                    total_energy_kwh=climb + horizontal)

    def trip(self, typ, box_ids, route, start=0.):
        if not math.isfinite(start) or start < 0:
            raise ValueError("Start time must be finite and nonnegative")
        if not box_ids or len(set(box_ids)) != len(box_ids):
            raise ValueError("Empty or repeated cargo")
        boxes = [self.boxes[b] for b in box_ids]
        k = self.types[typ]
        if len(set(route)) != len(route) or set(route) != {b["destination"] for b in boxes}:
            raise ValueError("Route must visit exactly the cargo destinations once")
        mass = sum(b["mass_kg"] for b in boxes)
        volume = sum(b["volume_m3"] for b in boxes)
        if mass > k["capacity_kg"] + 1e-10 or volume > k["capacity_m3"] + 1e-12:
            raise ValueError("Payload/volume violation")
        loading = k["load_box_s"] * len(boxes)
        departure = start + k["prep_s"] + loading
        t = departure
        segments, deliveries = [], []
        path = ["O01"] + route + ["O01"]
        remaining = mass
        for seq, (a, b) in enumerate(zip(path, path[1:]), 1):
            leg = self.leg(a, b, typ, remaining)
            s = dict(segment_id=seq, **leg, ascent_start_s=t)
            t += leg["ascent_duration_s"]
            s.update(ascent_end_s=t, cruise_start_s=t)
            t += leg["cruise_duration_s"]
            s.update(cruise_end_s=t, descent_start_s=t)
            t += leg["descent_duration_s"]
            s.update(descent_end_s=t, arrival_s=t, handover_start_s=t)
            at_stop = [box for box in boxes if box["destination"] == b]
            if at_stop:
                t += k["handover_base_s"] + k["handover_box_s"] * len(at_stop)
            s.update(handover_end_s=t, is_return=int(b == "O01"))
            for box in at_stop:
                hard = box["hard_due_s"]
                if hard is not None and t > hard + 1e-8:
                    raise ValueError(f"Hard deadline {box['box_id']}")
                deliveries.append(dict(box, arrival_s=s["arrival_s"],
                                       handover_start_s=s["handover_start_s"],
                                       delivery_complete_s=t,
                                       lateness_s=max(0, t - box["desired_due_s"])))
            remaining -= sum(box["mass_kg"] for box in at_stop)
            segments.append(s)
        energy = sum(s["total_energy_kwh"] for s in segments)
        reserve = self.config.get("reserve_override", None)
        reserve = k["reserve"] if reserve is None else reserve
        if energy > (1 - reserve) * k["energy_kwh"] + 1e-10:
            raise ValueError("Return reserve violation")
        return dict(type_id=typ, box_ids=list(box_ids), route=path, start_s=start,
                    departure_s=departure, return_s=t, total_energy_kwh=energy,
                    return_soc=1 - energy / k["energy_kwh"], mass_kg=mass,
                    volume_m3=volume, preparation_s=k["prep_s"], loading_s=loading,
                    turnaround_s=self.config["turnaround_s"],
                    segments=segments, deliveries=deliveries)

    def max_payload(self, typ, destination, reserve=None):
        k = self.types[typ]
        r = self.config["reserve_override"] if reserve is None else reserve
        r = k["reserve"] if r is None else r
        if not 0 <= r < 1:
            raise ValueError("Invalid reserve")
        def excess(mass):
            return (self.leg("O01", destination, typ, mass)["total_energy_kwh"]
                    + self.leg(destination, "O01", typ, 0)["total_energy_kwh"]
                    - (1-r)*k["energy_kwh"])
        if excess(0) > 0:
            return {"reachable": False, "max_payload_kg": None}
        maximum = k["capacity_kg"] if excess(k["capacity_kg"]) <= 0 else brentq(excess, 0, k["capacity_kg"])
        return {"reachable": True, "max_payload_kg": maximum}


class Trajectory:
    def __init__(self, results=DEFAULT_RESULTS):
        path = Path(results)
        with (path / "q2_trips.csv").open(encoding="utf-8-sig") as f:
            self.trips = {r["trip_id"]: r for r in csv.DictReader(f)}
        with (path / "q2_segments.csv").open(encoding="utf-8-sig") as f:
            self.segments = list(csv.DictReader(f))
        self.nodes = json.loads((path / "q2_inputs.json").read_text(encoding="utf-8"))["nodes"]
        self.inverse = Transformer.from_crs(32649, 4326, always_xy=True)

    def position(self, trip_id, t):
        if not math.isfinite(t):
            raise ValueError("Time must be finite")
        trip = self.trips[trip_id]
        origin = self.nodes["O01"]
        x, y, z = origin["x_m"], origin["y_m"], origin["work_m"]
        phase = "not_started" if t < float(trip["preparation_start_s"]) else "preparation"
        flight_phase, is_return = "", False
        if t >= float(trip["return_s"]):
            phase = "finished"
        elif t >= float(trip["takeoff_s"]):
            for s in self.segments:
                if s["trip_id"] != trip_id:
                    continue
                a, b = self.nodes[s["origin"]], self.nodes[s["destination"]]
                h = float(s["cruise_altitude_m"])
                for stage in ("ascent", "cruise", "descent", "handover"):
                    t0, t1 = float(s[stage + "_start_s"]), float(s[stage + "_end_s"])
                    if t0 <= t < t1:
                        f = (t-t0)/(t1-t0)
                        if stage == "ascent":
                            x, y, z = a["x_m"], a["y_m"], a["work_m"] + f*(h-a["work_m"])
                        elif stage == "cruise":
                            x, y, z = a["x_m"]+f*(b["x_m"]-a["x_m"]), a["y_m"]+f*(b["y_m"]-a["y_m"]), h
                        elif stage == "descent":
                            x, y, z = b["x_m"], b["y_m"], h+f*(b["work_m"]-h)
                        else:
                            x, y, z = b["x_m"], b["y_m"], b["work_m"]
                        is_return = s["is_return"] == "1"
                        flight_phase = stage
                        phase = "return" if is_return else stage
                        lon, lat = self.inverse.transform(x, y)
                        return dict(lon=lon, lat=lat, altitude_m=z, phase=phase,
                                    flight_phase=flight_phase, is_return=is_return)
            raise ValueError("Gap in trajectory")
        lon, lat = self.inverse.transform(x, y)
        return dict(lon=lon, lat=lat, altitude_m=z, phase=phase,
                    flight_phase=flight_phase, is_return=is_return)
