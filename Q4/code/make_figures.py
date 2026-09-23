"""Q4 paper figures (PNG)."""
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

REPO = Path(__file__).resolve().parents[2]
Q2R = REPO / "Q2" / "results"
OUT = REPO / "Q4" / "results"
FIG = REPO / "Q4" / "figures"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


def read_csv(p):
    with Path(p).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def nodes():
    q2 = json.loads((Q2R / "q2_inputs.json").read_text(encoding="utf-8"))
    return q2["nodes"]


def draw_map(ax, group_sites, title):
    nd = nodes()
    # multi-site edges (blocks)
    trips = read_csv(Q2R / "q2_trips.csv")
    edges = set()
    for r in trips:
        route = [x for x in r["route"].split("-") if x not in ("", "O01")]
        for i in range(len(route)):
            for j in range(i + 1, len(route)):
                edges.add(tuple(sorted([route[i], route[j]])))
    for a, b in edges:
        ax.plot([nd[a]["x_m"], nd[b]["x_m"]], [nd[a]["y_m"], nd[b]["y_m"]],
                color="0.6", lw=1.5, ls="--", zorder=1)
    # O01
    ax.plot(nd["O01"]["x_m"], nd["O01"]["y_m"], "*", color="red", ms=16, zorder=3)
    ax.annotate("O01", (nd["O01"]["x_m"], nd["O01"]["y_m"]), textcoords="offset points",
                xytext=(8, 8), color="red", fontsize=10)
    colors = ["tab:blue", "tab:orange", "tab:green"]
    for gi, gs in enumerate(group_sites):
        xs = [nd[s]["x_m"] for s in gs if s != "O01"]
        ys = [nd[s]["y_m"] for s in gs if s != "O01"]
        ax.scatter(xs, ys, c=colors[gi % 3], s=60, zorder=2, label=f"组{gi + 1} ({len(gs)}区)")
        for s in gs:
            if s != "O01":
                ax.annotate(s, (nd[s]["x_m"], nd[s]["y_m"]), textcoords="offset points",
                            xytext=(4, 4), fontsize=7)
    ax.set_xlabel("UTM 东向 x (m)")
    ax.set_ylabel("UTM 北向 y (m)")
    ax.set_title(title)
    ax.set_aspect("equal")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)


def fig_partition_maps():
    best2 = json.loads((OUT / "q4_best_2groups.json").read_text(encoding="utf-8"))
    group_sites = [g["service_ids"] for g in best2["groups"]]
    fig, ax = plt.subplots(figsize=(8, 7))
    draw_map(ax, group_sites, "2 任务组最优分区")
    fig.tight_layout()
    fig.savefig(FIG / "q4_partition_map_2groups.png", dpi=150)
    plt.close(fig)

    best3 = json.loads((OUT / "q4_best_3groups.json").read_text(encoding="utf-8"))
    group_sites3 = [g["service_ids"] for g in best3["groups"]]
    fig, ax = plt.subplots(figsize=(8, 7))
    draw_map(ax, group_sites3, "3 任务组最优分区")
    fig.tight_layout()
    fig.savefig(FIG / "q4_partition_map_3groups.png", dpi=150)
    plt.close(fig)


def fig_resource_comparison():
    rows = read_csv(OUT / "q4_resource_comparison.csv")
    labels = [r["scenario"] for r in rows]
    drone = [r["transport_drones"] for r in rows]
    batt = [r["batteries"] for r in rows]
    rd = [r["relay_drones"] for r in rows]
    rm = [r["relay_modules"] for r in rows]
    x = np.arange(len(labels))
    w = 0.2
    fig, ax = plt.subplots(figsize=(7, 4.5))
    def bar(vals, off, color, name):
        vals = [0 if v in (None, "") else int(v) for v in vals]
        ax.bar(x + off, vals, w, color=color, label=name)
        for i, v in enumerate(vals):
            ax.text(x[i] + off, v + 0.2, str(v) if v else ("×" if vals == drone and False else ""),
                    ha="center", fontsize=9)
    bar(drone, -1.5 * w, "tab:blue", "运输无人机")
    bar(batt, -0.5 * w, "tab:orange", "共享电池")
    bar(rd, 0.5 * w, "tab:green", "中继无人机")
    bar(rm, 1.5 * w, "tab:red", "中继能源组件")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("资源数量")
    ax.set_title("资源配置对比（Q3集中式 vs 2组 vs 3组）")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "q4_resource_comparison.png", dpi=150)
    plt.close(fig)


def fig_workload():
    rows = [r for r in read_csv(OUT / "q4_workload_comparison.csv") if r["feasible"] == "True"]
    labels = [f"{r['scenario']}-组{r['group']}" for r in rows]
    trips = [int(r["n_trips"]) for r in rows]
    boxes = [int(r["n_boxes"]) for r in rows]
    energy = [float(r["transport_energy_kwh"]) for r in rows]
    x = np.arange(len(labels))
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.5))
    axes[0].bar(x, trips, color="tab:blue")
    axes[0].set_title("运输架次数")
    axes[0].set_xticks(x); axes[0].set_xticklabels(labels, fontsize=8)
    for i, v in enumerate(trips):
        axes[0].text(i, v + 0.3, str(v), ha="center", fontsize=9)
    axes[1].bar(x, boxes, color="tab:orange")
    axes[1].set_title("货箱数")
    axes[1].set_xticks(x); axes[1].set_xticklabels(labels, fontsize=8)
    for i, v in enumerate(boxes):
        axes[1].text(i, v + 0.5, str(v), ha="center", fontsize=9)
    axes[2].bar(x, energy, color="tab:green")
    axes[2].set_title("运输能耗 (kWh)")
    axes[2].set_xticks(x); axes[2].set_xticklabels(labels, fontsize=8)
    for i, v in enumerate(energy):
        axes[2].text(i, v + 0.5, f"{v:.1f}", ha="center", fontsize=8)
    for ax in axes:
        ax.grid(axis="y", alpha=0.3)
    fig.suptitle("组间工作量对比（2组/3组）")
    fig.tight_layout()
    fig.savefig(FIG / "q4_workload_balance.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    fig_partition_maps()
    fig_resource_comparison()
    fig_workload()
    print("figures written")
