"""g2/render.py —— G2 练习卡片的渲染器与校验器（口径见 g2/README.md）。

唯一事实源：`g2/cards.json`（22 张卡：B1–B22）。
- `--write`：渲染 `g2/README.md`（索引）+ `g2/B<编号>.md`（每张卡）；
- `--check`：重算比对（渲染过期即红），并逐条核验事实来源——
  每张卡的每个来源锚点必须**逐字**存在于目标文件里（README 措辞一漂就红），
  锚点长度 ≥ 12（防"短串哪都能命中"的平凡锚点）。

卡片内容全部取自各项目 README 的「练习建议」「踩过的坑」与 dorm-repair 的练习
（不新造题）；「完成记录」留白，完成归用户。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G2 = ROOT / "g2"
CARDS = G2 / "cards.json"
EXPECTED_IDS = [f"B{i}" for i in range(1, 23)]

VERIFY_CARD = "python g2/render.py --check"


def load_cards(root: Path | None = None) -> list:
    root = root or ROOT
    return json.loads((root / "g2" / "cards.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 渲染

def render_card(card: dict) -> str:
    lines = [
        f"# {card['id']} · {card['title']}（G2 卡片）",
        "",
        f"- 课程：{card['course']}",
        f"- 项目：`projects/{card['project']}`（一键校验：`run.bat`）",
        f"- 取材：项目 README 的「练习建议」「知识点」「踩过的坑」；锚点由 `{VERIFY_CARD}` 逐字核对",
        "",
        "## 一、口述提纲（不看代码讲得出）",
        "",
    ]
    for i, item in enumerate(card["oral"], 1):
        lines.append(f"{i}. {item}")
    lines += [
        "",
        f"## 二、独立修改任务（出处：{card['modify_from']}）",
        "",
        card["modify"],
        "",
        "做完的标准：改完后 `run.bat` 全绿，且你能在口述提纲里补上「这次改动的取舍」。",
        "",
        f"## 三、失败复现任务（出处：{card['fail_from']}）",
        "",
        card["fail"],
        "",
        "先写下「我预言哪条会红、为什么」，再动手跑；对不上预言本身就是收获。",
        "",
        "## 四、完成记录（你填）",
        "",
        "- [ ] 日期：______ ／ 一句话心得：______",
        "",
        "## 来源（逐字锚点，机器核对）",
        "",
    ]
    for s in card["sources"]:
        lines.append(f"- `{s['file']}`：「{s['anchor']}」")
    lines.append("")
    return "\n".join(lines)


def render_index(cards: list) -> str:
    lines = [
        "# G2 练习册（生成物：`python g2/render.py --write`）",
        "",
        "> 22 张卡片（B1–B22）：**口述提纲 / 独立修改任务 / 失败复现任务**——内容全部取自",
        "> 各项目 README 的「练习建议」与「踩过的坑」（或 dorm-repair 的练习），**不新造题**；",
        f"> 每张卡的来源锚点由 `{VERIFY_CARD}` 逐字核对，README 一改就红。",
        "> **完成归你**：卡片只搭脚手架，不代做、不代勾。",
        "",
        "## 用法（每张卡 30–60 分钟）",
        "",
        "1. 先做「口述提纲」：关掉代码把这些讲给空气听一遍；卡壳的点就是该回读的。",
        "2. 做「独立修改任务」：改完跑项目 `run.bat`，全绿再收手。",
        "3. 做「失败复现任务」：先写下「我预言哪条会红」，再跑——对不上是更有价值的收获。",
        "4. 填「完成记录」。22 张全做完，你对这个仓库的掌握就不再是「我写过」，而是「我能改」。",
        "",
        "## 卡片",
        "",
        "| 卡 | 主题 | 课程 | 项目 |",
        "|---|---|---|---|",
    ]
    for c in cards:
        lines.append(f"| [{c['id']}]({c['id']}.md) | {c['title']} | {c['course']} | "
                     f"`projects/{c['project']}` |")
    lines += [
        "",
        "## 维护",
        "",
        f"- 机器可读源是 `g2/cards.json`；重渲染 `python g2/render.py --write`，校验 `{VERIFY_CARD}`。",
        "- 改过任何项目的 README 练习建议/坑之后，`--check` 会因锚点漂移报红——按提示对齐锚点与文案。",
        "- 自测（含「改坏必须红」的负面对照）：`python g2/tests/test_g2.py`。",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ 校验

def validate_cards(root: Path, cards: list) -> list:
    """结构 + 锚点核验。返回问题列表。"""
    problems = []
    if not isinstance(cards, list):
        return ["cards.json 顶层必须是数组"]
    ids = [c.get("id") for c in cards]
    if ids != EXPECTED_IDS:
        problems.append(f"卡片编号必须恰好是 B1–B22 各一张：实际 {ids}")
    seen = set()
    for c in cards:
        cid = c.get("id", "?")
        if cid in seen:
            problems.append(f"{cid}：编号重复")
        seen.add(cid)
        for key in ("project", "title", "course", "modify", "modify_from", "fail", "fail_from"):
            if not str(c.get(key) or "").strip():
                problems.append(f"{cid}：缺少字段 {key}")
        if len(c.get("oral") or []) < 3:
            problems.append(f"{cid}：口述提纲至少 3 条")
        sources = c.get("sources") or []
        if len(sources) < 3:
            problems.append(f"{cid}：来源锚点至少 3 个")
        for s in sources:
            f = root / str(s.get("file") or "")
            anchor = str(s.get("anchor") or "")
            if not f.is_file():
                problems.append(f"{cid}：来源文件不存在 {s.get('file')}")
                continue
            if len(anchor) < 12:
                problems.append(f"{cid}：锚点过短（<12，防平凡）{anchor!r}")
                continue
            if anchor not in f.read_text(encoding="utf-8"):
                problems.append(f"{cid}：锚点不在 {s['file']} 里逐字存在：{anchor!r}")
    return problems


def freshness_problems(root: Path, cards: list) -> list:
    """渲染物与现算比对；多余/缺失的卡文件也算红。"""
    problems = []
    expected = {"README.md": render_index(cards)}
    for c in cards:
        if c.get("id"):
            expected[f"{c['id']}.md"] = render_card(c)
    for name, text in expected.items():
        p = root / "g2" / name
        if not p.is_file():
            problems.append(f"g2/{name} 不存在：跑 python g2/render.py --write")
        elif p.read_text(encoding="utf-8") != text:
            problems.append(f"g2/{name} 与 cards.json 现算不一致（过期或手改过）："
                            "跑 python g2/render.py --write")
    for p in sorted((root / "g2").glob("B*.md")):
        if p.name not in expected:
            problems.append(f"g2/{p.name} 是多余文件（cards.json 里没有对应卡）")
    return problems


def check(root: Path | None = None) -> list:
    root = root or ROOT
    if not (root / "g2" / "cards.json").is_file():
        return ["g2/cards.json 不存在"]
    cards = load_cards(root)
    return validate_cards(root, cards) + freshness_problems(root, cards)


def write(root: Path | None = None) -> None:
    root = root or ROOT
    cards = load_cards(root)
    problems = validate_cards(root, cards)
    if problems:
        raise SystemExit("cards.json 自身有问题，拒绝渲染：\n  - " + "\n  - ".join(problems))
    (root / "g2" / "README.md").write_text(render_index(cards), encoding="utf-8", newline="\n")
    for c in cards:
        (root / "g2" / f"{c['id']}.md").write_text(render_card(c), encoding="utf-8", newline="\n")
    print(f"已写出 g2/README.md 与 {len(cards)} 张卡片（B1–B22）")


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="G2 练习卡片渲染器/校验器")
    ap.add_argument("--write", action="store_true", help="渲染 g2/README.md 与各卡片")
    ap.add_argument("--check", action="store_true", help="重算比对（不带参数时的默认行为）")
    args = ap.parse_args(argv[1:])
    if args.write:
        write()
        return 0
    problems = check()
    if problems:
        print(f"G2 校验发现 {len(problems)} 处问题：")
        for p in problems:
            print("  -", p)
        return 1
    cards = load_cards()
    n_anchor = sum(len(c["sources"]) for c in cards)
    print(f"G2 校验通过：{len(cards)} 张卡片（B1–B22）、{n_anchor} 个来源锚点逐字可验、"
          "渲染物与现算一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
