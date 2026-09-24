# Q3 结果文件角色说明（论文引用须知）

> 本目录同时包含「当前正式结果」与「历史/对照」文件，请勿混淆。以下按角色划分。

## 当前正式结果（论文引用请用这些）

| 文件 | 内容 |
|---|---|
| `q3_current_report.md` | 本次自动报告（总状态 PASS） |
| `q3_final_validation.json` / `q3_validation.json` | 57 项检查全 PASS，strict_feasible=True |
| `e4_final_validation.json` | 完整验证 + 输入 SHA-256 + 逐阶段能源 |
| `e4_relay_validation.json` / `e4_transport_validation.json` / `e4_communication_validation.json` | 中继/运输/通信分项验证 |
| `q3_relay_schedule.csv` / `q3_final_schedule.csv` | 三架次中继表（PASS） |
| `q3_communication_links.csv` | 逐样本通信归属（provider） |
| `q3_los_resolution_sensitivity.csv` / `e4_los_sensitivity.csv` / `e4_temporal_sensitivity.csv` | LOS 5/10/15 m 与 0.5/0.25 s 敏感性 |
| `q3_transport_schedule.csv` / `q3_transport_timeline.csv` | 运输调度与时序 |
| `q3_official_plan.json` | 冻结中继决策（含 S02 前移 45 s） |

## 对照基线（用于三方案对比，不是最终方案）

| 文件 | 内容 |
|---|---|
| `e0_baseline.json` | 原始方案基线：407 uncovered（FAIL） |
| `comparison_2relay_static/` | 静态两中继：407 uncovered（FAIL） |
| `archive_3relay/` | 三架增配：仅作增配对照，非原题方案 |

## 历史/废弃（NOT FOR PAPER，仅追溯）

| 文件 | 说明 |
|---|---|
| `e4_best.json` | 旧 E4 实验候选：旧能量（R01 2.5458 kWh 等）与旧 R02 西窗 [6490.4, 6906.4]，已被当前正式方案取代 |
| `history_pre_audit/` | 修复前快照（旧 schedule / 旧 summary / 旧 temporal） |
| `two_relay_failure_*` | 历史失败分析（407 样本根因） |
| `Q3/figures/history_pre_audit/*.png` | 修复前旧图 |
| `Q3/E4_E5_TWO_RELAY_REPORT.md`、`Q3/E4_FINAL_VALIDATION_REPORT.md`、`Q3/TWO_RELAY_EXPERIMENT_REPORT.md` | 历史实验报告（含旧 PASS/旧数值） |
