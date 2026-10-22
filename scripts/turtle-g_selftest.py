#!/usr/bin/env python3
"""turtle-g 自测：在临时 GAME_HOME 里跑一整局（建题 → 红线拦截 → 过审 → 开局 → 线索 → 问答 → 还原 → 结算 → 榜），
不碰正式题库。用法：python3 turtle-g_selftest.py（全过退出码 0，有挂的退出 1）。
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "turtle-g.py")
FAILED = []


def run(home, *args):
    env = dict(os.environ, GAME_HOME=home)
    r = subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True, env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def check(name, cond, extra=""):
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"\n       ← {extra.strip()[:400]}"))
    if not cond:
        FAILED.append(name)


def main():
    tmp = tempfile.mkdtemp(prefix="turtle-g-selftest-")
    try:
        code, out = run(tmp, "list")
        check("空题库 list 不崩", code == 0 and "空的" in out, out)

        code, out = run(tmp, "add", "自测题", "--soup", "甲在屋里关了灯，乙却笑了。",
                        "--answer", "假汤底：自测用。", "--difficulty", "1", "--tag", "双生",
                        "--hint", "线索一", "--hint", "线索二", "--hint", "线索三",
                        "--point", "判定点一")
        check("add 建题", code == 0 and "001" in out, out)
        check("add 提示前提（双生题没写会走兜底）", "前提：" in out and "兜底" in out, out)

        code, out = run(tmp, "idea", "测试灵感：电梯按钮")
        check("记灵感进池", code == 0 and "第 1 条" in out, out)
        code, out = run(tmp, "ideas")
        check("列灵感池", "待用 1" in out and "电梯按钮" in out, out)
        code, out = run(tmp, "idea-done", "1", "--as", "001")
        check("划掉已用灵感", code == 0 and "已划掉" in out, out)
        code, out = run(tmp, "ideas")
        check("划掉后从待用里消失", "待用 0" in out, out)

        code, out = run(tmp, "open")
        check("没过红线的题开不出去", code != 0 and "红" in out, out)

        code, out = run(tmp, "check", "001", "--ok")
        check("check --ok 过审", code == 0 and "已过审" in out, out)

        code, out = run(tmp, "open")
        check("open 出群发文本（纯文本、带局号与规则）",
              code == 0 and "【海龟汤 · 第 1 局】" in out and "汤面：" in out and "还原" in out, out)
        check("开局文本不含 markdown 标记", "##" not in out.split("── 群发文本")[1], out)
        check("open 公布答案承诺（公平自证）", "答案承诺：" in out and len(out.split("答案承诺：")[1][:16]) == 16, out)
        check("open 带前提背景行（让人认出是双生的题）", "背景：双生视界" in out, out)

        code, out = run(tmp, "open")
        check("一局没结算不许开下一局", code != 0 and "结算" in out, out)

        for i in (1, 2, 3):
            code, out = run(tmp, "hint")
            check(f"放第 {i} 条线索", code == 0 and f"【线索 {i}/3】" in out, out)
        code, out = run(tmp, "hint")
        check("线索放完要拦", code != 0 and "放完" in out, out)

        run(tmp, "log", "甲：他死了吗？→ 否")
        run(tmp, "log", "乙：跟灯有关吗？→ 是")
        run(tmp, "solve", "阿丙", "--no", "他困了")
        code, out = run(tmp, "solve", "阿丁", "--ok", "灯是信号灯")
        check("记还原尝试", code == 0 and "还原成功" in out, out)

        code, out = run(tmp, "state")
        check("state 汇总（题号/线索/问答/还原）",
              code == 0 and "放了 3/3" in out and "2 批" in out and "2 次" in out, out)

        code, out = run(tmp, "show", "001")
        check("show 默认不吐汤底", code == 0 and "假汤底" not in out, out)
        code, out = run(tmp, "show", "001", "--full")
        check("show --full 才给汤底与线索", code == 0 and "假汤底" in out and "线索一" in out, out)

        code, out = run(tmp, "verify", "001")
        check("verify 复算承诺一致（公平自证）", code == 0 and "✓ 一致" in out, out)

        code, out = run(tmp, "close", "--note", "自测")
        check("close 结算并清状态", code == 0 and "已结算" in out and "阿丁" in out, out)
        check("close 摊盐 + 复算一致", "盐值：" in out and "✓ 一致" in out, out)
        check("close 记进跨游戏台账（收盘必记）", "海龟汤" in out, out)
        code, out = run(tmp, "state")
        check("结算后没有进行中的局", code != 0 and "没有进行中" in out, out)

        code, out = run(tmp, "board")
        check("榜记胜场", code == 0 and "阿丁 —— 1 胜" in out, out)

        code, out = run(tmp, "list", "--all")
        check("list --all 标已开×1 与过审", code == 0 and "已开×1" in out and "✓过审" in out, out)

        code, out = run(tmp, "index")
        check("重建题库索引", code == 0 and "1 题" in out, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(FAILED)
    print(f"\n  {'全过 ✓' if not total else f'{total} 项没过 ✗'}（自测数据已清）")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
