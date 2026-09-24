# 海龟汤 · 推理手册 + 档案流水线

> 海龟汤（情境推理谜题）怎么推、怎么记、怎么收：角色分工、推理方法论、提问纪律，外加一条 `turtle` 档案流水线（含**数学反推求解器**）。

## 这是什么

分工是死的：**出题方给汤面与线索，推理方还原汤底**。本仓两份东西：

- **`SKILL.md` + `references/推理方法论.md`** —— 怎么推：读汤面拆解 → 末日三问定调 → 从宽到窄生成假设 → 是/否自问收敛 → 线索整合 → 收束判断。附常见误导设定与复盘套路。
- **`scripts/turtle.py`** —— 怎么记、怎么收：一手一条命令，把「建档 / 线索登记 / 验证关卡原样归档 / 提交并反推 / 官方答案收录 / 复盘 + 索引重建」全焊成 CLI，别手贴 md。

几条纪律是血换来的：**线索到达全栏目同步**（只记事实 = 没登记）、**验证关卡题面连同全部选项原样归档**、**官方答案原文逐字收录**（与解读分离，防记忆污染）、**重复提交禁令**（没有新线索就重排再交 = 降智）、**数学反推优先于故事脑补**。

## turtle CLI

```bash
python3 scripts/turtle.py new "手指所向" --soup "<汤面原文>" --source 经典
python3 scripts/turtle.py lead "<线索原文>"                      # 记进「已确认事实」
python3 scripts/turtle.py quiz A "<问题>" "1 … / 2 … / 3 …"      # 关卡题面 + 全部选项原样归档
python3 scripts/turtle.py submit A=2 B=4 C=7 --wrong 2           # 记一轮提交 + 数学反推
python3 scripts/turtle.py answer "<官方答案原文>"                 # 原文逐字收录
python3 scripts/turtle.py close --replied "<新套路>"              # 复盘落定 + 索引标已还原
python3 scripts/turtle.py show / index [--backfill]              # 看局面 / 重建索引
```

**数学反推是真在算**：候选空间 = 各关选项数的笛卡尔积，每轮「错 N 个」就是一条硬约束，全筛一遍后告诉你——还剩几种可能、每题还可能是什么、什么时候锁死。若某轮反馈与已记约束**互相矛盾**，它会报冲突并列出可疑的旧约束（不会静默给你一个空）；同一组合再交一遍会被拦下（没新信息）。

**索引从档案 meta 重建**（`index`）——手改会被下一次冲掉；`index --backfill` 能把没有 meta 的旧档补上，缺 meta 的档会在索引里显式标出、不会被悄悄丢掉。

## 存档与私档

**一局一档的档案、真题集、出题史都不在本仓**——那是出题方的私人记录。本仓只有方法、纪律、模板与工具；CLI 默认把档案写进 `<数据根>/workspace/records/sea-turtle-soup/`（`$GAME_HOME` 可改，`--archive` 可覆盖，引擎里没有写死的绝对路径）。

**题源要标**：建局时 `--source 经典|自编`。第三方原题不入档——题面是别人的东西，只记来源。

## 目录

| 路径 | 内容 |
|:---|:---|
| `SKILL.md` | 入口：角色分工、推理流程、提问纪律、工具用法 |
| `references/推理方法论.md` | 推理方法论全文（含 T 分级速查、误导设定、三选一提交准则） |
| `templates/对局模板.md` | 一局档案的栏目骨架 |
| `scripts/turtle.py` | 档案流水线 CLI（建档 / 线索 / 关卡 / 提交+反推 / 答案 / 复盘 / 索引） |
| `scripts/turtle_selftest.py` | 回归自测（51 项：建档 / 反推求解器 / 冲突检测 / 索引重建） |

```bash
python3 scripts/turtle_selftest.py    # 51 项，临时目录跑
```

## 姊妹仓库

**同一族（聊天里能玩的东西）**

- [liya-chat-game-referee](https://github.com/feverZHONG/liya-chat-game-referee) —— 回合制棋盘游戏裁判：扫雷 / 五子棋 / 大话骰 / 骗子牌 / 掷骰
- [liya-spy-game](https://github.com/feverZHONG/liya-spy-game) —— 谁是卧底：黑板规则 / 出题方法论 / 身份分配器

**莉娅名下其他**

- [liya-vision-recognition-traps](https://github.com/feverZHONG/liya-vision-recognition-traps) —— 视觉模型识图陷阱手册
- [liya-subtraction-skill](https://github.com/feverZHONG/liya-subtraction-skill) —— 技能库做减法的方法论
- [liya-persona-authoring](https://github.com/feverZHONG/liya-persona-authoring) —— 人格 / 身份文件的写法
- [liya-sillytavern-cards](https://github.com/feverZHONG/liya-sillytavern-cards) —— 酒馆角色卡写法与工具
- [liya-sillytavern-worldbook](https://github.com/feverZHONG/liya-sillytavern-worldbook) —— 酒馆世界书（Lorebook）：触发链源码实证 + 触发体检 / 模拟 / 生成工具

## 提思路 / 提修正

- 新的推理套路、误导设定、求解器改进 → 开 [Issue](https://github.com/feverZHONG/liya-sea-turtle-soup/issues)
- 想直接改 → Fork + PR

## 许可

MIT —— 拿去用、改、再发，保留版权声明即可。

---

*莉娅（[@feverZHONG](https://github.com/feverZHONG)）· 宇宙美好记录官*
