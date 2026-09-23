"""E4: local transport re-reschedule + 2-relay joint optimisation.

Shifts T011 (and reassigns T015) so T011's S004 low-altitude blind spot moves
to a 'quiet' time window, then checks whether two relays (R01 north; R02 south
then re-positioned to S004-west) can cover 100%.  Only e4_* outputs are written;
Q2/Q3 formal results are untouched.

The rearrangement tried here:
  U07: T001, T005, T011 (shifted later by D1), idle gap
  U08: T003, T007, T012, T015 (moved from U07, shift D2)
R02 is free after its last south trip (T021 returns 4751 s), so it can fly to
the S004-west position and serve T011's shifted blind spot.
"""
from __future__ import annotations
import csv, json, sys, math
from pathlib import Path
import numpy as np

CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE))
from strict_feasibility import Engine
from config import RESULTS

OUT = RESULTS


def read_csv(p):
    with Path(p).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    e = Engine(10)
    rp = e.rp
    g01 = rp.g01
    di = e.di
    meta = e.meta
    dp = e.dp
    dt = e.dt

    # relay positions (x, y, z)
    R01 = (315675.158634, 2550876.435495, 920.210144)      # north
    R02south = (322575.158634, 2546026.435495, 662.347198)  # south
    R02west = (314175.158634, 2553526.435495, 975.402405)   # S004-west (=R03 pos)

    # --- build shifted demand --------------------------------------------
    # shift T011 by D1, T015 by D2 (samples keep their position, time moves)
    D1 = 2320.0   # T011 -> descent at ~6495 s (so R02 can arrive after reposition, with margin)
    D2 = 1223.0   # T015 -> U08 after T012 (prep 6517)
    shift = {"T011": D1, "T015": D2}

    n = len(di)
    new_time = np.array([t for t in dt])
    new_trip = [meta[i][0] for i in di]
    for j in range(n):
        tid = meta[di[j]][0]
        if tid in shift:
            new_time[j] += shift[tid]

    pts = dp  # positions unchanged
    print(f"shifted demand samples: {n}")

    def los_ok(p, q):
        return bool(e.links(p, np.array([q]), e.b[3])[0])

    def backhaul_ok(p):
        return bool(e.links(p, np.array([g01]), e.b[4])[0])

    # --- relay sorties with service windows -----------------------------
    # R01 north: cover north + shifted T015.  Its last covered sample is
    # T015's shifted last sample.
    t015_shifted = [new_time[j] for j in range(n) if new_trip[j] == "T015"]
    r01_end = max(t015_shifted) + 1 if t015_shifted else 6611.5
    # R02 south: until T021 returns (4751 s) + margin
    r02_south_end = 4751.0
    # R02 west: T011's shifted blind spot window (low-altitude samples)
    t011_shifted = [(new_time[j], j) for j in range(n) if new_trip[j] == "T011"]
    t011_z = [float(pts[j, 2]) for _, j in t011_shifted]
    # the blind spot = T011 samples at low altitude (z < 250)
    t011_lo = [new_time[j] for j in range(n) if new_trip[j] == "T011" and pts[j, 2] < 250]
    west_a = min(t011_lo) if t011_lo else 6605
    west_b = max(t011_lo) + 1 if t011_lo else 7012

    print(f"R01 window: [816, {r01_end:.0f}]  R02south: [745, {r02_south_end:.0f}]  "
          f"R02west: [{west_a:.0f}, {west_b:.0f}]")

    # --- R02 repositioning timing (south -> O01 -> west) -----------------
    k = e.k
    f_r02south = rp.relay_sortie(R02south, 0)
    f_r02west = rp.relay_sortie(R02west, 0)
    r02_south_return = r02_south_end + f_r02south["flight_back_s"]
    r02_west_prep = r02_south_return + k["turnaround_s"]
    r02_west_service_start = r02_west_prep + k["prep_s"] + f_r02west["flight_out_s"] + k["link_build_s"]
    print(f"R02 south return={r02_south_return:.0f}s, west prep={r02_west_prep:.0f}s, "
          f"west service start={r02_west_service_start:.0f}s (must be <= {west_a:.0f}s)")

    # --- coverage ---------------------------------------------------------
    # R02 can only serve west after it repositions (arrival = r02_west_service_start).
    west_effective_start = max(west_a, r02_west_service_start)
    uncovered = 0
    uncovered_detail = []
    relay_serve = {"R01": 0, "R02south": 0, "R02west": 0}
    for j in range(n):
        t = new_time[j]
        q = pts[j]
        cov = False
        if 816 <= t < r01_end and los_ok(R01, q):
            cov = True; relay_serve["R01"] += 1
        elif 745 <= t < r02_south_end and los_ok(R02south, q):
            cov = True; relay_serve["R02south"] += 1
        elif west_effective_start <= t < west_b and los_ok(R02west, q):
            cov = True; relay_serve["R02west"] += 1
        if not cov:
            uncovered += 1
            if len(uncovered_detail) < 20:
                uncovered_detail.append((new_trip[j], round(t, 1), round(float(q[0])), round(float(q[1])), round(float(q[2]))))

    total = n
    cov_frac = 1 - uncovered / total
    print(f"uncovered = {uncovered} / {total}  coverage = {cov_frac*100:.6f}%")
    print(f"relay_serve = {relay_serve}")

    # --- energy checks ----------------------------------------------------
    k = e.k
    def sortie_energy(p, a, b):
        f = rp.relay_sortie(p, b - a)
        return f["energy_kwh"], f["flight_out_s"], f["flight_back_s"]

    e_r01, _, _ = sortie_energy(R01, 816, r01_end)
    e_r02s, _, _ = sortie_energy(R02south, 745, r02_south_end)
    e_r02w, _, _ = sortie_energy(R02west, west_effective_start, west_b)

    result = dict(
        uncovered_samples=uncovered, total_samples=total, coverage=cov_frac,
        shifts={"T011": D1, "T015": D2},
        relay_windows=dict(R01_north=[816, round(r01_end, 1)],
                           R02_south=[745, r02_south_end],
                           R02_west=[round(west_effective_start, 1), round(west_b, 1)]),
        relay_energy_kwh=dict(R01_north=round(e_r01, 6),
                              R02_south=round(e_r02s, 6),
                              R02_west=round(e_r02w, 6)),
        relay_serve_counts=relay_serve,
        r02_west_service_start=round(r02_west_service_start, 1),
        r02_west_arrives_in_time=bool(r02_west_service_start <= west_a),
        uncovered_detail=uncovered_detail,
        backhaul=dict(R01=backhaul_ok(R01), R02south=backhaul_ok(R02south),
                      R02west=backhaul_ok(R02west)),
    )
    dump("e4_best.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
