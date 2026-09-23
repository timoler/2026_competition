"""Q3 pipeline entry point: run every stage in order (reproducible).

Stages:
  1. timeline      -> q3_transport_timeline.csv
  2. baseline      -> q3_blackout_intervals.csv, q3_baseline_communication.csv
  3. schedule      -> q3_relay_schedule.csv, q3_communication_links.csv
  4. summary       -> q3_summary.csv
  5. sensitivity   -> q3_sensitivity.csv (slow: recomputes coverage per parameter)
  6. validate      -> q3_validation.json (independent check)
  7. figures       -> Q3/figures/*.png
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import timeline
import baseline
import schedule
import summary
import sensitivity
import validate
import make_figures


def main():
    print("== 1/7 timeline ==")
    timeline.build_timeline(timeline.load_scenario()["model"]["time_step_s"],
                            timeline.RESULTS / "q3_transport_timeline.csv")
    print("== 2/7 baseline ==")
    baseline.detect_blackouts(step_s=1.0)
    baseline.write_csv(baseline.RESULTS / "q3_blackout_intervals.csv",
                       baseline.detect_blackouts(step_s=1.0)[0])
    baseline.write_csv(baseline.RESULTS / "q3_baseline_communication.csv",
                       baseline.build_baseline_table(step_s=5.0))
    print("== 3/7 schedule ==")
    schedule.run_schedule()
    print("== 4/7 summary ==")
    summary.main()
    print("== 5/7 sensitivity ==")
    sensitivity.main()
    print("== 6/7 validate ==")
    validate.main()
    print("== 7/7 figures ==")
    make_figures.fig_spatial()
    make_figures.fig_blackout_timeline()
    make_figures.fig_relay_gantt()
    make_figures.fig_comparison()
    make_figures.fig_sensitivity()
    print("Q3 pipeline complete.")


if __name__ == "__main__":
    main()
