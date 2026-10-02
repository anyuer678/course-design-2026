"""tools/logdiff.py —— run.bat 两次日志的规范化比对（B35：只有两处实测数字）

B35 的演示内容由固定种子驱动，唯一不稳定的就是标注【实测】的两行：
    吞吐【实测】  333 条/秒   →  数字是实时测量
    重连耗时【实测】 16 ms     →  同上
本工具把这两类数字规范成占位符后逐字比对；其余任何差异都算失败。
（同 B29 的 logdiff 纪律：规范条目会打印出来供审计，不允许偷偷滤内容。）

用法：python tools/logdiff.py a.log b.log
"""
from __future__ import annotations

import pathlib
import re
import sys

RULES: list[tuple[str, re.Pattern, str]] = [
    ("吞吐实测", re.compile(r"[\d.]+ 条/秒"), "X 条/秒"),
    ("重连耗时实测", re.compile(r"[\d.]+ ms（含 broker 启动）"), "X ms（含 broker 启动）"),
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
