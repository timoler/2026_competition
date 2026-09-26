"""Generate Q2 final paper figures + tables from official CSVs (read-only)."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

REPO = Path(__file__).resolve().parents[2]
R = REPO / "Q2" / "results"
PFIG = REPO / "paper_figures"
PTAB = REPO / "paper_tables"
PFIG.mkdir(parents=True, exist_ok=True)
PTAB.mkdir(parents=True, exist_ok=True)

BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#d03b3b"
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
TYPE_COLOR = {"A": BLUE, "B": ORANGE, "C": AQUA}
TYPE_NAME = {"A": "A 型", "B": "B 型", "C": "C 型"}

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
# Figure 1: drone gantt
# ---------------------------------------------------------------------------
def fig1():
    trips = read_csv("q2_trips.csv")
    drones = sorted({t["drone_id"] for t in trips})
    ypos = {d: i for i, d in enumerate(drones)}
    fig, ax = plt.subplots(figsize=(10, 4.4))
    for t in trips:
        y = ypos[t["drone_id"]]
        s, e = float(t["preparation_start_s"]), float(t["return_s"])
        ax.barh(y, e - s, left=s, height=0.6, color=TYPE_COLOR[t["type_id"]],
                edgecolor="white", linewidth=0.3)
    ax.legend(handles=[mpatches.Patch(color=TYPE_COLOR[k], label=TYPE_NAME[k])
                       for k in ("A", "B", "C")],
              loc="lower right", frameon=False, ncol=3, fontsize=9)
    ax.set_yticks(list(ypos.values()))
    ax.set_yticklabels(drones)
    ax.set_ylim(-0.5, len(drones) - 0.5)
    ax.set_xlabel("时间 (s)")
    ax.set_ylabel("运输无人机")
    ax.set_xlim(0, max(float(t["return_s"]) for t in trips) * 1.02)
    fig.tight_layout()
    fig.savefig(PFIG / "q2_drone_gantt_final.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 2: hard-deadline margin (horizontal, sorted ascending)
# ---------------------------------------------------------------------------
def fig2():
    deliv = read_csv("q2_deliveries.csv")
    hard = [r for r in deliv if r["hard_due_s"] and r["hard_due_s"].strip()]
    # 剩余裕量 = 硬截止时刻 − 交付完成时刻，逐箱复算。
    data = [(float(r["hard_due_s"]) - float(r["delivery_complete_s"]), r["box_id"])
            for r in hard]
    # 由大到小排序：最大裕量在最下方、最小裕量在最上方，使"从上到下"读作升序。
    data.sort(key=lambda x: x[0], reverse=True)
    margins = [d[0] for d in data]
    labels = [d[1] for d in data]
    n = len(data)
    y = list(range(n))

    fig, ax = plt.subplots(figsize=(7.6, 5.8))
    ax.barh(y, margins, height=0.6, color=AQUA, edgecolor="white", linewidth=0.3)
    ax.axvline(0, color=RED, linewidth=1.2)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=6.5)
    ax.set_xlabel("硬时限剩余裕量 (s)")
    ax.set_ylabel("硬时限货箱（按剩余裕量升序）")

    # 最小裕量在最上方；标注放在上部空白处，用箭头指向最短条形右端。
    mn = margins[-1]
    mn_y = n - 1
    xmax = margins[0]
    ax.set_xlim(0, xmax * 1.22)
    ax.annotate(
        f"最小裕量 {mn:.2f} s > 0",
        xy=(mn, mn_y),
        xytext=(xmax * 0.46, mn_y - 1.5),
        arrowprops=dict(arrowstyle="->", color=INK, lw=0.9, shrinkA=0, shrinkB=0),
        fontsize=8.5, color=INK, ha="left", va="center",
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.92),
    )
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(PFIG / "q2_deadline_margin_final.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 4: SOC sensitivity
# ---------------------------------------------------------------------------
def fig4():
    trips = read_csv("q2_trips.csv")
    socs = [float(t["return_soc"]) for t in trips]
    factors = [0.98, 1.00, 1.02, 1.05]
    xs = factors
    ys = [min(1 - f * (1 - s) for s in socs) * 100 for f in factors]
    colors = [AQUA if v >= 20 else RED for v in ys]
    fig, ax = plt.subplots(figsize=(6.6, 3.8))
    ax.plot(xs, ys, color=MUTED, linewidth=1.2, zorder=1)
    ax.scatter(xs, ys, color=colors, s=56, zorder=2, edgecolor="white", linewidth=1)
    ax.axhline(20, color=INK, linestyle="--", linewidth=1.0)
    ax.text(0.9805, 20.4, "返航 SOC 下限 20%", color=INK, fontsize=8)
    for xi, yi in zip(xs, ys):
        ax.annotate(f"{yi:.1f}%", (xi, yi), textcoords="offset points",
                    xytext=(0, 7), ha="center", fontsize=8, color=INK)
    ax.set_xlabel("能耗统一缩放系数")
    ax.set_ylabel("全方案最低返航 SOC (%)")
    ax.set_xticks(xs)
    ax.set_ylim(0, max(ys) * 1.15)
    fig.tight_layout()
    fig.savefig(PFIG / "q2_soc_sensitivity_final.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Table: search comparison
# ---------------------------------------------------------------------------
def table():
    hist = read_csv("q2_search_history.csv")
    best = {}
    for r in hist:
        if float(r["weighted_soft_lateness_s"]) != 0:
            continue
        m = float(r["makespan_s"])
        if r["method"] not in best or m < best[r["method"]][0]:
            best[r["method"]] = (m, float(r["energy_kwh"]), int(r["trips"]))
    improved = read_csv("q2_improvement.csv")
    imp = improved[-1]
    method_label = {"single_stop_baseline": "单点构造", "multipoint": "多点构造"}
    rows = [
        dict(方案="单点构造", 完工时间_s=round(best["single_stop_baseline"][0], 6),
             总能耗_kWh=round(best["single_stop_baseline"][1], 6),
             架次数=best["single_stop_baseline"][2]),
        dict(方案="多点构造", 完工时间_s=round(best["multipoint"][0], 6),
             总能耗_kWh=round(best["multipoint"][1], 6),
             架次数=best["multipoint"][2]),
        dict(方案="局部改进", 完工时间_s=round(float(imp["makespan_s"]), 6),
             总能耗_kWh=round(float(imp["energy_kwh"]), 6),
             架次数=int(imp["trips"])),
    ]
    rows = [{"方案": r["方案"], "完工时间 (s)": r["完工时间_s"],
             "总能耗 (kWh)": r["总能耗_kWh"], "架次数": r["架次数"]} for r in rows]
    with (PTAB / "q2_search_comparison.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    fig1(); fig2(); fig4(); table()
    print("Q2 final figures + table written")
