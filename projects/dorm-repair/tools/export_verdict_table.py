"""tools/export_verdict_table.py —— 生成"判定表"，用于跨语言对拍（B18）。

为什么不是"把转换表再导一份 JSON"：转换表只说*允许*什么，不说*拒绝*时长什么样。
真正会分叉的是拒绝路径——是 NO_SUCH_TRANSITION 还是 ROLE_NOT_ALLOWED、
前置条件先查哪一个、宽限期到点算不算过期，这些在两边走一遍才知道是不是一台机器。

做法：用固定种子从草稿走出 7 个状态的代表工单，然后穷举
    状态 × 动作 × 角色身份 × 输入齐全/缺失 × 时刻(宽限内/外)
把每一次判定的结果（`OK:目标状态` 或 `ERR:错误码`）钉成一张表。
Python 侧由这条命令生成，Java 侧的 `VerdictParityTest` 独立重算同一张表并逐格比对。
两边任一改动（含只改文档没重生成契约）都会对不上。

用法：

```
python tools/export_verdict_table.py --write    # 生成 contracts/verdict_table.json
python tools/export_verdict_table.py --check    # 已提交的是否最新（CI 用）
```
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec import workorder as W                        # noqa: E402

OUT = ROOT / "contracts" / "verdict_table.json"

#: 出处：docs/02-srs.md 第 1 节的动作枚举；这张表就是按它穷举的
ACTORS = [("STUDENT", "stu-1"), ("STUDENT", "stu-2"),
          ("WORKER", "w-1"), ("WORKER", "w-2"),
          ("ADMIN", "adm-1")]

#: 两个时刻：一个在验收宽限期内、一个正好到点，用来把 BR-10 的边界钉进表里。
#: 手算：canonical RESOLVED 的 resolved_at=4000，168×3600=604800 → 到期 608800.0
TIMES = [5000.0, 608800.0]

FULL = {"assignee": "w-1", "note": "好了", "reason": "理由"}
EMPTY = {"assignee": None, "note": None, "reason": None}


def _draft() -> W.Order:
    return W.create_order(id="V1", reporter="stu-1", room="A01-101", category="WATER_ELEC",
                          priority="NORMAL", description="水管漏水", contact="13800000000",
                          created_at=100.0)


def _apply(order, role, who, action, now, **inputs):
    return W.apply_transition(order, W.Role(role), who, W.Action(action), now=now, **inputs)


def canonical() -> dict:
    """7 个状态各造一张代表工单。序列固定，所以两边的起点对齐。"""
    d = _draft()
    s = _apply(d, "STUDENT", "stu-1", "submit", 1000.0)
    a = _apply(s, "ADMIN", "adm-1", "assign", 2000.0, assignee="w-1")
    p = _apply(a, "WORKER", "w-1", "accept", 3000.0)
    r = _apply(p, "WORKER", "w-1", "resolve", 4000.0, note="换了垫圈")
    c = _apply(r, "STUDENT", "stu-1", "confirm", 5000.0)
    x = _apply(s, "STUDENT", "stu-1", "cancel", 1500.0, reason="误报")
    return {o.state: o for o in (d, s, a, p, r, c, x)}


def verdicts() -> dict:
    table = {}
    for state, order in sorted(canonical().items()):
        for action in sorted(W.Action, key=lambda a: a.value):
            for role, who in ACTORS:
                for label, inputs in (("full", FULL), ("empty", EMPTY)):
                    for now in TIMES:
                        key = "|".join([state, action.value, role, who, label, repr(now)])
                        try:
                            nxt = W.apply_transition(order, W.Role(role), who, action,
                                                     now=now, **inputs)
                            table[key] = "OK:" + nxt.state
                        except W.TransitionError as e:
                            table[key] = "ERR:" + e.code
    return table


def build() -> dict:
    return {
        "contract": "dorm-repair/verdict-table",
        "schema_version": 1,
        "workflow_schema_version": json.loads((ROOT / "contracts" / "workflow.json")
                                              .read_text(encoding="utf-8"))["schema_version"],
        "source": "由 spec/workorder.py 对固定序列的判定结果生成（tools/export_verdict_table.py）",
        "actors": [{"role": r, "id": i} for r, i in ACTORS],
        "times": TIMES,
        "inputs": {"full": FULL, "empty": EMPTY},
        "count": None,
        "verdicts": verdicts(),
    }


def text_of(data: dict) -> str:
    payload = dict(data)
    payload["count"] = len(payload["verdicts"])
    return json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main(argv: list) -> int:
    if "--write" in argv:
        OUT.write_text(text_of(build()), encoding="utf-8")
        print(f"已写出 {OUT}")
        return 0
    data = build()
    if not OUT.exists():
        print("判定表不存在，跑：python tools/export_verdict_table.py --write")
        return 1
    saved = json.loads(OUT.read_text(encoding="utf-8"))
    if saved.get("verdicts") != data["verdicts"]:
        differs = [k for k in data["verdicts"] if saved.get("verdicts", {}).get(k) != data["verdicts"][k]]
        missing = sorted(set(saved.get("verdicts", {})) ^ set(data["verdicts"]))
        print(f"判定表与当前模型不一致：{len(differs)} 格判定不同"
              + (f"，键集合差 {len(missing)} 个" if missing else ""))
        for key in differs[:5]:
            print(f"  - {key}：已存 {saved['verdicts'][key]} vs 现在 {data['verdicts'][key]}")
        return 1
    print(f"判定表与模型一致：{len(data['verdicts'])} 格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
