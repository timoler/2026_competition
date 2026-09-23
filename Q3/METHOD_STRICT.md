# Q3 联合调度方法与统计口径

## 输入与局部重调度

Q2 的 26 个架次、货箱组批与访问路线作为**运输初始方案**保持不变；Q3 加入连续通信约束后，允许**局部调整**：
- trip start time（本次调整 T011 +2320 s、T015 +1224 s）；
- transport UAV assignment（本次 T015 从 U07 调到 U08）；
- shared battery schedule（沿用原分配，重新校验充电与复用）。

调整后的运输 schedule 重新经过**运输、电池、通信三类独立验证**，Q2 正式结果不被回写。DEM 使用仓库已有 `q3_terrain_cache.npz`，不替换地形。

## 通信状态定义

运输机 i 在时刻 t 的通信状态：

```
C_i(t) = C_direct_i(t)
      OR [ (C_access_i,R01(t) AND C_backhaul_R01(t))
        OR (C_access_i,R02(t) AND C_backhaul_R02(t)) ]
```

- `C_direct`：与固定网关 G01 的直连链路可用。
- `C_access_i,Rk`：运输机 i 与中继 Rk 的接入链路可用。
- `C_backhaul_Rk`：中继 Rk 与 G01 的回传链路可用。
- 接入与回传必须同一时刻同时可用；每架运输机任一时刻最多由 G01 或一架中继保障；不允许中继间多跳。

## 唯一正式口径

- 时间网格：**1 s**（逐架次 t = takeoff_s + k，k 非负整数，t < return_s，跳过 finished）。
- LOS 间距：**10 m**（地形最近像元，排除两端点，地形高程 ≥ 视线高程即遮挡，净空 0 m）。
- 双向链路预算与 LOS 复用 `check_core.py`；总计 36,351 个通信样本。
- 严格可行：`uncovered_samples == 0` 且全部资源/时序/能量检查通过。
- 敏感性：最终方案固定，分别按 **15 / 10 / 5 m** 重算；另做 **0.5 s / 0.25 s** 时间边界检查。

## 中继资源

- **physical relay UAV = 2（R01 / R02）**，仅原题两架。
- **relay sorties = 3**：R01 一次悬停 + R02 两次顺序架次（南侧结束 → 返 O01 → 周转 → 西侧）。
- relay components = 3 ≤ 6；AGL ≤ 300 m；返航 SOC ≥ 20%。
- 中继飞行/能耗沿用 `relay_sortie`：准备 180 s、建链 30 s、悬停+通信 1.10 kW、下降能耗 0、对称往返时间近似。

## 结论边界

- 本方案在 1 s / 10 m 及 LOS 15/10/5 m、0.5 s / 0.25 s 下均达到 0 中断，但不构成对任意连续时空扰动或其它净空/链路预算假设的鲁棒性证明。
- **R01 能量临界**（SOC 20.4423%，仅高于 20% 下限 0.44 pct），不得声称强能源鲁棒性。
- 早期三架增配（R03）方案仅作对照，见 `results/archive_3relay/`；静态两架 407 中断结果见 `results/comparison_2relay_static/`。

## 复现

```bash
python Q3/code/validate_two_relay_experiment.py   # 独立严格验收
python Q3/code/finalize_e4_q3.py                  # 固化正式文件
```

Q4 已基于本两架联合调度方案重跑，不再依赖旧三架增配方案。
