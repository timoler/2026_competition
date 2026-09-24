"""Generate Q2 paper figures + a minimal SOC sensitivity from official CSVs.

Figures (300 dpi, white background, restrained palette):
  q2_fig1_drone_gantt.png   trip occupancy across the 8 drones
  q2_fig2_hard_deadline_margin.png   slack of the 31 hard-deadline boxes
  q2_fig3_search_comparison.png      single / multi construct vs improved
  q2_fig4_soc_sensitivity.png        min return SOC vs energy scale factor
Also writes q2_soc_sensitivity.csv.
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
    "font.size": 10,
})


def read_csv(name):
    with (RESULTS / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Figure 1: drone gantt
# ---------------------------------------------------------------------------
def fig1():
    trips = read_csv("q2_trips.csv")
    drones = sorted({t["drone_id"] for t in trips})
    ypos = {d: i for i, d in enumerate(drones)}
    fig, ax = plt.subplots(figsize=(10, 4.6))
    for t in trips:
        y = ypos[t["drone_id"]]
        s, e = float(t["preparation_start_s"]), float(t["return_s"])
        ax.barh(y, e - s, left=s, height=0.62, color=TYPE_COLOR[t["type_id"]],
                edgecolor="white", linewidth=0.3)
    # legend by type (use explicit patches, not off-screen bars)
    import matplotlib.patches as mpatches
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
    fig.savefig(FIG / "q2_fig1_drone_gantt.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 2: hard-deadline margin
# ---------------------------------------------------------------------------
def fig2():
    deliv = read_csv("q2_deliveries.csv")
    hard = [r for r in deliv if r["hard_due_s"] and r["hard_due_s"].strip()]
    hard.sort(key=lambda r: float(r["delivery_complete_s"]))
    margin = [float(r["hard_due_s"]) - float(r["delivery_complete_s"]) for r in hard]
    fig, ax = plt.subplots(figsize=(9, 4))
    x = list(range(1, len(hard) + 1))
    ax.bar(x, margin, color=AQUA, width=0.8, edgecolor="white")
    ax.axhline(0, color=RED, linewidth=1.2)
    ax.set_xlabel("硬时限货箱（按送达完成时刻排序）")
    ax.set_ylabel("剩余裕量 = 截止 − 送达完成 (s)")
    ax.set_xlim(0, len(hard) + 1)
    mn = min(margin)
    ax.text(1, mn + (max(margin) - mn) * 0.06, f"最小裕量 {mn:.0f} s > 0",
            color=INK, fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG / "q2_fig2_hard_deadline_margin.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 3: search comparison
# ---------------------------------------------------------------------------
def fig3():
    hist = read_csv("q2_search_history.csv")
    best = defaultdict(lambda: None)
    for r in hist:
        if float(r["weighted_soft_lateness_s"]) != 0:
            continue
        m = float(r["makespan_s"])
        key = r["method"]
        if best[key] is None or m < best[key]["makespan"]:
            best[key] = dict(makespan=m, energy=float(r["energy_kwh"]),
                             trips=int(r["trips"]))
    improved = read_csv("q2_improvement.csv")
    imp_last = improved[-1]

    method_label = {"single_stop_baseline": "单点构造",
                    "multipoint": "多点构造"}
    order = sorted(best, key=lambda k: best[k]["makespan"])
    schemes = order + ["improved"]
    makespan = [best[k]["makespan"] for k in order] + [float(imp_last["makespan_s"])]
    energy = [best[k]["energy"] for k in order] + [float(imp_last["energy_kwh"])]
    trips = [best[k]["trips"] for k in order] + [int(imp_last["trips"])]
    labels = [method_label.get(k, k) for k in order] + ["局部改进"]

    fig, axes = plt.subplots(1, 3, figsize=(10.4, 3.4))
    x = range(len(schemes))
    axes[0].bar(x, makespan, color=BLUE, width=0.55, edgecolor="white")
    axes[0].set_ylabel("makespan (s)")
    axes[1].bar(x, energy, color=AQUA, width=0.55, edgecolor="white")
    axes[1].set_ylabel("总能耗 (kWh)")
    axes[2].bar(x, trips, color=ORANGE, width=0.55, edgecolor="white")
    axes[2].set_ylabel("架次数")
    for ax in axes:
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, fontsize=9)
        ax.tick_params(axis="x", rotation=0)
    for ax, vals in zip(axes, (makespan, energy, trips)):
        ax.set_ylim(0, max(vals) * 1.12)
    fig.tight_layout()
    fig.savefig(FIG / "q2_fig3_search_comparison.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# SOC sensitivity (scheme A: uniform energy scale, no re-optimisation)
# ---------------------------------------------------------------------------
def sensitivity():
    trips = read_csv("q2_trips.csv")
    socs = [float(t["return_soc"]) for t in trips]
    factors = [0.98, 1.00, 1.02, 1.05]
    rows = []
    for f in factors:
        new_socs = [1 - f * (1 - s) for s in socs]
        m = min(new_socs)
        rows.append(dict(energy_scale=f, min_return_soc=round(m, 6),
                         feasible=(m >= 0.20)))
    with (RESULTS / "q2_soc_sensitivity.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    fig, ax = plt.subplots(figsize=(6.6, 3.8))
    x = [r["energy_scale"] for r in rows]
    y = [r["min_return_soc"] * 100 for r in rows]
    colors = [AQUA if r["feasible"] else RED for r in rows]
    ax.plot(x, y, color=MUTED, linewidth=1.2, zorder=1)
    ax.scatter(x, y, color=colors, s=60, zorder=2, edgecolor="white", linewidth=1)
    ax.axhline(20, color=INK, linestyle="--", linewidth=1.0)
    ax.text(0.9805, 20.3, "返航 SOC 下限 20%", color=INK, fontsize=9)
    for xi, yi in zip(x, y):
        ax.annotate(f"{yi:.1f}%", (xi, yi), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=9, color=INK)
    ax.set_xlabel("能耗统一缩放系数")
    ax.set_ylabel("全方案最低返航 SOC (%)")
    ax.set_xticks(x)
    ax.set_ylim(0, max(y) * 1.18)
    fig.tight_layout()
    fig.savefig(FIG / "q2_fig4_soc_sensitivity.png", dpi=300)
    plt.close(fig)
    return rows


if __name__ == "__main__":
    fig1(); fig2(); fig3()
    sens = sensitivity()
    print("Q2 figures + sensitivity written to", FIG)
    for r in sens:
        print(f"  energy_scale={r['energy_scale']}: min_SOC={r['min_return_soc']*100:.2f}% feasible={r['feasible']}")
