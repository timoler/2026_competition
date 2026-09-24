# Q3 图目录（非论文图）

Q3 的**论文图与表格统一在** [`paper_figures/`](../../paper_figures/) 与
[`paper_tables/`](../../paper_tables/) 生成，脚本为 `code/make_paper_figures.py`（时序/方案对照图）
与 `code/make_spatial_figure.py`（运输—中继协同空间图），均为只读生成。
本目录下的 PNG 是早期版本，**不是当前论文图**，仅留作追溯：

- `q3_fig1_joint_timeline.png` —— 早期版本，已被 `paper_figures/q3_joint_timeline_final.png` 取代
- `q3_fig2_scheme_comparison.png` —— 早期版本，已被 `paper_figures/q3_scheme_comparison_final.png` 取代
- `q3_fig3_comm_sensitivity.png` —— 早期版本；正文以表
  `paper_tables/q3_communication_sensitivity.csv` 呈现

`history_pre_audit/` 中的基准历史图是修复前快照（含 `q3_spatial_map.png`，其 `imshow`
范围换算有误），**不得作为当前正式证据**。当前可引用表格见[自动报告](../results/q3_current_report.md)。

图表索引与重新生成方式见 [`paper_figures/README.md`](../../paper_figures/README.md)。
