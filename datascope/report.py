"""datascope/report.py —— SVG 报告渲染（轮四之三）：清洗账本 + 挖掘摘要 → 一张图。

吸收 B28 的血缘思想：报告里能看到"数据从哪来、每一步动过什么"——
清洗步骤链逐条画出，账本计数原样展示；挖掘结果（可选）作为第二个区块。
所有文本 html.escape（B32 的 XSS 规矩），尺寸随内容自适应。
"""
from __future__ import annotations

import html


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def render_report(report: dict, mining: dict | None = None,
                  title: str = "DataScope 清洗报告") -> str:
    """清洗报告（datascope.apply_recipe 的 report）+ 可选挖掘结果 → SVG 字符串。"""
    steps = report.get("steps", [])
    width = 760
    row_h = 34
    head_h = 96
    mining_h = (58 + 24 * len(mining.get("itemsets", []) + mining.get("rules", []))
                if mining else 0)
    height = head_h + len(steps) * row_h + 46 + mining_h + 40

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui,\'Microsoft YaHei\',sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#f5f6f8"/>',
        f'<rect x="16" y="14" width="{width - 32}" height="52" rx="10" fill="#1d4ed8"/>',
        f'<text x="32" y="38" fill="#fff" font-size="17" font-weight="650">{_esc(title)}</text>',
        f'<text x="32" y="57" fill="#dbe7ff" font-size="12">DataScope · 报告即账本 · '
        f'rows {_esc(report.get("rows_before"))} → {_esc(report.get("rows_after"))}</text>',
        '<text x="16" y="90" fill="#5f6773" font-size="13">清洗账本（每步计数 = 动过多少行/格）</text>',
    ]

    y = head_h
    if not steps:
        parts.append(f'<text x="24" y="{y}" fill="#a41f1f" font-size="13">（配方为空：没有执行任何清洗步骤）</text>')
        y += row_h
    for step in steps:
        counts = "；".join(f"{k}={v}" for k, v in step.get("counts", {}).items()) or "（无改动）"
        dark = step["step"] % 2 == 1
        parts.append(f'<rect x="16" y="{y}" width="{width - 32}" height="{row_h - 8}" '
                     f'rx="6" fill="{"#ffffff" if dark else "#eef3ff"}"/>')
        parts.append(f'<text x="28" y="{y + 17}" fill="#16181d" font-size="12.5">'
                     f'第 {_esc(step["step"])} 步 {_esc(step["op"])}'
                     f'　行 {_esc(step["rows_before"])}→{_esc(step["rows_after"])}</text>')
        parts.append(f'<text x="28" y="{y + 31}" fill="#5f6773" font-size="11.5">{_esc(counts)}</text>')
        y += row_h

    parts.append(f'<text x="16" y="{y + 18}" fill="#5f6773" font-size="13">画像（清洗后）</text>')
    y += 24
    profile_after = report.get("profile_after", {})
    for name, stat in profile_after.items():
        parts.append(f'<text x="24" y="{y + 12}" fill="#16181d" font-size="11.5">'
                     f'{_esc(name)}：{_esc(stat["type"])}，缺失 {_esc(stat["missing"])}，'
                     f'去重 {_esc(stat["distinct"])}</text>')
        y += 17

    if mining:
        y += 30
        parts.append(f'<text x="16" y="{y}" fill="#5f6773" font-size="13">'
                     f'挖掘（{_esc(mining.get("task"))}，B26 引擎）</text>')
        y += 20
        for itemset in mining.get("itemsets", [])[:8]:
            parts.append(f'<text x="24" y="{y + 12}" fill="#16181d" font-size="11.5">'
                         f'项集 {{{_esc("，".join(itemset["items"]))}}}　'
                         f'计数 {_esc(itemset["count"])}　支持度 {_esc(itemset["support"])}</text>')
            y += 17
        for rule in mining.get("rules", [])[:6]:
            parts.append(f'<text x="24" y="{y + 12}" fill="#16181d" font-size="11.5">'
                         f'规则 {{{_esc("，".join(rule["ante"]))}}} → '
                         f'{{{_esc("，".join(rule["cons"]))}}}　'
                         f'置信度 {_esc(rule["confidence"])}　提升度 {_esc(rule["lift"])}</text>')
            y += 17
        if not mining.get("itemsets") and not mining.get("rules"):
            parts.append(f'<text x="24" y="{y + 12}" fill="#a41f1f" font-size="11.5">'
                         '（该支持度下没有频繁项集）</text>')
            y += 17

    parts.append(f'<text x="16" y="{height - 14}" fill="#94a0ad" font-size="11">'
                 'DataScope P4 · 引擎 import 原项目（B26），零重写 · 本图为现算产出</text>')
    parts.append("</svg>")
    return "".join(parts)
