# Q1–Q3 本地审查与实际复现报告

> **⚠️ 已修复标记（2026-09-24）：本报告中的 Q3 FAIL 结论已被后续修复取代，不是当前正式结果。**
> 修复内容：采用方向性返航模型（返程从悬停海拔爬升，不再复制去程时长），并将 S02 服务窗口整体前移 45 s（[745,4751]→[700,4706]）。修复后：R02 周转 gap 由 −44.568 s 变为 **+0.450 s**；1.0/0.5/0.25 s 与 LOS 5/10/15 m 全部 **0 uncovered**；`finalize_e4_q3.py` 退出码 **0**；Q3 当前正式状态 **PASS**（57 项检查全过）。下方 Q3 的 FAIL 明细、命令退出码 1 等为历史审计记录，仅作追溯。

日期：2026-09-24。审查版本为 main@afba25c976360f32f4a49d7e8cb0af64b63f0e79，正好等于指定基准；没有基准之外的初始已跟踪修改。原有未跟踪Q4/FIX_checkpoint_before.md完整保留。本次工作分支work/q1-q3-validation，未提交、推送或合并。实际仓库在E:/GitHub_Project/2026_competition；环境初始目录2026_comp是原始附件目录。

## 本次状态与核心指标

- Q1：PASS；18架次，B/C各9，80箱；总能耗59.130796486658 kWh；累计作业32776.092676944 s；最低返航SOC 23.088787400%。9份方案表166条记录实际重验；模型和正式组批不变。
- Q2：PASS（声明模型假设下）；80箱，31个硬时限全满足，26架次/55航段，运输能耗71.440968978416 kWh，完工6973.648576673 s，最低SOC 20.948947326%。独立重算航段载荷、能源、SOC、电池充电、时序和资源冲突，并核对DEM及轨迹边界。未运行优化和改进回放。通信、回传不是Q2模型约束，Q2本次不宣称已验证这些约束。
- Q3：**FAIL**；2架物理中继、3架次、3组组件不变。运输约束通过，运输能耗71.440968978416 kWh，完工8197.648576673 s；中继能源4.536233592950 kWh，各架次SOC与余量通过，但中继时序和细时间网格失败。

[全部逐架次能源、SOC、实际样本数与失败明细](../results/q3_current_report.md)。1秒覆盖是固定名义服务窗口下的离散覆盖，不代表物理时序可执行。

## 能耗差异的代码与数据依据

修复前正式CSV合计4.702102000 kWh，旧e4 JSON为4.702222000 kWh。旧finalize固定S03窗口[6478.3,6902.0)，旧验证器evaluate却把西侧结束时刻改成残余需求最后样本+1，即6902.392351884103秒，多计0.392351884103秒服务。1.10 kW×该时长/3600=0.000119885298 kWh，各架次先舍入6位后正好复现旧差0.000120 kWh。主要原因是不同窗口，不是单纯浮点误差或DEM版本。
固定窗口按旧公式不提前舍入总量为4.702101677804 kWh。进一步逐阶段核查发现relay.relay_sortie复制去程时长为返程，并把中心到悬停海拔的爬升能耗重复用于返程；三个悬停点均等于各自巡航海拔，返程应先水平飞行再下降，不应再次计中心起飞爬升。去除重复爬升0.193368084854 kWh，加入三次各30秒建链悬停/通信共0.027500000000 kWh，得唯一正式值4.536233592950 kWh。
建链时无线电开启是显式保守假设；下降附加能耗维持附件0口径。能源是固定窗口下逐个架次的计算合计，不证明组合时序可行。原输入位置、服务窗口、归属与计划时刻均未改变。公式见METHOD_STRICT.md，逐阶段数值及新旧对账见energy_reconciliation.json。

## 明确失败与边界

- S01/S02/S03分阶段计算返航为8506.220613995 / 5190.368457385 / 7795.123233770秒，原计划8440.2 / 5145.8 / 7724.5秒。R02第二次准备5445.8秒，前一架次返航+300秒周转后应至少5490.368457385秒，差44.568457385秒。
- 1秒、LOS15/10/5米各36351样本、0 uncovered、100%；0.5秒72690样本/1 uncovered/99.998624295%；0.25秒145366样本/3 uncovered/99.997936244%。细网格失败来自T004在744.25/744.5/744.75秒尚无可用链路，早于南侧中继745秒名义服务起点。中断段1段，分别0.5/0.75“样本秒”，不是严格连续中断长度。
- 三处中继到基站的双向回传在各LOS间距均通过。LOS值表示地形采样间距，不是净空；净空0米。服务窗口与采样端点规则见自动报告。
- 全部运输巡航的最小DEM净空50米，已从240个有向几何重算；节点作业高度按附件海拔定义，起降采样相对DEM最小约−1.02554米，属于节点指定海拔与DEM像元差异，不得把它当作地面一致性认证或实飞保证。
- 原节点/DEM、Q2充电并行与运输补充能源模型的假设边界仍存在；投影像元遍历是数值实现，不是任意地区的形式化证明。连续时间覆盖未获证明，本次反而检出细网格失败。
- 修正固定方案可行性需要重排中继/服务或相关运输时序；本次按固定方案审查范围保留失败方案与证据，没有为追求PASS另搜新解，不声称已满足全部约束。历史三架和静态两架仅作明确标记对照。

## 实际命令与退出码

| 标签 | 实际命令 | 退出码 |
|---|---|---:|
| q1 | `E:\Miniconda3\python.exe -B Q1/code/verify.py E:\GitHub_Project\2026_comp` | 0 |
| q2 | `E:\Miniconda3\python.exe -B -c "import sys; sys.path.insert(0,'Q2/code'); from validate import validate; validate('Q2/results',save=False)"` | 0 |
| q2_independent | `E:\Miniconda3\python.exe -B Q2/code/independent_audit.py --dem E:\GitHub_Project\2026_comp\数据\镇龙乡地理空间数据\镇龙乡及周边地理数据\数字高程模型数据（DEM）\镇龙乡及周边30米DEM.mat --skip-improve-replay` | 0 |
| build_transport | `E:\Miniconda3\python.exe -B Q3/code/build_official_transport.py` | 0 |
| q3_finalize | `E:\Miniconda3\python.exe -B Q3/code/finalize_e4_q3.py` | 1 |
| failure_tests | `E:\Miniconda3\python.exe -B Q3/code/test_finalize_e4_q3.py` | 0 |
| q3_independent_reproduction | `E:\Miniconda3\python.exe -B Q3/code/validate_two_relay_experiment.py --output C:\Users\陈佳政\AppData\Local\Temp\q3-reproduce-amwnpx3d` | 1 |

日志位于logs/，结构化记录见commands.json。finalize和直接独立验证均退出1，表示真实方案FAIL；11项失败路径/算术回归测试退出0。此前开发阶段一次ERROR来自原运输CSV六位小数舍入造成资源微重叠，已由全精度重建消除；原始异常日志仍保留，未冒充验证通过。

## 复现与保护证据

- run_review.py从原Q2时间重新生成运输CSV，字节一致；再次直接运行独立验证器，所有数值/检查和CSV输出一致，仅排除运行时间/临时路径等provenance字段。见reproduction.json。原始DEM与Q3缓存逐像元子集一致，见terrain_source_check.json。
- Q4共27个文件（含用户未跟踪文件）前后SHA-256完全相同；git diff --numstat -- Q4为空；共享README及Q3既存文档中所有涉及Q4的原行逐字节保留。Q2代码和结果亦逐字节不变。证据见before.json、protection_check.json。
- 未运行Q4入口、仓库总入口、任何新优化搜索或历史三架实验；未推送或合并。Q4已有结论未确认，本次不予认证。

## 修改文件逐项清单

| 文件 | 目的 |
|---|---|
| `Q1/README.md` | 同步本次复核状态，保留模型结论边界 |
| `Q1/code/verify.py` | 补齐默认方案、分阶段时间、SOC、提交表数值、汇总与失败退出码；不改模型 |
| `Q1/results/q1_verification.json` | 本次166条记录和新增核对项的实际结果 |
| `Q2/README.md` | 说明本次独立重验及通信未纳入Q2；模型和结果逐字节不变 |
| `Q3/E4_E5_TWO_RELAY_REPORT.md` | 同步真实FAIL与能源/采样边界，旧实验显式标历史，Q4既存语句原样保留 |
| `Q3/E4_FINAL_VALIDATION_REPORT.md` | 同步真实FAIL与能源/采样边界，旧实验显式标历史，Q4既存语句原样保留 |
| `Q3/METHOD_STRICT.md` | 同步真实FAIL与能源/采样边界，旧实验显式标历史，Q4既存语句原样保留 |
| `Q3/README.md` | 同步真实FAIL与能源/采样边界，旧实验显式标历史，Q4既存语句原样保留 |
| `Q3/TWO_RELAY_EXPERIMENT_REPORT.md` | 同步真实FAIL与能源/采样边界，旧实验显式标历史，Q4既存语句原样保留 |
| `Q3/code/finalize_e4_q3.py` | 新临时目录启动验证、哈希绑定、真实状态汇总、FAIL/ERROR非零退出、统一派生正式结果 |
| `Q3/code/generate_q3_links.py` | 正式别名入口统一调用新finalize，避免旧调度或旧PASS覆盖 |
| `Q3/code/solve.py` | 正式别名入口统一调用新finalize，避免旧调度或旧PASS覆盖 |
| `Q3/code/summary.py` | 正式别名入口统一调用新finalize，避免旧调度或旧PASS覆盖 |
| `Q3/code/validate.py` | 正式别名入口统一调用新finalize，避免旧调度或旧PASS覆盖 |
| `Q3/code/validate_two_relay_experiment.py` | 正式固定输入、独立运输算术/DEM/轨迹、分阶段中继能源和时序、全网格通信重算 |
| `Q3/figures/q3_blackout_timeline.png` | 移至history_pre_audit原样保留（不是删除历史证据） |
| `Q3/figures/q3_comparison.png` | 移至history_pre_audit原样保留（不是删除历史证据） |
| `Q3/figures/q3_relay_gantt.png` | 移至history_pre_audit原样保留（不是删除历史证据） |
| `Q3/figures/q3_sensitivity.png` | 移至history_pre_audit原样保留（不是删除历史证据） |
| `Q3/figures/q3_spatial_map.png` | 移至history_pre_audit原样保留（不是删除历史证据） |
| `Q3/results/e4_blackout_intervals.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/e4_communication_validation.json` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/e4_final_validation.json` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/e4_los_sensitivity.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/e4_relay_validation.json` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/e4_temporal_sensitivity.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/e4_transport_validation.json` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_blackout_intervals.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_communication_links.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_final_blackout_intervals.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_final_schedule.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_final_validation.json` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_los_resolution_sensitivity.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_relay_schedule.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_schedule_summary.json` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_sensitivity.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_summary.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_transport_schedule.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_transport_timeline.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_validation.json` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/方法与口径.md` | 同步真实FAIL与能源/采样边界，旧实验显式标历史，Q4既存语句原样保留 |
| `README.md` | 仅替换第三问边界条目，所有Q4内容保留 |
| `Q3/audit/REVIEW.md` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/before.json` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/build_review_results.py` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/changed_files.json` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/check_final_consistency.py` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/commands.json` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/energy_reconciliation.json` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/final_consistency.json` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/logs/build_transport.log` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/logs/failure_tests.log` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/logs/git_diff_check.log` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/logs/q1.log` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/logs/q2.log` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/logs/q2_independent.log` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/logs/q3_finalize.log` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/logs/q3_finalize_initial.log` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/logs/q3_independent_reproduction.log` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/protection_check.json` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/reproduction.json` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/run_review.py` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/audit/terrain_source_check.json` | 审查输入状态、命令日志、负向测试、复现、差异与保护证据 |
| `Q3/code/build_official_transport.py` | 按既有两个平移量恢复Q3运输全精度时间，不搜索、不回写Q2 |
| `Q3/code/test_finalize_e4_q3.py` | 临时目录错误注入与非对称往返能源算例 |
| `Q3/code/validation_io.py` | 轻量I/O与输入哈希；科学依赖加载异常也能使finalize撤销旧成功状态 |
| `Q3/figures/README.md` | 同步真实FAIL与能源/采样边界，旧实验显式标历史，Q4既存语句原样保留 |
| `Q3/figures/history_pre_audit/q3_blackout_timeline.png` | 保存基准历史资料；非当前正式证据 |
| `Q3/figures/history_pre_audit/q3_comparison.png` | 保存基准历史资料；非当前正式证据 |
| `Q3/figures/history_pre_audit/q3_relay_gantt.png` | 保存基准历史资料；非当前正式证据 |
| `Q3/figures/history_pre_audit/q3_sensitivity.png` | 保存基准历史资料；非当前正式证据 |
| `Q3/figures/history_pre_audit/q3_spatial_map.png` | 保存基准历史资料；非当前正式证据 |
| `Q3/results/e4_blackout_samples_0.25s.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/e4_blackout_samples_0.5s.csv` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/history_pre_audit/e4_final_validation.json` | 保存基准历史资料；非当前正式证据 |
| `Q3/results/history_pre_audit/e4_temporal_sensitivity.csv` | 保存基准历史资料；非当前正式证据 |
| `Q3/results/history_pre_audit/q3_final_validation.json` | 保存基准历史资料；非当前正式证据 |
| `Q3/results/history_pre_audit/q3_relay_schedule.csv` | 保存基准历史资料；非当前正式证据 |
| `Q3/results/history_pre_audit/q3_sensitivity.csv` | 保存基准历史资料；非当前正式证据 |
| `Q3/results/history_pre_audit/q3_summary.csv` | 保存基准历史资料；非当前正式证据 |
| `Q3/results/q3_current_report.md` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
| `Q3/results/q3_official_plan.json` | 从基准CSV冻结中继决策及运输调整，切断结果与验证循环依赖 |
| `Q3/results/q3_validator_run.log` | 从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史 |
