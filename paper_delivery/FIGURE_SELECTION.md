# 论文图片清单（正文 / 附录 / 转表）

> 正式论文图统一在 `paper_figures/`（13 张，300 dpi、白底、中文标签）。本清单给出
> 「正文必留 / 可放附录或改表」的建议，供论文手根据版面取舍。

## 正文必留

| 图 | 文件 | 作用 |
|---|---|---|
| Q1 安全余量敏感性 | `paper_figures/q1_safety_margin_final.png` | 说明 18 架次在 20% 余量内稳定 |
| Q1 组批/分配结果 | `paper_figures/q1_batch_allocation_final.png` | 15 服务区 B/C 组批与质量分配 |
| Q2 全局运输航迹图 | `paper_figures/q2_transport_routes_final.png` | 26 架次空间路径（A/B/C 分色） |
| Q2 调度甘特图 | `paper_figures/q2_drone_gantt_final.png` | 8 机 26 架次时序 |
| Q2 硬时限裕量图 | `paper_figures/q2_deadline_margin_final.png` | 31 硬时限全部 > 0 |
| Q2 SOC 敏感性图 | `paper_figures/q2_soc_sensitivity_final.png` | 能源安全裕量小 |
| Q3 3D DEM 运输—中继协同图 | `paper_figures/q3_transport_relay_spatial_final.png` | 真实地形 + 航迹 + R01/R02 部署 |
| Q3 联合时序图 | `paper_figures/q3_joint_timeline_final.png` | 中继架次与运输覆盖时序 |
| Q3 三方案通信对照图 | `paper_figures/q3_scheme_comparison_final.png` | 407→0 的改进 |
| Q4 2/3 组空间分区（建议 (a)(b) 组合） | `paper_figures/q4_partition_comparison_final.png` | 分区结构 |
| Q4 资源需求对比 | `paper_figures/q4_resource_comparison_final.png` | 集中式 vs 2/3 组 |

> 若正文篇幅紧，Q3 的 3D 与 2D（`q3_transport_relay_spatial_2d_final.png`）为同数据
> 两种画法，**二选一**，另一张放附录或不放。

## 可放附录 / 改表

| 图/内容 | 处理建议 |
|---|---|
| Q1 目标优先级图（`Q1/figures/q1_fig3_priority_tradeoff.png`） | 差异很小 → 正文一句话带过，完整表放附录（`paper_tables/q1_priority_comparison.csv`） |
| Q2 搜索阶段对比（`Q2/figures/q2_fig3_search_comparison.png`） | 正文简述「局部改进降 makespan 约 8.8%」，对比数据放附录（`paper_tables/q2_search_comparison.csv`） |
| Q3 通信敏感性 PNG（`Q3/figures/q3_fig3_comm_sensitivity.png`） | 改三线表（5 组采样均 0 未覆盖，见 `paper_tables/q3_communication_sensitivity.csv`），不放截图 |
| Q4 工作量均衡图（`Q4/figures/q4_workload_balance.png`） | 视版面决定；若放，须配「缺口优先口径下的均衡特征」说明，不可当作「已均衡优化」 |
| Q2 典型多点架次路径（`paper_figures/q2_multistop_route_final.png`） | 解释「多点配送架次如何飞」的辅助图，可放附录或正文边栏 |

## 图片质量确认（本轮检查结论）

- 13 张 `paper_figures/*.png` 全部存在，DPI 均 ≈300，白底（脚本 `figure.facecolor`/`axes.facecolor` 为白）。
- 新增 3 张空间图已完成：Q2 全局航迹、Q2 典型多点架次、Q3 3D DEM 运输—中继部署（含 2D 备用版）。
- 空间图数据来源全部为正式 CSV/JSON/DEM：航迹来自 `q2_segments.csv`，中继悬停来自
  `q3_relay_schedule.csv`，链路来自 `q3_communication_links.csv`，地形来自经审计的
  `q3_terrain_cache.npz`；三维航迹与权威轨迹接口逐点比对最大偏差 1.979e-09 m。
- 无手填数字、无虚构中继覆盖圆；3D 高度来自真实 DEM 与正式飞行高度（z 轴标注 4× 视觉放大，
  数值为真实高程）。
- 中文字体（微软雅黑/黑体）、单色系地形底图，适合黑白打印；图例遮挡与标签重叠已在生成时
  修正。
