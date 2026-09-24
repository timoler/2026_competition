"""Generate Q1 paper figures from the official result CSVs (read-only inputs).

Figures (300 dpi, white background, restrained palette):
  q1_fig1_safety_margin.png   sorties / energy vs return-safety margin
  q1_fig2_batch_allocation.png  80 boxes across 15 sites by model (B/C)
  q1_fig3_priority_tradeoff.png  three objective priorities compared
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS = Path(__file__).resolve().parents[1] / "results"
FIG = Path(__file__).resolve().parents[1] / "figures"
FIG.mkdir(parents=True, exist_ok=True)

# Palette (validated, light mode)
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": "#c3c2b7",
    "axes.labelcolor": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "font.size": 10,
})


def read_csv(name):
    with (RESULTS / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Figure 1: safety-margin sensitivity
# ---------------------------------------------------------------------------
def fig1():
    rows = read_csv("q1_model_comparison.csv")
    by_p = defaultdict(list)
    for r in rows:
        by_p[r["priority"]].append(r)
    # default priority = the one run at every margin level (5 rows)
    default_p = max(by_p, key=lambda k: len(by_p[k]))
    d = sorted(by_p[default_p], key=lambda r: float(r["reserve"]))
    reserves = [int(round(float(r["reserve"]) * 100)) for r in d]
    sorties = [int(r["trips"]) for r in d]
    energy = [float(r["energy_kwh"]) for r in d]
    ops = [float(r["operation_s"]) / 3600 for r in d]

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6))
    # left: sorties
    ax = axes[0]
    bars = ax.bar(reserves, sorties, width=3.0, color=BLUE, edgecolor="white")
    for b, v in zip(bars, sorties):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.15, str(v),
                ha="center", va="bottom", fontsize=10, color=INK)
    ax.set_xlabel("返航安全余量 (%)")
    ax.set_ylabel("架次数")
    ax.set_ylim(0, max(sorties) + 1.5)
    ax.set_xticks(reserves)

    # right: energy (bar) with time annotated
    ax = axes[1]
    bars = ax.bar(reserves, energy, width=3.0, color=AQUA, edgecolor="white")
    for b, v in zip(bars, energy):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.4, f"{v:.1f}",
                ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_xlabel("返航安全余量 (%)")
    ax.set_ylabel("总运输能耗 (kWh)")
    ax.set_ylim(0, max(energy) * 1.12)
    ax.set_xticks(reserves)
    fig.tight_layout()
    fig.savefig(FIG / "q1_fig1_safety_margin.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 2: batch / site allocation
# ---------------------------------------------------------------------------
def fig2():
    rows = read_csv("q1_batches_default.csv")
    # box count + mass per site, split by model B/C
    site_boxes = defaultdict(lambda: {"B": 0, "C": 0, "mass": 0.0})
    for r in rows:
        m = r["model"]
        n = len(r["box_ids"].split(";"))
        site_boxes[r["site"]][m] += n
        site_boxes[r["site"]]["mass"] += float(r["mass_kg"])
    sites = sorted(site_boxes)
    B = [site_boxes[s]["B"] for s in sites]
    C = [site_boxes[s]["C"] for s in sites]
    mass = [site_boxes[s]["mass"] for s in sites]

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8))
    ax = axes[0]
    x = range(len(sites))
    ax.bar(x, B, color=BLUE, label="B 型架次", width=0.72, edgecolor="white")
    ax.bar(x, C, bottom=B, color=ORANGE, label="C 型架次", width=0.72, edgecolor="white")
    ax.set_xticks(list(x))
    ax.set_xticklabels(sites, rotation=45, ha="right", fontsize=8)
    ax.set_xlabel("服务区")
    ax.set_ylabel("货箱数")
    ax.legend(frameon=False)
    ax.set_ylim(0, max(a + b for a, b in zip(B, C)) + 1)

    ax = axes[1]
    ax.bar(x, mass, color=AQUA, width=0.72, edgecolor="white")
    ax.set_xticks(list(x))
    ax.set_xticklabels(sites, rotation=45, ha="right", fontsize=8)
    ax.set_xlabel("服务区")
    ax.set_ylabel("货物总质量 (kg)")
    fig.tight_layout()
    fig.savefig(FIG / "q1_fig2_batch_allocation.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 3: objective-priority tradeoff
# ---------------------------------------------------------------------------
def fig3():
    rows = read_csv("q1_model_comparison.csv")
    reserve_020 = [r for r in rows if abs(float(r["reserve"]) - 0.2) < 1e-9]
    label_map = {
        "时间_架次_能耗": "时间→架次→能耗",
        "架次_能耗_时间": "架次→能耗→时间",
        "架次_时间_能耗": "架次→时间→能耗",
        "能耗_架次_时间": "能耗→架次→时间",
    }
    labels = []
    sorties, energy, ops = [], [], []
    for r in reserve_020:
        labels.append(label_map.get(r["priority"], r["priority"]))
        sorties.append(int(r["trips"]))
        energy.append(float(r["energy_kwh"]))
        ops.append(float(r["operation_s"]) / 3600)

    x = range(len(labels))
    fig, axes = plt.subplots(1, 3, figsize=(10.4, 3.4))
    ax = axes[0]
    ax.bar(x, sorties, color=BLUE, width=0.6, edgecolor="white")
    for i, v in enumerate(sorties):
        ax.text(i, v + 0.15, str(v), ha="center", fontsize=10, color=INK)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("架次数"); ax.set_ylim(0, max(sorties) + 1)

    ax = axes[1]
    ax.bar(x, energy, color=AQUA, width=0.6, edgecolor="white")
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("总能耗 (kWh)"); ax.set_ylim(0, max(energy) * 1.1)

    ax = axes[2]
    ax.bar(x, ops, color=ORANGE, width=0.6, edgecolor="white")
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("累计作业时间 (h)"); ax.set_ylim(0, max(ops) * 1.1)
    fig.tight_layout()
    fig.savefig(FIG / "q1_fig3_priority_tradeoff.png", dpi=300)
    plt.close(fig)


if __name__ == "__main__":
    fig1()
    fig2()
    fig3()
    print("Q1 figures written to", FIG)
