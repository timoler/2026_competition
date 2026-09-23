"""Boundary, trajectory, geometry and corruption tests on real exported data."""
import contextlib
import csv
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from prepare_data import Terrain
from solve import recompute
from transport_core import Model, Trajectory, DEFAULT_RESULTS, charge_time, write_csv
from validate import validate, rows
from utm_interval import monotonic_signs


class Identity:
    def transform(self, x, y):
        return np.asarray(x), np.asarray(y)


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = Model()
        cls.trajectory = Trajectory()
        cls.trips = rows(DEFAULT_RESULTS, "trips")
        cls.plan = json.loads((DEFAULT_RESULTS / "q2_plan.json").read_text(encoding="utf-8"))

    def test_charge_boundaries(self):
        self.assertAlmostEqual(charge_time(0, 1800), 1800)
        self.assertAlmostEqual(charge_time(.9, 1800), 630)
        self.assertAlmostEqual(charge_time(1, 1800), 0)
        self.assertAlmostEqual(charge_time(.9-1e-12, 1800), charge_time(.9+1e-12, 1800), places=7)
        with self.assertRaises(ValueError):
            charge_time(-.1, 1800)

    def test_payload_limits_and_empty_return(self):
        for k in self.model.types:
            for node in self.model.nodes:
                if node == "O01":
                    continue
                result = self.model.max_payload(k, node)
                if result["reachable"]:
                    m = result["max_payload_kg"]
                    energy = sum(self.model.leg(a,b,k,q)["total_energy_kwh"] for a,b,q in
                                 [("O01",node,m),(node,"O01",0)])
                    limit = (1-self.model.types[k]["reserve"])*self.model.types[k]["energy_kwh"]
                    self.assertLessEqual(energy, limit+1e-9)
                    if m < self.model.types[k]["capacity_kg"]-1e-6:
                        self.assertAlmostEqual(energy, limit, places=8)

    def test_two_stop_load_decreases(self):
        model = self.model
        feasible = False
        for x, bx in model.boxes.items():
            for y, by in model.boxes.items():
                if bx["destination"] == by["destination"]:
                    continue
                try:
                    t = model.trip("C", [x,y], [bx["destination"],by["destination"]])
                except ValueError:
                    continue
                self.assertEqual([s["remaining_cargo_kg"] for s in t["segments"]],
                                 [bx["mass_kg"]+by["mass_kg"], by["mass_kg"], 0])
                feasible = True
                break
            if feasible:
                break
        self.assertTrue(feasible)

    def test_review_regressions(self):
        cfg = dict(self.model.config)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "scenario.json"
            cfg["reserve_override"] = .99
            p.write_text(json.dumps(cfg), encoding="utf-8")
            self.assertFalse(Model(config=p).max_payload("A", "S001")["reachable"])
            cfg["delivery_event"] = "arrival"
            p.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaises(ValueError):
                Model(config=p)
        for a, na in self.model.nodes.items():
            for b, nb in self.model.nodes.items():
                if a < b:
                    signs = monotonic_signs((na["x_m"],na["y_m"]), (nb["x_m"],nb["y_m"]))
                    self.assertEqual(signs, [1 if nb[k] > na[k] else -1 for k in ("lon","lat")])

    def test_geometry_closed_corner_and_edge(self):
        terrain = Terrain.__new__(Terrain)
        terrain.z = np.arange(25).reshape(5,5).astype(float)
        terrain.dx, terrain.dy = 1., 1.
        terrain.west, terrain.north, terrain.nodata = 0., 0., -32767
        terrain.inverse = Identity()
        # Diagonal touches side cells at every exact integer corner.
        z, count = terrain.maximum((.5,.5),(3.5,3.5))
        self.assertEqual(count, 10)
        self.assertEqual(z, 18)
        self.assertEqual((z,count), terrain.maximum((3.5,3.5),(.5,.5)))
        self.assertEqual(terrain.maximum((1.,.5),(1.,3.5))[1], 8)
        terrain.z[2,1] = terrain.nodata
        with self.assertRaises(ValueError):
            terrain.maximum((.5,.5),(3.5,3.5))
        with self.assertRaises(ValueError):
            terrain.maximum((-.1,.5),(3.5,3.5))

    def test_trajectory_all_boundaries(self):
        trajectory = self.trajectory
        for t in self.trips:
            tid = t["trip_id"]
            self.assertEqual(trajectory.position(tid, -1)["phase"], "not_started")
            self.assertEqual(trajectory.position(tid, float(t["return_s"]))["phase"], "finished")
            for s in [s for s in trajectory.segments if s["trip_id"] == tid]:
                for phase in ("ascent", "cruise", "descent", "handover"):
                    lo, hi = float(s[phase+"_start_s"]), float(s[phase+"_end_s"])
                    if hi <= lo:
                        continue
                    pos = trajectory.position(tid, (lo+hi)/2)
                    self.assertEqual(pos["flight_phase"], phase)
                    p, q = trajectory.position(tid, hi-1e-7), trajectory.position(tid, hi)
                    self.assertLess(abs(p["altitude_m"]-q["altitude_m"]), 1e-4)
                    self.assertLess(abs(p["lon"]-q["lon"]), 1e-7)
                    self.assertLess(abs(p["lat"]-q["lat"]), 1e-7)
        with self.assertRaises(ValueError):
            trajectory.position(self.trips[0]["trip_id"], float("nan"))

    def test_recompute_matches(self):
        trips = recompute(self.model, self.plan)
        for original, actual in zip(self.trips, trips):
            self.assertAlmostEqual(float(original["return_s"]), actual["return_s"])
            self.assertAlmostEqual(float(original["total_energy_kwh"]), actual["total_energy_kwh"])

    def test_recompute_rejects_bad_plan(self):
        for mode in ("duplicate", "negative", "nan", "wrong_battery", "late", "conflict"):
            plan = json.loads(json.dumps(self.plan))
            if mode == "duplicate":
                plan.append(plan[0])
            elif mode == "negative":
                plan[0]["preparation_start_s"] = -1
            elif mode == "nan":
                plan[0]["preparation_start_s"] = float("nan")
            elif mode == "wrong_battery":
                original_type = self.model.drones[plan[0]["drone_id"]]
                plan[0]["battery_id"] = next(b for b,k in self.model.batteries.items() if k != original_type)
            elif mode == "late":
                for trip in plan:
                    trip["preparation_start_s"] += 100000
            else:
                by_drone = {}
                for trip in plan:
                    if trip["drone_id"] in by_drone:
                        trip["preparation_start_s"] = by_drone[trip["drone_id"]]["preparation_start_s"]
                        break
                    by_drone[trip["drone_id"]] = trip
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                recompute(self.model, plan)

    def test_csv_corruptions_rejected(self):
        mutations = [
            ("deliveries", "box_id", "UNKNOWN"),
            ("deliveries", "delivery_complete_s", "100000"),
            ("trips", "takeoff_mass_kg", "10000"),
            ("trips", "takeoff_volume_m3", "100"),
            ("trips", "return_soc", "0.99"),
            ("segments", "cruise_start_s", "10000"),
            ("segments", "ascent_energy_kwh", "0"),
            ("drone_schedule", "occupancy_start_s", "-100"),
            ("battery_schedule", "next_available_s", "0")]
        for table, key, value in mutations:
            with self.subTest(table=table, key=key), tempfile.TemporaryDirectory() as tmp:
                dst = Path(tmp)
                for p in DEFAULT_RESULTS.glob("q2_*.csv"):
                    shutil.copy2(p, dst / p.name)
                for name in ("q2_inputs.json", "q2_scenario.json"):
                    shutil.copy2(DEFAULT_RESULTS / name, dst / name)
                records = rows(dst, table)
                records[0][key] = value
                write_csv(dst / f"q2_{table}.csv", records)
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    validate(dst, save=False)
        for metric in ("hard_deadline_boxes", "min_return_soc", "multipoint_trips"):
            with self.subTest(metric=metric), tempfile.TemporaryDirectory() as tmp:
                dst = Path(tmp)
                for p in DEFAULT_RESULTS.glob("q2_*.csv"):
                    shutil.copy2(p, dst / p.name)
                for name in ("q2_inputs.json", "q2_scenario.json"):
                    shutil.copy2(DEFAULT_RESULTS / name, dst / name)
                records = rows(dst, "summary")
                next(r for r in records if r["metric"] == metric)["value"] = "-100"
                write_csv(dst / "q2_summary.csv", records)
                with self.assertRaises(AssertionError):
                    validate(dst, save=False)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TransportTests)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = unittest.TextTestRunner(stream=buffer, verbosity=2).run(suite)
    text = buffer.getvalue()
    print(text)
    (DEFAULT_RESULTS / "q2_tests.txt").write_text(text, encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
