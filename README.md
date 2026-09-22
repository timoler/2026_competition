# 2026_competition

三人数学建模比赛共享仓库。一个仓库、每问一个分支，验证后合并到 `main`。不建立重复的 deliverables 汇总区。

## 开赛第一步

1. 仓库拥有者在 Settings → Collaborators 邀请两位队友；队友接受后克隆本仓库。
2. 三人共同填写下面的分工表，指定一人负责论文与合并协调（可以兼任建模）。
3. 拿到题目后，协调人在 main 上传原始题目、附件和数据，再按实际问题数创建 q1、q2、q3、q4 等分支。只创建实际需要的分支。
4. 每问负责人切换到对应分支，复制 `模板/Qx/` 为根目录的 `Q1/`、`Q2/` 等，填写 README 后开始工作。

## 三人分工

| 成员 | 负责问题 | 交叉复核 | 兼任角色 |
| --- | --- | --- | --- |
| A（待填 GitHub 用户名） | 待定 | 复核 B 的关键结论 | 合并协调（可调整） |
| B（待填 GitHub 用户名） | 待定 | 复核 C 的关键结论 | 待定 |
| C（待填 GitHub 用户名） | 待定 | 复核 A 的关键结论 | 论文整合（可调整） |

三个人可以负责四问；每问必须指定一个负责人。论文手是兼任角色，不增加第四个人。分工变化直接更新此表。

## 目录与分支

```text
README.md
上传规范.md
.gitignore
模板/Qx/README.md          # 复制后填写，不作为比赛结果
题目与附件/               # 拿到题目后建立，原件只读
data/raw/                 # 原始数据，禁止覆盖
Q1/                       # 在 q1 开发，通过复核后合并 main
  code/                   # 代码、依赖说明
  results/                # 处理后数据、结果表、运行记录
  figures/                # 论文图与必要的分析图
  README.md               # 本问唯一成果入口
Q2/                       # 同理，按实际问题数建立
```

`main` 保存稳定、已复核的阶段成果及最终版本；未完成实验留在对应问题分支。问题分支是同一共享仓库里的分支，不必各自 Fork。所有人遵守 [上传规范](上传规范.md)。

## 日常操作（以 Q1 为例）

首次克隆后，若远程已经有 q1：

```bash
git clone https://github.com/timoler/2026_competition.git
cd 2026_competition
git fetch origin
git switch --track origin/q1
```

若尚未创建，由负责人从最新 main 创建（其他问题替换数字）：

```bash
git switch main
git pull --ff-only origin main
git switch -c q1
git push -u origin q1
```

每次工作前拉取自己分支；提交时明确选择自己的目录：

```bash
git switch q1
git pull --ff-only origin q1
git add Q1/
git diff --cached --stat
git diff --cached
git commit -m "feat(q1): 完成基线模型并附运行结果"
git push origin q1
```

代码、结果、图和 README 一起更新。通过复核后在 GitHub 发起 `q1 → main` 的 Pull Request（合并请求），由另一位队友检查并合并。不需要额外建审批系统或自动化流水线。

## 论文手如何取成果

在 **main** 打开 `Q1/README.md`、`Q2/README.md` 等，先看“当前状态”“最终结果”“论文图表清单”“复核记录”。清单必须链接到具体文件，并给出单位、图注和论文用途。未标记“最终”的稳定阶段结果仍可能更新；不要仅凭文件名认定最终版本。

尚未合并的内容可切换问题分支查看，但只能作为草稿参考。定稿时记录采用的 main 提交编号，确保正文数值、结果表和图来自同一版本。
