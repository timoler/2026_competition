# 论文交付索引（论文手唯一入口）

> 论文手从本文件开始读。所有数字、表、图、验证状态均指向 `main` 的正式文件；本文件不复制数字，
> 只给"问题 → 在哪里找什么"的索引。数字的**唯一引用口径**是 [`FINAL_NUMBERS.md`](FINAL_NUMBERS.md)
> 及对应正式 CSV/JSON，措辞边界见 [`WORDING_GUARDRAILS.md`](WORDING_GUARDRAILS.md)。

## 目录

- [数据特点及建模影响](DATA_FEATURES.md) —— 论文"数据分析与预处理"章节的素材
- [模型评价](MODEL_EVALUATION.md) —— 论文"模型评价"章节素材
- [模型检验总表](MODEL_VALIDATION_SUMMARY.md) —— 论文"检验与评价"表格
- [最终数字](FINAL_NUMBERS.md) —— 唯一引用口径
- [图片清单](FIGURE_SELECTION.md) —— 正文/附录取舍建议
- [措辞红线](WORDING_GUARDRAILS.md) —— 禁用/推荐表述

## 四问总索引

| 问题 | 正式结果（关键数字） | 建议正文表 | 建议正文图 | 详细数据 | 验证记录 | 适用边界 |
|---|---|---|---|---|---|---|
| Q1 单点运输 | 18 架次（B9/C9）、80 箱、总能耗 59.130796 kWh、累计作业 32776.09 s | `paper_tables/q1_max_payload.csv`（15×3 安全载荷）、`q1_batch_detail.csv`（18 架次逐箱）、`q1_priority_comparison.csv`（4 优先级）、`q1_sensitivity.csv`（余量 10–30%） | `paper_figures/q1_safety_margin_final.png`（余量敏感性）、`q1_batch_allocation_final.png`（组批） | `Q1/results/q1_batches_default.csv`、`q1_max_payload_sensitivity.csv`、`q1_model_comparison.csv` | `Q1/results/q1_verification.json`（PASS，7 项） | 水平/爬升能耗为本文补充假设；18 架次为下界、非唯一最优 |
| Q2 多点调度 | 26 架次、55 航段、总能耗 71.440969 kWh、makespan 6973.65 s、最低 SOC 20.95%、31 硬时限全满足 | `paper_tables/q2_search_comparison.csv`（搜索阶段对照） | `paper_figures/q2_transport_routes_final.png`、`q2_drone_gantt_final.png`、`q2_deadline_margin_final.png`、`q2_soc_sensitivity_final.png`（+附录 `q2_multistop_route_final.png`） | `Q2/results/q2_trips.csv`、`q2_deliveries.csv`、`q2_battery_schedule.csv`、`q2_segments.csv` | `Q2/results/q2_validation.json`（PASS_UNDER_DECLARED_SCENARIO，12 项） | 启发式较优可行解，非全局最优；最低 SOC 对能耗敏感（上浮约 2% 跌破 20%） |
| Q3 通信中继 | 2 物理中继、3 架次、0 未覆盖、覆盖率 100%、中继能耗 4.536234 kWh、联合完工 8506.22 s、R01 返航 SOC 22.36% | `paper_tables/q3_communication_sensitivity.csv`（5 组采样） | `paper_figures/q3_transport_relay_spatial_final.png`（3D/2D 二选一）、`q3_joint_timeline_final.png`、`q3_scheme_comparison_final.png` | `Q3/results/q3_relay_schedule.csv`、`q3_communication_links.csv`、`q3_transport_schedule.csv` | `Q3/results/q3_final_validation.json`（PASS，57 项，strict_feasible=True） | 离散采样口径，非连续时间严格证明；R02 周转余量约 0.45 s |
| Q4 分区资源 | 2 组 gap=2（9 机/15 电池/2 中继/3 组件）、3 组 gap=4（10/15/3/4） | （正文表 7/8/9 可从 `Q4/results/q4_best_2groups.json`、`q4_best_3groups.json`、`q4_resource_gap.csv` 取） | `paper_figures/q4_partition_comparison_final.png`、`q4_resource_comparison_final.png` | `Q4/results/q4_service_blocks.csv`、`q4_group_resources_2groups.csv`、`q4_group_resources_3groups.csv`、`q4_resource_comparison.csv` | `Q4/results/q4_validation.json`（PASS，27 项） | 基于 Q3 固定调度；中继按"可跨组重复配置"口径；均衡为末位辅助指标（不算 CV） |

## 图/表数据来源与生成脚本

| 产物 | 来源数据 | 生成脚本 |
|---|---|---|
| `paper_figures/*.png`（Q1） | `Q1/results/q1_model_comparison.csv`、`q1_batches_default.csv` | `Q1/code/make_paper_figures.py` |
| `paper_figures/*.png`（Q2） | `q2_trips.csv`、`q2_deliveries.csv`、`q2_segments.csv`、`q2_nodes.csv` + 30 m DEM | `Q2/code/make_paper_figures.py`、`make_spatial_figures.py` |
| `paper_figures/*.png`（Q3） | `q3_relay_schedule.csv`、`q3_transport_schedule.csv`、`q3_communication_links.csv` | `Q3/code/make_paper_figures.py`、`make_spatial_figure.py` |
| `paper_figures/*.png`（Q4） | `Q4/results/` | `Q4/code/make_figures.py` |
| `paper_tables/q1_*.csv`（4 张） | `q1_max_payload_sensitivity.csv`、`q1_batches_default.csv`、`q1_model_comparison.csv` | `Q1/code/make_paper_figures.py`（table1–4） |
| `paper_tables/q2_search_comparison.csv` | `q2_search_history.csv`/`q2_improvement.csv` | `Q2/code/make_paper_figures.py` |
| `paper_tables/q3_communication_sensitivity.csv` | `q3_los_resolution_sensitivity.csv`+`e4_temporal_sensitivity.csv` | `Q3/code/make_paper_figures.py` |

所有图/表均由脚本从正式 CSV/JSON **只读生成**，不手填数字；`paper_tables/*.csv` 为论文展示精度，
原始精度见对应 `Qx/results/` 文件。

## 哪些是最终版、哪些是历史对照

- **最终版**：`paper_figures/*_final.png`、`paper_tables/*.csv`、各 `Qx/results/` 中无
  `history`/`archive`/`pre_audit` 标记的文件。
- **历史对照（不得写入正文结论）**：`Q3/figures/history_pre_audit/`、`Q3/results/history_pre_audit/`、
  `Q3/results/archive_3relay/`、`Q3/results/comparison_2relay_static/`、`Q1/figures/`、`Q2/figures/`、
  `Q3/figures/`（早期版本）、`Q4/figures/`（见各问 figures README）。

## ⚠️ 给论文手的三个必须核对项（本轮已发现）

1. **Q3 数字已更新**：桌面论文 docx 里 Q3 仍是审计前的旧数——联合完工 8440.2 s、中继能耗
   4.702102 kWh、R01 返航 SOC 20.44%。审计修正后的正式值为 **8506.22 s、4.536234 kWh、22.36%**，
   以 [`FINAL_NUMBERS.md`](FINAL_NUMBERS.md) 和 `Q3/results/q3_relay_schedule.csv` 为准，论文正文
   与摘要必须同步更新。
2. **Q1 表 2 累计作业时间**：docx 里 10/15/20% 档写成 32776.52 s，应为 **32776.09 s**。
3. **Q1 组批图图例**：`q1_batch_allocation_final.png` 左图纵轴是"货箱数"，图例已从"B/C 型架次"
   改为"B/C 型承运货箱数"；正文"堆叠柱给出……架次数"应改为"承运货箱数"。组批**明细**须配
   `paper_tables/q1_batch_detail.csv`，仅靠该图查不到 18 个架次分别装哪些箱。

## 仍须论文手自行判断的事项

- 能耗补充假设（水平/爬升）是否接受为本队口径——影响 Q1/Q2 全部能耗与 SOC 数值。
- Q3 三维/二维空间图二选一入正文，另一张放附录。
- Q4 中继"可跨组重复配置"口径 vs 严格绑定口径（后者见 `Q4/results/strict_relay_binding_sensitivity.json`）如何向评审交代。
