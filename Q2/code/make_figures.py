"""Descriptive schedule figures, not statistical evidence of optimality."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from transport_core import DEFAULT_RESULTS


def main():
    folder = DEFAULT_RESULTS.parent / "figures"
    folder.mkdir(exist_ok=True)
    with (DEFAULT_RESULTS / "q2_trips.csv").open(encoding="utf-8-sig") as f:
        trips = list(csv.DictReader(f))
    with (DEFAULT_RESULTS / "q2_deliveries.csv").open(encoding="utf-8-sig") as f:
        deliveries = list(csv.DictReader(f))
    assert len({d["box_id"] for d in deliveries}) == 80
    profile = {
        "trips": len(trips), "boxes": len(deliveries),
        "trips_by_type": {k: sum(t["type_id"] == k for t in trips) for k in ("A","B","C")},
        "missing_required_fields": sum(not t[key] for t in trips for key in
                                       ("trip_id","drone_id","preparation_start_s","takeoff_s","return_s")),
        "contract": "Show resource occupancy and individual delivery timeliness; not global optimality.",
        "backend": "matplotlib", "units": "minutes; relative to t=0",
        "source": ["q2_trips.csv", "q2_deliveries.csv"],
        "output": "q2_schedule.png (180dpi) and vector PDF, 11x7 inches",
        "note": "No inferred confidence intervals; 80 individual boxes, grouped trips."
    }
    (folder / "q2_figure_profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "pdf.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False})
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(11, 7), constrained_layout=True,
                                  gridspec_kw={"height_ratios":[1.3,1]})
    colors = {"A":"#0072B2", "B":"#009E73", "C":"#D55E00"}
    entities = sorted({t["drone_id"] for t in trips})
    for t in trips:
        y = entities.index(t["drone_id"])
        start, takeoff, end = (float(t[k])/60 for k in ("preparation_start_s","takeoff_s","return_s"))
        ax.barh(y, end-start, left=start, height=.58, color=colors[t["type_id"]], alpha=.85)
        ax.barh(y, takeoff-start, left=start, height=.58, color="#CACACA", hatch="//", edgecolor="#777777")
        ax.text((takeoff+end)/2,y,t["trip_id"],ha="center",va="center",fontsize=7,color="white")
    ax.set(yticks=range(len(entities)), yticklabels=entities, xlabel="Time since start (min)",
           title="Transport occupancy | provisional energy scenario")
    ax.legend(handles=[Patch(color=c,label=f"Type {k}") for k,c in colors.items()]
              +[Patch(facecolor="#CACACA",hatch="//",label="Preparation + loading")],
              ncol=4,loc="upper right",fontsize=8)
    ax.set_xlim(0, max(float(t["return_s"])/60 for t in trips)*1.02)
    ax.grid(axis="x",alpha=.2)
    for hard, marker, label, color in [(True,"o","Hard-deadline boxes","#0072B2"),
                                       (False,"x","Other boxes","#D55E00")]:
        subset = [d for d in deliveries if bool(d["hard_due_s"]) == hard]
        x = [float(d["desired_due_s"])/60 for d in subset]
        y = [float(d["delivery_complete_s"])/60 for d in subset]
        bx.scatter(x,y,marker=marker,label=label,color=color,s=24,alpha=.65)
    limit = max(float(d["desired_due_s"])/60 for d in deliveries)*1.05
    bx.plot([0,limit],[0,limit],color="#666666",linestyle="--",linewidth=1,label="Delivery = desired time")
    bx.set(xlabel="Desired delivery time (min)",ylabel="Actual delivery completion (min)",
           xlim=(0,limit),ylim=(0,limit))
    bx.legend(fontsize=8,loc="upper left")
    bx.grid(alpha=.2)
    for ext in ("png","pdf"):
        fig.savefig(folder / f"q2_schedule.{ext}", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
