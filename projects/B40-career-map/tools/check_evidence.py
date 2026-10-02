"""tools/check_evidence.py —— 证据索引核验器：每条声明必须是"可机验的指针"

课程要点（与 B39 的检查器同一条纪律，作用在"求职证据"上）：
简历上的"熟悉 XX"无法核验，但"哪一行代码、哪个提交、哪句实测数字"可以。
本核验器对 data/evidence.json 逐条检查：
    1. pointers 里每个仓库路径必须存在；
    2. commit（若有）必须在 git 里存在；
    3. anchor（若有）必须真出现在某个指针文件里（数字/短语逐字比对）；
    4. id 不许重复；
并交叉检查 data/skills.json：evidence 引用不许悬空；**每条 evidence 必须被至少一个
技能引用**（没人引用的条目就是装饰，同 B22 台账的规矩）。
注意：技能允许**空 evidence**——那正是"缺口"的定义（如容器/K8s），不是错误。

用法：python tools/check_evidence.py [项目根]
退出码 0 = 全部通过；1 = 有问题（逐条打印）。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

DEFAULT_ROOT = pathlib.Path(__file__).resolve().parents[1]     # tools/ → B40-career-map/


def load_json(path) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _commit_exists(repo_root: pathlib.Path, sha: str) -> bool | None:
    """True/False；git 不可用时返回 None。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True, text=True)
    except OSError:
        return None
    return proc.returncode == 0


def check_evidence_data(evidence_path, repo_root) -> list[str]:
    repo_root = pathlib.Path(repo_root)
    problems: list[str] = []
    data = load_json(evidence_path)
    entries = data.get("evidence", [])
    if not entries:
        return ["evidence.json 里没有任何条目"]
    seen: set[str] = set()
    git_broken = False
    for e in entries:
        eid = e.get("id", "")
        if not eid:
            problems.append("有条目缺少 id")
            continue
        if eid in seen:
            problems.append(f"id 重复：{eid}")
        seen.add(eid)
        pointers = e.get("pointers", [])
        if not pointers:
            problems.append(f"{eid}：pointers 为空（证据必须指向具体文件）")
        anchor = e.get("anchor", "")
        if not anchor:
            problems.append(f"{eid}：anchor 为空（数字/短语要能被逐字比对）")
        texts = []
        for rel in pointers:
            p = repo_root / rel
            if not p.is_file():
                problems.append(f"{eid}：指针路径不存在：{rel}")
            else:
                texts.append(p.read_text(encoding="utf-8"))
        if anchor and texts and not any(anchor in t for t in texts):
            problems.append(f"{eid}：anchor {anchor!r} 没有出现在任何指针文件里")
        sha = e.get("commit")
        if sha:
            exists = _commit_exists(repo_root, sha)
            if exists is None:
                if not git_broken:
                    problems.append("找不到 git，无法核验 commit（先装 git 再跑核验器）")
                    git_broken = True
            elif not exists:
                problems.append(f"{eid}：commit 在 git 里不存在：{sha}")
    return problems


def check_skills_data(skills_path, evidence_ids: set[str]) -> list[str]:
    problems: list[str] = []
    data = load_json(skills_path)
    skills = data.get("skills", [])
    if not skills:
        return ["skills.json 里没有任何技能"]
    seen: set[str] = set()
    used: set[str] = set()
    for s in skills:
        sid = s.get("id", "")
        if not sid:
            problems.append("有技能缺少 id")
            continue
        if sid in seen:
            problems.append(f"技能 id 重复：{sid}")
        seen.add(sid)
        if not s.get("keywords"):
            problems.append(f"{sid}：keywords 为空（映射器无法命中它）")
        if not s.get("practice"):
            problems.append(f"{sid}：practice 为空（缺口的下一步练习没人写）")
        for ref in s.get("evidence", []):
            if ref not in evidence_ids:
                problems.append(f"{sid}：引用了不存在的证据 id：{ref}")
            used.add(ref)
    dead = sorted(evidence_ids - used)
    if dead:
        problems.append("有证据条目没有被任何技能引用（装饰条目）：" + "、".join(dead))
    return problems


def main(argv: list[str]) -> int:
    root = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_ROOT
    repo_root = root.parents[1]                     # B40-career-map/ → projects/ → 仓库根
    problems = check_evidence_data(root / "data" / "evidence.json", repo_root)
    ev = load_json(root / "data" / "evidence.json")["evidence"]
    problems += check_skills_data(root / "data" / "skills.json",
                                  {e["id"] for e in ev})
    if not problems:
        print(f"PASS：{len(ev)} 条证据、{len(load_json(root / 'data' / 'skills.json')['skills'])} 个技能面，"
              f"指针/提交/锚点全部核验通过")
        return 0
    print(f"RED：{len(problems)} 个问题")
    for item in problems:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
