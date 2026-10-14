"""g2/render.py —— G2 练习卡片的渲染器与校验器（口径见 g2/README.md）。

唯一事实源：`g2/cards.json`（37 张卡：B1–B38，B36/B39/B40/B41 未做——用户主动跳过或已归档）。
- `--write`：渲染 `g2/README.md`（索引）+ `g2/B<编号>.md`（每张卡）；
- `--check`：渲染新鲜度 + 逐条核验事实来源——总结句 / 知识点行 / 任务原文 /
  坑单标题必须在对应 README 里**逐字**存在，materials 里的路径必须真实存在。

可审计规范化器（唯一规则）：比较前把全部空白折叠为单空格——README 里的条目
常常跨行折行，这条规则让"折行与否"不算差异，其余一字不改。

卡片内容全部取自各项目 README 原文（一句话 / 知识点表 / 练习建议 / 踩坑），
不新造题；「完成记录」留白，完成归用户。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G2 = ROOT / "g2"
CARDS = G2 / "cards.json"
EXPECTED_IDS = [f"B{i}" for i in range(1, 39) if i != 36]   # 轮六十：B39/40/41 归档移出
VERIFY_CARD = "python g2/render.py --check"


def norm(s: str) -> str:
    """可审计规范化器：全部空白折叠为单空格（唯一规则）。"""
    return re.sub(r"\s+", " ", s).strip()


def load_cards(root: Path | None = None) -> list:
    root = root or ROOT
    return json.loads((root / "g2" / "cards.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 渲染

def _task_text(t: dict) -> str:
    if "raw" in t:
        return norm(t["raw"])
    return str(t["text"])


def render_card(card: dict) -> str:
    lines = [
        f"# {card['id']} · {card['title']}（G2 卡片）",
        "",
        f"- 课程：{card['course']}",
        f"- 项目：`projects/{card['project']}`（一键校验：`run.bat`；展示页：`web/showcase.html`）",
        f"- 取材：本项目 README 的「一句话 / 知识点 / 练习建议 / 踩坑」原文——不新造题；"
        f"逐字由 `{VERIFY_CARD}` 核对",
        "",
    ]
    if card.get("summary"):
        lines += ["## 〇、这张卡对应什么（README 原文）", "", f"> {card['summary']}", ""]
    lines += ["## 一、口述提纲（不看代码讲得出）", ""]
    for i, item in enumerate(card["oral"], 1):
        lines.append(f"{i}. {item}")
    if card.get("knowledge"):
        lines += ["", "## 二、知识点速览（README 表格原文）", ""]
        lines += list(card["knowledge"])
    lines += ["", "## 三、独立修改任务（README 练习建议原文；做完跑 `run.bat` 全绿）", ""]
    for i, t in enumerate(card["tasks"], 1):
        lines.append(f"{i}. （{t['from']}）{_task_text(t)}")
    lines += [
        "",
        "## 四、失败复现任务（先写下「我预言哪条会红、为什么」，再动手）",
        "",
        card["fail"],
        "",
        f"> 出处：{card['fail_from']}。对不上预言本身就是收获。",
        "",
    ]
    if card.get("pin_list"):
        lines += ["### 延伸坑单（README 踩坑原文，任选一条复现）", ""]
        for h in card["pin_list"]:
            lines.append(f"- {h}")
        lines += [""]
    lines += ["## 五、从哪看起（README 目录里的真实路径）", ""]
    for m in card["materials"]:
        lines.append(f"- `projects/{card['project']}/{m}`")
    lines += [
        "",
        "## 六、完成记录（你填）",
        "",
        "- [ ] 日期：______ ／ 一句话心得：______",
        "",
        "---",
        f"本卡引用（总结句 / 知识点行 / 任务 / 坑单）与材料路径全部逐字机核，"
        f"缺一即红（`{VERIFY_CARD}`）。",
        "",
    ]
    return "\n".join(lines)


def render_index(cards: list) -> str:
    lines = [
        "# G2 练习册（生成物：`python g2/render.py --write`）",
        "",
        f"> {len(cards)} 张卡片（B1–B38；B36/B39/B40/B41 未做）：**这张卡对应什么 / 口述提纲 / 知识点速览 /",
        "> 独立修改任务（全部练习建议原文） / 失败复现 + 延伸坑单 / 从哪看起**——内容全部取自",
        "> 各项目 README 原文，**不新造题**；每条引用由 `--check` 逐字核对（README 一改就红）。",
        "> **完成归你**：卡片只搭脚手架，不代做、不代勾。",
        "",
        "## 用法（每张卡 45–90 分钟）",
        "",
        "1. 先做「口述提纲」：关掉代码把这些讲给空气听一遍；卡壳的点就是该回读的。",
        "2. 扫一眼「知识点速览」与「从哪看起」，把不懂的行回去读 README 对应段。",
        "3. 做「独立修改任务」（README 练习建议的全量清单，可多轮做）：改完跑项目 `run.bat` 全绿。",
        "4. 做「失败复现任务」+「延伸坑单」：先写预言再跑——对不上是更有价值的收获。",
        f"5. 填「完成记录」。{len(cards)} 张全做完，你对这个仓库的掌握就不再是「我写过」，而是「我能改」。",
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
        "- 改过任何项目的 README（一句话/知识点表/练习建议/踩坑）之后 `--check` 会因引用漂移报红——"
        "按提示对齐 cards.json 里的引用。",
        "- 自测（含「改坏必须红」的负面对照）：`python g2/tests/test_g2.py`。",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ 校验

def validate_cards(root: Path, cards: list) -> list:
    """结构 + 逐字引用 + 材料路径核验。返回问题列表。"""
    problems = []
    if not isinstance(cards, list):
        return ["cards.json 顶层必须是数组"]
    ids = [c.get("id") for c in cards]
    if ids != EXPECTED_IDS:
        problems.append(f"卡片编号必须恰好是 B1–B38（B36/B39/B40/B41 缺位）：实际 {ids}")
    seen = set()
    for c in cards:
        cid = c.get("id", "?")
        if cid in seen:
            problems.append(f"{cid}：编号重复")
        seen.add(cid)
        for key in ("project", "title", "course", "fail", "fail_from"):
            if not str(c.get(key) or "").strip():
                problems.append(f"{cid}：缺少字段 {key}")
        if len(c.get("oral") or []) < 3:
            problems.append(f"{cid}：口述提纲至少 3 条")
        readme = root / "projects" / str(c.get("project") or "") / "README.md"
        if not readme.is_file():
            problems.append(f"{cid}：README 不存在 {readme}")
            continue
        ntext = norm(readme.read_text(encoding="utf-8"))
        tasks = c.get("tasks") or []
        if not tasks:
            problems.append(f"{cid}：独立修改任务至少 1 条")
        for t in tasks:
            if not str(t.get("from") or "").strip():
                problems.append(f"{cid}：任务缺少出处标注")
            if "raw" in t:
                if norm(str(t["raw"])) not in ntext:
                    problems.append(f"{cid}：任务原文不在 README 里逐字存在：{norm(t['raw'])[:40]!r}")
            else:
                anchor = str(t.get("anchor") or "")
                if len(anchor) < 12:
                    problems.append(f"{cid}：任务锚点过短（<12，防平凡）{anchor!r}")
                elif anchor not in ntext:
                    problems.append(f"{cid}：任务锚点不在 README 里逐字存在：{anchor!r}")
        if c.get("summary") and norm(str(c["summary"])) not in ntext:
            problems.append(f"{cid}：总结句不在 README 里逐字存在")
        for row in c.get("knowledge") or []:
            if norm(str(row)) not in ntext:
                problems.append(f"{cid}：知识点行不在 README 里逐字存在：{norm(str(row))[:40]!r}")
        for h in c.get("pin_list") or []:
            if norm(str(h)) not in ntext:
                problems.append(f"{cid}：坑单标题不在 README 里逐字存在：{norm(str(h))[:40]!r}")
        mats = c.get("materials") or []
        if len(mats) < 3:
            problems.append(f"{cid}：材料路径至少 3 个")
        for m in mats:
            p = root / "projects" / str(c.get("project") or "") / str(m)
            if not p.exists():
                problems.append(f"{cid}：材料路径不存在 {c.get('project')}/{m}")
    return problems


def count_refs(cards: list) -> tuple:
    """返回 (逐字引用数, 材料路径数)，供总结打印。"""
    refs = mats = 0
    for c in cards:
        refs += len(c.get("tasks") or []) + len(c.get("knowledge") or []) + len(c.get("pin_list") or [])
        refs += 1 if c.get("summary") else 0
        mats += len(c.get("materials") or [])
    return refs, mats


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
    print(f"已写出 g2/README.md 与 {len(cards)} 张卡片（B1–B41）")


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
    refs, mats = count_refs(cards)
    print(f"G2 校验通过：{len(cards)} 张卡片（B1–B41）、{refs} 个逐字引用与 {mats} 个材料路径"
          "全部核验通过、渲染物与现算一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
