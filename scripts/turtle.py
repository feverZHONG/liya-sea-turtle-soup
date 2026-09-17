#!/usr/bin/env python3
"""海龟汤对局档案流水线 CLI：建档 / 线索登记 / 关卡原样归档 / 提交数学反推 / 官方答案收录 / 复盘收局。

用法:
  python3 turtle.py new "<题目简称>" --soup "<汤面原文>" [--source 经典|自编] [--archive DIR]
      从 templates/对局模板.md 建一档对局档案（编号取下一个空号，三位补零），写 meta、登记进索引，
      打印档案路径——一次命令建完，不用手 cp。
  python3 turtle.py lead "<线索原文>"             # 追加一条「已确认事实」（带日期）+ 提醒全栏目同步
  python3 turtle.py quiz A "<问题>" "1 xx / 2 xx / 3 xx"   # 关卡题面连同全部选项**原样**归档（可 A/B/C… 多次调）
  python3 turtle.py submit A=2 B=4 C=7 --wrong 2  # 记一轮提交（含错几个）并跑数学反推
  python3 turtle.py solve                         # 只算当前候选空间（不新增提交）
  python3 turtle.py answer "<官方答案原文>"        # 官方答案**逐字**收录（与解读分离，另开解读栏）
  python3 turtle.py close [--replied "<新套路>"]   # 复盘栏落定 → 索引标「已还原」→ INDEX 重建
  python3 turtle.py show / index [--backfill]     # 看当前局面 / 重建索引

数学反推（这个 CLI 的正事）:
  候选空间 = 各关卡选项数的笛卡尔积（选项数从 quiz 归档里数出来；没归档过 quiz 就 submit --space A=8 B=7 C=8）。
  每轮提交 (…, 错 w 个) 是一条硬约束 `#{i : 提交_i ≠ 真答案_i} == w`，把候选组合全筛一遍：
  全对 = 锁定；全错 = 每题排除该选项；筛空 = 这轮反馈与已记约束冲突（列可疑旧约束，不静默给空）；
  同一组合交过 = 告警不计入（没有新线索就重排再交 = 降智）。

档案与索引:
  一局一档 `<编号>-<题目简称>.md`，档内写 `<!-- meta {"number":…,"title":…,"source":…,"status":…} -->`。
  索引 `对局记录.md` 一律从各档 meta 重建——存档是唯一事实源，手改索引会被下一次冲掉。
  `index --backfill`：给没有 meta 的旧档按 `# <编号> · <题名>` 标题行补 meta 再重建；
  不加 --backfill 时，缺 meta 的档在索引里显式标「缺 meta」，不会被悄悄丢掉。
  当前局 = 档案目录里编号最大的那一档（新档永远最新）。

可用 --archive /path/to/dir 换档案目录（默认 <数据根>/workspace/records/sea-turtle-soup/）。
数据根：$GAME_HOME ＞ 往上找带 temp/ 或 workspace/ 的一层 ＞ 脚本上一级。引擎放哪都能跑。
"""
import datetime
import itertools
import json
import os
import re
import sys

# ---------- 数据根 ----------
# 档案落 <根>/workspace/records/。根怎么定：
#   ① $GAME_HOME 指哪儿是哪儿；
#   ② 否则从脚本位置往上找「带 temp/ 或 workspace/ 的那一层」；
#   ③ 都没有（别人 clone 出去单跑）就用脚本上一级。
# 引擎放哪都能跑——不必再拷一份到别处跑。
HERE = os.path.dirname(os.path.abspath(__file__))


def _data_root():
    env = os.environ.get("GAME_HOME")
    if env:
        return os.path.abspath(env)
    p = HERE
    while True:
        if os.path.isdir(os.path.join(p, "temp")) or os.path.isdir(os.path.join(p, "workspace")):
            return p
        up = os.path.dirname(p)
        if up == p:
            return os.path.dirname(HERE)
        p = up


ROOT = _data_root()
RECORDS_DIR = os.path.join(ROOT, "workspace", "records")
DEFAULT_ARCHIVE = os.path.join(RECORDS_DIR, "sea-turtle-soup")
SKILL_DIR = os.path.dirname(HERE)
TEMPLATE = os.path.join(SKILL_DIR, "templates", "对局模板.md")
INDEX_NAME = "对局记录.md"
LEGACY_SUB = "对局"            # 旧布局：档案在 <档案目录>/对局/ 下，顺手一起扫
META_RE = re.compile(r"<!-- meta (\{.*?\}) -->")
TITLE_RE = re.compile(r"^#\s*(\d{1,4})\s*[·・.．\-]\s*(.+?)\s*$")
QUIZ_RE = re.compile(r"^\*\*([A-Z])\.\s*(.*?)\*\*\s*$")
SUB_RE = re.compile(r"([A-Z]=\d.*?)→\s*(全对|错\s*(\d+))")
PAIR_RE = re.compile(r"([A-Z])\s*=\s*(\d+)")
HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TZ = datetime.timezone(datetime.timedelta(hours=8))   # 口径一律 +8，不写 UTC
MAX_SPACE = 2000000                                   # 候选空间上限（再多就不是「反推」是「瞎筛」了）

DEFAULTS = {"archive": DEFAULT_ARCHIVE, "soup": None, "source": None,
            "wrong": None, "replied": None, "space": [], "backfill": False}


def today():
    return datetime.datetime.now(TZ).strftime("%Y-%m-%d")


def _rel_or_abs(p):
    r = os.path.relpath(p, ROOT)
    return p if r.startswith("..") else r


def parse_argv(argv):
    pos, opts, i = [], dict(DEFAULTS), 0
    while i < len(argv):
        a = argv[i]
        if a in ("--soup", "--source", "--archive", "--wrong", "--replied"):
            if i + 1 >= len(argv):
                sys.exit(f"{a} 后面要跟一个值")
            opts[a[2:]] = argv[i + 1]
            i += 2
            continue
        if a.startswith(("--soup=", "--source=", "--archive=", "--wrong=", "--replied=")):
            k, v = a[2:].split("=", 1)
            opts[k] = v
            i += 1
            continue
        if a == "--backfill":
            opts["backfill"] = True
            i += 1
            continue
        if a == "--space":   # 手动给候选空间（该局没归档过 quiz 时用）
            i += 1
            while i < len(argv) and re.fullmatch(r"[A-Za-z]=\d+", argv[i]):
                opts["space"].append(argv[i])
                i += 1
            if not opts["space"]:
                sys.exit("--space 后面要跟 A=8 B=7 C=8 这样的选项数")
            continue
        if a.startswith("--space="):
            opts["space"].append(a.split("=", 1)[1])
            i += 1
            continue
        if a in ("-h", "--help"):
            print((__doc__ or "").strip())
            sys.exit(0)
        if a.startswith("-"):
            sys.exit(f"不认识的参数: {a}")
        pos.append(a)
        i += 1
    return pos, opts


# ---------- 文件读写 ----------
def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)  # 空目录首次用不许崩
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_md(path, lines):
    """落 md：连续空行收成一空行（占位行剔掉后留的串空行），结尾保证一个换行。"""
    write_text(path, re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip("\n") + "\n")


def index_path(archive):
    return os.path.join(archive, INDEX_NAME)


def archive_subdir(archive):
    """新档落哪儿：既有私档是 <档案目录>/对局/ 布局（那 6 档都在里面），跟着它放；
    没有 对局/ 子目录的新目录就平铺——读的时候两种布局都认（见 archive_files）。"""
    sub = os.path.join(archive, LEGACY_SUB)
    return sub if os.path.isdir(sub) else archive


def _md_in(dirpath):
    try:
        names = sorted(os.listdir(dirpath))
    except OSError:
        return []
    return [os.path.join(dirpath, n) for n in names
            if n.endswith(".md") and n not in (INDEX_NAME, "INDEX.md")]


# ---------- meta（索引的唯一事实源） ----------
def _meta_of(path):
    """读一档档案的 `<!-- meta {...} -->`（INDEX 靠它重建，存档是唯一事实源）。"""
    try:
        with open(path, encoding="utf-8") as f:
            m = META_RE.search(f.read())
        return json.loads(m.group(1)) if m else None
    except (OSError, ValueError):
        return None


def _fmt_meta(d):
    meta = {k: d.get(k, "") for k in ("number", "title", "source", "status")}
    return "<!-- meta " + json.dumps(meta, ensure_ascii=False) + " -->"


def _title_of(path):
    """从 `# <编号> · <题名>` 标题行取 (编号, 题名)——旧档（没有 meta）靠它补。"""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = TITLE_RE.match(line.rstrip("\n"))
                if m:
                    return m.group(1), m.group(2)
    except OSError:
        pass
    return None, None


def set_meta(path, **kw):
    """写 meta：有就改，没有就补在 H1 下面（旧档 backfill 走这条路）。"""
    text = read_text(path)
    num, title = _title_of(path)
    meta = _meta_of(path) or {}
    if not meta.get("number"):
        meta["number"] = f"{int(num):03d}" if (num or "").isdigit() else ""
    if not meta.get("title"):
        meta["title"] = title or ""
    meta.setdefault("source", "经典")
    meta.setdefault("status", "进行中")
    meta.update(kw)
    line = _fmt_meta(meta)
    if META_RE.search(text):
        text = META_RE.sub(lambda m: line, text, count=1)
    else:
        lines = text.splitlines()
        idx = next((i for i, l in enumerate(lines) if l.startswith("# ")), -1)
        lines[idx + 1:idx + 1] = ["", line]
        text = "\n".join(lines) + "\n"
    write_text(path, text)


# ---------- 档案发现 ----------
def archive_files(archive):
    """档案目录下的对局 md（顺带扫旧布局 <档案目录>/对局/），返回 [(编号|None, 题名, 路径)]。"""
    out = []
    for p in _md_in(archive) + _md_in(os.path.join(archive, LEGACY_SUB)):
        meta = _meta_of(p) or {}
        num, title = meta.get("number"), meta.get("title")
        if not num or not title:
            n2, t2 = _title_of(p)
            num, title = num or n2, title or t2
        out.append((int(num) if str(num or "").isdigit() else None,
                    title or os.path.basename(p)[:-3], p))
    out.sort(key=lambda r: (r[0] is None, r[0] or 0, r[2]))
    return out


def current_path(archive):
    """当前局 = 编号最大的那一档（新档永远最新）。"""
    rows = [r for r in archive_files(archive) if r[0] is not None]
    if not rows:
        sys.exit(f"档案目录里还没有对局档案：{_rel_or_abs(archive)}（先 turtle new \"<题目简称>\" --soup \"…\"）")
    return rows[-1][2]


# ---------- md 栏目 ----------
def _heading_spans(lines):
    spans = []
    for i, l in enumerate(lines):
        m = HEAD_RE.match(l)
        if m:
            spans.append((i, len(m.group(1)), m.group(2).strip()))
    return spans


def section_range(lines, key, levels=(2,)):
    """按标题关键词定位栏目，返回 (起行, 止行, 标题)——`## 一、末日三问定调` 用 '末日三问' 找。"""
    spans = _heading_spans(lines)
    for k, (i, lv, title) in enumerate(spans):
        if key in title and lv in levels:
            end = len(lines)
            for j, lv2, _t in spans[k + 1:]:
                if lv2 <= lv:
                    end = j
                    break
            return i, end, title
    return None


def read_section(path, key, levels=(2,)):
    """读栏目正文行（不含标题行）；栏目不在返回 None。"""
    lines = read_text(path).splitlines()
    r = section_range(lines, key, levels)
    return None if not r else lines[r[0] + 1:r[1]]


def _pop_tail(body):
    """栏目尾的空白行与 `---` 分隔线先提出来——新内容插在它们前面，分隔线别顶到中间去。"""
    tail = []
    while body and (not body[-1].strip() or body[-1].strip() == "---"):
        tail.insert(0, body.pop())
    return tail


def append_section(path, key, new_lines, levels=(2,)):
    """往栏目尾追加（save 前 makedirs 已在 write_text 里）。"""
    text = read_text(path)
    lines = text.splitlines()
    r = section_range(lines, key, levels)
    if not r:
        sys.exit(f"档案里没有「{key}」栏目：{_rel_or_abs(path)}——先 turtle new 建档，或手工补栏目")
    start, end = r[0] + 1, r[1]
    body = lines[start:end]
    tail = _pop_tail(body)
    if not body:
        body = [""]                       # 空栏目：标题与正文之间留一行
    lines[start:end] = body + list(new_lines) + [""] + tail
    write_md(path, lines)


# ---------- 关卡选项 / 提交记录（都从档案里读回，档案是唯一事实源） ----------
def count_options(s):
    """`1 xx / 2 xx / 3 xx` → 3（只在「斜杠+数字」处断，选项原文里带斜杠也不怕）。"""
    parts = [p for p in re.split(r"\s*/\s*(?=\d+\s)", s.strip()) if p.strip()]
    return len(parts)


def quiz_space(path):
    """从 〇 关卡归档里数选项数：{'A': 8, 'B': 7, …}——只数，不动题面与选项原文。"""
    out, body = {}, read_section(path, "关卡") or []
    for i, l in enumerate(body):
        m = QUIZ_RE.match(l.strip())
        if not m:
            continue
        opts = next((n.strip() for n in body[i + 1:] if n.strip()), "")
        n = count_options(opts)
        if n:
            out[m.group(1)] = n
    return out


def parse_constraints(path):
    """从「提交记录」栏读回每轮提交：[( {题: 答案}, 错几个 )]。

    认两种写法：CLI 自己写的 `第 N 轮提交：A=2 / B=4 → 错 2 个`，和旧档手写的
    `方案一：A=2 … / C=4 … → 错3`——只要「题=数 … → 错 N / 全对」就收，档案是唯一事实源。
    """
    out = []
    for l in read_section(path, "提交记录") or []:
        m = SUB_RE.search(l.strip())
        if not m:
            continue
        pairs = {k: int(v) for k, v in PAIR_RE.findall(m.group(1))}
        if not pairs:
            continue
        out.append((pairs, 0 if m.group(2).startswith("全对") else int(m.group(3))))
    return out


def space_of(path, opts, sub=None):
    """候选空间：先数 quiz 归档，缺的用 --space 补（该局没归档过 quiz 时）。"""
    space = quiz_space(path)
    for pair in opts.get("space") or []:
        m = re.fullmatch(r"([A-Za-z])=(\d+)", pair.strip())
        if m and m.group(1).upper() not in space:
            space[m.group(1).upper()] = int(m.group(2))
    for l in sorted(sub or {}):
        if l not in space:
            sys.exit(f"关卡 {l} 没有归档选项数——先 turtle quiz {l} \"…\" \"1 … / 2 …\"，"
                     f"或 --space {l}=8 手动给")
    if not space:
        sys.exit("这局还没有关卡选项数——先 turtle quiz A \"…\" \"1 … / 2 …\"，"
                 "或 submit --space A=8 B=7 C=8 手动给")
    return space


# ---------- 数学反推 ----------
def combo_str(c, letters=None):
    return " / ".join(f"{k}={c[k]}" for k in (letters or sorted(c)))


def candidates(space, constraints):
    """筛一遍候选组合：每条约束 `#{提交_i ≠ 真答案_i} == 错几个` 都要满足。"""
    letters = sorted(space)
    total = 1
    for l in letters:
        total *= space[l]
    if total > MAX_SPACE:
        sys.exit(f"候选空间 {total} 太大——先核对关卡选项数（--space 是不是给多了）")
    out = []
    for combo in itertools.product(*[range(1, space[l] + 1) for l in letters]):
        c = dict(zip(letters, combo))
        if all(sum(1 for l, v in sub.items() if c.get(l) != v) == wrong
               for sub, wrong in constraints):
            out.append(c)
    return out


def report_conflict(space, constraints):
    print("  ⚠️ 这轮反馈与已记约束冲突：按现有约束筛，候选空间已经空了（不是无解，就是有人的数字记错了）。")
    print("  可疑约束（逐条去掉后重筛，剩 >0 的那条嫌疑最大）：")
    for i, (sub, wrong) in enumerate(constraints):
        rest = constraints[:i] + constraints[i + 1:]
        n = len(candidates(space, rest))
        tag = " ← 最新一轮" if i == len(constraints) - 1 else ""
        print(f"    {i + 1}. 第 {i + 1} 轮：{combo_str(sub)} → 错 {wrong} 个 ｜ 去掉后剩 {n}{tag}")
    print("  回头核对上面剩 >0 的那条（或这轮的「错几个」）——查清前这轮不记入档案。")


def show_solve(space, constraints):
    """唯一出口：候选空间 / 剩余候选数 / 每题仍可能的选项 / 剩余组合（≤20 全列）。"""
    letters = sorted(space)
    total = 1
    for l in letters:
        total *= space[l]
    print("  候选空间：" + " × ".join(f"{l}({space[l]})" for l in letters) + f" = {total}")
    if not constraints:
        print("  约束：还没有提交记录——先按线索推，提交要有背书（别上来就凭脑补组合）")
        return
    print(f"  约束：{len(constraints)} 轮提交")
    cands = candidates(space, constraints)
    if not cands:
        report_conflict(space, constraints)
        return
    poss = {l: sorted({c[l] for c in cands}) for l in letters}
    print(f"  剩余候选：{len(cands)} / {total}")
    print("  仍可能：" + " ｜ ".join(f"{l} " + "/".join(str(v) for v in poss[l]) for l in letters))
    head = cands[:20]
    for c in head:
        print("    " + combo_str(c, letters))
    if len(cands) > len(head):
        print(f"    ……还有 {len(cands) - len(head)} 个（先把线索用上再收窄）")
    if len(cands) == 1:
        print("  锁定：" + combo_str(cands[0], letters) + " ✓")


# ---------- 索引重建 ----------
INDEX_TAIL = """
## 新开一局流程

1. `turtle new "<题目简称>" --soup "<汤面原文>" --source 经典|自编` —— 建档 + 自动登记索引（不用手 cp 模板）
2. 推理推进时同步更新档案（已确认事实 / 当前假设 / 推理历程 / 提交记录）——线索到达**全栏目同步**；验证关卡题面 + 全部选项原样归档
3. 官方答案确认后：汤底还原先**原文完整收录**（解读分离）→ 补全三问定调最终结论 + 复盘栏 → `turtle close --replied "<新套路>"`
4. 新套路写回 `references/推理方法论.md`，SKILL.md 如有流程/纪律级教训同步更新

---

*莉娅 · 题目索引 · 进度跟着阁下走*
"""

INDEX_HEAD = """# 海龟汤 · 对局索引

> 一局一档 `<编号>-<题目简称>.md`，档案是私档（不在 skill 仓里）。
> 本页由各档 `<!-- meta … -->` 自动重建（`turtle index`）——**手改会被下一次冲掉**，要改就改档案的 meta。

## 索引

| 编号 | 题目 | 来源 | 状态 | 对局文件 |
|------|------|------|------|---------|
"""


def _review_substantial(path):
    """复盘栏有没有实质内容 → 旧档算不算「已还原」（注释块、表格线不算）。"""
    for l in read_section(path, "复盘") or []:
        s = l.strip()
        if not s or s[0] in ">|" or s.startswith("---"):
            continue
        return True
    return False


def backfill(archive):
    """给没有 meta 的旧档按 `# <编号> · <题名>` 补 meta：复盘栏有实质内容 = 已还原。"""
    n = 0
    for num, title, path in archive_files(archive):
        if _meta_of(path):
            continue
        if num is None and not title:
            continue          # 连标题行都没有：补不了，索引里标「缺 meta」
        status = "已还原" if _review_substantial(path) else "进行中"
        set_meta(path, number=f"{num:03d}" if num else "", title=title or "", status=status)
        print(f"  补 meta：{os.path.basename(path)} → {num or '—'} {title}｜{status}（来源未知的按 经典 记）")
        n += 1
    return n


def rebuild_index(archive):
    """INDEX 从各档 md 的 meta 重建 —— 存档是唯一事实源，手改 INDEX 会被下一次冲掉。"""
    rows, missing = [], []
    for num, title, path in archive_files(archive):
        rel = os.path.relpath(path, archive)
        meta = _meta_of(path)
        if meta:
            rows.append((num if num is not None else 0, meta, rel))
        else:
            missing.append((num if num is not None else 0, title, rel))
    rows.sort(key=lambda r: r[0])
    missing.sort(key=lambda r: r[0])
    out = [INDEX_HEAD.rstrip("\n")]
    for num, meta, rel in rows:
        out.append(f"| {meta.get('number', '')} | {meta.get('title', '')} "
                   f"| {meta.get('source', '')} | {meta.get('status', '')} | [{rel}]({rel}) |")
    if missing:
        out.append("")
        out.append(f"## ⚠️ 缺 meta（{len(missing)} 档——跑 `turtle index --backfill` 补）")
        out.append("")
        for _num, title, rel in missing:
            out.append(f"- 缺 meta：{title}｜[{rel}]({rel})")
    out.append("")
    out.append("状态：进行中 / 已还原 / 放弃")
    out.append(INDEX_TAIL)
    write_text(index_path(archive), "\n".join(out) + "\n")
    return {"with_meta": len(rows), "missing": missing, "count": len(rows) + len(missing)}


# ---------- 建档 ----------
def _safe_name(title):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("_") or "对局"


def build_doc(number, title, soup, source):
    """按 templates/对局模板.md 生成一档档案（模板改格式，这里跟着变，不另抄一份骨架）。"""
    try:
        tpl = read_text(TEMPLATE)
    except OSError:
        sys.exit(f"找不到模板：{_rel_or_abs(TEMPLATE)}")
    SOUP = "@@汤面@@"
    lines = tpl.splitlines()
    i = next((k for k, l in enumerate(lines) if l.startswith("> 汤面")), 0)
    body = "\n".join(lines[i:])
    for k, v in (("{编号}", number), ("{题目简称}", title), ("{是/否/待确认}", "待确认"),
                 ("{理由}", "待补"), ("{原文}", SOUP)):
        body = body.replace(k, v)
    keep = [l for l in body.splitlines()
            if "{" not in l and "}" not in l
            and not l.startswith("> 有则填") and not l.startswith("> 官方答案确认后填写")]
    soup_q = "\n".join(("> " + l if k else l) for k, l in enumerate(soup.splitlines()))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).replace(SOUP, soup_q).rstrip("\n")
    meta = {"number": number, "title": title, "source": source, "status": "进行中"}
    return f"# {number} · {title}\n\n{_fmt_meta(meta)}\n\n{text}\n"


def cmd_new(rest, opts):
    if not rest:
        sys.exit('用法: turtle new "<题目简称>" --soup "<汤面原文>" [--source 经典|自编] [--archive DIR]')
    title = rest[0].strip()
    soup = (opts.get("soup") or "").strip()
    if not soup:
        sys.exit('new 要带汤面原文：--soup "<汤面原文>"（档案第一行就靠它）')
    source = (opts.get("source") or "经典").strip()
    if source not in ("经典", "自编"):
        sys.exit(f'--source 只认 经典|自编：{source}')
    archive = opts["archive"]
    used = {n for n, _t, _p in archive_files(archive) if n}
    n = 1
    while n in used:            # 下一个空号，不是 max+1（中间空号要能填回来）
        n += 1
    number = f"{n:03d}"
    target = archive_subdir(archive)
    os.makedirs(target, exist_ok=True)
    path = os.path.join(target, f"{number}-{_safe_name(title)}.md")
    if os.path.exists(path):
        sys.exit(f"档案已存在：{_rel_or_abs(path)}")
    write_text(path, build_doc(number, title, soup, source))
    info = rebuild_index(archive)
    print(f"  新档：{_rel_or_abs(path)}")
    print(f"  编号 {number}｜来源 {source}｜状态 进行中")
    print(f"  索引：{_rel_or_abs(index_path(archive))}（已登记，共 {info['count']} 档）")


# ---------- 线索 / 关卡 / 提交 / 答案 / 复盘 ----------
def cmd_lead(rest, opts):
    if not rest:
        sys.exit('用法: turtle lead "<线索原文>"')
    text = rest[0].strip()
    path = current_path(opts["archive"])
    body = read_section(path, "已确认事实") or []
    n = len([l for l in body if l.strip().startswith("-")])
    append_section(path, "已确认事实", [f"- [{today()}] {text}"])
    print(f"  已登记第 {n + 1} 条事实：{text}")
    print("  提醒：三问定调 / 当前假设 / 推理历程 也要跟着同步（全栏目更新，只记事实=没登记）")


def cmd_quiz(rest, opts):
    if len(rest) < 3:
        sys.exit('用法: turtle quiz A "<问题>" "1 … / 2 … / 3 …"（题面与选项都要带引号）')
    if len(rest) > 3:
        sys.exit('参数要加引号：turtle quiz A "<问题>" "1 … / 2 … / 3 …"')
    letter, question, options = rest[0].strip().upper(), rest[1].strip(), rest[2].strip()
    if not re.fullmatch(r"[A-Z]", letter):
        sys.exit(f"关卡编号用单个字母（A/B/C…）：{rest[0]}")
    n = count_options(options)
    path = current_path(opts["archive"])
    text = read_text(path)
    lines = text.splitlines()
    r = section_range(lines, "关卡")
    if not r:
        sys.exit(f"这档没有「〇、验证关卡」栏目：{_rel_or_abs(path)}")
    start, end = r[0] + 1, r[1]
    body, block, replaced = lines[start:end], [f"**{letter}. {question}**", options], False
    i = 0
    while i < len(body):
        m = QUIZ_RE.match(body[i].strip())
        if m and m.group(1) == letter:
            j = i + 1
            while j < len(body) and body[j].strip():
                j += 1
            body[i:j] = block
            replaced = True
            break
        i += 1
    if replaced:
        lines[start:end] = body
    else:
        tail = _pop_tail(body)
        body = (body + [""]) if body else [""]
        lines[start:end] = body + block + tail
    write_md(path, lines)
    print(f"  关卡 {letter} 已归档（{n} 选项，题面与选项原样）" + ("［覆盖旧内容］" if replaced else ""))
    if n < 2:
        print("  ⚠️ 只数出 1 个选项——选项串要写成「1 xx / 2 xx」这样，数学反推才数得准")


def cmd_submit(rest, opts):
    if not rest:
        sys.exit("用法: turtle submit A=2 B=4 C=7 --wrong 2")
    sub = {}
    for a in rest:
        m = re.fullmatch(r"([A-Za-z])=(\d+)", a)
        if not m:
            sys.exit(f"提交要写成 A=2 这样的键值对：{a}")
        sub[m.group(1).upper()] = int(m.group(2))
    if opts.get("wrong") is None:
        sys.exit("要带上 --wrong N（错几个；全对写 0）")
    try:
        wrong = int(opts["wrong"])
    except ValueError:
        sys.exit(f"--wrong 要整数：{opts['wrong']}")
    if not 0 <= wrong <= len(sub):
        sys.exit(f"--wrong {wrong} 超出这轮提交的题数 {len(sub)}")
    path = current_path(opts["archive"])
    space = space_of(path, opts, sub)
    constraints = parse_constraints(path)
    if any(c == sub for c, _w in constraints):
        print("  ⚠️ 这组合交过了，不计入——没有新线索就重排再交=降智（001 局教训：信息真空重排）。")
        show_solve(space, constraints)
        return
    before = len(candidates(space, constraints))
    new_list = constraints + [(sub, wrong)]
    if not candidates(space, new_list):
        show_solve(space, new_list)
        return
    rnd = len(constraints) + 1
    tail = "全对，汤底还原 ✓" if wrong == 0 else f"错 {wrong} 个"
    append_section(path, "提交记录", [f"- [{today()}] 第 {rnd} 轮提交：{combo_str(sub)} → {tail}"])
    print(f"  已记：第 {rnd} 轮 {combo_str(sub)} → {tail}")
    if len(candidates(space, new_list)) == before:
        print("  ⚠️ 这轮没带来任何候选空间收缩——没新信息，等线索（别再重排硬交）。")
    show_solve(space, new_list)


def cmd_solve(rest, opts):
    path = current_path(opts["archive"])
    print(f"  当前局：{_rel_or_abs(path)}")
    show_solve(space_of(path, opts), parse_constraints(path))


def cmd_answer(rest, opts):
    if not rest:
        sys.exit('用法: turtle answer "<官方答案原文>"')
    text = rest[0]
    if not text.strip():
        sys.exit("官方答案原文是空的——逐字收录，别塞空")
    path = current_path(opts["archive"])
    lines = read_text(path).splitlines()
    quote = [("> " + l) if l.strip() else ">" for l in text.splitlines()]
    sub = section_range(lines, "官方答案原文", levels=(3,))
    if sub:
        lines[sub[0] + 1:sub[1]] = [""] + quote + [""]
    else:
        top = section_range(lines, "汤底还原")
        if not top:
            sys.exit(f"这档没有「汤底还原」栏目：{_rel_or_abs(path)}")
        lines[top[0] + 1:top[0] + 1] = [""] + quote + ["", "### 本天使还原解读", ""]
    write_md(path, lines)
    print(f"  官方答案原文已收录（{len(text.splitlines())} 行，逐字）")
    if section_range(read_text(path).splitlines(), "本天使还原解读", levels=(3,)):
        print("  解读栏（### 本天使还原解读）另开——原文与解读分离存储，防记忆污染")
    else:
        print("  ⚠️ 档里没有「### 本天使还原解读」栏——解读另开一栏写，别混进原文")


def cmd_close(rest, opts):
    archive = opts["archive"]
    path = current_path(archive)
    stamp = f"- [{today()}] 复盘落定"
    if any(stamp in l for l in read_section(path, "复盘") or []):
        sys.exit("这局今天已经收过了（同一天不重收）——要补就明天再收。")
    ans = read_section(path, "官方答案原文", levels=(3,)) or []
    if not any(l.strip() for l in ans):
        sys.exit('档里还没有官方答案原文——先 turtle answer "<原文>"（登记完整性是 T0，不收半截档案）')
    constraints = parse_constraints(path)
    if constraints and constraints[-1][1] == 0:
        result = "最后一轮全对"
    elif constraints:
        result = f"最后一轮错 {constraints[-1][1]} 个"
    else:
        result = "没有提交记录"
    new = [f"{stamp}：{len(constraints)} 轮提交，{result}；官方答案已原文收录（与解读分离）→ 索引标「已还原」"]
    if opts.get("replied"):
        new.append(f"- 新套路入库：{opts['replied']}")
    append_section(path, "复盘", new)
    set_meta(path, status="已还原")
    info = rebuild_index(archive)
    print(f"  复盘已落定：{_rel_or_abs(path)}")
    print("  状态：进行中 → 已还原（meta 已改）")
    print(f"  索引：{_rel_or_abs(index_path(archive))}（重建，共 {info['count']} 档）")
    if opts.get("replied"):
        print("  提醒：新套路记得写回 references/推理方法论.md（skill 自我进化）")


def cmd_show(rest, opts):
    archive = opts["archive"]
    path = current_path(archive)
    meta = _meta_of(path) or {}
    num, t = _title_of(path)
    lines = read_text(path).splitlines()
    soup = re.sub(r"^>\s*汤面[：:]\s*", "", next((l.strip() for l in lines if l.startswith("> 汤面")), ""))
    space = quiz_space(path)
    cons = parse_constraints(path)
    facts = len([l for l in read_section(path, "已确认事实") or [] if l.strip().startswith("-")])
    ans = read_section(path, "官方答案原文", levels=(3,)) or []
    print(f"  当前局：{_rel_or_abs(path)}")
    print(f"  编号 {meta.get('number') or num or '—'} · {meta.get('title') or t or '—'}"
          f"｜来源 {meta.get('source') or '—'}｜状态 {meta.get('status') or '—'}")
    print(f"  汤面：{soup[:60]}{'…' if len(soup) > 60 else ''}")
    print("  关卡：" + ("、".join(f"{l}({space[l]})" for l in sorted(space)) if space else "还没归档 quiz")
          + f"｜已确认事实 {facts} 条｜提交 {len(cons)} 轮"
          + f"｜官方答案 {'已收录' if any(l.strip() for l in ans) else '未收录'}")
    if space:
        show_solve(space, cons)


def cmd_index(rest, opts):
    archive = opts["archive"]
    n_bf = backfill(archive) if opts.get("backfill") else 0
    info = rebuild_index(archive)
    print(f"  索引：{_rel_or_abs(index_path(archive))}（重建，共 {info['count']} 档）")
    if opts.get("backfill"):
        tail = "（来源未知的按 经典 记，要改直接改 meta）" if n_bf else "（没有要补的）"
        print(f"  补 meta：{n_bf} 档{tail}")
    if info["missing"]:
        print(f"  ⚠️ 缺 meta {len(info['missing'])} 档（索引里已显式标出，跑 index --backfill 补）："
              + "、".join(m[2] for m in info["missing"]))


def main():
    pos, opts = parse_argv(sys.argv[1:])
    act, rest = (pos[0] if pos else "show"), (pos[1:] if pos else [])
    if act == "new":
        cmd_new(rest, opts)
    elif act == "lead":
        cmd_lead(rest, opts)
    elif act == "quiz":
        cmd_quiz(rest, opts)
    elif act == "submit":
        cmd_submit(rest, opts)
    elif act == "solve":
        cmd_solve(rest, opts)
    elif act == "answer":
        cmd_answer(rest, opts)
    elif act == "close":
        cmd_close(rest, opts)
    elif act == "index":
        cmd_index(rest, opts)
    elif act == "show":
        cmd_show(rest, opts)
    else:
        sys.exit(f'不认识的子命令: {act}（可用 new / lead / quiz / submit / solve / answer / close / show / index）')


if __name__ == "__main__":
    main()
