"""tools/logdiff.py —— run.bat 两次日志的规范化比对（B23：unittest 计时 + 演示里的一切毫秒/兆字节）

规则只允许两类（会被打印计数、可供审计）：
    - unittest 的 `Ran 45 tests in 1.2s` → 去计时；
    - 第六段规模曲线的【实测】时间（`X.X ms`）与 tracemalloc 峰值（`X.XX MB`）。
其余任何差异都算失败——对照差值、精度读数、断言计数都必须是确定性的
（对照读数若漂移，说明种子或口径被动过，应当红）。

用法：python tools/logdiff.py a.log b.log
"""
from __future__ import annotations

import pathlib
import re
import sys

RULES: list[tuple[str, re.Pattern, str]] = [
    ("unittest 计时", re.compile(r"^(Ran \d+ tests) in [\d.]+s$"), r"\1"),
    # 连右对齐的补位空格一起吃进规则：3 位数值与 4 位数值的对齐宽度不同
    # （B37 同款教训：只换数字不换空格，规范化后会留下空格差）
    ("实测毫秒", re.compile(r"\s+\d+(?:\.\d+)? ms"), " X ms"),
    ("实测兆字节", re.compile(r"\s+\d+(?:\.\d+)? MB"), " X MB"),
]


def normalize(lines: list[str]) -> tuple[list[str], dict[str, int]]:
    counts: dict[str, int] = {}
    out = []
    for line in lines:
        for name, pattern, repl in RULES:
            if pattern.search(line):
                line = pattern.sub(repl, line)
                counts[name] = counts.get(name, 0) + 1
        out.append(line)
    return out, counts


def main() -> int:
    if len(sys.argv) != 3:
        print("用法：python tools/logdiff.py a.log b.log")
        return 2
    a = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
    b = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace").splitlines()
    na, ca = normalize(a)
    nb, cb = normalize(b)
    print(f"规范化统计：A={ca}  B={cb}")
    if na == nb:
        print(f"规范化后逐字相同：是（各 {len(na)} 行）")
        return 0
    print(f"规范化后仍有差异：A={len(na)} 行，B={len(nb)} 行")
    import difflib
    for line in list(difflib.unified_diff(na, nb, "A", "B", lineterm=""))[:40]:
        print(line)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
