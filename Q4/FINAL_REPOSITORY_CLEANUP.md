# Q4 最终仓库一致性收尾

> 本轮目标：**只**修正文档、复现证据与验证器覆盖范围，使仓库描述与当前真实代码/结果完全一致。
> **未修改任何正式模型、优化目标、约束或正式方案。**

## 1. 修改前基线

- 分支：`main`
- HEAD：`3452099` — `chore(repo): 论文图统一到 paper_figures/，清理重复图目录`
- 工作区：干净（`git status` 空）

## 2. 修改文件

| 文件 | 类型 | 目的 |
|---|---|---|
| `Q4/README.md` | 文档 | 修正「全量枚举」与「CV」错误表述 |
| `Q4/方法与口径.md` | 文档 | 修正「CV」错误表述 |
| `Q4/code/validate.py` | 验证器 | 修正 docstring 项数错误；新增分区合法性与枚举一致性独立检查；失败时非零退出码 |
| `Q4/results/q4_rerun_manifest.json` | 复现证据 | 用真实 SHA-256 重新生成（修复失效 hash） |
| `Q4/results/q4_validation.json` | 验证输出 | 因新增独立穷举与逐行复算检查合理变化（11 → 35 项，全部 PASS） |
| `Q4/FINAL_REPOSITORY_CLEANUP.md` | 报告 | 本文档 |

未改动：`q4_solve.py`、Q1/Q2/Q3 核心代码、`q4_best_*.json`、任何 CSV/JSON 正式结果。

## 3. README「全量枚举」如何修正

- 旧：`q4_all_partitions_2groups.csv`、`q4_all_partitions_3groups.csv` —— **全量枚举**
- 新：
  - 2 组 CSV —— 全量枚举（2047 个候选，按字典序排序）
  - 3 组 CSV —— 枚举的**排序前 1000 个**候选（完整枚举 86526 个，计数见 `q4_all_partitions_3groups_summary.json`）

求解器截断逻辑（`q4_solve.py` 的 `limit = None if k == 2 else 1000`）**未改动**；仅修正文档措辞，使其与代码行为一致。

## 4. CV 表述如何修正

代码实际只有 `workload_imbalance`（5 项等权归一化后的 `max(W)−min(W)`），**从未计算 CV**。

- 旧（`README.md` §7、`方法与口径.md` §5）：报告 `max(W)−min(W) 与 CV`
- 新：报告 `max(W)−min(W)`（`workload_imbalance`），并明确该指标**仅作为字典序目标中的末位辅助择优指标**，用于同等资源缺口与总资源需求下的辅助比较，**不解释为严格意义上的组间工作量均衡最优；当前实现不计算 CV**。

`q4_solve.py` 排序键 `(gap_sum, total_res, imbalance)` **未改动**；未新增 CV 进入优化。

## 5. validate.py 项数文档错误如何修正

- 旧 docstring：`checks the 15 required conditions`
- 实际原正式验证为 11 项，且存在循环变量残留导致 `no_empty_group` 只落在 3 组、`multi_site_trips_co_grouped` 只验 2 组、`resources_nonnegative` 只验 3 组的问题。
- 新 docstring 改为对覆盖范围（块构造、逐组资源重算、分区合法性、资源非负、枚举一致性）的准确描述，不再声称固定项数。

## 6. 新增分区合法性检查

对 `q4_best_2groups.json` 与 `q4_best_3groups.json` **分别独立**执行（命名带 `2groups_` / `3groups_` 前缀，杜绝循环变量残留）：

| 检查 | 2 组 | 3 组 |
|---|---|---|
| `service_area_complete_coverage`（S001–S015 全覆盖） | PASS | PASS |
| `service_area_exactly_once`（不重不漏） | PASS | PASS |
| `no_empty_group`（各组非空） | PASS | PASS |
| `atomic_block_integrity`（12 块各恰好一次，不跨组） | PASS | PASS |
| `multi_site_trip_co_grouped`（多站架次同组） | PASS | PASS |
| `resources_nonnegative`（资源非负） | PASS | PASS |

原 11 项中保留的检查（`each_service_area_exactly_once`、`resource_recomputation_matches`、`trip_count_unchanged`、`relay_schedule_unchanged`、`gap_calculation_correct`、`2group_reproducible`、`3group_reproducible`、`strict_binding_sensitivity_present`）继续 PASS。

## 7. 枚举结果一致性验证

- 2 组：CSV 2047 行（= 全量枚举数），独立重算 2047 个候选并通过唯一性检查
- 3 组：summary `total_enumerated=86526`、`saved_top_n=1000`，CSV 1000 行，均 PASS
- 排序：2 组与 3 组 CSV 均按 `(gap_sum, total_resources, imbalance)` 非降序排列，`csv_sorted` PASS
- 逐行复算：2 组 CSV 2047/2047 行、3 组 CSV 1000/1000 行的目标值与独立重算一致。
- 独立最优性：验证器不调用 `q4_solve.py`，而是重新生成全部合法分区、重算资源与字典序目标；提交的 2 组和 3 组方案均达到独立枚举得到的字典序最优值。
- Top1000：3 组 CSV 的 1000 行逐行复算通过，并与独立全量枚举排序后的前 1000 个目标值逐项一致。

> 说明：上述“最优”仅针对固定 Q3 调度、固定资源核算和既定 `(gap_sum, total_resources, imbalance)` 字典序目标；不等同于所有可能调度模型下的全局最优。

## 8. manifest 更新

修复前失效项：`Q3/results/q3_relay_schedule.csv` 记录 `a4519692…`，与磁盘文件、任何 git 版本均不匹配。

修复后（全部为磁盘文件真实 SHA-256，程序计算，非手填）：

| 输入 | 修复前 | 修复后 |
|---|---|---|
| `Q2/results/q2_trips.csv` | `42cabfa2…`（未变） | `42cabfa2…` |
| `Q2/results/q2_inputs.json` | `d195b844…`（未变） | `d195b844…` |
| `Q3/results/q3_relay_schedule.csv` | `a4519692…`（失效） | `2530de7e…` |
| `Q3/results/q3_communication_links.csv` | `4816bb7e…` | `e7b19589…` |

新增字段：`generated_at`、`q4_results_sha256`（`q4_best_2groups.json`、`q4_best_3groups.json` 内容哈希）；`q4_head_at_run` 更新为当前 HEAD。生成后立即复核：6 项哈希全部与磁盘一致。

> 说明：hash 为工作区字节哈希（沿用 `rerun_from_q3.py` 的 `read_bytes()` 口径）。CSV 属文本文件、受 git 行尾规范化影响，该哈希随检出行尾设置变化；这是既有 schema 的固有限制，本轮未改动哈希方法。

## 9. Q4 验证最终状态

- `OVERALL: PASS`
- 检查项数：**35**（原 11 + 新增独立枚举、逐行复算及库存一致性检查）
- 退出码：**0**
- `q4_validation.json` 与重跑输出逐字段一致

## 10. 正式核心数字修改前后对比

| 结果 | 修改前 | 修改后 | 结论 |
|---|---|---|---|
| Q1 架次 / 箱 / 能耗 / 作业时间 | 18 / 80 / 59.130796487 / 32776.092677 | 18 / 80 / 59.130796487 / 32776.092677 | 不变 |
| Q2 架次 / 航段 / 能耗 / makespan / minSOC | 26 / 55 / 71.440968978 / 6973.648577 / 20.95% | 26 / 55 / 71.440968978 / 6973.648577 / 20.9489% | 不变 |
| Q3 状态 / 物理中继 / 架次 / uncovered / 中继能耗 / makespan | PASS / 2 / 3 / 0 / 4.536233593 / 8506.22 | PASS / 2 / 3 / 0 / 4.536233593 / 8506.220614 | 不变 |
| Q4 2 组（运输/电池/中继/组件，gap） | 9/15/2/3，2 | 9/15/2/3，2 | 不变 |
| Q4 3 组（运输/电池/中继/组件，gap） | 10/15/3/4，4 | 10/15/3/4，4 | 不变 |

## 11. 声明

**本轮未修改任何正式模型、优化目标、约束或正式方案，仅完善文档一致性、复现证据与独立验证覆盖范围。**
