"""Canonical (independent) 10 m LOS sampler + link budget for Q3 connectivity checks.

Shared by validate.py (independent re-check), baseline.py and summary.py so that
every headline metric uses one single statistical convention:
  1 s sample counting on [takeoff_s, return_s], 10 m LOS sampling.

Kept in its own module because Q2/code also contains a validate.py and importing
Q3's validate by bare name is ambiguous once trajectory.py puts Q2/code on path.
"""
from __future__ import annotations

import math

import numpy as np


def independent_los_occluded(terr, x1, y1, z1, x2, y2, z2, clearance=0.0):
    """True if terrain blocks the 3D sight line (10 m sampling, strict inequality)."""
    d = float(np.hypot(x2 - x1, y2 - y1))
    n = max(4, int(np.ceil(d / 10.0)) + 1)
    t = np.linspace(0.0, 1.0, n)
    xs = x1 + (x2 - x1) * t
    ys = y1 + (y2 - y1) * t
    zs = z1 + (z2 - z1) * t
    terr_e = terr.elevations(xs[1:-1], ys[1:-1])
    return bool(np.any(terr_e >= zs[1:-1] - clearance))


def independent_link_budget(sc):
    comm = sc["official_communication"]
    f = comm["carrier_frequency_mhz"]
    fsp = 20 * np.log10(f) + 32.44
    thr = comm["receiver_sensitivity_dbm"] + comm["fading_margin_db"]

    def lmax(tx, rx):
        return (tx["tx_power_dbm"] + tx["antenna_gain_dbi"] + rx["antenna_gain_dbi"]
                - comm["system_loss_db"] - thr)

    th_direct = min(lmax(comm["transport"], comm["g01"]), lmax(comm["g01"], comm["transport"]))
    th_access = min(lmax(comm["transport"], comm["relay_access"]),
                    lmax(comm["relay_access"], comm["transport"]))
    th_backhaul = min(lmax(comm["relay_backhaul"], comm["g01"]),
                      lmax(comm["g01"], comm["relay_backhaul"]))
    return fsp, comm["terrain_occlusion_loss_db"], th_direct, th_access, th_backhaul


def link_ok(fsp, lobs, th, d_km, occluded):
    return 20 * np.log10(max(d_km, 1e-9)) + fsp + (lobs if occluded else 0.0) <= th


def _dist3(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])
