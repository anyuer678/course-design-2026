"""checks/check_pm.py —— 管理文档的核对器（B22）。

管理文档烂掉的方式和技术文档不一样：它不会"错"，它只是**慢慢过期**——
测试数、层数、风险条数抄在正文里，代码演化后没人回头改，而**没有任何东西会因此变红**。
这一层就是把"过期"变成红灯，具体核对四件事：

1. 台账自己是否自洽，且 `contracts/ledger.json` 是否还是现算结果；
2. `docs/13/14/15` 里每个 `L:键=值` 标记是否等于台账现算值（**管理文档不许手抄数字**）；
3. 台账里每个公开键是否真的被 `docs/13` 的指标表引用——**没人读的指标就该删掉**，
   否则台账自己就变成新的装饰；
4. 风险登记册是否覆盖了所有未裁决的 AQ（少一条 = 有代价没登记），
   复盘的分类表是否**恰好**覆盖每一条坑（重号或漏号 = 复盘在编故事）。

它作为流水线的 `pm` 层跑，因此也受门禁口径管辖。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import project_ledger as L                  # noqa: E402

PM_DOCS = L.PM_DOCS        # 清单只有一份：docs 列表由台账持有
RISK_DOC = ROOT / PM_DOCS[1]
RETRO_DOC = ROOT / PM_DOCS[0].replace("13-project-plan", "15-retrospective")
INDICATOR_DOC = ROOT / PM_DOCS[0]

CATEGORY_RE = re.compile(r"^\| (一|二|三) · .*?\| (\d+) \| (.+?) \|$", re.M)
AQ_ROW_RE = re.compile(r"^\| (AQ-\d{2}) \|", re.M)   # 没有 re.M，^ 只匹配整串开头 → 9 行全查不到


def marker_problems(facts: dict) -> list:
    out = []
    for rel in PM_DOCS:
        out.extend(L.markers_in(ROOT / rel, facts))
    return out


def indicator_problems(facts: dict, text: str | None = None) -> list:
    """台账的每个公开键都必须出现在指标表里——否则它就是没人读的装饰。"""
    text = INDICATOR_DOC.read_text(encoding="utf-8") if text is None else text
    cited = set(L.MARKER_RE.findall(text) and [k for k, _ in L.MARKER_RE.findall(text)])
    return [f"台账键 {key} 没有被 docs/13 第 8 节引用（没人读的指标就该删）"
            for key in L.public(facts) if key not in cited]


def risk_problems(facts: dict, text: str | None = None) -> list:
    """风险登记册第 1 节的 AQ 行：必须**恰好**是未裁决的那几条。"""
    text = RISK_DOC.read_text(encoding="utf-8") if text is None else text
    section = text.split("## 1. 需求风险", 1)
    if len(section) < 2:
        return ["docs/14 找不到『1. 需求风险』小节"]
    body = section[1].split("## 2.", 1)[0]
    listed = AQ_ROW_RE.findall(body)
    problems = []
    for qid in listed:
        if listed.count(qid) > 1:
            problems.append(f"风险登记册把 {qid} 登记了 {listed.count(qid)} 次")
    for qid in facts["_open_aq_ids"]:
        if qid not in listed:
            problems.append(f"未裁决的 {qid} 没有登记进风险登记册——它的代价就没人认")
    for qid in facts["_ruled_aq_ids"]:
        if qid in listed:
            problems.append(f"{qid} 已裁决，却还留在未决风险表里（状态过期）")
    return [p for p in dict.fromkeys(problems)]


def retrospective_problems(facts: dict, text: str | None = None) -> list:
    """复盘分类必须恰好覆盖 1..N：漏号＝有条目没复盘，重号＝分类不是划分。"""
    text = RETRO_DOC.read_text(encoding="utf-8") if text is None else text
    rows = CATEGORY_RE.findall(text)
    if not rows:
        return ["docs/15 找不到分类表（表头需为『类别 | 条数 | 编号』）"]
    problems, seen = [], []
    for name, claimed, numbers in rows:
        nums = [int(x) for x in re.findall(r"\d+", numbers)]
        seen.extend(nums)
        if len(nums) != int(claimed):
            problems.append(f"复盘第 {name} 类写了 {claimed} 条，实际列出 {len(nums)} 个编号")
    n = facts["pitfalls"]
    expected = set(range(1, n + 1))
    dupes = sorted({x for x in seen if seen.count(x) > 1})
    if dupes:
        problems.append(f"复盘编号有重号：{dupes}（分类必须是划分）")
    missing = sorted(expected - set(seen))
    extra = sorted(set(seen) - expected)
    if missing:
        problems.append(f"复盘漏了 {len(missing)} 条坑没有归类：{missing[:8]}"
                        f"{'…' if len(missing) > 8 else ''}")
    if extra:
        problems.append(f"复盘引用了不存在的坑号：{extra}")
    return problems


def check() -> tuple:
    f = L.facts()
    problems = [f"台账：{p}" for p in L.problems(f)]
    if not L.LEDGER.is_file():
        problems.append(f"{L.LEDGER.name} 不存在，跑：python tools/project_ledger.py --write")
    elif json.loads(L.LEDGER.read_text(encoding="utf-8")) != L.public(f):
        problems.append(f"{L.LEDGER.name} 与现算事实不一致（事实源改了没重生成，或手改过 JSON）")
    problems.extend(marker_problems(f))
    problems.extend(indicator_problems(f))
    problems.extend(risk_problems(f))
    problems.extend(retrospective_problems(f))
    return problems, f


def main() -> int:
    problems, f = check()
    if problems:
        print(f"管理文档核对发现 {len(problems)} 处问题：")
        for p in problems:
            print("  -", p)
        return 1
    keys = len(L.public(f))
    print(f"管理文档核对通过：台账 {keys} 个键全部被 docs/13 引用且与现算一致；"
          f"未决 {f['aq_open']} 条全部登记进风险册；复盘覆盖坑 1..{f['pitfalls']} 无重号无漏号")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
