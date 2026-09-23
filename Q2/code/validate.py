"""Independent CSV validator: does not call Model.trip or Model.leg."""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

from transport_core import DEFAULT_RESULTS


def rows(root, name):
    with (Path(root) / f"q2_{name}.csv").open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def close(a, b):
    assert math.isfinite(float(a)) and math.isfinite(float(b))
    assert abs(float(a)-float(b)) <= 1e-8 + 1e-8*max(abs(float(a)), abs(float(b))), (a, b)


def validate(root, save=True):
    if not __debug__:
        raise RuntimeError("Run validation without Python -O")
    root = Path(root)
    data = json.loads((root / "q2_inputs.json").read_text(encoding="utf-8"))
    cfg = json.loads((root / "q2_scenario.json").read_text(encoding="utf-8"))
    trips, delivery, seg = (rows(root, n) for n in ("trips", "deliveries", "segments"))
    drones, batteries = rows(root, "drone_schedule"), rows(root, "battery_schedule")
    boxes, types = data["boxes"], data["types"]
    assert Counter(d["box_id"] for d in delivery) == Counter({b: 1 for b in boxes}), "coverage"
    tids = [t["trip_id"] for t in trips]
    assert len(set(tids)) == len(tids)
    for table in (delivery, seg):
        assert all(r["trip_id"] in tids for r in table), "unknown trip reference"
    for table in (drones, batteries):
        assert Counter(r["trip_id"] for r in table) == Counter(tids)
    total_e, late = 0., 0.
    for t in trips:
        tid, typ = t["trip_id"], t["type_id"]
        k = types[typ]
        assert data["drones"][t["drone_id"]] == typ
        assert data["batteries"][t["battery_id"]] == typ
        for table in (delivery, seg, drones, batteries):
            for r in [r for r in table if r["trip_id"] == tid]:
                assert all(r[key] == t[key] for key in ("drone_id", "battery_id", "type_id"))
        ids = json.loads(t["box_ids_json"])
        assert Counter(ids) == Counter(d["box_id"] for d in delivery if d["trip_id"] == tid)
        mass = sum(boxes[b]["mass_kg"] for b in ids)
        vol = sum(boxes[b]["volume_m3"] for b in ids)
        assert mass <= k["capacity_kg"] + 1e-10 and vol <= k["capacity_m3"] + 1e-12
        close(mass, t["takeoff_mass_kg"]); close(vol, t["takeoff_volume_m3"])
        close(k["prep_s"], t["preparation_s"])
        close(k["load_box_s"]*len(ids), t["loading_s"])
        start = float(t["preparation_start_s"])
        assert start >= 0
        clock = start + k["prep_s"] + k["load_box_s"] * len(ids)
        close(clock, t["takeoff_s"])
        route = t["route"].split("-")
        assert route[0] == route[-1] == "O01"
        assert len(set(route[1:-1])) == len(route)-2
        assert set(route[1:-1]) == {boxes[b]["destination"] for b in ids}
        legs = sorted((s for s in seg if s["trip_id"] == tid), key=lambda s: int(s["segment_id"]))
        assert [int(s["segment_id"]) for s in legs] == list(range(1, len(route)))
        energy, flight, handover = 0., 0., 0.
        for i, s in enumerate(legs):
            a, b = route[i:i+2]
            assert (s["origin"], s["destination"]) == (a, b)
            assert int(s["is_return"]) == (b == "O01")
            g = data["geometry"][a+"|"+b]
            for name in ("distance_m", "terrain_max_m", "cruise_altitude_m", "ascent_m", "descent_m"):
                close(s[name], g[name])
            for prefix, node in (("origin", data["nodes"][a]), ("destination", data["nodes"][b])):
                close(s[prefix+"_x_m"], node["x_m"])
                close(s[prefix+"_y_m"], node["y_m"])
                close(s[prefix+"_work_altitude_m"], node["work_m"])
            close(s["remaining_cargo_kg"], mass)
            times = [g["ascent_m"]/k["ascent_mps"], g["distance_m"]/k["cruise_mps"],
                     g["descent_m"]/k["descent_mps"]]
            for phase, dur in zip(("ascent", "cruise", "descent"), times):
                close(s[phase+"_start_s"], clock)
                clock += dur
                close(s[phase+"_end_s"], clock)
                close(s[phase+"_duration_s"], dur)
            flight += sum(times)
            close(s["arrival_s"], clock)
            close(s["handover_start_s"], clock)
            delivered = [boxes[ident] for ident in ids if boxes[ident]["destination"] == b]
            dur = k["handover_base_s"]+len(delivered)*k["handover_box_s"] if delivered else 0
            clock += dur
            handover += dur
            close(s["handover_end_s"], clock)
            for box in delivered:
                d = next(r for r in delivery if r["box_id"] == box["box_id"])
                assert d["destination"] == b
                close(d["mass_kg"], box["mass_kg"]); close(d["volume_m3"], box["volume_m3"])
                close(d["arrival_s"], clock-dur); close(d["handover_start_s"], clock-dur)
                close(d["delivery_complete_s"], clock)
                close(d["desired_due_s"], box["desired_due_s"])
                close(d["priority"], box["priority"])
                if box["hard_due_s"] is not None:
                    close(d["hard_due_s"], box["hard_due_s"])
                    assert clock <= box["hard_due_s"] + 1e-8, "deadline"
                else:
                    assert d["hard_due_s"] == ""
                    late += box["priority"]*max(0, clock-box["desired_due_s"])
                close(d["lateness_s"], max(0, clock-box["desired_due_s"]))
            r = k["empty_range_m"] - (k["empty_range_m"]-k["full_range_m"])*(mass/k["capacity_kg"])**1.5
            eh = k["energy_kwh"] * g["distance_m"] / r * cfg["horizontal_multiplier"]
            eu = (k["empty_kg"]+mass)*cfg["gravity_mps2"]*g["ascent_m"]/k["ascent_efficiency"]/3600000*cfg["climb_multiplier"]
            close(s["cruise_energy_kwh"], eh); close(s["ascent_energy_kwh"], eu)
            close(s["descent_energy_kwh"], 0); close(s["handover_energy_kwh"], 0)
            close(s["total_energy_kwh"], eh+eu)
            energy += eh+eu
            mass -= sum(box["mass_kg"] for box in delivered)
        close(mass, 0)
        close(t["flight_s"], flight); close(t["handover_s"], handover)
        close(t["turnaround_s"], cfg["turnaround_s"])
        close(t["return_s"], clock); close(t["total_energy_kwh"], energy)
        soc = 1-energy/k["energy_kwh"]
        reserve = cfg["reserve_override"] if cfg["reserve_override"] is not None else k["reserve"]
        assert soc >= reserve - 1e-10, "reserve"
        close(t["return_soc"], soc)
        dr = next(r for r in drones if r["trip_id"] == tid)
        close(dr["occupancy_start_s"], start); close(dr["return_s"], clock)
        close(dr["occupancy_end_s"], clock+cfg["turnaround_s"])
        close(dr["next_available_s"], clock+cfg["turnaround_s"])
        bt = next(r for r in batteries if r["trip_id"] == tid)
        recharge = k["full_charge_s"] * (
            .65*(.9-soc)/.9+.35 if soc < .9 else .35*(1-soc)/.1)
        close(bt["occupancy_start_s"], start); close(bt["use_end_s"], clock)
        close(bt["initial_soc"], 1); close(bt["task_end_soc"], soc)
        close(bt["charge_start_s"], clock); close(bt["charge_end_s"], clock+recharge)
        close(bt["next_available_s"], clock+recharge); close(bt["charged_soc"], 1)
        total_e += energy
    for table, key in ((drones, "drone_id"), (batteries, "battery_id")):
        for ident in {r[key] for r in table}:
            schedule = sorted((r for r in table if r[key] == ident), key=lambda r: float(r["occupancy_start_s"]))
            for a, b in zip(schedule, schedule[1:]):
                assert float(a["next_available_s"]) <= float(b["occupancy_start_s"])+1e-8, key+" conflict"
    summary = {r["metric"]: r["value"] for r in rows(root, "summary")}
    close(summary["total_trips"], len(trips))
    close(summary["total_boxes"], len(boxes))
    close(summary["total_energy_kwh"], total_e)
    close(summary["weighted_soft_lateness_s"], late)
    close(summary["makespan_s"], max(float(t["return_s"]) for t in trips))
    assert summary["scenario_status"] == cfg["status"]
    close(summary["hard_deadline_boxes"], sum(b["hard_due_s"] is not None for b in boxes.values()))
    close(summary["multipoint_trips"], sum(len(t["route"].split("-")) > 3 for t in trips))
    close(summary["late_boxes"], sum(float(d["lateness_s"]) > 1e-8 for d in delivery))
    close(summary["min_return_soc"], min(float(t["return_soc"]) for t in trips))
    close(summary["total_operation_s"], sum(float(t["return_s"])-float(t["preparation_start_s"])
                                           +float(t["turnaround_s"]) for t in trips))
    report = dict(status="PASS_UNDER_DECLARED_SCENARIO", boxes=len(boxes), trips=len(trips),
                  segments=len(seg), checks=["coverage", "payload", "volume", "hard_deadlines",
                  "drone_conflicts", "battery_conflicts", "charging", "return_reserve",
                  "decreasing_load", "stage_timestamps", "energy", "summary"],
                  note="Independent CSV arithmetic; not official-assumption approval or terrain certification.")
    if save:
        (root / "q2_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    validate(p.parse_args().results)
