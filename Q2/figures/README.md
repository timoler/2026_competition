# Q2 图目录（非论文图）

Q2 的**论文图与表格统一在** [`paper_figures/`](../../paper_figures/) 与
[`paper_tables/`](../../paper_tables/) 生成，脚本为 `code/make_paper_figures.py`（时序/敏感性图）
与 `code/make_spatial_figures.py`（空间航迹图），均为只读生成。
本目录下的 PNG 是早期版本或附录图，**不是当前论文图**，仅留作追溯：

- `q2_fig1_drone_gantt.png` —— 早期版本，已被 `paper_figures/q2_drone_gantt_final.png` 取代
- `q2_fig2_hard_deadline_margin.png` —— 早期版本，已被 `paper_figures/q2_deadline_margin_final.png` 取代
- `q2_fig3_search_comparison.png` —— 搜索方案对比图；正文以表
  `paper_tables/q2_search_comparison.csv` 呈现，本图可作附录
- `q2_fig4_soc_sensitivity.png` —— 早期版本，已被 `paper_figures/q2_soc_sensitivity_final.png` 取代

`code/make_figures.py` 为早期可选绘图入口，未纳入论文图。

图表索引与重新生成方式见 [`paper_figures/README.md`](../../paper_figures/README.md)。
