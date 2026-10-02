"""tools/report_seeds.py —— 从 seeds.json 现算三维比较表（markdown）

输出即"开题前的比较文档"：候选 × 三维（数据/资源/评价）+ 风险表 + 每条的
实测基线（行数与探针由 check_seeds.py 复核）。**选定哪一个是用户的决定**——
表格只负责让比较有据可依。

用法：python tools/report_seeds.py [--write]（--write 写 build/seeds.md）
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load():
    import json
    return json.loads((ROOT / "data" / "seeds.json").read_text(encoding="utf-8"))


def render_report(data: dict) -> str:
    seeds = data["seeds"]
    chosen = data.get("chosen") or []
    if isinstance(chosen, dict):
        chosen = [chosen]
    lines = ["# B41 毕设种子：候选三维可行性比较（选定由你）", "",
             "> 数字全部由 `tools/check_seeds.py` 现算复核（行数重算、缺口探针重跑）；",
             "> **选定由你**——本表不替你开题，候选题清单不等于开题。", ""]
    if chosen:
        lines += [f"## 已选定并实施（{len(chosen)} 个）", ""]
        for c in chosen:
            lines += [f"### {c['title']}（{c['date']}）", "",
                      c["note"], "",
                      f"证据：`{c['evidence']['path']}`（锚点 {c['evidence']['anchor']}）", ""]
        if seeds:
            lines += [f"## 其余候选比较（如果你还想调整方向，下面 {len(seeds)} 个仍然可选）", ""]
        else:
            lines += ["## 候选表已清零（5 个候选全部选定实施完成）", ""]
    lines += ["| # | 候选 | 研究问题 | 数据面 | 资源面 | 评价面 |",
              "|---|---|---|---|---|---|"]
    for i, seed in enumerate(seeds, 1):
        lines.append(f"| {i} | **{seed['title']}** | {seed['question']} | "
                     f"{seed['data']} | {seed['resources']} | {seed['evaluation']} |")
    lines += ["", "## 风险对照", "", "| 候选 | 主要风险 |", "|---|---|"]
    for seed in seeds:
        lines.append(f"| {seed['title']} | {seed['risks']} |")
    lines += ["", "## 每条的实测基线（check_seeds.py 复核）", ""]
    for seed in seeds:
        lines.append(f"### {seed['title']}")
        lines.append("")
        lines.append(f"- 基线证据：`{seed['evidence']['path']}`（锚点 {seed['evidence']['anchor']}）")
        for item in seed["files"]:
            lines.append(f"- 文件：`{item['path']}` = {item['lines']} 行")
        for probe in seed["probes"]:
            if probe["kind"] == "code-count":
                detail = (f"`{probe['glob']}` 中 `{probe['pattern']}` 计数"
                          f" = {probe['expected']}")
            elif probe["kind"] == "file-exists":
                detail = f"`{probe['path']}` 存在"
            else:
                detail = (f"import {probe['module']} "
                          f"{'可导入' if probe['expected'] else '不可导入'}")
            lines.append(f"- 探针：**{probe['name']}**（{detail}）")
        lines.append("")
    ids = "、".join(c["id"] for c in chosen) if chosen else "（无）"
    tail = ("候选表已清零；如要加新候选或调整方向，把方向告诉我即可。"
            if not seeds else "其余候选如要改选，把 id 告诉我即可。")
    lines += ["---",
              f"已选定并实施：{ids}（2026-10-02）。{tail}",
              "选定前建议先跑 `run.bat` 把基线与 fsync 基准都过一遍。"]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    report = render_report(_load())
    print(report)
    if "--write" in argv:
        out = ROOT / "build"
        out.mkdir(exist_ok=True)
        (out / "seeds.md").write_text(report, encoding="utf-8")
        print("\n[written] build/seeds.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
