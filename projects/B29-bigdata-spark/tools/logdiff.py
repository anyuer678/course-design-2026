"""tools/logdiff.py —— run.bat 两次运行日志的规范化比对（把"噪声"与"内容"分开）

B29 的日志里有三类**机器噪声**天然不稳定，逐字比对前必须先规范化（并报告规范掉了什么，
供审计——不允许偷偷滤掉内容）：
    1. JVM 日志的时间戳前缀：`26/10/02 17:50:52 WARN ...` → 去掉时间戳保留正文；
    2. Spark 收尾时的进程清理播报：`SUCCESS: The process with PID ...` 整行去除
       （这是 Windows taskkill 的输出，出现位置和 PID 都不稳定）；
    3. 计时数字：`Ran 17 tests in 45.073s` 与演示第 6 段的 `plain 173 ms / salted 250 ms`
       —— 实时测量值，规范化成占位符（行数与上下文仍然参与比对）。

用法：python tools/logdiff.py a.log b.log
通过（规范化后逐字相同）返回 0；不同则打印差异行并返回 1。
"""
from __future__ import annotations

import pathlib
import re
import sys

RULES: list[tuple[str, re.Pattern, str]] = [
    ("JVM 时间戳", re.compile(r"^\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} "), ""),
    ("进程清理播报", re.compile(r"^SUCCESS: The process with PID .*$"), ""),   # 整行删：出现位置不稳定
    ("unittest 计时", re.compile(r"^(Ran \d+ tests) in [\d.]+s$"), r"\1"),
    ("实测耗时", re.compile(r"plain \d+ ms / salted \d+ ms"), "plain X ms / salted X ms"),
    ("生成耗时", re.compile(r"用时\s+[\d.]+ s"), "用时 X s"),
    ("warehouse 临时名", re.compile(r"b29-warehouse-\w+"), "b29-warehouse-<tmp>"),
]


def normalize(lines: list[str]) -> tuple[list[str], dict[str, int]]:
    counts: dict[str, int] = {}
    out: list[str] = []
    for line in lines:
        dropped = False
        for name, pattern, repl in RULES:
            if pattern.search(line):
                line = pattern.sub(repl, line)
                counts[name] = counts.get(name, 0) + 1
                if line.strip() == "" and name == "进程清理播报":
                    dropped = True
        if not dropped:
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
    print(f"规范化统计：A={ {k: v for k, v in ca.items()} }  B={ {k: v for k, v in cb.items()} }")

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
