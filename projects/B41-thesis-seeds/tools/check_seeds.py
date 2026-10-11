"""tools/check_seeds.py —— 毕设种子的事实核验器：可行性数字不许"文艺创作"

对 data/seeds.json 逐条现算复核（与 B40 的证据核验同一条纪律，但更硬）：
    - files 里的行数用**重算值逐字比对**（谁动了代码，这里立刻红）；
    - probes 是"缺口证明"：code-count 的 glob 必须真匹配到文件
      （否则"计数 0"毫无意义），计数与 expected 相等才算通过；
      import-check 用当前解释器实跑 import（夹具用 stdlib 的 json，跨机器确定）；
    - evidence 的锚点必须真出现在对应 README 里；
    - 每条种子至少 1 个文件、1 个探针，文本段不许空。

用法：python tools/check_seeds.py [项目根]
退出码 0 = 全部通过；1 = 有问题（逐条打印）。
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

DEFAULT_ROOT = pathlib.Path(__file__).resolve().parents[1]
TEXT_FIELDS = ("title", "question", "data", "resources", "evaluation", "risks")


def load_seeds(path) -> list[dict]:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))["seeds"]


def _code_count(repo_root: pathlib.Path, glob_pat: str, pattern: str):
    files = sorted(repo_root.glob(glob_pat))
    files = [f for f in files if f.is_file()]
    total = 0
    for f in files:
        total += len(re.findall(pattern, f.read_text(encoding="utf-8"), re.IGNORECASE))
    return total, len(files)


def _import_ok(module: str) -> bool:
    proc = subprocess.run([sys.executable, "-c", f"import {module}"],
                          capture_output=True, text=True)
    return proc.returncode == 0


def synthetic_seed() -> dict:
    """候选清零态的**注入夹具**：一条必然通过的最小候选（测试与演示的负面对照用）。

    收官后 seeds=[]，但"改坏必须红"的规则不能因此失去牙齿——负面对照先注入这条
    夹具再改坏。钉在 data/iris.csv（151 行，结构稳定）；锚点用 B23 README 的现役短语。
    探针模块必须选**任何 Python 3 都存在的标准库**（json）：夹具要跨机器确定——
    曾钉在 numpy 上，CI runner 没装 numpy，"改坏探针期望值"负面对照当场失效
    （改坏了却没红，页面如实记成 BUG）。import-check 的意义是"期望与实际不符必须红"，
    用 stdlib 模块两头都确定，牙齿才钉得住。
    """
    return {
        "id": "synthetic-fixture", "title": "合成夹具（注入用）",
        "question": "夹具问题？",
        "evidence": {"path": "projects/B23-ml-from-scratch/README.md",
                     "anchor": "54 项双入口同数"},
        "files": [{"path": "projects/B23-ml-from-scratch/data/iris.csv", "lines": 151}],
        "probes": [{"name": "夹具探针", "kind": "import-check",
                    "module": "json", "expected": True}],
        "data": "夹具", "resources": "夹具", "evaluation": "夹具", "risks": "夹具",
    }


def check_seeds_data(seeds_path, repo_root) -> list[str]:
    repo_root = pathlib.Path(repo_root)
    problems: list[str] = []
    data = json.loads(pathlib.Path(seeds_path).read_text(encoding="utf-8"))
    seeds = data.get("seeds", [])
    # 已选定记录（列表）：每条记录的指针与锚点同样要真实存在
    chosen_list = data.get("chosen") or []
    if isinstance(chosen_list, dict):          # 兼容旧格式（单条）
        chosen_list = [chosen_list]
    # 候选表允许清零（全部选定实施后的收官状态）——但"候选与已选定"不能同时为空
    if not seeds and not chosen_list:
        return ["seeds.json 里既没有候选、也没有已选定记录（两边不能同时为空）"]
    for chosen in chosen_list:
        cid = chosen.get("id", "?")
        for field in ("id", "title", "date", "note"):
            if not chosen.get(field):
                problems.append(f"chosen/{cid}：{field} 为空")
        ev_path = repo_root / chosen.get("evidence", {}).get("path", "")
        anchor = chosen.get("evidence", {}).get("anchor", "")
        if not ev_path.is_file():
            problems.append(f"chosen/{cid}：证据路径不存在：{chosen.get('evidence', {}).get('path')}")
        elif anchor and anchor not in ev_path.read_text(encoding="utf-8"):
            problems.append(f"chosen/{cid}：证据锚点 {anchor!r} 不在 {chosen.get('evidence', {}).get('path')} 里")
    seen: set[str] = set()
    for seed in seeds:
        sid = seed.get("id", "")
        if not sid:
            problems.append("有候选缺少 id")
            continue
        if sid in seen:
            problems.append(f"候选 id 重复：{sid}")
        seen.add(sid)
        for field in TEXT_FIELDS:
            if not seed.get(field):
                problems.append(f"{sid}：{field} 为空（三维/问题/风险都要写）")
        evidence = seed.get("evidence", {})
        ev_path = repo_root / evidence.get("path", "")
        anchor = evidence.get("anchor", "")
        if not ev_path.is_file():
            problems.append(f"{sid}：证据路径不存在：{evidence.get('path')}")
        elif anchor and anchor not in ev_path.read_text(encoding="utf-8"):
            problems.append(f"{sid}：证据锚点 {anchor!r} 不在 {evidence.get('path')} 里")
        files = seed.get("files", [])
        if not files:
            problems.append(f"{sid}：files 为空（实测数字从哪来）")
        for item in files:
            p = repo_root / item.get("path", "")
            if not p.is_file():
                problems.append(f"{sid}：文件不存在：{item.get('path')}")
                continue
            actual = len(p.read_text(encoding="utf-8").splitlines())
            if actual != item.get("lines"):
                problems.append(f"{sid}：{item.get('path')} 行数对不上"
                                f"（记录 {item.get('lines')}，实测 {actual}）")
        probes = seed.get("probes", [])
        if not probes:
            problems.append(f"{sid}：probes 为空（缺口要有证明）")
        for probe in probes:
            name = probe.get("name", "?")
            kind = probe.get("kind")
            if kind == "code-count":
                actual, matched = _code_count(repo_root, probe.get("glob", ""),
                                              probe.get("pattern", ""))
                if matched == 0:
                    problems.append(f"{sid}/{name}：glob 没匹配到任何文件"
                                    f"（计数 0 无意义）：{probe.get('glob')}")
                elif actual != probe.get("expected"):
                    problems.append(f"{sid}/{name}：计数不符"
                                    f"（记录 {probe.get('expected')}，实测 {actual}）")
            elif kind == "file-exists":
                if not (repo_root / probe.get("path", "")).is_file():
                    problems.append(f"{sid}/{name}：文件不存在：{probe.get('path')}")
            elif kind == "import-check":
                ok = _import_ok(probe.get("module", ""))
                if ok != probe.get("expected"):
                    wanted = "可导入" if probe.get("expected") else "不可导入"
                    problems.append(f"{sid}/{name}：import {probe.get('module')} "
                                    f"当前{'成功' if ok else '失败'}，记录要求{wanted}")
            else:
                problems.append(f"{sid}/{name}：未知探针类型 {kind!r}")
    return problems


def main(argv: list[str]) -> int:
    root = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_ROOT
    repo_root = root.parents[1]                      # B41-thesis-seeds/ → projects/ → 仓库根
    problems = check_seeds_data(root / "data" / "seeds.json", repo_root)
    seeds = load_seeds(root / "data" / "seeds.json")
    if not problems:
        n_files = sum(len(s["files"]) for s in seeds)
        n_probes = sum(len(s["probes"]) for s in seeds)
        raw_meta = json.loads((root / "data" / "seeds.json").read_text(encoding="utf-8"))
        chosen = raw_meta.get("chosen") or []
        if isinstance(chosen, dict):
            chosen = [chosen]
        tail = "；已选定 " + "、".join(c["id"] for c in chosen) if chosen else ""
        print(f"PASS：{len(seeds)} 个未选候选、{n_files} 处文件行数、{n_probes} 个探针"
              f"——全部现算复核通过{tail}")
        return 0
    print(f"RED：{len(problems)} 个问题")
    for item in problems:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
