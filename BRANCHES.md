# 分支说明

本文件记录 2026-09-23 分支整理后的实际拓扑。
整理只新增提交与 tag，未改写任何历史、未强推、未合并 `main`。

## 当前拓扑

四个问题分支构成一条干净的祖先链，每一环都包含前一环的全部内容：

```text
main   8a55043  协作规范与每问模板
└── q2 81915bb  Q2：多点运输调度与资源分配
    └── q1 fee99f9  = q2 + Q1
        └── q3 698d7d9  = q1 + Q3
            └── q4 d069a32  = q3 + Q4   ← 当前最完整的集成分支
```

`q1` 含 `Q2/` 是**必需**的：`Q1/code/main.py` 复用 `Q2/code/prepare_data.py` 的 `Terrain`
做 UTM 直线逆投影 DEM 遍历（240 航段 0 差异，CASE A），只检出 `Q1/` 会 `ImportError`。

| 分支 | 内容 | 改哪里 |
|---|---|---|
| `q2` | 第二问：多点运输调度与资源分配 | `Q2/` |
| `q1` | 第二问 + 第一问：单点运输、组批、能耗/时间 | `Q1/` |
| `q3` | 以上 + 第三问：通信盲区检测与中继调度 | `Q3/` |
| `q4` | 以上 + 第四问：分区与独立资源配置 | `Q4/` |

## 改动怎么合并

只改自己那一问的目录，然后沿链条往下游合并，不要反向合并，也不要在下游分支里直接改上游目录：

- 改 `Q2/` → 提交到 `q2`，再依次合并进 `q1 → q3 → q4`
- 改 `Q1/` → 提交到 `q1`，再依次合并进 `q3 → q4`
- 改 `Q3/` → 提交到 `q3`，再合并进 `q4`
- 改 `Q4/` → 直接提交到 `q4`

## 标签

| tag | 指向 | 用途 |
|---|---|---|
| `pre-tidy/q1` … `pre-tidy/q4` | 整理前的四个分支尖端 | 回滚对照 |
| `post-tidy/q1` … `post-tidy/q4` | 整理后的四个分支尖端 | 本次交付状态 |
| `archive/audit-fixes` | `77f518d` | 已删除分支的永久存档 |
| `archive/audit-q1-coordinate` | `6a45d36` | 已删除分支的永久存档 |

回滚到整理前：`git checkout pre-tidy/q3`（或 `git branch <名> pre-tidy/q3`）。
取回已删除的审计分支：`git checkout archive/audit-fixes`。

## 已删除的临时审计分支

两个分支的产物都已归位到 `q1`（索引见 [`Q1/audit/README.md`](Q1/audit/README.md)），
分支本身已删除，提交由上面的 `archive/*` tag 保留。

| 分支 | 原用途 | 产物去向 |
|---|---|---|
| `audit-fixes` | 证明 Q1 自建 DEM 遍历与 Q2 认证遍历 240 航段 0 差异；顺带修 Q2 可复现性 | `Q1/audit/common_geometry_*` → `q1`；`Q2/code/solve.py`+`Q2/README.md` → `q2` |
| `audit-q1-coordinate` | 对照局部仿射与统一 UTM49N 两种水平坐标口径 | `Q1/audit/compare_q1.py`、`q1_coordinate_*`、`unified_results/` → `q1` |

两个审计结论都是 **CASE A（结论不变）**，细节见 `Q1/audit/README.md`。
整理前 `q1` 与 `audit-fixes` 各有一份互不相关的 Q1，现在以 `audit-fixes` 的版本为准。

## 整理前的 SHA（回滚用）

```text
main                 8a5504384d5d08ad65b53a6bc31fbc50b55c2ed5
q1                   f3b705bd8b2f7d16e5e6d5c74d9f11e5d5b47a9b
q2                   d660e84fe91e79c1092b57824a8c0eab83e1fed9
q3                   8e5f42161863e0995725aa776e9a3caa4d2f14ec
q4                   e4d75aa99204af08a0f425aefb5510941df83893
audit-fixes          77f518d52414b790a8c86a4cea20c89005e4108b
audit-q1-coordinate  6a45d369a2d574e883bd9dac03fd1dab2b66a179
```

## 未处理项

- `Q2/README.md` 首行标题写作「第三问运输初始方案」，按内容应为第二问。属内容修订，
  留给该问负责人确认后修改，本次整理未改动。
- `main` 仍只含协作规范。四问齐备并复核后，由合并协调人决定何时从 `q4` 合并 `main`。
