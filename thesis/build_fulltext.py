"""thesis/build_fulltext.py —— 把章节草稿合并成全文草稿（含目录与字数统计）。

章节文件是唯一出处；本脚本只做**机械合并**（不改正文），产物
`全文草稿.md` 头部标注"自动生成，勿手改"——改内容请改章节文件后重跑。
格式清理两件（不动正文）：剥离章节头部的"> 状态：草稿"块、去掉与注入
标题重复的文件自带 H1。此前 `^> 状态：` 正则因章节先有 # 标题而从未
命中——合并稿一直漏泄状态头（2026-10-06 通读合并稿时抓出）。
用法：python build_fulltext.py
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "全文草稿.md"

# 合并顺序：摘要 → ch1..ch6 → ch0（作为附录 A 前期工程基础）→ 参考文献
PARTS = [
    ("摘要", "摘要.md"),
    ("第 1 章 绪论", "ch1-绪论.md"),
    ("第 2 章 需求分析", "ch2-需求分析.md"),
    ("第 3 章 系统设计", "ch3-系统设计.md"),
    ("第 4 章 系统实现", "ch4-系统实现.md"),
    ("第 5 章 系统测试与部署", "ch5-系统测试与部署.md"),
    ("第 6 章 总结与展望", "ch6-总结与展望.md"),
    ("附录 A 前期工程基础（产品矩阵）", "ch0-前期工程基础.md"),
    ("附录 B 参考文献草稿", "references.md"),
]


def cjk_words(text: str) -> int:
    """粗口径字数：CJK 字符逐字计 + 连续拉丁词计一（对照学校字数要求够用）。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9./_'-]*", text))
    return cjk + latin


def _strip_state_block(text: str) -> str:
    """剥离章节头部的"> 状态：…"块（含其连续 > 续行与块后空行）。"""
    out: list[str] = []
    stripping = False
    for ln in text.splitlines():
        if not stripping and ln.startswith("> 状态："):
            stripping = True
            continue
        if stripping:
            if ln.startswith(">") or ln.strip() == "":
                continue
            stripping = False
        out.append(ln)
    return "\n".join(out)


def _drop_duplicate_h1(text: str, title: str) -> str:
    """文件首个非空行恰为注入标题的 H1 时，去掉文件那份（避免合并稿标题双份）。"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "":
            continue
        if ln.strip() == f"# {title}":
            lines.pop(i)
        break
    return "\n".join(lines)


def main() -> int:
    parts: list[str] = [
        "<!-- 自动生成：python build_fulltext.py —— 勿手改；改章节文件后重跑 -->",
        f"<!-- 生成时间：{datetime.datetime.now():%Y-%m-%d %H:%M} -->",
        "# 毕业论文草稿（全文合并稿）",
        "",
        "> 题目（2026-10-06 定稿）：零第三方依赖的课程实验教学平台 CourseLab 的设计与实现",
        "> Design and Implementation of CourseLab: A Course Experiment Platform with Zero Third-Party Dependencies",
        "",
        "> CourseLab 课程工坊为论文主体，产品矩阵为工程背景。",
        "> 学校模板到手后：按模板重排编号/字体/图表号，核对英文摘要格式。",
        "",
        "## 目录",
        "",
    ]
    body: list[str] = []
    total = 0
    for title, name in PARTS:
        text = (ROOT / name).read_text(encoding="utf-8")
        text = _strip_state_block(text)        # 状态头（含素材/数字口径等草稿注记）
        text = _drop_duplicate_h1(text, title)  # 文件自带 H1 与注入标题重复时去一份
        parts.append(f"- {title}")
        body.append(f"\n\n# {title}\n\n{text.strip()}\n")
        words = cjk_words(text)
        total += words
        body.append(f"\n<!-- [{name}] 字数（粗口径）：{words} -->\n")
    parts.append(f"- 全文字数（粗口径）：约 {total}")
    doc = "\n".join(parts) + "\n" + "".join(body)
    OUT.write_text(doc, encoding="utf-8")
    print(f"已生成 {OUT.name}（{OUT.stat().st_size} 字节，粗口径字数 约 {total}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
