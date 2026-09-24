# 论文图统一目录

**论文正文/附录用图只认这一处。** 所有 `*_final.png` 均由 `Qx/code/` 下的脚本从该问正式
CSV/JSON 只读生成，300 dpi、白底、中文标签；不手工改图，不做后处理。

各问 `Qx/figures/` 下另有早期版本与历史快照，**不是论文图**，仅供追溯，见各问 figures README。

## 正文图

| 文件 | 内容 | 生成脚本 | 数据来源 |
|---|---|---|---|
| `q1_safety_margin_final.png` | 返航安全余量 10–30% 下的架次数与总能耗 | `Q1/code/make_paper_figures.py::fig1` | `Q1/results/q1_model_comparison.csv` |
| `q1_batch_allocation_final.png` | 15 服务区 80 箱的 B/C 组批与质量分配 | `Q1/code/make_paper_figures.py::fig2` | `Q1/results/q1_batches_default.csv` |
| `q2_drone_gantt_final.png` | 8 架运输无人机 26 架次调度甘特图 | `Q2/code/make_paper_figures.py::fig1` | `Q2/results/q2_trips.csv` |
| `q2_deadline_margin_final.png` | 硬时限货箱剩余裕量（升序，全部 > 0） | `Q2/code/make_paper_figures.py::fig2` | `Q2/results/q2_deliveries.csv` |
| `q2_soc_sensitivity_final.png` | 最低返航 SOC 对能耗缩放系数的敏感性 | `Q2/code/make_paper_figures.py::fig4` | `Q2/results/q2_trips.csv` |
| `q2_transport_routes_final.png` | Q2 全局运输航迹空间分布（26 架次，A/B/C 分色） | `Q2/code/make_spatial_figures.py::fig5` | `q2_trips/q2_segments/q2_nodes.csv` + 30 m DEM |
| `q2_multistop_route_final.png` | 典型多点配送架次路径（自动选中 T022，B 型 U05，O01→S005→S008→O01） | `Q2/code/make_spatial_figures.py::fig6` | `q2_segments/q2_deliveries/q2_nodes.csv` + 30 m DEM |
| `q3_joint_timeline_final.png` | 中继架次与运输覆盖联合时序 | `Q3/code/make_paper_figures.py::fig1` | `q3_relay_schedule / q3_transport_schedule / q3_communication_links.csv` |
| `q3_scheme_comparison_final.png` | 原始 / 静态两中继 / 联合调度两中继 三方案对照 | `Q3/code/make_paper_figures.py::fig2` | `e0_baseline.json`、`comparison_2relay_static/`、`q3_final_validation.json` |
| `q4_partition_comparison_final.png` | Q4 两种分区方案对照 | `Q4/code/make_figures.py` | `Q4/results/` |
| `q4_resource_comparison_final.png` | Q4 分区资源配置对照 | `Q4/code/make_figures.py` | `Q4/results/` |

## 三/四问协同空间图（二选一入正文，另一张作附录）

同一脚本的两种画法，**内容同源、只画法不同**，由论文手择优选用；不要两张同时进正文。

| 文件 | 内容 | 生成脚本 |
|---|---|---|
| `q3_transport_relay_spatial_final.png` | 真实 30 m DEM 三维地形 + 26 架次三维航迹 + R01/R02 中继悬停部署 + G01 回传与 21 条接入链路（z 轴标注 4× 视觉放大，坐标数值为真实高程） | `Q3/code/make_spatial_figure.py` |
| `q3_transport_relay_spatial_2d_final.png` | 同数据的平面画法 | `Q3/code/make_spatial_figure.py` |

三维航迹由 `q2_segments.csv` 的爬升—巡航—下降分段几何重建，已与权威轨迹接口
`transport_core.Trajectory` 逐架次逐时刻比对，最大偏差 1.979e-09 m；中继坐标取
`q3_relay_schedule.csv` 的 `hover_x_m/hover_y_m/hover_altitude_m`，链路关系全部来自
`q3_communication_links.csv` 的实际服务时间窗，未虚构任何高度、位置、覆盖圆或通信关系。

## 表格

见 [`../paper_tables/`](../paper_tables/)：`q1_priority_comparison.csv`、`q2_search_comparison.csv`、
`q3_communication_sensitivity.csv`，分别由对应 `Qx/code/make_paper_figures.py` 的 `table*()` 生成。

## 重新生成

```bash
python Q1/code/make_paper_figures.py
python Q2/code/make_paper_figures.py
python Q2/code/make_spatial_figures.py
python Q3/code/make_paper_figures.py
python Q3/code/make_spatial_figure.py
python Q4/code/make_figures.py
```

均为只读生成：不写入、不修改任何正式 CSV/JSON，不重新优化。
