"""tools/logdiff.py —— run.bat 两次日志的规范化比对（B13：只有 unittest 计时在动）

规则只允许一类（会被打印计数、可供审计）：
    - unittest 的 `Ran 85 tests in 0.9s` → 去计时
其余任何差异都算失败（demo 的输出、用例计数、样例读数都必须是确定性的）。

用法：python tools/logdiff.py a.log b.log
"""
from __future__ import annotations

import pathlib
import re
import sys

RULES: list[tuple[str, re.Pattern, str]] = [
    ("unittest 计时", re.compile(r"^(Ran \d+ tests) in [\d.]+s$"), r"\1"),
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
