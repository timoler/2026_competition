"""Generate Q3 paper figures (PNG) from the results CSVs."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config import RESULTS, Q2_RESULTS, FIGURES, load_scenario, TERRAIN_CACHE
from terrain import Terrain, node_bbox_utm
from trajectory import TransportTrajectory

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fig_spatial():
    tj = TransportTrajectory(Q2_RESULTS)
    nodes = tj.nodes()
    terr = Terrain.load_npz(TERRAIN_CACHE)
    sc = load_scenario()

    fig, ax = plt.subplots(figsize=(9, 7))
    # terrain background (cropped DEM, downsampled for display)
    z = terr.z
    step = max(1, z.shape[0] // 600)
    zz = z[::step, ::step]
    west, north, dx, dy = terr.west, terr.north, terr.dx * step, terr.dy * step
    lon0, lon1 = west, west + zz.shape[1] * dx
    lat0, lat1 = north, north + zz.shape[0] * dy
    inv = terr.inverse
    lon_c = np.array([lon0, lon1, lon0, lon1])
    lat_c = np.array([lat0, lat0, lat1, lat1])
    xx, yy = inv.transform(lon_c, lat_c)
    im = ax.imshow(zz, cmap="terrain", origin="upper",
                   extent=[xx.min(), xx.max(), yy.min(), yy.max()], alpha=0.55, zorder=0)
    cbar = fig.colorbar(im, ax=ax, shrink=0.7)
    cbar.set_label("地形高程 (m)")

    # trajectories (sample timeline)
    rows = read_csv(RESULTS / "q3_transport_timeline.csv")
    paths = {}
    for r in rows:
        paths.setdefault(r["trip_id"], []).append((float(r["x"]), float(r["y"])))
    for tid, pts in paths.items():
        pts = np.array(pts)
        ax.plot(pts[:, 0], pts[:, 1], lw=0.6, color="0.4", alpha=0.35, zorder=1)

    # nodes
    for nid, n in nodes.items():
        c = "red" if nid == "O01" else "blue"
        mk = "*" if nid == "O01" else "o"
        ax.plot(n["x_m"], n["y_m"], mk, color=c, ms=8 if nid == "O01" else 4, zorder=3)
        if nid == "O01":
            ax.annotate("O01(G01)", (n["x_m"], n["y_m"]), textcoords="offset points",
                        xytext=(6, 6), fontsize=9, color="red")

    # relay hover positions
    if (RESULTS / "q3_relay_schedule.csv").exists():
        sched = read_csv(RESULTS / "q3_relay_schedule.csv")
        seen = {}
        for s in sched:
            key = (s["relay_id"], s["hover_x_m"], s["hover_y_m"])
            if key not in seen:
                seen[key] = True
                ax.plot(float(s["hover_x_m"]), float(s["hover_y_m"]), "^", color="green",
                        ms=11, zorder=4)
                ax.annotate(s["relay_id"], (float(s["hover_x_m"]), float(s["hover_y_m"])),
                            textcoords="offset points", xytext=(6, -6), fontsize=10, color="green")
    ax.set_xlabel("UTM 东向 x (m)")
    ax.set_ylabel("UTM 北向 y (m)")
    ax.set_title("运输无人机轨迹与中继悬停位置（空间分布）")
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "q3_spatial_map.png", dpi=150)
    plt.close(fig)


def _utm(inv, lo, la):
    x, y = inv.transform(np.array([lo]), np.array([la]))
    return float(x[0]), float(y[0])


def fig_blackout_timeline():
    rows = read_csv(RESULTS / "q3_blackout_intervals.csv")
    if not rows:
        return
    trips = sorted(set(r["trip_id"] for r in rows))
    ypos = {t: i for i, t in enumerate(trips)}
    fig, ax = plt.subplots(figsize=(11, 6))
    for r in rows:
        s, e = float(r["start_s"]), float(r["end_s"])
        y = ypos[r["trip_id"]]
        ax.barh(y, e - s, left=s, height=0.7, color="crimson", alpha=0.8)
    ax.set_yticks(list(ypos.values()))
    ax.set_yticklabels(list(ypos.keys()), fontsize=8)
    ax.set_xlabel("时间 (s)")
    ax.set_ylabel("架次")
    ax.set_title("无中继时各架次通信盲区（baseline）")
    ax.set_xlim(0, max(float(r["end_s"]) for r in rows) + 200)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "q3_blackout_timeline.png", dpi=150)
    plt.close(fig)


def fig_relay_gantt():
    if not (RESULTS / "q3_relay_schedule.csv").exists():
        return
    rows = read_csv(RESULTS / "q3_relay_schedule.csv")
    fig, ax = plt.subplots(figsize=(11, 3.5))
    relays = ["R01", "R02"]
    ypos = {r: i for i, r in enumerate(relays)}
    colors = {"R01": "tab:green", "R02": "tab:orange"}
    for r in rows:
        rid = r["relay_id"]
        prep = float(r["prep_start_s"]); ret = float(r["return_s"])
        serv_s = float(r["service_start_s"]); serv_e = float(r["service_end_s"])
        y = ypos[rid]
        ax.barh(y, ret - prep, left=prep, height=0.55, color=colors[rid], alpha=0.25)
        ax.barh(y, serv_e - serv_s, left=serv_s, height=0.55, color=colors[rid], alpha=0.9)
        ax.text((serv_s + serv_e) / 2, y, f"悬停({r['hover_altitude_m']}m)", va="center",
                ha="center", fontsize=8)
    ax.set_yticks(list(ypos.values()))
    ax.set_yticklabels(relays)
    ax.set_xlabel("时间 (s)")
    ax.set_title("中继无人机调度甘特图（浅色=准备/往返，深色=悬停服务）")
    ax.set_xlim(0, max(float(r["return_s"]) for r in rows) + 300)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "q3_relay_gantt.png", dpi=150)
    plt.close(fig)


def fig_comparison():
    if not (RESULTS / "q3_summary.csv").exists():
        return
    rows = read_csv(RESULTS / "q3_summary.csv")
    labels = ["A 无中继", "B 简单中继", "C 优化中继"]
    cov = [float(r["coverage"]) * 100 for r in rows]
    out = [float(r["outage_s"]) for r in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    bars = ax1.bar(labels, cov, color=["gray", "tab:blue", "tab:green"])
    for b, v in zip(bars, cov):
        ax1.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.1f}%", ha="center", fontsize=10)
    ax1.set_ylabel("通信覆盖率 (%)")
    ax1.set_ylim(0, 110)
    ax1.set_title("通信覆盖率对比")
    bars2 = ax2.bar(labels, out, color=["gray", "tab:blue", "tab:green"])
    for b, v in zip(bars2, out):
        ax2.text(b.get_x() + b.get_width() / 2, v + 50, f"{v:.0f}s", ha="center", fontsize=9)
    ax2.set_ylabel("通信中断总时长 (s)")
    ax2.set_title("中断总时长对比")
    fig.tight_layout()
    fig.savefig(FIGURES / "q3_comparison.png", dpi=150)
    plt.close(fig)


def fig_sensitivity():
    if not (RESULTS / "q3_sensitivity.csv").exists():
        return
    rows = read_csv(RESULTS / "q3_sensitivity.csv")
    groups = {}
    for r in rows:
        groups.setdefault(r["parameter"], []).append((float(r["value"]), float(r["improved_coverage"])))
    names = {"relay_agl_m": "中继悬停离地高度 (m)", "los_clearance_m": "视线净空裕度 (m)",
             "time_step_s": "时间离散步长 (s)", "link_margin_db": "链路预算裕度 (dB)"}
    fig, axes = plt.subplots(1, len(groups), figsize=(4 * len(groups), 3.5))
    if len(groups) == 1:
        axes = [axes]
    for ax, (p, pts) in zip(axes, groups.items()):
        pts = sorted(pts)
        x = [a for a, b in pts]; y = [b * 100 for a, b in pts]
        ax.plot(x, y, "o-", color="tab:blue")
        ax.set_xlabel(names.get(p, p))
        ax.set_ylabel("改进覆盖率 (%)")
        ax.set_ylim(0, 105)
        ax.grid(alpha=0.3)
    fig.suptitle("敏感性分析（改进方案 2 中继覆盖）")
    fig.tight_layout()
    fig.savefig(FIGURES / "q3_sensitivity.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    fig_spatial()
    fig_blackout_timeline()
    fig_relay_gantt()
    fig_comparison()
    fig_sensitivity()
    print("figures written to", FIGURES)
