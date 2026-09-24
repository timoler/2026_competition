"""Generate Q1 final paper figures + tables from official CSV (read-only)."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[2]
R = REPO / "Q1" / "results"
PFIG = REPO / "paper_figures"
PTAB = REPO / "paper_tables"
PFIG.mkdir(parents=True, exist_ok=True)
PTAB.mkdir(parents=True, exist_ok=True)

# Unified academic palette
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "font.size": 10, "savefig.dpi": 300,
})


def read_csv(name):
    with (R / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Figure 1: safety-margin sensitivity
# ---------------------------------------------------------------------------
def fig1():
    rows = read_csv("q1_model_comparison.csv")
    by_p = defaultdict(list)
    for r in rows:
        by_p[r["priority"]].append(r)
    default_p = max(by_p, key=lambda k: len(by_p[k]))
    d = sorted(by_p[default_p], key=lambda r: float(r["reserve"]))
    reserves = [int(round(float(r["reserve"]) * 100)) for r in d]
    sorties = [int(r["trips"]) for r in d]
    energy = [float(r["energy_kwh"]) for r in d]

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.4))
    ax = axes[0]
    bars = ax.bar(reserves, sorties, width=3.0, color=BLUE, edgecolor="white")
    for b, v in zip(bars, sorties):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.15, str(v),
                ha="center", va="bottom", fontsize=11, color=INK)
    ax.set_xlabel("返航安全余量 (%)")
    ax.set_ylabel("架次数")
    ax.set_ylim(0, max(sorties) + 1.5)
    ax.set_xticks(reserves)

    ax = axes[1]
    bars = ax.bar(reserves, energy, width=3.0, color=AQUA, edgecolor="white")
    for b, v in zip(bars, energy):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.4, f"{v:.1f}",
                ha="center", va="bottom", fontsize=10, color=INK)
    ax.set_xlabel("返航安全余量 (%)")
    ax.set_ylabel("总运输能耗 (kWh)")
    ax.set_ylim(0, max(energy) * 1.13)
    ax.set_xticks(reserves)
    fig.tight_layout(w_pad=1.5)
    fig.savefig(PFIG / "q1_safety_margin_final.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 2: site batch allocation
# ---------------------------------------------------------------------------
def fig2():
    rows = read_csv("q1_batches_default.csv")
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

    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.6))
    x = range(len(sites))
    ax = axes[0]
    ax.bar(x, B, color=BLUE, label="B 型架次", width=0.7, edgecolor="white")
    ax.bar(x, C, bottom=B, color=ORANGE, label="C 型架次", width=0.7, edgecolor="white")
    ax.set_xticks(list(x))
    ax.set_xticklabels(sites, rotation=30, ha="right", fontsize=9)
    ax.set_xlabel("服务区")
    ax.set_ylabel("货箱数")
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    ax.set_ylim(0, max(a + b for a, b in zip(B, C)) + 1)

    ax = axes[1]
    ax.bar(x, mass, color=AQUA, width=0.7, edgecolor="white")
    ax.set_xticks(list(x))
    ax.set_xticklabels(sites, rotation=30, ha="right", fontsize=9)
    ax.set_xlabel("服务区")
    ax.set_ylabel("货物总质量 (kg)")
    fig.tight_layout(w_pad=1.5)
    fig.savefig(PFIG / "q1_batch_allocation_final.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Table 1: objective-priority comparison
# ---------------------------------------------------------------------------
def table1():
    rows = read_csv("q1_model_comparison.csv")
    reserve_020 = [r for r in rows if abs(float(r["reserve"]) - 0.2) < 1e-9]
    label_map = {
        "时间_架次_能耗": "时间→架次→能耗",
        "架次_能耗_时间": "架次→能耗→时间",
        "架次_时间_能耗": "架次→时间→能耗",
        "能耗_架次_时间": "能耗→架次→时间",
    }
    out = []
    for r in reserve_020:
        out.append(dict(
            目标优先级=label_map.get(r["priority"], r["priority"]),
            架次数=int(r["trips"]),
            总能耗_kWh=round(float(r["energy_kwh"]), 6),
            累计作业时间_s=round(float(r["operation_s"]), 6)))
    out.sort(key=lambda r: (r["架次数"], r["总能耗_kWh"]))
    # 规范列名（带单位）
    out = [{"目标优先级": r["目标优先级"], "架次数": r["架次数"],
            "总能耗 (kWh)": r["总能耗_kWh"], "累计作业时间 (s)": r["累计作业时间_s"]}
           for r in out]
    with (PTAB / "q1_priority_comparison.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    fig1(); fig2(); table1()
    print("Q1 final figures + table written")
