"""Relay drone scheduling for Q3.

Pipeline:
  1. demand reconstruction (blackout samples on a time grid);
  2. candidate hover positions (DEM grid, backhaul-visible to G01);
  3. coverage matrix (candidate x demand) via batched LOS, cached to .npz;
  4. static set cover (greedy + optional pair search) -> hover positions;
  5. two-relay temporal schedule (each relay = sequence of O01->hover->O01 sorties);
  6. fine-grid verification of the final schedule.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from config import Q2_RESULTS, RESULTS, load_scenario, TERRAIN_CACHE, resolve_dem_path
from terrain import Terrain, node_bbox_utm
from communication import LinkBudget, Connectivity
from trajectory import TransportTrajectory

COV_CACHE = RESULTS / "q3_coverage_cache.npz"


def write_csv(path, records):
    if not records:
        raise ValueError(f"Refusing empty table {path}")
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)


class RelayProblem:
    def __init__(self, scenario=None):
        self.sc = scenario or load_scenario()
        self.terr = Terrain.load_npz(TERRAIN_CACHE)
        self.lb = LinkBudget(self.sc["official_communication"], self.sc["official_relay"])
        self.tj = TransportTrajectory(Q2_RESULTS)
        o01 = self.tj.nodes()["O01"]
        self.g01 = (o01["x_m"], o01["y_m"],
                    o01["ground_m"] + self.sc["official_communication"]["g01"]["antenna_height_m"])
        self.conn = Connectivity(self.terr, self.lb, self.g01,
                                 self.sc["model"]["los_clearance_m"],
                                 self.sc["model"]["cruise_sample_spacing_m"])
        self.agl = self.sc["model"]["relay_agl_m"]

    # ---- Phase 1: demand -------------------------------------------------
    def demand(self, step_s=None) -> tuple[np.ndarray, list]:
        step_s = step_s or self.sc["model"]["time_step_s"]
        rows = []
        for trip_id, trip in self.tj.trips().items():
            t0, t1 = float(trip["takeoff_s"]), float(trip["return_s"])
            t = t0
            while t < t1:
                s = self.tj.position(trip_id, t)
                if s["phase"] != "finished":
                    p = (s["x"], s["y"], s["altitude_m"])
                    if not self.conn.direct_ok(p):
                        rows.append((t, trip_id, trip["drone_id"], p[0], p[1], p[2]))
                t += step_s
        t_arr = np.array([r[0] for r in rows])
        pos_arr = np.array([r[3:] for r in rows])
        meta = [dict(time_s=r[0], trip_id=r[1], drone_id=r[2]) for r in rows]
        return t_arr, pos_arr, meta

    # ---- Phase 2: candidates --------------------------------------------
    def candidates(self, spacing_m=None) -> list[tuple]:
        spacing = spacing_m or self.sc["model"]["candidate_grid_spacing_m"]
        xmin, xmax, ymin, ymax = node_bbox_utm(self.tj.nodes())
        m = self.sc["model"]["terrain_margin_m"]
        xmin -= m; xmax += m; ymin -= m; ymax += m
        xs = np.arange(xmin, xmax, spacing)
        ys = np.arange(ymin, ymax, spacing)
        cands = []
        for x in xs:
            for y in ys:
                try:
                    z = self.terr.hover_altitude(float(x), float(y), self.agl)
                except ValueError:
                    continue
                p = (float(x), float(y), z)
                if self.conn.backhaul_ok(p):
                    cands.append(p)
        return cands

    # ---- Phase 3: coverage ----------------------------------------------
    def coverage(self, cands, pos_arr, use_cache=True) -> np.ndarray:
        if use_cache and COV_CACHE.exists():
            d = np.load(COV_CACHE)
            return d["cov"]
        nC, nD = len(cands), len(pos_arr)
        cov = np.zeros((nC, nD), dtype=bool)
        t0 = time.time()
        for i, p in enumerate(cands):
            occ = self.terr.los_occluded_batch(p, pos_arr, 15.0, self.sc["model"]["los_clearance_m"])
            dx = pos_arr[:, 0] - p[0]; dy = pos_arr[:, 1] - p[1]; dz = pos_arr[:, 2] - p[2]
            dkm = np.sqrt(dx * dx + dy * dy + dz * dz) / 1000.0
            cov[i] = self.lb.available_arr(self.lb.th_access, dkm, occ)
        if use_cache:
            np.savez_compressed(COV_CACHE, cov=cov)
        print(f"[relay] coverage {nC}x{nD} in {time.time()-t0:.1f}s (cached={use_cache})")
        return cov

    # ---- Phase 4: set cover ---------------------------------------------
    @staticmethod
    def greedy_set_cover(cov: np.ndarray) -> list[int]:
        nD = cov.shape[1]
        uncovered = np.ones(nD, dtype=bool)
        chosen = []
        while uncovered.any() and len(chosen) < cov.shape[0]:
            rem = np.where(uncovered)[0]
            counts = cov[:, rem].sum(axis=1)
            best = int(np.argmax(counts))
            if counts[best] == 0:
                break
            chosen.append(best)
            uncovered &= ~cov[best]
        return chosen

    @staticmethod
    def best_pair(cov: np.ndarray) -> tuple[int, int, int]:
        """Best pair (i,j) maximizing union coverage (exact over all pairs)."""
        nC, nD = cov.shape
        words = (nD + 63) // 64
        packed = np.zeros((nC, words), dtype=np.uint64)
        idx = np.arange(nD)
        for i in range(nC):
            bits = idx[cov[i]]
            for w in range(words):
                sel = bits[(bits // 64) == w]
                if sel.size:
                    packed[i, w] = np.bitwise_or.reduce(np.uint64(1) << (sel % 64))
        _PC = [bin(i).count("1") for i in range(65536)]
        def pc64(x):
            return _PC[x & 0xFFFF] + _PC[(x >> 16) & 0xFFFF] + _PC[(x >> 32) & 0xFFFF] + _PC[(x >> 48) & 0xFFFF]

        best = (0, -1, -1)
        for i in range(nC):
            pi = packed[i]
            for j in range(i + 1, nC):
                cnt = 0
                u = np.bitwise_or(pi, packed[j])
                for v in u.tolist():
                    cnt += pc64(v)
                if cnt > best[0]:
                    best = (cnt, i, j)
        return best

    # ---- relay flight/energy model --------------------------------------
    def relay_sortie(self, p, service_s: float) -> dict:
        """Times/energy for O01 -> hover p -> serve service_s -> O01."""
        k = self.sc["official_relay"]
        o01 = self.tj.nodes()["O01"]
        # horizontal distance O01->p
        dh = float(np.hypot(p[0] - o01["x_m"], p[1] - o01["y_m"]))
        # terrain max along O01->p (needed for cruise altitude): use a fine LOS-free pass
        terr_max = self._terrain_max_along(o01["x_m"], o01["y_m"], p[0], p[1])
        flight_alt = max(terr_max + 50.0, p[2])
        climb = max(0.0, flight_alt - o01["work_m"])
        descent = max(0.0, flight_alt - p[2])
        climb_t = climb / k["ascent_mps"]
        cruise_t = dh / k["cruise_mps"]
        descent_t = descent / k["descent_mps"]
        flight_out = climb_t + cruise_t + descent_t
        g = self.sc["model"]["gravity_mps2"]
        climb_e = k["takeoff_mass_kg"] * g * climb / k["ascent_efficiency"] / 3.6e6
        cruise_e = k["cruise_power_kw"] * cruise_t / 3600.0
        # round trip flight (out+back): back has no climb beyond same altitude
        flight_back = flight_out  # symmetric
        flight_energy = 2 * (climb_e + cruise_e)
        hover_e = k["hover_power_kw"] * service_s / 3600.0
        comm_e = k["comm_power_kw"] * service_s / 3600.0
        energy = flight_energy + hover_e + comm_e
        return dict(hover=p, dh_m=round(dh, 1), terr_max_m=round(terr_max, 1),
                    flight_alt_m=round(flight_alt, 1), climb_m=round(climb, 1),
                    descent_m=round(descent, 1), flight_out_s=round(flight_out, 1),
                    flight_back_s=round(flight_back, 1), energy_kwh=round(energy, 6),
                    flight_energy_kwh=round(flight_energy, 6),
                    service_energy_kwh=round(hover_e + comm_e, 6))

    def _terrain_max_along(self, x1, y1, x2, y2) -> float:
        n = max(2, int(np.hypot(x2 - x1, y2 - y1) / 15.0) + 1)
        t = np.linspace(0, 1, n)
        return float(self.terr.elevations(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t).max())


def run_relay(scenario=None) -> dict:
    rp = RelayProblem(scenario)
    step = rp.sc["model"]["time_step_s"]
    t_arr, pos_arr, meta = rp.demand(step)
    print(f"[relay] demand={len(pos_arr)} step={step}s")
    cands = rp.candidates()
    print(f"[relay] candidates={len(cands)}")
    cov = rp.coverage(cands, pos_arr)
    chosen = rp.greedy_set_cover(cov)
    print(f"[relay] greedy set cover -> {len(chosen)} positions, "
          f"uncovered={int((~np.logical_or.reduce(cov[chosen], axis=0)).sum() if chosen else len(pos_arr))}")
    positions = [cands[i] for i in chosen]
    pair = rp.best_pair(cov)
    print(f"[relay] best pair covers {pair[0]}/{len(pos_arr)} (idx {pair[1]},{pair[2]})")
    return dict(t_arr=t_arr, pos_arr=pos_arr, meta=meta, cands=cands, cov=cov,
                chosen=chosen, positions=positions, best_pair=pair)


if __name__ == "__main__":
    out = run_relay()
    for k, p in enumerate(out["positions"]):
        print(f"  pos{k+1}: x={p[0]:.0f} y={p[1]:.0f} z={p[2]:.0f}")
