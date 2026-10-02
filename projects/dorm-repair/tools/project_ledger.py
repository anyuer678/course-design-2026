"""tools/project_ledger.py —— 项目管理台账：把"账"和"文档"分开（B22）。

项目管理文档最容易烂掉的地方不是写得不好，而是**数字是手抄的**：
测试数、层数、变异条数、待决问题条数抄进另一份文档，代码一演化，文档就开始撒谎，
而且撒得很安静——没有任何东西会红。

所以这里只有一条机制：
* 事实由本文件现算（`facts()`），全部来自**唯一的事实源**（PLAN §7 标题、docs/05 表、
  contracts/*.json、docs/12 门禁表、mutation 登记表、README 的坑编号列表）；
* 管理文档（docs/13、docs/14、docs/15）里凡是要写数字的地方，写成 **`L:键名=值`** 标记；
* `checks/check_pm.py` 重新算一遍并逐个比对：值不对就红，键不存在也红。

台账**故意不记录**运行期度量（测试条数、耗时）——那些属于"某一次跑的结果"，
写在 `docs/11` / `docs/12` 的实测表里并标注日期，由流水线自己每次重测。
把它们塞进台账只会制造第二个需要人维护的副本，而那正是本文件要消灭的东西。

用法：

```
python tools/project_ledger.py --write   # 生成 contracts/ledger.json
python tools/project_ledger.py --check   # 文档里的 L: 标记是否与现算值一致（check_pm 也做这件事）
python tools/project_ledger.py --dump    # 打印台账，便于人工核对
```
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks import check_docs                          # noqa: E402
from tools import mutation_check, pipeline             # noqa: E402

PLAN = ROOT.parent.parent / "PLAN.md"
LEDGER = ROOT / "contracts" / "ledger.json"
OPEN_QUESTIONS = ROOT / "docs" / "05-open-questions.md"
README = ROOT / "README.md"
ADR_DIR = ROOT / "docs" / "adr"

ROUND_RE = re.compile(r"^### (B\d+) 已完成[^\n]*?（(\d{4}-\d{2}-\d{2})）", re.M)
#: 批次 5 的轮次（同一个 dorm-repair 目录），用于"这套代码上连做了几轮"
DORM_ROUNDS = ("B15", "B16", "B17", "B18", "B19", "B20", "B21", "B22")
MARKER_RE = re.compile(r"L:([a-z0-9_]+)=(\d+)")

#: 管理文档清单：只有这里列出的文件允许写 `L:` 标记，
#: `checks/check_pm.py` 复用同一个列表，避免两份清单各改一半。
PM_DOCS = ("docs/13-project-plan.md", "docs/14-risk-register.md",
           "docs/15-retrospective.md")


def _pitfalls() -> list:
    """README『踩过的坑』小节里的条目编号（到『已知局限』为止，别把练习建议算进来）。"""
    text = README.read_text(encoding="utf-8")
    start = text.index("## 踩过的坑")
    end = text.index("\n## ", start + 1)
    return [int(n) for n in re.findall(r"^(\d+)\. ", text[start:end], re.M)]


def _aq_status() -> tuple:
    rows = []
    for line in OPEN_QUESTIONS.read_text(encoding="utf-8").splitlines():
        if line.startswith("| AQ-"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append((cells[0], "已裁决" in cells[2]))
    total = len(rows)
    ruled = [qid for qid, done in rows if done]
    open_ids = [qid for qid, done in rows if not done]
    return total, ruled, open_ids


def _ac_slots() -> dict:
    data = check_docs.parse(check_docs.load())
    counts = {"executable": 0, "pending": 0, "manual": 0}
    for items in data["acs"].values():
        for a in items:
            verify = a["verify"]
            if check_docs.TEST_REF_RE.search(verify):
                counts["executable"] += 1
            elif check_docs.MANUAL_RE.search(verify):
                counts["manual"] += 1
            elif check_docs.PENDING_RE.search(verify):
                counts["pending"] += 1
    counts["total"] = sum(v for k, v in counts.items() if k != "total")
    return counts


def facts() -> dict:
    """每个键都必须能由现算得到；加一个键就要加一处引用，否则它就是装饰。"""
    if not PLAN.is_file():
        # 事实源在项目目录之外（仓库根的 PLAN.md）。缺它时给一句人话，
        # 不要抛 traceback：临时副本、精简部署都会走到这里，traceback 会把"红的原因"糊掉。
        raise SystemExit(f"台账需要计划文件 {PLAN}，但它不存在——"
                         f"（在项目副本里跑时，需要把仓库根的 PLAN.md 一起带上）")
    plan_text = PLAN.read_text(encoding="utf-8")
    rounds = [(m.group(1), m.group(2)) for m in ROUND_RE.finditer(plan_text)]
    by_date = {}
    for rid, date in rounds:
        by_date[date] = by_date.get(date, 0) + 1
    aq_total, ruled, open_ids = _aq_status()
    pitfall_numbers = _pitfalls()
    gate = json.loads((ROOT / "contracts" / "gate.json").read_text(encoding="utf-8"))
    workflow = json.loads((ROOT / "contracts" / "workflow.json").read_text(encoding="utf-8"))
    verdict = json.loads((ROOT / "contracts" / "verdict_table.json").read_text(encoding="utf-8"))
    buckets = {}
    for m in mutation_check.MUTATIONS:
        buckets[m["bucket"]] = buckets.get(m["bucket"], 0) + 1
    ac = _ac_slots()
    return {
        "rounds_done": len(rounds),
        "rounds_dorm": len([r for r, _ in rounds if r in DORM_ROUNDS]),
        "rounds_dates": len(by_date),
        "adr_count": len(list(ADR_DIR.glob("*.md"))),
        "doc_count": len(list((ROOT / "docs").glob("*.md"))),
        "aq_total": aq_total,
        "aq_ruled": len(ruled),
        "aq_open": len(open_ids),
        "pitfalls": len(pitfall_numbers),
        "pitfall_max": max(pitfall_numbers),
        "pitfall_gaps": len(set(range(1, max(pitfall_numbers) + 1)) - set(pitfall_numbers)),
        "gate_layers": len(gate["layers"]),
        "gate_blocking": sum(1 for row in gate["layers"] if row["blocking"]),
        "gate_advisory": sum(1 for row in gate["layers"] if not row["blocking"]),
        "gate_triage": len(gate["triage"]),
        "pipeline_layers": len(pipeline.LAYERS),
        "mutations": len(mutation_check.MUTATIONS),
        "mutation_buckets": len(buckets),
        "contract_transitions": len(workflow["transitions"]),
        "contract_permissions": len(workflow["permissions"]),
        "contract_preconditions": len(workflow["preconditions"]),
        "contract_states": len(workflow["states"]),
        "verdict_cells": len(verdict["verdicts"]),
        "ac_total": ac["total"],
        "ac_executable": ac["executable"],
        "ac_pending": ac["pending"],
        "ac_manual": ac["manual"],
        "_open_aq_ids": open_ids,
        "_ruled_aq_ids": ruled,
        "_mutation_buckets": buckets,
    }


def public(f: dict) -> dict:
    return {k: v for k, v in f.items() if not k.startswith("_")}


def problems(f: dict) -> list:
    out = []
    if f["pitfall_gaps"]:
        out.append(f"README 的坑编号有断号（缺 {f['pitfall_gaps']} 个）——"
                   f"条目会互相指代，断号意味着少了一条或被误删")
    if f["pitfalls"] != f["pitfall_max"]:
        out.append(f"坑条目数 {f['pitfalls']} 与最大编号 {f['pitfall_max']} 不等：有重号")
    if f["gate_layers"] != f["pipeline_layers"]:
        out.append(f"门禁表 {f['gate_layers']} 层 ≠ 流水线 {f['pipeline_layers']} 层")
    if f["ac_total"] != f["ac_executable"] + f["ac_pending"] + f["ac_manual"]:
        out.append("验收标准的三种出口没有覆盖全部条目")
    if f["aq_total"] != f["aq_ruled"] + f["aq_open"]:
        out.append("待决问题的已裁决/未决数目对不上总数")
    if f["mutation_buckets"] > f["gate_triage"]:
        out.append(f"变异用了 {f['mutation_buckets']} 类，分诊表只有 {f['gate_triage']} 类")
    return out


def markers_in(path: Path, f: dict) -> list:
    """文档里每个 `L:键=值` 都必须存在且等于现算值。"""
    out = []
    data = public(f)
    for key, value in MARKER_RE.findall(path.read_text(encoding="utf-8")):
        if key not in data:
            out.append(f"{path.name} 引用了台账里没有的键 L:{key}")
        elif int(value) != data[key]:
            out.append(f"{path.name} 写 L:{key}={value}，台账现算 {data[key]}"
                       f"（要么文档过期，要么事实源被改动）")
    return out


def refresh(f: dict) -> int:
    """把管理文档里的 `L:键=值` 刷成现算值——数字不该由人抄，也不该由人改。

    这不是"作弊"：`--check`（以及流水线 `pm` 层）核对的是**同一批值**，
    所以文档过期一定会被抓到；`--refresh` 只是把修法从"手工编辑文档"变成"重新生成"，
    和 `check_docs.py --write` 重生成追踪矩阵是完全同一套做法。
    """
    changed = 0
    for rel in PM_DOCS:
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        fresh, n = refresh_text(text, public(f))
        changed += n
        if n:
            path.write_text(fresh, encoding="utf-8")
    return changed


def refresh_text(text: str, data: dict) -> tuple:
    """纯函数：把 `L:键=值` 刷成现算值，返回 (新文本, 改动处数)。拆出来是为了能测。"""
    changed = 0

    def sub(match):
        nonlocal changed
        key, value = match.group(1), int(match.group(2))
        if key in data and value != data[key]:
            changed += 1
            return f"L:{key}={data[key]}"
        return match.group(0)

    return MARKER_RE.sub(sub, text), changed


def to_text(f: dict) -> str:
    return json.dumps(public(f), ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="项目管理台账")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="把管理文档里的 L: 标记刷成现算值")
    args = ap.parse_args(argv[1:])
    f = facts()
    bad = problems(f)
    if bad:
        print("台账自身不一致：")
        for p in bad:
            print("  -", p)
        return 1
    if args.refresh:
        n = refresh(f)
        print(f"已刷新 {n} 处 L: 标记（管理文档里的数字由台账写回，不是手改）")
        return 0
    if args.dump:
        print(to_text(f))
        return 0
    if args.write:
        LEDGER.write_text(to_text(f), encoding="utf-8")
        print(f"已写出 {LEDGER.name}：{len(public(f))} 个键；"
              f"轮次 {f['rounds_done']}（本业务 {f['rounds_dorm']}）、"
              f"AQ {f['aq_total']} 条（未决 {f['aq_open']}）、坑 {f['pitfalls']} 条")
        return 0
    saved = json.loads(LEDGER.read_text(encoding="utf-8"))
    if saved != public(f):
        print("ledger.json 与现算事实不一致（事实源改了没重生成）")
        return 1
    print(f"台账核对通过：{len(saved)} 个键与现算一致"
          f"（轮次 {f['rounds_done']}、AQ {f['aq_total']}／未决 {f['aq_open']}、"
          f"坑 {f['pitfalls']} 无断号、门禁 {f['gate_layers']} 层）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
