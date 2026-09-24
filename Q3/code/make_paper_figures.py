"""Generate Q3 paper figures from the current official CSVs/JSONs.

Figures (300 dpi, white background):
  q3_fig1_joint_timeline.png   relay sorties + transport coverage
  q3_fig2_scheme_comparison.png  original / static / joint (uncovered & coverage)
  q3_fig3_comm_sensitivity.png   sample counts table (all PASS)
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS = Path(__file__).resolve().parents[1] / "results"
FIG = Path(__file__).resolve().parents[1] / "figures"
FIG.mkdir(parents=True, exist_ok=True)

BLUE, ORANGE, AQUA, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"
GRAY, INK, MUTED, GRID, LIGHT = "#898781", "#0b0b0b", "#898781", "#e1e0d9", "#cde2fb"

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
# Figure 1: relay + transport joint timeline
# ---------------------------------------------------------------------------
def fig1():
    relay = read_csv("q3_relay_schedule.csv")
    transport = read_csv("q3_transport_schedule.csv")
    links = read_csv("q3_communication_links.csv")

    # per-trip provider set
    prov = defaultdict(set)
    for r in links:
        p = r["provider"]
        if p != "G01":
            prov[r["trip_id"]].add(p)
    def trip_color(tid):
        s = prov.get(tid, set())
        has_r01 = bool(s & {"S01"})
        has_r02 = bool(s & {"S02", "S03"})
        if has_r01 and has_r02:
            return VIOLET
        if has_r01:
            return BLUE
        if has_r02:
            return ORANGE
        return GRAY

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.2), sharex=True,
                                   gridspec_kw={"height_ratios": [1, 2.2]})

    # --- relay sorties ---
    ylabels = []
    for i, r in enumerate(relay):
        y = len(relay) - 1 - i
        prep, to, ss, se, ret = (float(r["prep_start_s"]), float(r["takeoff_s"]),
                                 float(r["service_start_s"]), float(r["service_end_s"]),
                                 float(r["return_s"]))
        color = BLUE if r["relay_id"] == "R01" else ORANGE
        # prep + outbound flight (light)
        ax1.barh(y, ss - prep, left=prep, height=0.55, color=LIGHT, edgecolor="white", linewidth=0.3)
        # service (colored)
        ax1.barh(y, se - ss, left=ss, height=0.55, color=color, edgecolor="white", linewidth=0.3)
        # return flight (light)
        ax1.barh(y, ret - se, left=se, height=0.55, color=LIGHT, edgecolor="white", linewidth=0.3)
        ax1.text(prep - 60, y, f"{r['sortie_id']} / {r['relay_id']}",
                 ha="right", va="center", fontsize=9, color=INK)
        ylabels.append(f"{r['sortie_id']} / {r['relay_id']}")
    ax1.set_yticks([])
    ax1.set_ylabel("中继架次", fontsize=9)
    ax1.set_ylim(-0.6, len(relay) - 0.4)
    # legend for relay panel
    import matplotlib.patches as mpatches
    ax1.legend(handles=[mpatches.Patch(color=LIGHT, label="准备/转场"),
                        mpatches.Patch(color=BLUE, label="R01 服务"),
                        mpatches.Patch(color=ORANGE, label="R02 服务")],
               loc="upper right", frameon=False, fontsize=8, ncol=3)

    # --- transport trips colored by relay coverage ---
    drones = sorted({t["drone_id"] for t in transport})
    ypos = {d: i for i, d in enumerate(drones)}
    for t in transport:
        y = ypos[t["drone_id"]]
        s, e = float(t["preparation_start_s"]), float(t["return_s"])
        ax2.barh(y, e - s, left=s, height=0.62, color=trip_color(t["trip_id"]),
                 edgecolor="white", linewidth=0.3)
    ax2.set_yticks(list(ypos.values()))
    ax2.set_yticklabels(drones)
    ax2.set_ylabel("运输无人机")
    ax2.set_xlabel("时间 (s)")
    ax2.set_xlim(0, max(float(r["return_s"]) for r in relay) * 1.02)
    ax2.legend(handles=[mpatches.Patch(color=GRAY, label="直连 G01"),
                        mpatches.Patch(color=BLUE, label="R01 保障"),
                        mpatches.Patch(color=ORANGE, label="R02 保障"),
                        mpatches.Patch(color=VIOLET, label="R01+R02 保障")],
               loc="upper right", frameon=False, fontsize=8, ncol=4)
    fig.tight_layout()
    fig.savefig(FIG / "q3_fig1_joint_timeline.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 2: three-scheme comparison
# ---------------------------------------------------------------------------
def fig2():
    e0 = json.loads((RESULTS / "e0_baseline.json").read_text(encoding="utf-8"))
    static = json.loads((RESULTS / "comparison_2relay_static" / "q3_feasibility_2relay.json")
                        .read_text(encoding="utf-8"))
    cur = json.loads((RESULTS / "q3_final_validation.json").read_text(encoding="utf-8"))
    names = ["原始方案", "静态两中继", "联合调度两中继"]
    unc = [e0["uncovered_samples"], static["uncovered_samples"], cur["uncovered_samples"]]
    cov = [e0["coverage"] * 100, static["coverage"] * 100, cur["coverage"] * 100]

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.6))
    x = range(3)
    cols = [GRAY, GRAY, AQUA]
    axes[0].bar(x, unc, color=cols, width=0.55, edgecolor="white")
    for i, v in enumerate(unc):
        axes[0].text(i, v + 8, str(v), ha="center", fontsize=10, color=INK)
    axes[0].set_xticks(list(x)); axes[0].set_xticklabels(names, rotation=20, ha="right", fontsize=8)
    axes[0].set_ylabel("uncovered 样本数")
    axes[0].set_ylim(0, max(unc) * 1.15)

    axes[1].bar(x, cov, color=cols, width=0.55, edgecolor="white")
    for i, v in enumerate(cov):
        axes[1].text(i, v + 0.6, f"{v:.2f}%", ha="center", fontsize=9, color=INK)
    axes[1].set_xticks(list(x)); axes[1].set_xticklabels(names, rotation=20, ha="right", fontsize=8)
    axes[1].set_ylabel("覆盖率 (%)")
    axes[1].set_ylim(0, 101)
    fig.tight_layout()
    fig.savefig(FIG / "q3_fig2_scheme_comparison.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 3: communication sensitivity (all PASS -> compact table)
# ---------------------------------------------------------------------------
def fig3():
    los = read_csv("q3_los_resolution_sensitivity.csv")
    tmp = read_csv("e4_temporal_sensitivity.csv")
    rows = los + tmp
    header = ["时间步长 s", "LOS 间距 m", "样本数", "uncovered", "覆盖率", "状态"]
    data = [[r["time_step_s"], r["los_spacing_m"], r["total_samples"],
             r["uncovered_samples"], f"{float(r['coverage'])*100:.4f}%", r["status"]]
            for r in rows]
    fig, ax = plt.subplots(figsize=(6.8, 2.6))
    ax.axis("off")
    tbl = ax.table(cellText=data, colLabels=header, cellLoc="center", loc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.6)
    for (r, c), cell in tbl.get_celld().items():
        if r == 0:
            cell.set_facecolor("#f0efec")
            cell.set_text_props(color=INK, weight="bold")
        cell.set_edgecolor("#e1e0d9")
    fig.tight_layout()
    fig.savefig(FIG / "q3_fig3_comm_sensitivity.png", dpi=300)
    plt.close(fig)


if __name__ == "__main__":
    fig1(); fig2(); fig3()
    print("Q3 figures written to", FIG)
