"""src/logstat.py —— 编译日志分析：把噪声统计成"哪类警告最多"。

课程要点（软件开发技术基础的教学扩展）：
    - 日志分析的第一步是**定格式**：GCC/Clang 的 `file:line:col: severity: message`；
    - 真正有用的是**聚合**：同一类消息（把行号/列号抹掉之后）出现多少次——
      不然 3000 行日志里"到底哪条最该修"是看不出来的；
    - 统计器要能对空日志、混合格式与"零警告"给出正确答案，而不是崩掉或假装有数据。
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

DIAG = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
                  r"(?P<sev>warning|error|note):\s*(?P<msg>.*)$")
SUMMARY = re.compile(r"^\s*(?P<count>\d+)\s+(?P<sev>warning|error)s?\s+generated", re.I)


def parse(text: str) -> dict:
    """返回 {"by_severity": {…}, "top": [(模板, 次数)], "summaries": […] }。"""
    by_sev: Counter[str] = Counter()
    templates: Counter[str] = Counter()
    summaries: list[tuple[int, str]] = []
    for raw in text.splitlines():
        m = DIAG.match(raw)
        if m:
            sev = m.group("sev")
            by_sev[sev] += 1
            # 把数字抹掉再聚合：同一类消息才算"一类"
            template = re.sub(r"\d+", "N", m.group("msg")).strip()
            templates[f"{sev}: {template}"] += 1
            continue
        s = SUMMARY.match(raw)
        if s:
            summaries.append((int(s.group("count")), s.group("sev").lower()))
    return {"by_severity": dict(by_sev), "top": templates.most_common(5),
            "summaries": summaries}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="编译日志统计（按消息模板聚合）")
    parser.add_argument("logfile")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args(argv)
    path = Path(args.logfile)
    if not path.is_file():
        print(f"logstat: 找不到日志 {path}", file=sys.stderr)
        return 2
    report = parse(path.read_text(encoding="utf-8", errors="replace"))
    print(f"日志：{path}（{sum(report['by_severity'].values())} 条诊断）")
    for sev in ("error", "warning", "note"):
        if report["by_severity"].get(sev):
            print(f"  {sev:<8}{report['by_severity'][sev]}")
    print(f"  顶部 {args.top} 类：")
    for template, count in report["top"][:args.top]:
        print(f"    {count:>4} × {template}")
    for count, sev in report["summaries"]:
        print(f"  工具自带汇总：{count} {sev}s generated")
    if not report["by_severity"] and not report["summaries"]:
        print("  没有可统计的诊断行（空日志或格式不符——都算 0，不是失败）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
