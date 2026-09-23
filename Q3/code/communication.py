"""Communication link budget and connectivity model for Q3 (Appendix 3).

Implements exactly the rules of 附录3:
  - effective receive threshold  Pr_th = Psens + M
  - directional max path loss     L_max(i->j) = Pt_i + Gt_i + Gr_j - Lsys - Pr_th
  - bidirectional threshold       L(i,j) = min(L_max(i->j), L_max(j->i))
  - free-space path loss          FSPL = 20log10(d_km) + 20log10(f_MHz) + 32.44
  - total path loss               L = FSPL + Lobs * occlusion
  - link available iff            L <= L(i,j)
  - transport drone connected iff direct(G01) OR (access(relay) AND backhaul(relay))
"""
from __future__ import annotations

import math

import numpy as np


class LinkBudget:
    def __init__(self, comm: dict, relay: dict):
        f = comm["carrier_frequency_mhz"]
        self.fsp = 20 * math.log10(f) + 32.44  # add 20log10(d_km) per link
        self.lsys = comm["system_loss_db"]
        self.lobs = comm["terrain_occlusion_loss_db"]
        self.psens = comm["receiver_sensitivity_dbm"]
        self.margin = comm["fading_margin_db"]
        self.g01 = comm["g01"]
        self.transport = comm["transport"]
        self.raccess = comm["relay_access"]
        self.rbackhaul = comm["relay_backhaul"]
        self.thr = self.psens + self.margin  # effective receive threshold (dBm)

        # Bidirectional thresholds (dB)
        self.th_direct = self._bidir(self.transport, self.g01)
        self.th_access = self._bidir(self.transport, self.raccess)
        self.th_backhaul = self._bidir(self.rbackhaul, self.g01)

    def _dmax(self, tx, rx) -> float:
        return tx["tx_power_dbm"] + tx["antenna_gain_dbi"] + rx["antenna_gain_dbi"] - self.lsys - self.thr

    def _bidir(self, a, b) -> float:
        return min(self._dmax(a, b), self._dmax(b, a))

    def freespace_db(self, d_km: float) -> float:
        return 20 * math.log10(max(d_km, 1e-9)) + self.fsp

    def loss_db(self, d_km: float, occluded: bool) -> float:
        return self.freespace_db(d_km) + (self.lobs if occluded else 0.0)

    def available(self, threshold_db: float, d_km: float, occluded: bool) -> bool:
        return self.loss_db(d_km, occluded) <= threshold_db

    def loss_db_arr(self, d_km, occluded) -> np.ndarray:
        d_km = np.asarray(d_km, dtype=np.float64)
        occluded = np.asarray(occluded, dtype=bool)
        return 20 * np.log10(np.maximum(d_km, 1e-9)) + self.fsp + np.where(occluded, self.lobs, 0.0)

    def available_arr(self, threshold_db: float, d_km, occluded) -> np.ndarray:
        return self.loss_db_arr(d_km, occluded) <= threshold_db

    def thresholds(self) -> dict:
        return {"direct": self.th_direct, "access": self.th_access, "backhaul": self.th_backhaul}


def _dist_km(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]) / 1000.0


class Connectivity:
    """Resolves connectivity of a transport drone at a 3D point, given a relay point."""

    def __init__(self, terrain, budget: LinkBudget, g01_xyz, los_clearance_m=0.0, spacing_m=15.0):
        self.terrain = terrain
        self.budget = budget
        self.g01 = g01_xyz
        self.clearance = los_clearance_m
        self.spacing = spacing_m

    def _occluded(self, p, q) -> bool:
        """Terrain occlusion of the 3D sight line between two endpoints."""
        return self.terrain.los_occluded(p[0], p[1], p[2], q[0], q[1], q[2],
                                         self.spacing, self.clearance)

    def direct_ok(self, p) -> bool:
        occluded = self._occluded(p, self.g01)
        return self.budget.available(self.budget.th_direct, _dist_km(p, self.g01), occluded)

    def direct_detail(self, p) -> dict:
        occluded = self._occluded(p, self.g01)
        d = _dist_km(p, self.g01)
        ok = self.budget.available(self.budget.th_direct, d, occluded)
        loss = self.budget.loss_db(d, occluded)
        return dict(occluded=occluded, d_km=d, loss_db=loss, ok=ok,
                    threshold_db=self.budget.th_direct)

    def access_ok(self, p, relay) -> bool:
        occluded = self._occluded(p, relay)
        return self.budget.available(self.budget.th_access, _dist_km(p, relay), occluded)

    def backhaul_ok(self, relay) -> bool:
        occluded = self._occluded(relay, self.g01)
        return self.budget.available(self.budget.th_backhaul, _dist_km(relay, self.g01), occluded)

    def connected(self, p, relay=None) -> tuple[bool, str]:
        """(connected, mode) where mode in {direct, relay, outage}."""
        if self.direct_ok(p):
            return True, "direct"
        if relay is not None:
            if self.access_ok(p, relay) and self.backhaul_ok(relay):
                return True, "relay"
        return False, "outage"

    def g01_position(self):
        return self.g01
