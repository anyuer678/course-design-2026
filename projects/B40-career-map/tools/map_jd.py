"""tools/map_jd.py —— JD 映射器：岗位描述 → 技能命中 → 已有证据 vs 缺口

口径（写死并测试，避免"看起来命中"）：
    - 英文关键词按**词边界**匹配：JD 小写化后切成 [a-z0-9+#.] 的 token，
      单 token 关键词要整个 token 相等（`go` 不会被 `gold` 命中）；
      含空格的短语（如 `spring boot`）在整文里做大小写不敏感的子串匹配；
    - 中文关键词**子串**匹配（中文没有词边界，这是显式口径不是偷懒）；
    - 命中且技能有证据 → "已覆盖"（列出证据条目，可去 check_evidence.py 复核）；
    - 命中但 skill.evidence 为空 → **缺口**（并给出 practice 下一步）。

用法：
    python tools/map_jd.py                # 读 jd/*.txt（文件名以 EXAMPLE 开头的会带示例横幅）
    python tools/map_jd.py --write        # 同时写 build/jd_matrix.md（默认只打 stdout）
无 JD 文件时打印怎么放文件并退出 2——**映射什么岗位由你决定，本工具不替你选**。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASCII_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


def load_skills(path) -> list[dict]:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))["skills"]


def load_evidence(path) -> dict[str, dict]:
    entries = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))["evidence"]
    return {e["id"]: e for e in entries}


def tokenize(text: str) -> set[str]:
    return set(ASCII_TOKEN_RE.findall(text.lower()))


def hit(keyword: str, tokens: set[str], lowered: str) -> bool:
    if all(ord(ch) < 128 for ch in keyword):
        if " " in keyword:
            return keyword in lowered          # 英文短语：子串（含空格，误命中小）
        return keyword in tokens               # 英文单词：词边界（token 相等）
    return keyword in lowered                  # 中文：子串（口径见头注释）


def match_skills(text: str, skills: list[dict]) -> list[dict]:
    tokens = tokenize(text)
    lowered = text.lower()
    rows = []
    for skill in skills:
        hits = [kw for kw in skill["keywords"] if hit(kw.lower(), tokens, lowered)]
        if hits:
            rows.append({"skill": skill, "hits": hits})
    return rows


def render_matrix(jd_name: str, text: str, skills: list[dict],
                  evidence: dict[str, dict], example: bool) -> str:
    lines = [f"# JD 映射矩阵：{jd_name}", ""]
    if example:
        lines += ["【示例（非真实岗位）】本文件是合成 JD，只演示工具怎么用；"
                  "把你的真实 JD 存成 jd/岗位名.txt 后重跑，映射结果才是你的。", ""]
    rows = match_skills(text, skills)
    lines += ["| 技能面 | 命中关键词 | 状态 | 证据 / 缺口练习 |", "|---|---|---|---|"]
    gaps, used_evidence = [], []
    for row in rows:
        skill = row["skill"]
        hits = "、".join(row["hits"])
        if skill["evidence"]:
            state = f"已覆盖（{len(skill['evidence'])} 条）"
            detail = "、".join(skill["evidence"])
            for eid in skill["evidence"]:
                if eid not in [u["id"] for u in used_evidence]:
                    used_evidence.append(evidence[eid])
        else:
            state = "**缺口**"
            detail = f"下一步：{skill['practice']}"
            gaps.append(skill)
        lines.append(f"| {skill['name']} | {hits} | {state} | {detail} |")
    missed = [s["name"] for s in skills
              if s["id"] not in [r["skill"]["id"] for r in rows]]
    lines += ["", f"**缺口清单（{len(gaps)} 项）**：" +
              ("；".join(s["name"] for s in gaps) if gaps else "无——但不能因此松口气："
               "真实 JD 的细分要求（框架/工具级）通常比技能面更窄。"), ""]
    if used_evidence:
        lines += ["证据明细（逐条可在 `tools/check_evidence.py` 复核）：", ""]
        for e in used_evidence:
            lines.append(f"- `{e['id']}`：{e['claim']}（指针：{e['pointers'][0]}"
                         + (f"，提交 `{e['commit']}`" if e.get("commit") else "") + "）")
        lines.append("")
    if missed:
        lines += [f"JD 未提及（不计入矩阵）：{'、'.join(missed)}", ""]
    lines += ["---",
              "本表由工具从「JD 文本 × 技能表 × 证据索引」现算；**不替代真实工作场景**——",
              "团队协作与业务上下文要靠真实团队实践。"]
    return "\n".join(lines)


def collect_jds(jd_dir) -> list[tuple[pathlib.Path, bool]]:
    jd_dir = pathlib.Path(jd_dir)
    out = []
    if jd_dir.is_dir():
        for p in sorted(jd_dir.glob("*.txt")):
            out.append((p, p.name.upper().startswith("EXAMPLE")))
    return out


def main(argv: list[str]) -> int:
    write = "--write" in argv
    jds = collect_jds(ROOT / "jd")
    if not jds:
        print("jd/ 里没有 .txt 文件——把你的目标岗位 JD 存成 jd/岗位名.txt 后重跑；")
        print("（本工具不替你选岗位：映射什么，由放进来的 JD 决定。）")
        return 2
    skills = load_skills(ROOT / "data" / "skills.json")
    evidence = load_evidence(ROOT / "data" / "evidence.json")
    outputs = []
    for path, example in jds:
        outputs.append(render_matrix(path.name, path.read_text(encoding="utf-8"),
                                     skills, evidence, example))
    report = "\n\n".join(outputs)
    print(report)
    if write:
        out = ROOT / "build"
        out.mkdir(exist_ok=True)
        (out / "jd_matrix.md").write_text(report, encoding="utf-8")
        print("\n[written] build/jd_matrix.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
