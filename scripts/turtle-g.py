#!/usr/bin/env python3
"""turtle-g —— 海龟汤 · 群局版引擎（出题 / 开局 / 放线索 / 记问答 / 结算 / 战绩榜）

用法:
  game turtle-g add "<简称>" --soup "<汤面>" --answer "<汤底>" [--difficulty 1|2|3]
                             [--source 自编|改编|经典] [--tag 本格|变格]
                             [--point "<判定关键点>"]… [--hint "<梯度线索>"]…
  game turtle-g check <编号> [--ok]        # 红线门禁：没过审的题不许开局（--ok 才算过审）
  game turtle-g list [--all]               # 题库一览（--all 连已开的也列）
  game turtle-g show <编号> [--full]       # 看题；默认**不显示汤底与线索**（防手滑发群）
  game turtle-g open [<编号>] [--force]    # 开局：抽一道过审未开的题，打印群发文本（纯文本）
  game turtle-g hint                       # 放下一梯度线索（自动递增），打印群发文本
  game turtle-g log "<一批问答原文>"        # 落当前局（跨会话续命用，随时可写）
  game turtle-g solve <玩家> --ok|--no "<还原原文>"   # 记一次还原尝试
  game turtle-g state                      # 当前局状态：题号 / 开了多久 / 线索进度 / 问答与还原记录
  game turtle-g close [--winner <玩家>] [--note "…"]  # 结算 → 写进题档「开局记录」→ 重建榜
  game turtle-g board                      # 战绩榜（从各题档「开局记录」重建）
  game turtle-g verify <编号>              # 复算开题时封的「答案承诺」（公平自证）
  game turtle-g idea "<反常点>"            # 记进灵感池（撞见就记，别等要用才现想）
  game turtle-g ideas [--all]              # 看池子（--all 连落成题的一起列）
  game turtle-g idea-done <序号> [--as <编号>]   # 落成题后划掉
  game turtle-g drop <编号> [--yes]        # 撤题
  game turtle-g index                      # 重建题库索引

公平自证（借群聊小游戏那套盐值承诺）:
  open 时封 salt，群发文本里公布 commit = sha256(编号|汤底|盐) 前 16 位；
  结算时把盐摊开，谁都能自己复算——证明本天使中途没改过答案。
  收盘还会往跨游戏台账记一条（`game ledger show` 里能看到「海龟汤」）：出题人视角，
  玩家还原成功＝本天使 loss，没人还原＝win。

数据（落档是唯一事实源，索引与榜都是重建的，手改会被下一次冲掉）:
  题库 <根>/workspace/records/sea-turtle-soup/群局题库/<编号>-<简称>.md   ← meta 是事实源
  榜   <根>/workspace/records/sea-turtle-soup/群局榜.md
  状态 <根>/temp/turtle-g.json    ← 当前局跨会话续命：题号 / 线索进度 / 问答 / 还原尝试 / 盐值
  台账 <根>/workspace/records/game-ledger/ledger.json（与扫雷五子棋等共用）

铁律（焊在代码上的）:
  · 没过红线的题开不出去（open 门禁查 meta.redline）——恐怖/自杀/血腥/性的题进不了群。
  · 一局没结算不许开下一局（state 非空要 --force），战绩不会串局。
  · show 默认不吐汤底——要看得自己加 --full，防手滑把答案发群里。
  · 开盘先落盘、断线先找盘（state）——会话过期收到「继续」时先 state，别凭印象重造。
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys

# ---------- 数据根（与 turtle.py 同一套口径） ----------
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
ARCHIVE = os.path.join(ROOT, "workspace", "records", "sea-turtle-soup")
BANK = os.path.join(ARCHIVE, "群局题库")
BOARD_NAME = "群局榜.md"
INDEX_NAME = "INDEX.md"
STATE_DIR = os.path.join(ROOT, "temp")
STATE = os.path.join(STATE_DIR, "turtle-g.json")
LEDGER = os.path.join(os.path.dirname(os.path.dirname(HERE)), "chat-game-referee", "scripts", "ledger.py")
COMMIT_LEN = 16          # 承诺只公布前 16 位——够防改，也好贴进群
# 双生题没写 premise 时的兜底背景——不点答案，只交代世界，让玩家知道往哪想
DEFAULT_PREMISE = "双生视界 · 大爆发之后的年代（源力结晶 / 晶骸 / 洛氏 / 统合联盟军）"
TZ = datetime.timezone(datetime.timedelta(hours=8))
META_RE = re.compile(r"<!-- meta (\{.*?\}) -->")
SECTIONS = ("汤底", "判定关键点", "梯度线索", "红线检查", "开局记录")
LOG_RE = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s*第\s*(\d+)\s*局\s*｜\s*胜者：(.+?)\s*｜")


def now():
    return datetime.datetime.now(TZ)


def stamp():
    return now().strftime("%Y-%m-%d %H:%M")


# ---------- 小工具 ----------
def die(msg, code=1):
    sys.exit(msg)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def stars(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    return "★" * max(0, min(3, n)) or "—"


def parse_argv(argv):
    """手写解析：--hint / --point 可重复，其余带值；--ok/--force/--all/--full 是开关。"""
    pos, opts, i = [], {}, 0
    val_opt = ("--soup", "--answer", "--difficulty", "--tag", "--source", "--basis", "--premise",
               "--winner", "--note", "--as")
    rep_opt = ("--hint", "--point")
    flag_opt = {"--ok": "ok", "--force": "force", "--all": "all", "--full": "full",
                "--redline": "redline", "--yes": "yes", "--no": "no"}
    while i < len(argv):
        a = argv[i]
        key = a[2:].split("=", 1)[0] if a.startswith("--") else ""
        if a in val_opt or a in rep_opt:
            if i + 1 >= len(argv):
                die(f"{a} 后面要跟一个值（记得加引号）")
            v = argv[i + 1]
            if a in rep_opt:
                opts.setdefault(key, []).append(v)
            else:
                opts[key] = v
            i += 2
            continue
        if any(a.startswith(o + "=") for o in val_opt):
            k, v = a[2:].split("=", 1)
            opts[k] = v
            i += 1
            continue
        if a in flag_opt:
            opts[flag_opt[a]] = True
            i += 1
            continue
        if a in ("-h", "--help"):
            print((__doc__ or "").strip())
            sys.exit(0)
        if a.startswith("-"):
            die(f"不认识的参数: {a}（-h 看用法）")
        pos.append(a)
        i += 1
    return pos, opts


# ---------- 题库档 ----------
def _meta_of(path):
    try:
        m = META_RE.search(read_text(path))
        return json.loads(m.group(1)) if m else None
    except (OSError, ValueError):
        return None


def _fmt_meta(d):
    keys = ("id", "title", "source", "difficulty", "tag", "status", "redline", "plays",
            "premise", "commit", "salt")
    return "<!-- meta " + json.dumps({k: d.get(k, "") for k in keys}, ensure_ascii=False) + " -->"


def answer_of(path):
    """汤底原文（剥掉 `> ` 引号与空行）——承诺与复算都吃它，改一个字承诺就对不上。"""
    out = []
    for l in section_lines(read_text(path), "汤底"):
        s = l.strip()
        if not s or s == "---":
            continue
        out.append(s.lstrip("> ").strip())
    return "\n".join(out)


def commit_of(num, answer, salt):
    """承诺 = sha256(编号|汤底|盐) 前 16 位——公平自证：开题前封好，结算时摊盐给玩家复算。"""
    return hashlib.sha256(f"{num}|{answer}|{salt}".encode("utf-8")).hexdigest()[:COMMIT_LEN]


def ledger_add(result, opponent, moves, note, source):
    """收盘必记（照游戏厅铁律）：海龟汤也进跨游戏台账。出题人视角——没人还原＝本天使胜。"""
    if not os.path.exists(LEDGER):
        print("  ⚠️ 没挂上跨游戏台账（ledger.py 不在）——手动补：game ledger add 海龟汤 …")
        return
    r = subprocess.run([sys.executable, LEDGER, "add", "海龟汤", result,
                        "--opponent", opponent, "--moves", str(moves),
                        "--note", note, "--source", source],
                       capture_output=True, text=True)
    out = (r.stdout or r.stderr or "").strip()
    if out:
        print("  " + out.replace("\n", "\n  "))


def set_meta(path, **kw):
    text = read_text(path)
    meta = _meta_of(path) or {}
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
    return meta


def bank_files():
    """题库档：[(编号|None, meta, 路径)]，按编号排。"""
    out = []
    if os.path.isdir(BANK):
        for n in sorted(os.listdir(BANK)):
            if n.endswith(".md") and not n.startswith("_") and n not in (INDEX_NAME, BOARD_NAME):
                p = os.path.join(BANK, n)
                meta = _meta_of(p) or {}
                num = str(meta.get("id") or "").strip() or None
                if not num:
                    m = re.match(r"(\d{1,4})", n)
                    num = m.group(1) if m else None
                out.append((num, meta, p))
    out.sort(key=lambda r: (r[0] is None, int(r[0]) if (r[0] or "").isdigit() else 0, r[2]))
    return out


def find_item(ref):
    ref = str(ref).strip()
    for num, meta, path in bank_files():
        if ref in (num, meta.get("title"), os.path.basename(path)[:-3]):
            return num, meta, path
        if ref.isdigit() and num and num.isdigit() and int(ref) == int(num):
            return num, meta, path
    die(f"题库里没有这一题：{ref}（game turtle-g list 看看有哪些）")


def section_lines(text, key):
    """取 `## …key…` 栏正文行；没有返回 []。"""
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if l.startswith("## ") and key in l]
    if not starts:
        return []
    i = starts[0] + 1
    out = []
    while i < len(lines) and not lines[i].startswith("## "):
        out.append(lines[i])
        i += 1
    return out


def hints_of(path):
    """梯度线索原文（去掉编号前缀）。"""
    out = []
    for l in section_lines(read_text(path), "梯度线索"):
        m = re.match(r"^\s*\d+[\.、]\s*(.+?)\s*$", l)
        if m:
            out.append(m.group(1))
    return out


def soup_of(path):
    for l in read_text(path).splitlines():
        if l.startswith("> 汤面"):
            return re.sub(r"^>\s*汤面[：:]\s*", "", l).strip()
    return ""


def board_rows():
    """扫所有题档「开局记录」→ [(日期, 局号, 胜者, 原行)]；落档是唯一事实源。"""
    rows = []
    for _num, _meta, path in bank_files():
        for l in section_lines(read_text(path), "开局记录"):
            m = LOG_RE.match(l.strip())
            if m:
                rows.append((m.group(1), int(m.group(2)), m.group(3).strip(), l.strip()))
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows


def next_round():
    rows = board_rows()
    return (rows[-1][1] + 1) if rows else 1


# ---------- 当前局状态（跨会话续命） ----------
def load_state():
    if not os.path.exists(STATE):
        return None
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        die(f"状态文件读不出来：{STATE}（坏了就删掉重开一局）")


def save_state(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def clear_state():
    if os.path.exists(STATE):
        os.remove(STATE)


def require_state():
    st = load_state()
    if not st:
        die("现在没有进行中的局——先 game turtle-g open 开一局")
    return st


# ---------- 子命令 ----------
def cmd_add(rest, opts):
    if not rest:
        die('用法: game turtle-g add "<简称>" --soup "<汤面>" --answer "<汤底>" [--difficulty 1|2|3] [--tag 本格] [--hint "…"]…')
    title = rest[0].strip()
    soup = (opts.get("soup") or "").strip()
    answer = (opts.get("answer") or "").strip()
    if not soup:
        die('缺汤面：--soup "<汤面原文>"')
    if not answer:
        die('缺汤底：--answer "<汤底原文>"（没汤底的题不许入库）')
    try:
        diff = int(opts.get("difficulty") or 2)
    except ValueError:
        die(f"--difficulty 只认 1|2|3：{opts.get('difficulty')}")
    if diff not in (1, 2, 3):
        die(f"--difficulty 只认 1(简单)/2(普通)/3(硬)：{diff}")
    tag = (opts.get("tag") or "本格").strip()
    source = (opts.get("source") or "自编").strip()
    if source not in ("自编", "改编", "经典"):
        die(f"--source 只认 自编|改编|经典：{source}（经典=网上原题，第三人原题不入档只记来源）")
    premise = (opts.get("premise") or "").strip()
    os.makedirs(BANK, exist_ok=True)
    used = {int(n) for n, _m, _p in bank_files() if n and n.isdigit()}
    n = 1
    while n in used:
        n += 1
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("_") or "题"
    while os.path.exists(os.path.join(BANK, f"{n:03d}-{safe}.md")):
        n += 1      # 编号被抢（群里那边的会话可能正在建题）→ 顺延，别报错退出
    num = f"{n:03d}"
    path = os.path.join(BANK, f"{num}-{safe}.md")
    hints = [h.strip() for h in (opts.get("hint") or []) if h.strip()]
    points = [p.strip() for p in (opts.get("point") or []) if p.strip()]
    lines = [f"# {num} · {title}", "",
             _fmt_meta({"id": num, "title": title, "source": source, "difficulty": diff, "tag": tag,
                        "status": "未开", "redline": False, "plays": 0, "premise": premise}), "",
             f"> 汤面：{soup}", "", "---", "",
             "## 一、汤底（官方答案原文）", ""]
    lines += [f"> {l}" if l.strip() else ">" for l in answer.splitlines()] + [""]
    lines += ["## 二、判定关键点", ""]
    lines += [f"- {p}" for p in points] or ["- （待补：还原判定要对着哪些点）"]
    lines += ["", "## 三、梯度线索", ""]
    lines += [f"{i}. {h}" for i, h in enumerate(hints, 1)] or ["1. （待补）"]
    lines += ["", "## 四、红线检查", "",
              "- 自杀／血腥／性／儿童受害：**未过审**（人工确认无以上内容后跑 `check <编号> --ok`）",
              "- 审题四查：死因链闭合 ／ 人数与自救路径 ／ 锁扣在汤面有影子 ／ 定性有背书",
              "", "## 五、开局记录", ""]
    basis = [b.strip() for b in (opts.get("basis") or "").splitlines() if b.strip()]
    if basis:
        lines += ["## 六、出题依据", ""] + [f"- {b}" for b in basis]
    lines += ["", "---", ""]
    write_text(path, "\n".join(lines))
    cmd_index([], opts)
    print(f"  新题：{os.path.relpath(path, ROOT)}")
    print(f"  编号 {num}｜来源 {source}｜难度 {stars(diff)}｜标签 {tag}｜线索 {len(hints)} 条｜判定点 {len(points)} 条")
    print(f"  前提：{premise or ('（没写——开局用兜底：' + DEFAULT_PREMISE + '）' if '双生' in tag else '（无）')}")
    print("  ⚠️ 没过红线开不出去——审完跑 `game turtle-g check "
          f"{num} --ok`（群局不许有自杀/血腥/性/儿童受害）")


def cmd_check(rest, opts):
    if not rest:
        die("用法: game turtle-g check <编号> [--ok]")
    num, meta, path = find_item(rest[0])
    if not opts.get("ok"):
        print(f"  {num} · {meta.get('title')}｜红线：{'已过审' if meta.get('redline') else '未过审'}")
        print("  过审要人工确认四件事：")
        print("    ① 无自杀／血腥／性／儿童受害")
        print("    ② 审题四查过：死因链闭合／人数与自救路径／锁扣在汤面有影子／定性有背书")
        print("    ③ 汤面瘦身：每一句删掉后谜面还成立吗？成立就删（季节／地点／来历／无关动机一律砍）")
        print("    ④ 主题题才写前提；常规题不写，开局不带背景行")
        print(f"  都没问题再跑：game turtle-g check {num} --ok")
        return
    text = read_text(path)
    text = text.replace("- 自杀／血腥／性／儿童受害：**未过审**（人工确认无以上内容后跑 `check <编号> --ok`）",
                        f"- 自杀／血腥／性／儿童受害：**已过审**（人工确认，{now().strftime('%Y-%m-%d')}）")
    write_text(path, text)
    set_meta(path, redline=True)
    print(f"  {num} 已过审 ✓ ——开得出去（open 门禁放行）")


def cmd_list(rest, opts):
    rows = bank_files()
    if not rows:
        print(f"  题库还是空的（{os.path.relpath(BANK, ROOT)}）——先 game turtle-g add …")
        return
    show_all = bool(opts.get("all"))
    n_ok = 0
    print(f"  题库：{os.path.relpath(BANK, ROOT)}（{len(rows)} 题）")
    for num, meta, _p in rows:
        status = meta.get("status") or "未开"
        if not show_all and status == "已开":
            continue
        n_ok += 1
        flag = "✓过审" if meta.get("redline") else "⚠未审"
        plays = meta.get("plays") or 0
        print(f"    {num}｜{meta.get('title')}｜{meta.get('source') or '—'}｜{stars(meta.get('difficulty'))}"
              f"｜{meta.get('tag')}｜{status}{f'×{plays}' if plays else ''}｜{flag}")
    if not show_all:
        print(f"  列的是没开过的 {n_ok} 题（--all 连已开的一起列）")


def cmd_show(rest, opts):
    if not rest:
        die("用法: game turtle-g show <编号> [--full]")
    num, meta, path = find_item(rest[0])
    print(f"  {num} · {meta.get('title')}｜难度 {stars(meta.get('difficulty'))}｜{meta.get('tag')}"
          f"｜{meta.get('status')}｜{'已过审' if meta.get('redline') else '⚠未过审'}")
    print(f"  汤面：{soup_of(path)}")
    if not opts.get("full"):
        print("  （汤底与线索用 --full 才显示——防手滑发群）")
        return
    print("  汤底：")
    for l in section_lines(read_text(path), "汤底"):
        if l.strip() and l.strip() != "---":
            print("    " + l.strip().lstrip("> ").strip())
    hs = hints_of(path)
    print(f"  线索（{len(hs)} 条）：")
    for i, h in enumerate(hs, 1):
        print(f"    {i}. {h}")


def cmd_open(rest, opts):
    st = load_state()
    if st and not opts.get("force"):
        die(f"上一局还没结算（{st.get('id')} · {st.get('title')}，{st.get('opened_at')} 开的）"
            f"——先 game turtle-g close；如果那是群里正在玩的局，别加 --force 把它丢掉")
    rows = bank_files()
    if not rows:
        die("题库是空的——先 game turtle-g add …")
    if rest:
        num, meta, path = find_item(rest[0])
        if not meta.get("redline"):
            die(f"{num} 还没过红线（game turtle-g check {num} --ok）——没过审的题不许开局")
        if meta.get("status") == "已开" and not opts.get("force"):
            die(f"{num} 开过了（plays={meta.get('plays') or 0}）——换一道，或 --force 重开")
    else:
        pick = [(n, m, p) for n, m, p in rows if m.get("status") != "已开" and m.get("redline")]
        if not pick:
            not_reviewed = [n for n, m, _p in rows if m.get("status") != "已开" and not m.get("redline")]
            if not_reviewed:
                die("没题能开：这些还没过红线（先 game turtle-g check <编号> --ok）——"
                    + "、".join(not_reviewed))
            die("题都开过了——game turtle-g list --all 看看，或先 add 新题")
        diff_pref = [r for r in pick if int(r[1].get("difficulty") or 2) <= 2] or pick
        num, meta, path = diff_pref[0]
    soup = soup_of(path)
    if not soup:
        die(f"{num} 的汤面读不出来（档里要有 `> 汤面：…`）")
    premise = (meta.get("premise") or "").strip()
    if not premise and "双生" in str(meta.get("tag") or ""):
        premise = DEFAULT_PREMISE          # 双生题忘写前提时的兜底——总得让人认出这是什么世界
    rnd = next_round()
    salt = secrets.token_hex(8)
    commit = commit_of(num, answer_of(path), salt)
    save_state({"id": num, "title": meta.get("title"), "difficulty": meta.get("difficulty"),
                "opened_at": stamp(), "hints_used": 0, "log": [], "solves": [],
                "salt": salt, "commit": commit})
    set_meta(path, status="已开", commit=commit, salt=salt)
    print(f"  ── 群发文本（纯文本，照抄进群）──────────────")
    print(f"【海龟汤 · 第 {rnd} 局】难度 {stars(meta.get('difficulty'))}｜{meta.get('tag')}")
    if premise:
        print(f"背景：{premise}")
    print(f"汤面：{soup}")
    print()
    print("规则：问就答「是／否／无关」；想还原喊「还原」＋完整故事＋推理链（每人一次机会）；卡住了喊「要线索」。")
    print("（不知道从哪问起的话：挑汤面里最怪的那个动作，问它一句「是不是……」——本天使只答是／否／无关）")
    print(f"答案承诺：{commit}（开题前就封好的，结算时公布盐值——谁都能自己复算，本天使改不了答案）")
    print(f"  ─────────────────────────────────────────")
    print(f"  已开局：{num} · {meta.get('title')}（线索 {len(hints_of(path))} 条备着）｜第 {rnd} 局")


def cmd_hint(rest, opts):
    st = require_state()
    _num, meta, path = find_item(st["id"])
    hs = hints_of(path)
    used = int(st.get("hints_used") or 0)
    if used >= len(hs):
        die(f"线索放完了（这题共 {len(hs)} 条）——该公布汤底了：game turtle-g close --winner …")
    text = hs[used]
    st["hints_used"] = used + 1
    save_state(st)
    print("  ── 群发文本 ─────────────────────────────")
    print(f"【线索 {used + 1}/{len(hs)}】{text}")
    print("  ─────────────────────────────────────────")


def cmd_log(rest, opts):
    if not rest:
        die('用法: game turtle-g log "<这一批问答的原文>"')
    st = require_state()
    st.setdefault("log", []).append({"at": stamp(), "text": rest[0].strip()})
    save_state(st)
    print(f"  已记第 {len(st['log'])} 批问答｜当前局 {st['id']} · {st['title']}（{st['opened_at']} 开）")


def cmd_solve(rest, opts):
    if not rest:
        die('用法: game turtle-g solve <玩家> --ok|--no "<还原原文>"')
    if not (opts.get("ok") or opts.get("no")):
        die("要标结果：--ok（还原成功）或 --no（不对）")
    st = require_state()
    st.setdefault("solves", []).append({"at": stamp(), "player": rest[0].strip(),
                                        "ok": bool(opts.get("ok")),
                                        "text": rest[1].strip() if len(rest) > 1 else ""})
    save_state(st)
    verdict = "还原成功 ✓" if opts.get("ok") else "没中"
    print(f"  记下：{rest[0].strip()} → {verdict}（本局第 {len(st['solves'])} 次还原尝试）")
    if opts.get("ok"):
        print(f"  下一步：game turtle-g close --winner {rest[0].strip()}")


def cmd_state(rest, opts):
    st = require_state()
    _n, meta, path = find_item(st["id"])
    hs = hints_of(path)
    print(f"  当前局：{st['id']} · {st['title']}｜难度 {stars(st.get('difficulty'))}"
          f"｜{st.get('opened_at')} 开（第 {next_round()} 局将结算）")
    print(f"  线索：放了 {st.get('hints_used') or 0}/{len(hs)} 条")
    print(f"  问答：{len(st.get('log') or [])} 批｜还原尝试：{len(st.get('solves') or [])} 次")
    for s in st.get("solves") or []:
        print(f"    · {s['at']} {s['player']} → {'✓' if s['ok'] else '✗'}")
    for l in st.get("log") or []:
        print(f"    · {l['at']}：{l['text'][:80]}{'…' if len(l['text']) > 80 else ''}")
    print(f"  结算：game turtle-g close [--winner <玩家>]")


def cmd_close(rest, opts):
    st = require_state()
    num, meta, path = find_item(st["id"])
    winner = (opts.get("winner") or "").strip()
    if not winner:
        oks = [s for s in (st.get("solves") or []) if s.get("ok")]
        winner = oks[-1]["player"] if oks else "无人还原"
    rnd = next_round()
    note = (opts.get("note") or "").strip()
    used = st.get("hints_used") or 0
    line = (f"- [{now().strftime('%Y-%m-%d')}] 第 {rnd} 局 ｜ 胜者：{winner} ｜ 难度 {stars(meta.get('difficulty'))}"
            f" ｜ 线索 {used} 条 ｜ 还原尝试 {len(st.get('solves') or [])} 次")
    if note:
        line += f" ｜ 备注：{note}"
    # 本局经过跟着落档——登记完整性：state 一清，这局的问答与还原就没了（私档那六份的老规矩）
    detail = [f"  ↳ {s['at']} {s['player']} {'✓' if s['ok'] else '✗'}：{(s.get('text') or '')[:60]}"
              for s in (st.get("solves") or [])]
    block = "\n".join([line] + detail)
    text = read_text(path)
    if "## 五、开局记录" not in text:
        text = text.rstrip("\n") + "\n\n## 五、开局记录\n\n---\n"
    text = text.replace("## 五、开局记录\n", "## 五、开局记录\n\n" + block + "\n", 1)
    write_text(path, text)
    set_meta(path, status="已开", plays=int(meta.get("plays") or 0) + 1)
    clear_state()
    print(f"  已结算：第 {rnd} 局｜{st['id']} · {st['title']}｜胜者 {winner}")
    salt = st.get("salt") or ""
    if salt:
        calc = commit_of(num, answer_of(path), salt)
        ok = calc == (st.get("commit") or "")
        print(f"  盐值：{salt} ｜ 复算 {calc} vs 开题公布 {st.get('commit')}"
              f" → {'✓ 一致，答案没被动过' if ok else '✗ 对不上'}")
    print("  汤底要发群的话自己念档里「## 一、汤底」那段（原文，别改）")
    # 收盘必记（照游戏厅铁律）：进跨游戏台账——出题人视角，没人还原＝本天使胜
    ledger_add("loss" if winner not in ("", "无人还原") else "win", winner or "群里",
               len(st.get("solves") or []), f"第{rnd}局·{st['title']}", os.path.relpath(path, ROOT))
    print("  归档在 workspace/records/…，推送走 bin/gitpush（收盘顺手推）")
    cmd_board([], opts)


IDEA_HEAD = """# 群局海龟汤 · 灵感池

> 撞见反常的点就记一条（`game turtle-g idea "…"`）——出题时从这儿取，别等要用才现想。
> 记的是**反常点**，不是成题；落成题后跑 `game turtle-g idea-done <序号> --as <编号>` 划掉。

"""


def ideas_path():
    return os.path.join(BANK, "_灵感池.md")


def _idea_rows():
    """池里的条目 → [(序号, 是否已用, 原文)]。落档是唯一事实源，序号从行里读。"""
    rows = []
    if os.path.exists(ideas_path()):
        for l in read_text(ideas_path()).splitlines():
            m = re.match(r"^-\s*\[( |x)\]\s*(\d+)\.\s*(.+?)\s*$", l)
            if m:
                rows.append((int(m.group(2)), m.group(1) == "x", m.group(3)))
    return rows


def cmd_idea(rest, opts):
    if not rest:
        die('用法: game turtle-g idea "<一句反常点>"（撞见就记，别等要用才现想）')
    text = rest[0].strip()
    p = ideas_path()
    rows = _idea_rows()
    n = (max(r[0] for r in rows) + 1) if rows else 1
    if not os.path.exists(p):
        write_text(p, IDEA_HEAD + "\n")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"- [ ] {n}. [{now().strftime('%Y-%m-%d')}] {text}\n")
    free = len([r for r in rows if not r[1]]) + 1
    print(f"  记上了：池里第 {n} 条（待用 {free} 条）——{text}")


def cmd_ideas(rest, opts):
    rows = _idea_rows()
    if not rows:
        print('  灵感池是空的——撞见反常的点就 game turtle-g idea "…" 记一条')
        return
    show_all = bool(opts.get("all"))
    drawn = [r for r in rows if show_all or not r[1]]
    print(f"  灵感池：{os.path.relpath(ideas_path(), ROOT)}"
          f"（待用 {len([r for r in rows if not r[1]])} / 共 {len(rows)}）")
    for num, used, text in drawn:
        print(f"    {'✓' if used else '·'} {num}. {text}")
    if not show_all:
        print("  （--all 连落成题的也一起列）")


def cmd_idea_done(rest, opts):
    if not rest:
        die("用法: game turtle-g idea-done <序号> [--as <题号>]（落成题后划掉它）")
    try:
        want = int(rest[0])
    except ValueError:
        die(f"序号要是个数字：{rest[0]}")
    p = ideas_path()
    rows = _idea_rows()
    if not any(r[0] == want for r in rows):
        die(f"池里没有第 {want} 条（game turtle-g ideas 看看）")
    as_num = (opts.get("as") or "").strip()
    t = read_text(p)
    def sub(m):
        if int(m.group(2)) != want:
            return m.group(0)
        tail = f"（→ {as_num}）" if as_num else ""
        return f"- [x] {m.group(2)}. {m.group(3)}{tail}"
    t = re.sub(r"^-\s*\[( |x)\]\s*(\d+)\.\s*(.+?)\s*$", sub, t, flags=re.M)
    write_text(p, t)
    print(f"  第 {want} 条已划掉" + (f"（落成题 {as_num}）" if as_num else ""))


def cmd_verify(rest, opts):
    if not rest:
        die("用法: game turtle-g verify <编号>（复算开题时封的答案承诺）")
    num, meta, path = find_item(rest[0])
    salt, commit = meta.get("salt"), meta.get("commit")
    if not salt or not commit:
        die(f"{num} 还没封过承诺——承诺是 open 开局时封的，没开过局的题没有")
    calc = commit_of(num, answer_of(path), salt)
    print(f"  {num} · {meta.get('title')}｜开题时公布的承诺：{commit}")
    print(f"  盐值：{salt}")
    print(f"  现算：{calc}  " + ("✓ 一致——答案从开题到现在没被动过" if calc == commit
                                else "✗ 对不上——答案被改过！"))
    print(f"  玩家自算：echo -n '{num}|<汤底原文>|{salt}' | sha256sum | cut -c1-{COMMIT_LEN}")


def cmd_board(rest, opts):
    rows = board_rows()
    if not rows:
        print("  还没有战绩（一局都没结算过）")
        return
    wins, total = {}, len(rows)
    for _d, _r, winner, _l in rows:
        if winner and winner != "无人还原":
            wins[winner] = wins.get(winner, 0) + 1
    print(f"  海龟汤 · 群局榜（共 {total} 局）")
    rank = sorted(wins.items(), key=lambda kv: (-kv[1], kv[0]))
    if rank:
        for i, (name, w) in enumerate(rank, 1):
            print(f"    {i}. {name} —— {w} 胜")
    else:
        print("    还没有人还原成功过")
    print("  最近 5 局：")
    for d, r, winner, _l in rows[-5:]:
        print(f"    第 {r} 局（{d}）｜{winner}")
    dead = [r for _d, r, w, _l in rows if w == "无人还原"]
    if dead:
        print(f"  没人还原的局：{len(dead)} 局（第 " + "、".join(str(x) for x in dead[:10]) + " 局）")


def cmd_drop(rest, opts):
    if not rest:
        die("用法: game turtle-g drop <编号> [--yes]")
    num, meta, path = find_item(rest[0])
    if not opts.get("yes"):
        die(f"{num} · {meta.get('title')}（{meta.get('status')}，开过 {meta.get('plays') or 0} 次）"
            f"——删了不可逆，确认再加 --yes：game turtle-g drop {num} --yes")
    st = load_state()
    if st and st.get("id") == num:
        clear_state()
        print("  这题正在局中——当前局状态一并清掉")
    os.remove(path)
    cmd_index([], opts)
    print(f"  已删：{num} · {meta.get('title')}")


def cmd_index(rest, opts):
    rows = bank_files()
    out = ["# 海龟汤 · 群局题库索引", "",
           "> 本页由各题档 `<!-- meta … -->` 自动重建（`game turtle-g index`）——手改会被下一次冲掉。", "",
           "| 编号 | 题目 | 来源 | 难度 | 标签 | 状态 | 开过 | 红线 |",
           "|------|------|------|------|------|------|------|------|"]
    for num, meta, _p in rows:
        out.append(f"| {num} | {meta.get('title')} | {meta.get('source') or '—'} | {stars(meta.get('difficulty'))} | {meta.get('tag')} "
                   f"| {meta.get('status') or '未开'} | {meta.get('plays') or 0} | "
                   f"{'✓' if meta.get('redline') else '⚠'} |")
    out += ["", "状态：未开 / 已开；红线 ✓ = 过审（没过审的题开局会被门禁拦下）", "",
            "*莉娅 · 群局题库 · 出题人换个位置*", ""]
    write_text(os.path.join(BANK, INDEX_NAME), "\n".join(out))
    print(f"  题库索引：{os.path.relpath(os.path.join(BANK, INDEX_NAME), ROOT)}（{len(rows)} 题）")


CMDS = {"add": cmd_add, "check": cmd_check, "list": cmd_list, "show": cmd_show, "open": cmd_open,
        "hint": cmd_hint, "log": cmd_log, "solve": cmd_solve, "state": cmd_state,
        "close": cmd_close, "board": cmd_board, "index": cmd_index, "drop": cmd_drop,
        "verify": cmd_verify, "idea": cmd_idea, "ideas": cmd_ideas, "idea-done": cmd_idea_done}


def main():
    pos, opts = parse_argv(sys.argv[1:])
    act, rest = (pos[0] if pos else "list"), (pos[1:] if pos else [])
    fn = CMDS.get(act)
    if not fn:
        die(f"不认识的子命令: {act}（可用：{' / '.join(CMDS)}；-h 看全用法）")
    fn(rest, opts)


if __name__ == "__main__":
    main()
