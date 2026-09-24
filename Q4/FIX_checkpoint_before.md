# Q4 中继架次统计修复 —— 修复前状态快照

> 保存时间：2026-09-24。此文件记录修复前的 Q4 结果与分析，用于修复后对比。

## 问题定位

Q4 读取 `q3_communication_links.csv` 时用 `relay_id` 作键：

```python
relay_trips[r["relay_id"]].add(r["trip_id"])   # 错误：R02 的两次架次被合并
```

`account()` 里 `sorties = [s for s in relay if any(t in tids for t in relay_trips[s["relay_id"]])]`
对 `relay_id="R02"` 会把 R02 的两次架次（S02/S03）全部计入，即使该分区只用到其中一次。

## 修复前的 Q4 结果（旧逻辑）

库存：运输机 {A:4, B:2, C:2}=8；电池 {A:6, B:4, C:4}=14；中继 2；中继组件 6。

| 项目 | 集中式 | 2组 | 3组 |
|---|---:|---:|---:|
| 运输机数 | 8 | 9 | 10 |
| 电池数 | 14 | 15 | 15 |
| 中继数 | 2 | 2 | 3 |
| 中继组件数 | 3 | 3 | 4 |
| 库存缺口(机/池/中继/组件) | 0/0/0/0 | 1/1/0/0 | 2/1/1/0 |

- 2组 gap_sum=2（无人机 B +1，电池 B +1）
- 3组 gap_sum=4（无人机 B +2，电池 B +1，中继 +1）

## 中继架次 → 服务航次映射（由时间窗推导）

`q3_relay_schedule.csv` 三个 sortie：S01=R01 [816,7834.5]、S02=R02 [745,4751]、S03=R02 [6478.3,6902]。

`q3_communication_links.csv` 中 relay 行按 relay_id+时间窗归属（0 条未匹配）：

- **R01_S1 (S01)**: 14 trips — T003,T007,T009,T010,T011,T012,T014,T015,T017,T019,T022,T023,T025,T026
- **R02_S1 (S02)**: 6 trips — T002,T004,T006,T008,T010,T021
- **R02_S2 (S03)**: 1 trip — T011

旧逻辑 `relay_trips["R02"]` = S02∪S03 = 7 trips（T002,T004,T006,T008,T010,T011,T021）。

## 不可分割块（block）→ 航次

B01(S001,S010):T005,T006,T016,T018,T020,T021,T024；B02(S002):T007,T017；B03(S003,S006):T001,T012,T019；
B04(S004):T011；B05(S005,S008):T010,T015,T022,T023,T025；B06(S007):T003；B07(S009):T014；
B08(S011):T013；B09(S012):T008；B10(S013):T004；B11(S014):T002；B12(S015):T009,T026。

关键点：T011（块 B04 / 站点 S004）是 R02_S2 唯一服务的航次，同时 T011 也由 R01_S1 服务。
修复后，仅含 B04 而不含其他 R02 块的分区，只会计入 R02_S2（1 架次），不再连带 R02_S1。

## 修复计划

1. 给 `q3_communication_links.csv` 增加 `sortie_id` 字段（relay 行按 relay_id+时间窗映射为 R01_S1/R02_S1/R02_S2；非 relay 行留空）。
2. 同步把 `q3_relay_schedule.csv` / `q3_final_schedule.csv` 的 sortie_id 由 S01/S02/S03 改名为 R01_S1/R02_S1/R02_S2（纯标签，不改方案）。
3. `Q4/code/q4_solve.py` 与 `Q4/code/validate.py`：`relay_trips` 改按 `sortie_id` 建键；`account()` 用 `relay_trips[s["sortie_id"]]`。
4. `Q4/code/rerun_from_q3.py`：删除旧三架增配说明与硬编码 commit，改为自动取当前 Q3 来源 commit。
5. 重跑 Q4 并对比。
