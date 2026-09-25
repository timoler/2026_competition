"""Generate Q4 final paper figures from official results (read-only)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[2]
Q2R = REPO / "Q2" / "results"
OUT = REPO / "Q4" / "results"
PFIG = REPO / "paper_figures"
PFIG.mkdir(parents=True, exist_ok=True)

BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#d03b3b"
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
GROUP_COLORS = [BLUE, ORANGE, AQUA]

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "font.size": 10, "savefig.dpi": 300,
})


def read_csv(p):
    with Path(p).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def nodes():
    return json.loads((Q2R / "q2_inputs.json").read_text(encoding="utf-8"))["nodes"]


def block_edges():
    trips = read_csv(Q3R / "q3_transport_schedule.csv")
    edges = set()
    for r in trips:
        route = [x for x in r["route"].split("-") if x not in ("", "O01")]
        for i in range(len(route)):
            for j in range(i + 1, len(route)):
                edges.add(tuple(sorted([route[i], route[j]])))
    return edges


def draw_map(ax, group_sites, tag):
    nd = nodes()
    edges = block_edges()
    for a, b in edges:
        ax.plot([nd[a]["x_m"], nd[b]["x_m"]], [nd[a]["y_m"], nd[b]["y_m"]],
                color="0.72", lw=1.3, ls="--", zorder=1)
    ax.plot(nd["O01"]["x_m"], nd["O01"]["y_m"], "*", color=RED, ms=16, zorder=4)
    ax.annotate("O01", (nd["O01"]["x_m"], nd["O01"]["y_m"]), textcoords="offset points",
                xytext=(8, 8), color=RED, fontsize=10)
    for gi, gs in enumerate(group_sites):
        xs = [nd[s]["x_m"] for s in gs if s != "O01"]
        ys = [nd[s]["y_m"] for s in gs if s != "O01"]
        ax.scatter(xs, ys, c=GROUP_COLORS[gi % 3], s=58, zorder=3,
                   edgecolor="white", linewidth=0.8, label=f"组{gi + 1}（{len(gs)} 区）")
        for s in gs:
            if s != "O01":
                ax.annotate(s, (nd[s]["x_m"], nd[s]["y_m"]), textcoords="offset points",
                            xytext=(4, 4), fontsize=7, color=INK)
    ax.set_xlabel("UTM 东向 x (m)")
    ax.set_ylabel("UTM 北向 y (m)")
    ax.set_aspect("equal")
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    ax.grid(alpha=0.25)
    ax.text(0.02, 0.96, tag, transform=ax.transAxes, fontsize=12, va="top",
            ha="left", color=INK, weight="bold")


def fig_partition_comparison():
    best2 = json.loads((OUT / "q4_best_2groups.json").read_text(encoding="utf-8"))
    best3 = json.loads((OUT / "q4_best_3groups.json").read_text(encoding="utf-8"))
    g2 = [g["service_ids"] for g in best2["groups"]]
    g3 = [g["service_ids"] for g in best3["groups"]]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 6), sharex=True, sharey=True)
    draw_map(ax1, g2, "(a)")
    draw_map(ax2, g3, "(b)")
    fig.tight_layout(w_pad=0.5)
    fig.savefig(PFIG / "q4_partition_comparison_final.png", dpi=300)
    plt.close(fig)


def fig_resource_comparison():
    rows = read_csv(OUT / "q4_resource_comparison.csv")
    rename = {"Q3集中式": "集中式", "2组分区": "2组分区", "3组分区": "3组分区"}
    labels = [rename.get(r["scenario"], r["scenario"]) for r in rows]
    drone = [int(r["transport_drones"]) for r in rows]
    batt = [int(r["batteries"]) for r in rows]
    rd = [int(r["relay_drones"]) for r in rows]
    rm = [int(r["relay_modules"]) for r in rows]
    x = np.arange(len(labels))
    w = 0.2
    fig, ax = plt.subplots(figsize=(7, 4.2))

    def bar(vals, off, color, name):
        ax.bar(x + off, vals, w, color=color, label=name, edgecolor="white")
        for i, v in enumerate(vals):
            ax.text(x[i] + off, v + 0.15, str(v), ha="center", fontsize=9, color=INK)

    bar(drone, -1.5 * w, BLUE, "运输无人机")
    bar(batt, -0.5 * w, ORANGE, "共享电池")
    bar(rd, 0.5 * w, AQUA, "中继无人机")
    bar(rm, 1.5 * w, RED, "中继能源组件")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("资源数量")
    ax.set_ylim(0, max(rm) * 1.2)
    ax.legend(fontsize=8, frameon=False, ncol=2)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(PFIG / "q4_resource_comparison_final.png", dpi=300)
    plt.close(fig)


if __name__ == "__main__":
    fig_partition_comparison()
    fig_resource_comparison()
    print("Q4 final figures written")
