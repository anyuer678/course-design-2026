"""demo.py —— B39 四段演示：模板与检查器 → 负面对照（改坏必须红）→ CRDT 收敛复现 → 使用指引。

确定性：全部种子固定、无计时输出——run.bat 两次日志除 unittest 计时行外逐字相同
（tools/logdiff.py 只允许那一类规范化）。
"""
from __future__ import annotations

import pathlib
import random
import re
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "repro"))

import check_record                                                       # noqa: E402
from crdt_lww import LWWRegister, VectorClock                             # noqa: E402

REPO_ROOT = ROOT.parents[1]
EXAMPLE = ROOT / "docs" / "records" / "example-crdt.md"


def section(no: int, title: str) -> None:
    print("\n" + "=" * 78 + f"\n  {no}) {title}\n" + "=" * 78)


def show(label: str, value: object) -> None:
    print(f"  {label:<32}{value}")


def mutated_problems(old: str, new: str) -> list[str]:
    text = EXAMPLE.read_text(encoding="utf-8")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="b39-demo-"))
    try:
        path = tmp / "mutated.md"
        path.write_text(text.replace(old, new), encoding="utf-8")
        return check_record.check_record(path, REPO_ROOT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("B39-tech-radar 演示：主题记录模板 + 可机验证据 + 一次最小复现（技术雷达）")

    # ------------------------------------------------------------------ 1
    section(1, "模板与检查器：示例记录的每一条证据都要真实存在")
    problems = check_record.check_record(EXAMPLE, REPO_ROOT)
    show("检查示例记录", "PASS（0 个问题）" if not problems else f"RED：{problems}")
    text = EXAMPLE.read_text(encoding="utf-8")
    evidence = text.split("## 证据（如何核验）", 1)[1].split("## ", 1)[0]
    pointers = re.findall(r"`([^`]+)`", evidence)
    paths = [p for p in pointers if "/" in p and not p.startswith("http")]
    commits = [p for p in pointers if p.startswith("@")]
    show("核验的指针", f"路径 {len(paths)} 条 + 提交 {len(commits)} 个（全部在仓库/git 里真实存在）")

    # ------------------------------------------------------------------ 2
    section(2, "负面对照：改坏一处，检查器必须报红（否则它就是装饰）")
    cases = [("删掉「局限与适用边界」节", "## 局限与适用边界", "## 其他"),
             ("证据指向不存在的文件", "repro/crdt_lww.py`", "repro/NOPE.py`"),
             ("引用一个假提交号", "@f0bb729", "@deadbeef0")]
    for label, old, new in cases:
        problems = mutated_problems(old, new)
        first = problems[0] if problems else "（没有报红——BUG）"
        show(label, f"RED，首条：{first}")

    # ------------------------------------------------------------------ 3
    section(3, "最小复现：LWW-Register 的收敛性（交换/结合/幂等 + 置换不变）")
    reg_a, reg_b, reg_c = LWWRegister("a"), LWWRegister("b"), LWWRegister("c")
    reg_a.set("x")                                     # 分区中各写各的
    reg_b.set("y")
    rng = random.Random(2026)
    reps = [reg_a, reg_b, reg_c]
    consistent = True
    winner = None
    for _ in range(100):
        order = [0, 1, 2]
        rng.shuffle(order)
        out = LWWRegister.merged([reps[i] for i in order])
        if winner is None:
            winner = out
        elif (out.value, out.ts) != (winner.value, winner.ts):
            consistent = False
    show("收敛性（100 组置换）", f"全部一致 = {consistent}")
    show("并列计数器的赢家", f"'{winner.ts.replica}'（时间戳 (1, '{winner.ts.replica}') "
                             f"战胜 (1, 'a')）→ 值 '{winner.value}'")
    ok_c = ok_a = ok_i = 0
    for _ in range(50):
        ra, rb = LWWRegister("a"), LWWRegister("b")
        ra.set(rng.randint(0, 9))
        rb.set(rng.randint(0, 9))
        ab, ba = LWWRegister.merged([ra, rb]), LWWRegister.merged([rb, ra])
        rc = LWWRegister("c")
        rc.set(3)
        left = LWWRegister.merged([ab, rc])
        right = LWWRegister.merged([ra, LWWRegister.merged([rb, rc])])
        ok_c += int((ab.value, ab.ts) == (ba.value, ba.ts))
        ok_a += int((left.value, left.ts) == (right.value, right.ts))
    merged = LWWRegister.merged([reg_a, reg_b])
    before = (merged.value, merged.ts)
    merged.merge_in(reg_b)
    ok_i = int((merged.value, merged.ts) == before)
    show("性质抽查（50 组随机）", f"交换 {ok_c}/50；结合 {ok_a}/50；幂等 {ok_i}/1")
    show("向量时钟（因果进度）", f"{{'a': {reg_a.clock.get('a')}, 'b': {reg_b.clock.get('b')}}}")

    # ------------------------------------------------------------------ 4
    section(4, "怎么用它：写你自己的主题记录")
    print("  1. 复制 docs/record-template.md 到 docs/records/<主题>.md，逐节填写；")
    print("  2. 「证据」节每条写成可核验指针：`仓库内路径` 与/或 `@提交号`；")
    print("  3. 跑检查：python tools/check_record.py docs/records/<主题>.md")
    print("     红了就改——不是形式主义：指针不存在意味着这条'证据'其实没人验证过。")
    print("  示例记录的来源栏明确写着「示例（非真实来源）」——真实条目请照实填。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
