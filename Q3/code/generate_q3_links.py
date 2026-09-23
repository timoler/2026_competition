"""Regenerate q3_communication_links.csv for the final two-relay schedule."""
from __future__ import annotations
import sys, math, csv
from collections import defaultdict
import numpy as np

CODE = Path = __import__("pathlib").Path
sys.path.insert(0, str(CODE(__file__).resolve().parent))
from relay import RelayProblem
from check_core import independent_link_budget, independent_los_occluded
from config import RESULTS

rp = RelayProblem()
k = rp.sc["official_relay"]
terr = rp.terr
g01 = rp.g01
fsp, lobs, th_direct, th_access, th_backhaul = independent_link_budget(rp.sc)

R01 = (315675.158634, 2550876.435495, 920.210144)
R02s = (322575.158634, 2546026.435495, 662.347198)
R02w = (314175.158634, 2553526.435495, 975.402405)
SHIFT = {"T011": 2320.0, "T015": 1224.0}
r01_a, r01_b = 816.0, 7834.5
r02s_a, r02s_b = 745.0, 4751.0
w_a, w_b = 6478.3, 6902.0


def link(p, q, th):
    d = math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2]) / 1000.0
    fs = 20 * math.log10(max(d, 1e-9)) + fsp
    if fs + lobs <= th:
        return True
    if fs > th:
        return False
    return not independent_los_occluded(terr, p[0], p[1], p[2], q[0], q[1], q[2], spacing_m=10.0)


tj = rp.tj
rows = []
rt = defaultdict(set)
outage = 0
for tid, tr in tj.trips().items():
    s = SHIFT.get(tid, 0.0)
    drone = tr["drone_id"] if tid != "T015" else "U08"
    t = float(tr["takeoff_s"]) + s
    while t < float(tr["return_s"]) + s:
        st = tj.position(tid, t - s)
        if st["phase"] != "finished":
            q = (st["x"], st["y"], st["altitude_m"])
            mode, rid = "outage", ""
            if link(g01, q, th_direct):
                mode = "direct"
            elif r01_a <= t < r01_b and link(R01, q, th_access):
                mode, rid = "relay", "R01"
            elif r02s_a <= t < r02s_b and link(R02s, q, th_access):
                mode, rid = "relay", "R02"
            elif w_a <= t < w_b and link(R02w, q, th_access):
                mode, rid = "relay", "R02"
            if mode == "outage":
                outage += 1
            rows.append(dict(time_s=t, trip_id=tid, drone_id=drone, mode=mode, relay_id=rid))
            if rid:
                rt[rid].add(tid)
        t += 1.0

with open(RESULTS / "q3_communication_links.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["time_s", "trip_id", "drone_id", "mode", "relay_id"],
                       lineterminator="\n")
    w.writeheader(); w.writerows(rows)

print("links rows:", len(rows))
print("outage samples:", outage)
print("R01 serves", len(rt["R01"]), "trips:", sorted(rt["R01"]))
print("R02 serves", len(rt["R02"]), "trips:", sorted(rt["R02"]))
