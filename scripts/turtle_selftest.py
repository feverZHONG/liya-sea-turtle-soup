#!/usr/bin/env python3
"""海龟汤档案流水线 CLI 上桌前的自测（回归）。全绿才上桌；有 FAIL 就非零退出。

用法:
  python3 scripts/turtle_selftest.py                    # 自测同目录的 turtle.py
  python3 scripts/turtle_selftest.py /path/to/turtle.py # 自测别的 CLI
  python3 scripts/turtle_selftest.py --keep             # 保留临时目录看现场

覆盖（按真实对局顺序，临时数据根、不碰正式私档）：
  空数据根 show 友好提示 → 首次 new 不崩 → 档案 meta / 栏目齐 / 汤面进档
  → lead / quiz（含斜杠的选项原样）/ answer 写进去读得回来
  → 数学反推：空间 A(8)×B(7)×C(8)=448 → 逐轮收缩 → 锁定 4/2/7
  → 重复提交告警不计入 / 无收缩提醒 / 矛盾提交报冲突（不静默给空）
  → 连续 new 编号递增不撞名 / --space 手动给空间 / 没官方答案不给 close
  → close 落定 + 索引标已还原 + 同一天重收被挡
  → 旧格式（无 meta）档：index 显式标「缺 meta」→ --backfill 补 meta 并按复盘判状态
  → 数据根走 $GAME_HOME 与「往上找带 temp/ 或 workspace/ 的一层」两条路

为什么要有这个：
  档案 CLI 的坑不在建档那条顺路上，而在「旧档没有 meta」「反馈互相打架」「同一组合交第二遍」
  这些边界上——手点两下碰不到，真开局才炸。改完 CLI 先跑这个，十几秒的事。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SELF = os.path.dirname(os.path.abspath(__file__))
META_RE = re.compile(r"<!-- meta (\{.*?\}) -->")
ROUND_RE = re.compile(r"- \[[^\]]*\] 第 \d+ 轮提交：")
SECTIONS = ["## 〇、验证关卡", "## 一、末日三问定调", "## 二、已确认事实", "## 三、当前假设",
            "## 四、推理历程", "## 五、汤底还原", "### 官方答案原文", "### 本天使还原解读",
            "## 六、提交记录", "## 七、复盘"]

LEGACY_DONE = """# 031 · 旧格式样本

> 汤面：旧档没有 meta，靠 `# <编号> · <题名>` 标题行补。

## 二、已确认事实

- 早年的一条线索

## 七、复盘

- 三选一结果：第三轮全对
- 翻车点：无
"""

LEGACY_SOLVE = """# 030 · 旧格式反推样本

> 汤面：旧档手写的关卡与提交记录，也要能读回来做数学反推。

## 〇、三选一关卡（三道全对才还原汤底）

**A. 甲问？**
1 一 / 2 二 / 3 三 / 4 四 / 5 五 / 6 六 / 7 七 / 8 八

**B. 乙问？**
1 一 / 2 二 / 3 三 / 4 四 / 5 五 / 6 六 / 7 七

**C. 丙问？**
1 一 / 2 二 / 3 三 / 4 四 / 5 五 / 6 六 / 7 七 / 8 八

## 六、提交记录

- [2020-01-01] 首轮提交两个方案：
  - 方案一：A=1 一 / B=1 一 / C=1 一 → 错3
  - 方案二：A=4 四 / B=2 二 / C=7 七 → 全对
"""

LEGACY_WIP = """# 032 · 没复盘样本

> 汤面：开了局还没推完的旧档。

## 二、已确认事实

- 刚开题
"""


class Harness:
    def __init__(self, cli):
        self.work = tempfile.mkdtemp(prefix="turtle-selftest-")
        self.script = os.path.join(self.work, "scripts", "turtle.py")
        os.makedirs(os.path.dirname(self.script), exist_ok=True)
        shutil.copy(cli, self.script)
        tpl_src = os.path.join(os.path.dirname(os.path.abspath(cli)), os.pardir, "templates")
        if os.path.isdir(tpl_src):   # 模板按脚本位置找同级 ../templates/ ——一起拷，别让它扑空
            shutil.copytree(tpl_src, os.path.join(self.work, "templates"))
        self.data = os.path.join(self.work, "data")
        self.archive = os.path.join(self.data, "workspace", "records", "sea-turtle-soup")
        self.results = []

    def run(self, *args, home="tmp", script=None, cwd=None):
        """home='tmp' 用临时数据根；home=None 不设 $GAME_HOME（走往上找那一层）；home=路径 用指定根。"""
        env = dict(os.environ)
        if home == "tmp":
            env["GAME_HOME"] = self.data
        elif home is None:
            env.pop("GAME_HOME", None)
        else:
            env["GAME_HOME"] = str(home)
        p = subprocess.run([sys.executable, script or self.script, *args],
                           capture_output=True, text=True, env=env, cwd=cwd or self.work)
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    def check(self, title, ok, detail=""):
        self.results.append((title, bool(ok)))
        print(("PASS " if ok else "FAIL ") + title + (f"  [{detail}]" if detail else ""))

    def md(self, name, archive=None):
        with open(os.path.join(archive or self.archive, name), encoding="utf-8") as f:
            return f.read()

    def unquote(self, body, key):
        """取 `### <key>` 下那段的引用文本，`> ` 前缀剥掉——用来验「逐字收录」。"""
        lines = body.splitlines()
        out, on = [], False
        for l in lines:
            if l.startswith("### "):
                on = key in l
                continue
            if on:
                out.append(re.sub(r"^>\s?", "", l))
        return "\n".join(out).strip()


def main():
    argv = [a for a in sys.argv[1:] if a != "--keep"]
    keep = "--keep" in sys.argv
    cli = argv[0] if argv else os.path.join(SELF, "turtle.py")
    if not os.path.exists(cli):
        sys.exit(f"找不到 CLI: {cli}")

    h = Harness(cli)
    soup = "小优拼命用她的食指指向地面，试图吸引别人的注意，可是周围的人却没在她脚边发现什么特别的东西。"
    opts_a = "1 在做梦 / 2 话剧表演 / 3 在弹琴 / 4 让别人看他们自己脚下 / 5 网络直播 / 6 告诉别人自己的位置 / 7 让别人看小优的脚 / 8 舞蹈表演"
    answer = "她食指朝下，对着镜头说：欢迎点击下方链接购买。\n购买链接是后期加上的，在场的人看不见。"

    # ---- A. 空档案目录 + 首次 new ----
    rc, out = h.run("show")
    h.check("空数据根 show 给中文提示不崩", rc != 0 and "还没有对局档案" in out and "Traceback" not in out,
            out.strip()[:60])

    rc, out = h.run("new", "手指所向", "--soup", soup, "--source", "经典")
    h.check("首次 new 跑通（空数据根，目录都是现建的）", rc == 0 and "Traceback" not in out, out.strip()[:80])
    h.check("new 打印档案路径", "001-手指所向.md" in out, out.strip().replace("\n", " | ")[:90])
    path1 = os.path.join(h.archive, "001-手指所向.md")
    h.check("档案落在数据根下", os.path.exists(path1), path1.replace(h.work, "$T"))
    body = h.md("001-手指所向.md")
    hit_meta = META_RE.search(body)
    meta = json.loads(hit_meta.group(1)) if hit_meta else {}
    h.check("档案含 meta 且四要素齐",
            meta.get("number") == "001" and meta.get("title") == "手指所向"
            and meta.get("source") == "经典" and meta.get("status") == "进行中", json.dumps(meta, ensure_ascii=False))
    miss = [s for s in SECTIONS if s not in body]
    h.check("模板栏目齐（关卡/三问/事实/假设/历程/汤底/原文/解读/提交/复盘）", not miss, str(miss))
    h.check("汤面原文进档（连标点照录）", soup in body)
    idx = h.md("对局记录.md")
    h.check("索引已建且含这一档", "001-手指所向.md" in idx and "进行中" in idx, idx.splitlines()[-1])

    # ---- B. 线索 / 关卡 / 提交（数学反推） ----
    rc, out = h.run("lead", "小优是在进行某种表演（某种程度上可以认为是的）")
    body = h.md("001-手指所向.md")
    h.check("lead 写进「已确认事实」并带日期",
            "小优是在进行某种表演" in body and re.search(r"- \[\d{4}-\d{2}-\d{2}\] 小优是在进行", body) is not None)
    h.check("lead 提醒全栏目同步（三问定调/当前假设/推理历程）",
            all(k in out for k in ("三问定调", "当前假设", "推理历程")), out.strip().splitlines()[-1][:80])

    for letter, q, o in (("A", "小优在做什么？", opts_a),
                         ("B", "在小优周围都是什么人？", "1 通灵者 / 2 同学 / 3 医生和护士 / 4 消防队 / 5 观众 / 6 相亲候补 / 7 同事"),
                         ("C", "小优实际指向的是什么？", "1 磁场的方向 / 2 陷阱 / 3 她的移动方向 / 4 一台手机 / 5 地球的另外一边 / 6 购物链接 / 7 键盘上的字母 / 8 她的尸体")):
        rc, out = h.run("quiz", letter, q, o)
        h.check(f"quiz {letter} 归档跑通", rc == 0 and f"{letter} 已归档" in out, out.strip()[:60])
    body = h.md("001-手指所向.md")
    h.check("quiz 选项原样（斜杠分隔一字不差）", opts_a in body and "\n" + opts_a + "\n" in body)
    h.check("quiz 题干原样进档", "**A. 小优在做什么？**" in body)
    rc, out = h.run("quiz", "A", "改过的题干？", "1 只留两个 / 2 选项")
    h.check("quiz 同关卡重调 = 覆盖不重复",
            "改过的题干" in out or "覆盖旧内容" in out)
    h.run("quiz", "A", "小优在做什么？", opts_a)   # 还原成正题，继续用
    body = h.md("001-手指所向.md")
    h.check("覆盖后 A 只有一处（不留旧版本）", body.count("**A. ") == 1, f"×{body.count('**A. ')}")

    rc, out = h.run("solve")
    h.check("solve 算出候选空间 A(8)×B(7)×C(8) = 448", "448" in out and "A(8)" in out, out.strip().splitlines()[1][:60])
    h.check("solve 不新增提交", len(ROUND_RE.findall(h.md("001-手指所向.md"))) == 0)

    rc, out = h.run("submit", "A=1", "B=1", "C=1", "--wrong", "3")
    h.check("首轮全错 → 每题排除该选项（448 → 294）",
            rc == 0 and "剩余候选：294 / 448" in out and "A 2/3/4/5/6/7/8" in out,
            " / ".join(l.strip() for l in out.splitlines() if "剩余候选" in l or "仍可能" in l))
    rc, out = h.run("submit", "A=4", "B=2", "C=7", "--wrong", "0")
    h.check("提交全对 → 锁到真答案 4/2/7",
            rc == 0 and "剩余候选：1 / 448" in out and "锁定：A=4 / B=2 / C=7 ✓" in out,
            " / ".join(l.strip() for l in out.splitlines() if "锁定" in l))
    rc, out = h.run("submit", "A=4", "B=2", "C=1", "--wrong", "1")
    h.check("没带来收缩的那轮要提醒（没新信息，等线索）",
            rc == 0 and "候选空间收缩" in out and "剩余候选：1 / 448" in out,
            " / ".join(l.strip() for l in out.splitlines() if "收缩" in l))
    n_rounds = len(ROUND_RE.findall(h.md("001-手指所向.md")))
    rc, out = h.run("submit", "A=4", "B=2", "C=1", "--wrong", "1")
    h.check("同一组合再交 → 告警不计入", rc == 0 and "交过了" in out and "不计入" in out,
            out.strip().splitlines()[0][:60])
    h.check("重复提交没多记一轮（还是 3 轮）",
            len(ROUND_RE.findall(h.md("001-手指所向.md"))) == n_rounds == 3)
    rc, out = h.run("submit", "A=3", "B=3", "C=3", "--wrong", "0")
    h.check("矛盾提交报冲突（不静默给空）",
            rc == 0 and "冲突" in out and "可疑约束" in out and "去掉后剩" in out,
            " / ".join(l.strip() for l in out.splitlines() if "冲突" in l or "可疑" in l))
    h.check("冲突那轮不写进档案（先查清楚）",
            len(ROUND_RE.findall(h.md("001-手指所向.md"))) == 3)

    # ---- C. 官方答案 / 复盘 / 索引 ----
    rc, out = h.run("answer", answer)
    h.check("answer 收录跑通并提示解读分离", rc == 0 and "逐字" in out and "解读" in out, out.strip()[:70])
    body = h.md("001-手指所向.md")
    h.check("官方答案原文逐字读回（两行都不少）", h.unquote(body, "官方答案原文") == answer,
            h.unquote(body, "官方答案原文").replace("\n", "⏎"))
    h.check("解读栏另开、没被原文污染", "### 本天使还原解读" in body
            and "她食指朝下" not in h.unquote(body, "本天使还原解读"))

    rc, out = h.run("close", "--replied", "后期叠加的东西，在场的人看不见")
    h.check("close 跑通并打索引路径", rc == 0 and "对局记录.md" in out, out.strip().replace("\n", " | ")[:80])
    body = h.md("001-手指所向.md")
    meta = json.loads(META_RE.search(body).group(1)) if META_RE.search(body) else {}
    h.check("close 后 meta 标已还原", meta.get("status") == "已还原")
    h.check("复盘栏落定 + 新套路入档", "复盘落定" in body and "后期叠加的东西，在场的人看不见" in body)
    h.check("复盘写进的是「七、复盘」栏（不串栏）",
            "复盘落定" in body.split("## 七、复盘")[-1])
    idx = h.md("对局记录.md")
    h.check("索引标「已还原」", "已还原" in idx and "001-手指所向.md" in idx)
    rc, out = h.run("close")
    h.check("同一天重收被挡", rc != 0 and "今天已经收过" in out, out.strip()[:50])

    # ---- D. 编号递增 / --space / 收局守卫 ----
    names = []
    for t in ("第二题", "第三题", "第四题"):
        rc, out = h.run("new", t, "--soup", f"{t}的汤面。")
        names.append(next((m for m in re.findall(r"\d{3}-[^\s]+\.md", out)), ""))
    h.check("连续 new 编号递增、不撞名",
            names == ["002-第二题.md", "003-第三题.md", "004-第四题.md"], str(names))
    h.check("三档都落了盘",
            all(os.path.exists(os.path.join(h.archive, n)) for n in names))
    rc, out = h.run("submit", "A=2", "B=4", "C=7", "--wrong", "1", "--space", "A=8", "B=7", "C=8")
    h.check("没归档 quiz 时 --space 手动给空间", rc == 0 and "448" in out and "第 1 轮" in out,
 " / ".join(l.strip() for l in out.splitlines() if "候选空间" in l))
    rc, out = h.run("close")
    h.check("没官方答案原文不给 close（不收半截档案）",
            rc != 0 and "官方答案原文" in out, out.strip()[:60])
    rc, out = h.run("show")
    h.check("show 报当前局（编号最大那档）",
            rc == 0 and "004" in out and "关卡：还没归档 quiz" in out, out.strip().splitlines()[1][:70])

    # ---- E. 旧格式（无 meta）档：标出来 → backfill ----
    os.makedirs(h.archive, exist_ok=True)
    with open(os.path.join(h.archive, "031-旧格式样本.md"), "w", encoding="utf-8") as f:
        f.write(LEGACY_DONE)
    with open(os.path.join(h.archive, "032-没复盘样本.md"), "w", encoding="utf-8") as f:
        f.write(LEGACY_WIP)
    rc, out = h.run("index")
    h.check("index 不静默丢旧档：显式标「缺 meta」", "缺 meta" in out and "031-旧格式样本" in out,
            out.strip().splitlines()[-1][:80])
    h.check("缺 meta 也写进索引文件（不只打印）",
            "缺 meta" in h.md("对局记录.md") and "031-旧格式样本.md" in h.md("对局记录.md"))
    rc, out = h.run("index", "--backfill")
    b31, b32 = h.md("031-旧格式样本.md"), h.md("032-没复盘样本.md")
    m31 = json.loads(META_RE.search(b31).group(1)) if META_RE.search(b31) else {}
    m32 = json.loads(META_RE.search(b32).group(1)) if META_RE.search(b32) else {}
    h.check("--backfill 给旧档补上 meta（编号/题名取自标题行）",
            m31.get("number") == "031" and m31.get("title") == "旧格式样本"
            and m32.get("number") == "032", f"{m31} / {m32}")
    h.check("--backfill 按复盘栏判状态（有实质内容 = 已还原）",
            m31.get("status") == "已还原" and m32.get("status") == "进行中",
            f"{m31.get('status')} / {m32.get('status')}")
    h.check("backfill 后索引里不再有「缺 meta」",
            "缺 meta" not in h.md("对局记录.md") and "031" in h.md("对局记录.md"))
    h.check("backfill 后旧档内容没被改坏（事实/复盘还在）",
            "早年的一条线索" in b31 and "翻车点：无" in b31)

    # ---- E2. 旧格式档案直接反推（选项数从旧档的关卡栏数，提交记录认手写「方案…→错N」） ----
    legacy_dir = os.path.join(h.work, "legacy-arch")
    os.makedirs(legacy_dir, exist_ok=True)
    with open(os.path.join(legacy_dir, "030-旧格式反推样本.md"), "w", encoding="utf-8") as f:
        f.write(LEGACY_SOLVE)
    rc, out = h.run("solve", "--archive", legacy_dir)
    h.check("旧格式档也能反推：选项数从关卡栏数、提交记录认手写写法",
            rc == 0 and "A(8) × B(7) × C(8) = 448" in out and "2 轮提交" in out,
            " / ".join(l.strip() for l in out.splitlines() if "候选空间" in l or "约束" in l))
    h.check("旧格式档反推到真答案（全对那轮锁 4/2/7）", "锁定：A=4 / B=2 / C=7 ✓" in out,
            " / ".join(l.strip() for l in out.splitlines() if "锁定" in l))

    # ---- F. 编号取下一个空号（中间空号要填回来） ----
    rc, out = h.run("new", "第五题", "--soup", "汤面。")
    h.check("编号取下一个空号（1-4 已用 + 31/32 占位 → 005）", "005-第五题.md" in out, out.strip()[:60])

    # ---- G. 数据根的另一条路：往上找带 temp/ 的一层 ----
    root2 = tempfile.mkdtemp(prefix="turtle-selftest-root-")
    os.makedirs(os.path.join(root2, "temp"))
    os.makedirs(os.path.join(root2, "scripts"))
    shutil.copy(cli, os.path.join(root2, "scripts", "turtle.py"))
    if os.path.isdir(os.path.join(h.work, "templates")):
        shutil.copytree(os.path.join(h.work, "templates"), os.path.join(root2, "templates"))
    rc, out = h.run("new", "无GAME_HOME", "--soup", "汤面。", home=None, script=os.path.join(root2, "scripts", "turtle.py"))
    hit = os.path.join(root2, "workspace", "records", "sea-turtle-soup", "001-无GAME_HOME.md")
    h.check("没 $GAME_HOME 时往上找到带 temp/ 的那层当数据根", rc == 0 and os.path.exists(hit),
            os.path.relpath(hit, root2))

    # ---- H. --archive 覆盖默认档案目录 ----
    other = os.path.join(h.work, "other-archive")
    rc, out = h.run("new", "换目录", "--soup", "汤面。", "--archive", other)
    h.check("--archive 覆盖默认档案目录",
            rc == 0 and os.path.exists(os.path.join(other, "001-换目录.md"))
            and os.path.exists(os.path.join(other, "对局记录.md")), out.strip()[:60])

    failed = [t for t, ok in h.results if not ok]
    print("\n" + ("全绿 ✓" if not failed else f"FAIL {len(failed)}/{len(h.results)}: " + ", ".join(failed)))
    print(f"通过 {len(h.results) - len(failed)}/{len(h.results)}")
    print("临时目录:", h.work)
    if not keep:
        shutil.rmtree(h.work, ignore_errors=True)
        shutil.rmtree(root2, ignore_errors=True)
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
