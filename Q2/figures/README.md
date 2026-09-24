# 图表状态

当前正式论文图（由 `code/make_paper_figures.py` 从正式 CSV 生成）：

- `q2_fig1_drone_gantt.png` —— 8 架运输无人机 26 架次调度甘特图
- `q2_fig2_hard_deadline_margin.png` —— 31 个硬时限货箱的剩余裕量（全部 >0）
- `q2_fig3_search_comparison.png` —— 单点/多点构造与局部改进后方案对比
- `q2_fig4_soc_sensitivity.png` —— 最低返航 SOC 对能耗缩放系数的敏感性

`code/make_figures.py` 为早期可选绘图入口，未纳入本次论文图；本次论文图统一由 `code/make_paper_figures.py` 生成。
