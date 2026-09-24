# Q3：固定两架中继方案的真实验证

**2026-09-24 本次总状态：PASS。** 固定两架物理中继 R01/R02、三个架次（R01×1、R02×2）、三组能源组件。悬停点不变；S02 服务窗口前移 45 s 以修复 R02 周转与 T004 早段空窗；未恢复三架方案。

1.0/0.5/0.25 秒网格在 LOS 5/10/15 米下采样覆盖全部通过（0 uncovered）；方向性返航模型下中继返航与 R02 周转时序均通过。当前方案满足已验证约束（57 项检查），不声称全局最优或连续时间的严格证明。

## 正式数据与证据

- [本次自动报告](results/q3_current_report.md)：能耗、SOC、时序、样本数、覆盖率与失败项，均由本次独立验证输出生成。
- [完整验证及输入身份](results/e4_final_validation.json)、[实际运行日志](results/q3_validator_run.log)、[审查报告](audit/REVIEW.md)。
- [固定中继决策](results/q3_official_plan.json)：从基准正式CSV冻结；S02 窗口前移 45 s（[745,4751]→[700,4706]）。
- [正式运输调度](results/q3_transport_schedule.csv)：T011 +2320秒；T015 +1224秒并分配U08。按Q2原时刻恢复双精度，保持组批、路线、电池不变；不回写Q2。
- [逐架次中继表](results/q3_relay_schedule.csv)：计划时刻与 calculated_* 一致，另列能耗、SOC 与状态。
- [逐阶段能源](results/e4_relay_validation.json)、[逐样本通信](results/q3_communication_links.csv)、[实际运输航段](results/q3_transport_timeline.csv)。

## 复现

```bash
python -B Q3/code/build_official_transport.py
python -B Q3/code/finalize_e4_q3.py
python -B Q3/code/test_finalize_e4_q3.py
```

finalize在新临时目录调用独立验证器，校验当前输入及代码SHA-256、检查项与退出码后发布。固定方案应退出0（PASS）；缺失、过期、异常输出退出2（ERROR）。solve.py、validate.py、summary.py、generate_q3_links.py统一进入该验证链，不重搜、不引用历史三架结果。

## 结论边界与历史

逐架次 t=takeoff+k×step，t<return；起飞纳入、返回排除，服务窗口左闭右开。100%仅代表指定离散网格的采样覆盖，并以名义服务窗口存在为条件。物理时序另行检查，本次通过。

方法见[METHOD_STRICT.md](METHOD_STRICT.md)。archive_3relay、comparison_2relay_static、history_pre_audit中的结果、标为历史的三个实验报告及figures/history_pre_audit仅作对照。历史experiment_*、strict_feasibility、relay、sensitivity、baseline等脚本不是正式入口，本次未运行。

results/e4_best.json、e0_baseline.json及two_relay_failure_*是历史实验/失败分析资料，不属于当前正式验证输入。
