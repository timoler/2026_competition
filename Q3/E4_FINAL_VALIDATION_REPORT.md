# E4 两架中继候选方案——最终严格验收报告

## 总判定：overall_pass = true

> E4 找到原题两架中继资源约束下的严格可行联合调度方案。

独立验证器 `validate_two_relay_experiment.py`（与优化器完全解耦，不读 coverage matrix / 缓存 LOS / 预计算标记，从头重建轨迹）给出：`overall_pass = true`。

## 验收检查表

| 检查项 | 结果 | 关键数值 |
|---|---|---|
| 运输调度（26 架次完整） | ✅ PASS | T011 +2320s；T015 +1224s 且 U07→U08 |
| 货箱 deadline | ✅ PASS | overdue_boxes = 0（T011 6897<7200，T015 7694<10800） |
| 运输 UAV 冲突 | ✅ PASS | 0 冲突 |
| 共享电池冲突 | ✅ PASS | 0 冲突（BAT-C-01/C-03 充电后复用） |
| 电池充电 | ✅ PASS | 充电完成后才复用 |
| 中继数量 | ✅ PASS | physical_relay_count = 2（R01/R02） |
| 中继时序 | ✅ PASS | R02 南→返O01(5145.8)→周转→西(6478.3 到达，早于盲区 6494.75) |
| 中继组件 | ✅ PASS | 3 组件 ≤ 6 |
| R01 energy / SOC | ✅ PASS | 2.545846 kWh / 20.4423%（下限 20%） |
| R02 南 energy / SOC | ✅ PASS | 1.485975 kWh / 53.5633% |
| R02 西 energy / SOC | ✅ PASS | 0.670401 kWh / 79.0500% |
| 1s / 10m 通信 | ✅ PASS | uncovered_samples = 0 |
| 15m LOS | ✅ PASS | uncovered = 0 |
| 10m LOS | ✅ PASS | uncovered = 0 |
| 5m LOS | ✅ PASS | uncovered = 0 |
| 0.5s 时间边界 | ✅ PASS | 0/890 未覆盖 |
| 0.25s 时间边界 | ✅ PASS | 0/1800 未覆盖 |
| **overall** | ✅ **PASS** | — |

## 关键指标（从验证后 schedule 重算）

- uncovered_samples = **0**，coverage = **100.000000%**
- 原 Q2 makespan = 6973.649 s
- 新 transport makespan = **8197.649 s**
- joint makespan = **8440.2 s**（R01 返航）
- transport total energy = 71.440969 kWh（不变）
- relay total energy = **4.702222 kWh**
- relay physical UAV = 2，relay sortie = 3，relay component = 3

## 方案概要

1. **T011 后移 +2320 s**：S004 低空盲区从 [4175,4582] 挪到 [6490,6902]（任务末期安静窗口）。
2. **T015 移 U08、后移 +1224 s**：腾出 U07 给 T011；T015 新 prep 6518.453 ≥ T012 返航 6517.499。
3. **R02 动态换位**：南侧需求 4751 s 结束 → 返 O01（5145.8）→ 周转 → 西侧到达 6478.3，早于盲区 6494.75，用第 2 架次覆盖 S004 盲区。

## 最脆弱约束（须在论文中如实说明）

**R01 能量**：2.545846 kWh，返航 SOC 20.4423%，仅高于 20% 下限 **0.44 个百分点**。
任何能耗口径的细微变化（如爬升效率、巡航功率、重力常数取整）都可能使 R01 越界。
这不是"方案错误"，但属于**零安全裕量**的临界可行，论文必须标注。

## 输出文件

- `Q3/code/validate_two_relay_experiment.py`
- `Q3/results/e4_transport_validation.json`
- `Q3/results/e4_relay_validation.json`
- `Q3/results/e4_communication_validation.json`
- `Q3/results/e4_blackout_samples.csv`（空表，0 中断）
- `Q3/results/e4_blackout_intervals.csv`（空表）
- `Q3/results/e4_los_sensitivity.csv`
- `Q3/results/e4_temporal_sensitivity.csv`
- `Q3/results/e4_final_validation.json`
- `Q3/E4_FINAL_VALIDATION_REPORT.md`

未修改 Q2/results/*、Q3/results/q3_final_*、Q4/results/*；未 commit / push。
