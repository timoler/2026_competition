# Q1 审计产物索引

本目录保存两组互不重复的审计实验，均为「结论不变」的证据，不是 Q1 的正式结果。
正式结果在 `../results/`，口径说明在 [`../方法与口径.md`](../方法与口径.md)。

## 一、坐标口径审计（局部仿射 vs 统一 UTM49N）

对应分支 `audit-q1-coordinate`（已归档为 tag `archive/audit-q1-coordinate`）。

| 文件 | 内容 |
|---|---|
| `compare_q1.py` | 对照实验脚本：旧口径（WGS84 经纬度直线）与统一 UTM49N 口径分别重算 Q1 |
| `q1_coordinate_comparison.csv` | 240 条有向航段的逐航段几何对照 |
| `q1_coordinate_audit.json` | 结论数据：CASE A |
| `q1_coordinate_audit.md` | 结论说明 |
| `unified_q1.py` | 统一 UTM 口径下的 Q1 重算 |
| `unified_results/` | 统一口径重算的全部结果表，用于与 `../results/` 逐项比对 |
| `verify_coordinate_audit.py` | 独立验证脚本 |
| `q1_coordinate_audit_verify.json` | 独立验证输出 |

**结论 CASE A**：距离差 ≤ 0.0094%（最大 0.692 m，O01–S012），DEM 最高高程 240 航段全为 0 差异；
组批、架次数、机型选择、敏感性结论全部不变；能耗差 ≤ 0.0025%，作业时间差 ≤ 0.42 s。

## 二、公共几何口径审计（Q1 独立 DEM 遍历 vs Q2 认证遍历）

对应分支 `audit-fixes`（已归档为 tag `archive/audit-fixes`），本轮整理的来源。

| 文件 | 内容 |
|---|---|
| `common_geometry_compare.py` | 比对脚本 |
| `common_geometry_comparison.csv` | 240 条航段逐条比对 |
| `common_geometry_summary.json` | 结论数据 |

**结论 CASE A**：`n_legs=240`，距离 / 最高高程 / 巡航海拔 / 爬升 / 下降的最大差全为 0.0 m；
`trips_unchanged=true`，能耗与作业时间差 0.0。据此 `code/main.py` 改为直接复用
`Q2/code/prepare_data.py` 的 `Terrain`（UTM 直线逆投影 + 六阶 Krueger 导数区间单调性证书），
不再自行从 GeoTIFF 解析像元。

## 复算前提

两个脚本都需要原始数据目录，且 `code/main.py` 复用 Q2 的 `Terrain`，
因此**运行 Q1 需要同仓库存在 `Q2/`**（`q1` 分支已包含完整 Q2，见根目录 `README.md` 的分支说明）。
