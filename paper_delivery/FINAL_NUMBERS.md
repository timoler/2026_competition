# 论文最终正式数字（唯一引用口径）

> 论文手只允许从这里或对应正式结果文件引用数字。所有数字均从当前 `main` 的正式
> CSV/JSON 只读读取，未做任何手工修改或换算。带 ≈ 的为展示用四舍五入，精确值以
> 「精确值」列为准。

## Q1 单点运输

| 指标 | 值（精确） | 来源 |
|---|---|---|
| 架次数 | 18 | `Q1/results/q1_submission_rows.csv` |
| 货箱数 | 80（每箱恰好配送一次） | `Q1/results/q1_batches_default.csv` |
| 总能耗 | 59.130796487 kWh | 同上（架次能耗求和） |
| 累计作业时间 | 32776.092676944 s | 同上（作业时间 operation_s 求和，含准备+飞行+交接） |
| 飞行往返时间（提交字段） | 19288.092676944 s | `q1_submission_rows.csv` 往返时间求和（纯飞行，不含准备/交接） |
| 最低返航 SOC | 23.0888%（≈23.09%） | `q1_submission_rows.csv` 返航SOC最小值 |
| 验证状态 | PASS（7 项检查） | `Q1/results/q1_verification.json` |
| 架次数下界 | 18（按各服务区质量/体积/安全载荷推得） | `Q1/README.md:69` |

安全余量敏感性（默认优先级「时间→架次→能耗」，`q1_model_comparison.csv`）：

| 返航安全余量 | 架次数 | 总能耗 (kWh) | 累计作业时间 (s) | 可行性 |
|---|---|---|---|---|
| 10% | 18 | 59.130796 | 32776.093 | 可行 |
| 15% | 18 | 59.130796 | 32776.093 | 可行 |
| 20% | 18 | 59.130796 | 32776.093 | 可行 |
| 25% | 19 | 61.164203 | 34559.741 | 可行 |
| 30% | 20 | 67.227086 | 36586.269 | 可行 |

目标优先级对照（返航安全余量 20%，`q1_model_comparison.csv`）：

| 优先级 | 架次 | 总能耗 (kWh) | 累计作业时间 (s) |
|---|---|---|---|
| 时间→架次→能耗 | 18 | 59.130796 | 32776.093 |
| 架次→能耗→时间 | 18 | 59.130796 | 32776.093 |
| 架次→时间→能耗 | 18 | 59.130796 | 32776.093 |
| 能耗→架次→时间 | 19 | 59.033414 | 34440.065 |

## Q2 多点运输调度

| 指标 | 值（精确） | 来源 |
|---|---|---|
| 架次数 | 26 | `Q2/results/q2_trips.csv` |
| 航段数 | 55 | `Q2/results/q2_segments.csv` |
| 总能耗 | 71.440968978 kWh | `q2_trips.csv` |
| 完工时间 makespan | 6973.648577 s | `q2_trips.csv` return_s 最大值 |
| 最低返航 SOC | 20.9489%（≈20.95%） | `q2_trips.csv` return_soc 最小值 |
| 硬时限货箱 | 31 个，全部满足 | `q2_deliveries.csv` |
| 验证状态 | PASS_UNDER_DECLARED_SCENARIO（12 项检查） | `Q2/results/q2_validation.json` |

搜索过程对照（`q2_search_history.csv` / `q2_improvement.csv`）：

| 阶段 | 架次 | makespan (s) | 能耗 (kWh) |
|---|---|---|---|
| 单点构造 | 26 | 7646.002065 | 71.663460 |
| 多点构造 | 23 | 8136.744214 | 76.918310 |
| 局部改进后（正式） | 26 | 6973.648577 | 71.440968978 |

SOC 敏感性（`q2_soc_sensitivity.csv`）：

| 能耗统一缩放系数 | 最低返航 SOC | 可行性 |
|---|---|---|
| 0.98 | 22.53% | 可行 |
| 1.00 | 20.95% | 可行 |
| 1.02 | 19.37% | 不可行（跌破 20% 下限） |
| 1.05 | 17.00% | 不可行 |

## Q3 通信盲区与中继调度

| 指标 | 值（精确） | 来源 |
|---|---|---|
| 物理中继 | 2（R01、R02） | `Q3/results/q3_relay_schedule.csv` |
| 中继架次 | 3（R01×1 + R02×2） | 同上 |
| 未覆盖样本 | 0 | `Q3/results/q3_final_validation.json` |
| 覆盖率 | 100%（采样口径） | 同上 |
| 中继能耗 | 4.536233593 kWh | `q3_relay_schedule.csv` 求和 |
| 联合完工时间 | 8506.220613995 s | `q3_relay_schedule.csv` return_s 最大值 |
| 严格可行性 | strict_feasible=True | `q3_final_validation.json` |
| 验证状态 | PASS（57 项检查） | `q3_final_validation.json` |
| R02 周转余量 | +0.450176 s | S03.prep_start − (S02.return + 300 s 周转) |

三方案对照（`e0_baseline.json` / `comparison_2relay_static/q3_feasibility_2relay.json` / `q3_final_validation.json`）：

| 方案 | 未覆盖样本 | 覆盖率 | 状态 |
|---|---|---|---|
| 原始方案 | 407 | 98.88% | FAIL |
| 静态两中继 | 407 | 98.88% | FAIL |
| 联合调度两中继 | 0 | 100% | PASS |

通信采样敏感性（`q3_los_resolution_sensitivity.csv` + `e4_temporal_sensitivity.csv`）：

| 时间步长 | LOS 采样间距 | 样本数 | 未覆盖样本 | 状态 |
|---|---|---|---|---|
| 1.0 s | 15 m | 36351 | 0 | PASS |
| 1.0 s | 10 m | 36351 | 0 | PASS |
| 1.0 s | 5 m | 36351 | 0 | PASS |
| 0.5 s | 10 m | 72690 | 0 | PASS |
| 0.25 s | 10 m | 145366 | 0 | PASS |

## Q4 分区与资源配置

| 方案 | 运输无人机 | 电池 | 中继 | 组件 | 库存缺口 |
|---|---|---|---|---|---|
| Q3 集中式（基线） | 8 | 14 | 2 | 3 | 0 |
| 2 组分区 | 9 | 15 | 2 | 3 | 2 |
| 3 组分区 | 10 | 15 | 3 | 4 | 4 |

来源：`Q4/results/q4_best_2groups.json`、`q4_best_3groups.json`、`q4_resource_gap.csv`。

枚举规模：

| 组数 | 实际枚举候选数 | CSV 保存数量 |
|---|---|---|
| 2 组 | 2047 | 2047（全量） |
| 3 组 | 86526 | 1000（排序前 1000） |

来源：`q4_all_partitions_2groups.csv`（行数）、`q4_all_partitions_3groups_summary.json`。

独立验证：`q4_validation.json`，status=PASS，27 项检查全部通过。

## 全局约定

- 所有能耗、SOC、时刻均为正式结果文件原始值；本文件未做四舍五入改写。
- 能耗模型（水平能耗 = 电池可用能量×距离/等效航程；爬升能耗 = 势能/效率）为本队
  **补充建模假设**，非题目唯一指定，详见 `Q1_Q2_energy_assumption_audit.md`。
- 涉及表述边界的措辞，以 `WORDING_GUARDRAILS.md` 为准。
