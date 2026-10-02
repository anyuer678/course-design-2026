"""checks/check_qa.py —— 质量保证层的核对器（B21）。

它只管三件事，每件都能被某次改动弄红：

1. **门禁口径本身是不是最新的**：`contracts/gate.json` 必须由 `docs/12-qa.md` 两张表现算得到，
   这里直接调用 `tools/export_gate.py` 的函数，不重写一遍解析（B19 的教训：两份解析迟早漂移）。
2. **走查清单的"自动证据"不许吹牛**：`docs/07` 每步要么给出真实存在的测试（`T:文件::方法`，
   复用 `check_docs.resolve_test` 去源码里核实方法真在），要么明写 `只能人工`。
   写一个不存在的测试比留空更坏——它看起来像已经验过了。
3. **"你的结果"那一列必须还是空的（未验证）**：PLAN 第 6 节与记忆都写着
   界面观感由用户实跑确认，**我不代勾**。如果哪天这一列被我或别人填成"通过"，这里就红。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks import check_docs                            # noqa: E402
from tools import export_gate                            # noqa: E402

WALK = ROOT / "docs" / "07-walkthrough.md"
WALK_HEADER = ["#", "做什么", "期望（回链）", "自动证据", "你的结果"]
HUMAN = "只能人工"
UNVERIFIED = {"未验证", "待验证", ""}


def walk_rows() -> tuple:
    found, problems = check_docs.tables_in(WALK.read_text(encoding="utf-8"))
    if problems:
        return [], list(problems)
    try:
        rows = check_docs.one(found, WALK_HEADER, "走查清单表")
    except check_docs.Problem as exc:
        return [], [str(exc)]
    return rows, []


def walk_problems(rows: list) -> list:
    out = []
    if len(rows) != 20:
        out.append(f"走查清单应有 20 步，实际 {len(rows)} 行（少一行就少一步核对）")
    for row in rows:
        number = row[0].strip()
        evidence = row[3].strip()
        result = row[4].strip() if len(row) > 4 else ""
        if result not in UNVERIFIED:
            out.append(f"第 {number} 步的『你的结果』被填成了 {result!r}："
                       f"界面表现由用户实跑确认，检查器不许代填")
        if not evidence:
            out.append(f"第 {number} 步没有自动证据说明：要么给出真实测试，要么写 {HUMAN}")
        for token in [t.strip() for t in evidence.replace("；", "、").split("、") if t.strip()]:
            if token.startswith(HUMAN):
                continue
            if "T:" not in token:
                out.append(f"第 {number} 步的证据 {token!r} 看不懂：既不是 T: 引用也不是『{HUMAN}』")
                continue
            problem = check_docs.resolve_test(token)
            if problem:
                out.append(f"第 {number} 步声称有自动证据，但 {problem}")
    return out


def walk_stats(rows: list) -> dict:
    both = human_only = auto = 0
    for row in rows:
        evidence = row[3]
        has_auto = "T:" in evidence
        has_human = HUMAN in evidence
        both += int(has_auto and has_human)
        human_only += int(has_human and not has_auto)
        auto += int(has_auto and not has_human)
    return {"步数": len(rows), "纯自动": auto, "自动+人工": both, "只能人工": human_only}


def gate_problems() -> list:
    """口径新鲜度：复用 export_gate，不重写第二份。"""
    data = export_gate.build()
    out = [f"门禁表：{p}" for p in export_gate.problems(data)]
    if not export_gate.OUT.is_file():
        return out + [f"{export_gate.OUT.name} 不存在，跑：python tools/export_gate.py --write"]
    import json
    if json.loads(export_gate.OUT.read_text(encoding="utf-8")) != data:
        out.append(f"{export_gate.OUT.name} 与 docs/12 不一致（文档改了没重生成，或有人手改了 JSON）："
                   f"跑 python tools/export_gate.py --write")
    return out


def check() -> list:
    problems = gate_problems()
    rows, bad = walk_rows()
    problems.extend(bad)
    problems.extend(walk_problems(rows))
    return problems


def main() -> int:
    problems = check()
    if problems:
        print(f"QA 核对发现 {len(problems)} 处问题：")
        for p in problems:
            print("  -", p)
        return 1
    stats = walk_stats(walk_rows()[0])
    import json
    gate = json.loads(export_gate.OUT.read_text(encoding="utf-8"))
    print(f"QA 核对通过：门禁契约与文档、流水线三方一致（{len(gate['layers'])} 层，"
          f"blocking {sum(1 for r in gate['layers'] if r['blocking'])} 层），"
          f"分诊 {len(gate['triage'])} 类每类都有真实样本；"
          f"走查 {stats['步数']} 步＝纯自动 {stats['纯自动']} + 自动且仍需人工 {stats['自动+人工']} "
          f"+ 只能人工 {stats['只能人工']}，结果列全部仍是『未验证』（等你实跑填）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
