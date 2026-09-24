"""Generate Q3 final paper figures + table from official CSVs/JSONs (read-only)."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

REPO = Path(__file__).resolve().parents[2]
R = REPO / "Q3" / "results"
PFIG = REPO / "paper_figures"
PTAB = REPO / "paper_tables"
PFIG.mkdir(parents=True, exist_ok=True)
PTAB.mkdir(parents=True, exist_ok=True)

BLUE, ORANGE, AQUA, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"
GRAY, INK, MUTED, GRID, LIGHT = "#898781", "#0b0b0b", "#898781", "#e1e0d9", "#cde2fb"

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
# Figure 1: joint timeline
# ---------------------------------------------------------------------------
def fig1():
    relay = read_csv("q3_relay_schedule.csv")
    transport = read_csv("q3_transport_schedule.csv")
    links = read_csv("q3_communication_links.csv")

    prov = defaultdict(set)
    for r in links:
        p = r["provider"]
        if p != "G01":
            prov[r["trip_id"]].add(p)

    def trip_color(tid):
        s = prov.get(tid, set())
        h1, h2 = bool(s & {"S01"}), bool(s & {"S02", "S03"})
        if h1 and h2:
            return VIOLET
        if h1:
            return BLUE
        if h2:
            return ORANGE
        return GRAY

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.6), sharex=True,
                                   gridspec_kw={"height_ratios": [1, 2.6]})

    for i, r in enumerate(relay):
        y = len(relay) - 1 - i
        prep, ss, se, ret = (float(r["prep_start_s"]), float(r["service_start_s"]),
                             float(r["service_end_s"]), float(r["return_s"]))
        color = BLUE if r["relay_id"] == "R01" else ORANGE
        ax1.barh(y, ss - prep, left=prep, height=0.5, color=LIGHT, edgecolor="white", linewidth=0.3)
        ax1.barh(y, se - ss, left=ss, height=0.5, color=color, edgecolor="white", linewidth=0.3)
        ax1.barh(y, ret - se, left=se, height=0.5, color=LIGHT, edgecolor="white", linewidth=0.3)
    ax1.set_yticks([len(relay) - 1 - i for i in range(len(relay))])
    ax1.set_yticklabels([f"{r['sortie_id']}  {r['relay_id']}" for r in relay], fontsize=9)
    ax1.set_ylabel("中继架次", fontsize=9)
    ax1.set_ylim(-0.5, len(relay) - 0.5)
    ax1.legend(handles=[mpatches.Patch(color=LIGHT, label="准备/转场"),
                        mpatches.Patch(color=BLUE, label="R01 服务"),
                        mpatches.Patch(color=ORANGE, label="R02 服务")],
               loc="lower left", frameon=False, fontsize=8, ncol=3)

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
    ax2.set_xlim(0, max(float(r["return_s"]) for r in relay) * 1.03)
    ax2.legend(handles=[mpatches.Patch(color=GRAY, label="直连 G01"),
                        mpatches.Patch(color=BLUE, label="R01 保障"),
                        mpatches.Patch(color=ORANGE, label="R02 保障"),
                        mpatches.Patch(color=VIOLET, label="R01+R02 保障")],
               loc="lower right", frameon=False, fontsize=8, ncol=2)
    fig.tight_layout(h_pad=0.8)
    fig.savefig(PFIG / "q3_joint_timeline_final.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 2: three-scheme comparison
# ---------------------------------------------------------------------------
def fig2():
    e0 = json.loads((R / "e0_baseline.json").read_text(encoding="utf-8"))
    static = json.loads((R / "comparison_2relay_static" / "q3_feasibility_2relay.json")
                        .read_text(encoding="utf-8"))
    cur = json.loads((R / "q3_final_validation.json").read_text(encoding="utf-8"))
    names = ["原始方案", "静态两中继", "联合调度两中继"]
    unc = [e0["uncovered_samples"], static["uncovered_samples"], cur["uncovered_samples"]]
    cov = [e0["coverage"] * 100, static["coverage"] * 100, cur["coverage"] * 100]

    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.6))
    x = range(3)
    cols = [GRAY, GRAY, AQUA]
    axes[0].bar(x, unc, color=cols, width=0.55, edgecolor="white")
    for i, v in enumerate(unc):
        axes[0].text(i, v + 8, str(v), ha="center", fontsize=11, color=INK)
    axes[0].set_xticks(list(x)); axes[0].set_xticklabels(names, rotation=15, ha="right", fontsize=9)
    axes[0].set_ylabel("未覆盖通信样本数")
    axes[0].set_ylim(0, max(unc) * 1.15)

    axes[1].bar(x, cov, color=cols, width=0.55, edgecolor="white")
    for i, v in enumerate(cov):
        axes[1].text(i, v + 0.7, f"{v:.2f}%", ha="center", fontsize=9, color=INK)
    axes[1].set_xticks(list(x)); axes[1].set_xticklabels(names, rotation=15, ha="right", fontsize=9)
    axes[1].set_ylabel("覆盖率 (%)")
    axes[1].set_ylim(0, 101)
    fig.tight_layout(w_pad=1.6)
    fig.savefig(PFIG / "q3_scheme_comparison_final.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Table: communication sensitivity
# ---------------------------------------------------------------------------
def table():
    los = read_csv("q3_los_resolution_sensitivity.csv")
    tmp = read_csv("e4_temporal_sensitivity.csv")
    rows = []
    for r in los:
        rows.append(dict(时间步长_s=float(r["time_step_s"]), LOS间距_m=float(r["los_spacing_m"]),
                         样本数=int(r["total_samples"]), 未覆盖样本数=int(r["uncovered_samples"]),
                         覆盖率_pct=f"{float(r['coverage'])*100:.4f}%", 状态=r["status"]))
    for r in tmp:
        rows.append(dict(时间步长_s=float(r["time_step_s"]), LOS间距_m=float(r["los_spacing_m"]),
                         样本数=int(r["total_samples"]), 未覆盖样本数=int(r["uncovered_samples"]),
                         覆盖率_pct=f"{float(r['coverage'])*100:.4f}%", 状态=r["status"]))
    rows = [{"时间步长 (s)": r["时间步长_s"], "LOS 间距 (m)": r["LOS间距_m"],
             "样本数": r["样本数"], "未覆盖样本数": r["未覆盖样本数"],
             "覆盖率 (%)": r["覆盖率_pct"], "状态": r["状态"]} for r in rows]
    with (PTAB / "q3_communication_sensitivity.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    fig1(); fig2(); table()
    print("Q3 final figures + table written")
