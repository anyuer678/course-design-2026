"""tools/export_contract.py —— 把 SRS 的规范性表导出成机器可读契约。

为什么要一份 JSON 契约（ADR-03 里有完整理由）：B18 要用 Java 重做实现，B20 要写测试。
如果它们各自去 `docs/02-srs.md` 里**用眼睛抄**那张状态转换表，就等于把同一台状态机
抄成三份——抄错的那一份不会报错，只会在某个下午变成"界面允许、后端拒绝"这种没人信得过的行为。

契约只由**文档**生成，再与 `spec` 三方比对：

* 文档改了、忘了改模型 → 这里报错（不会写出契约）；
* 模型改了、忘了改文档 → 同样报错；
* 有人手改 `contracts/workflow.json` → `--check` 会发现和文档算出来的不一样。

用法：

```
python tools/export_contract.py            核对并打印摘要，不写文件
python tools/export_contract.py --write    重新生成 contracts/workflow.json
python tools/export_contract.py --check    契约是否过期（CI 用，过期返回非 0）
```
"""
from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks import check_docs                              # noqa: E402
from spec import workorder as W                            # noqa: E402

CONTRACT = ROOT / "contracts" / "workflow.json"
SCHEMA_VERSION = 2      # 2 = B18 加了 acceptance_grace_hours 与 field_effects；读方必须按版本分支


def build():
    """从 SRS 的表算出契约。注意：不读 `spec`——文档是唯一出处，spec 只用来做一致性断言。"""
    docs = check_docs.load()
    tables, problems = check_docs.tables_in(docs["srs"])
    if problems:
        raise SystemExit("SRS 表格本身有问题，先修文档：\n  " + "\n  ".join(problems))
    parsed = check_docs.parse(docs)

    transitions = [{"id": t["tid"], "action": t["action"], "from": t["source"], "to": t["target"],
                    "roles": sorted(r.strip() for r in t["roles"].split(",")),
                    "requires": sorted(p.strip() for p in t["pre"].split(","))}
                   for t in parsed["trans"]]

    permissions = {}
    for row in transitions:
        permissions.setdefault(row["action"], set()).update(row["roles"])

    # 第 9 节的字段列写成 "`room` 宿舍编号"：机器读的键必须只是标识符那一段。
    # （原先用 row[0].strip("`") 只削掉首尾反引号，留下 "room` 宿舍编号" ——B18 写 Java 时才暴露。）
    fields = {}
    for row in check_docs.one(tables, ["字段", "规则", "违反时的错误码"], "第 9 节字段表"):
        name = re.search(r"`(\w+)`", row[0])
        if not name:
            raise SystemExit(f"第 9 节字段表的字段列 {row[0]!r} 里没有反引号标识符，"
                             f"契约的键会是半截中文")
        fields[name.group(1)] = row[2].strip().strip("`")

    return {
        "contract": "dorm-repair/workflow",
        "schema_version": SCHEMA_VERSION,
        "source": "docs/02-srs.md 第 1/3/4/5/6/8/9 节（由 tools/export_contract.py 生成，勿手改）",
        "roles": [r.value for r in W.Role],
        "states": [s.value for s in W.State],
        "actions": sorted(permissions),
        "terminal_states": [s.value for s in W.TERMINAL],
        "categories": [c.value for c in W.Category],
        "priorities": [p.value for p in W.Priority],
        "preconditions": sorted(parsed["legend"]),
        "transitions": transitions,
        "permissions": {k: sorted(v) for k, v in sorted(permissions.items())},
        "visibility": {k.strip(): v.strip() for k, v in sorted(parsed["vis"].items())},
        "sla_hours": {k: v for k, v in sorted(parsed["sla"].items())},
        "acceptance_grace_hours": parsed["params"]["ACCEPTANCE_GRACE_HOURS"],
        "field_effects": sorted(({"field": row["field"].strip().strip("`"),
                                  "when": row["when"].strip(),
                                  "test": row["verify"].strip()}
                                 for row in parsed["field_effects"]),
                                key=lambda row: row["field"]),
        "field_errors": dict(sorted(fields.items())),
        "field_limits": {k: {"min": v[0], "max": v[1], "pattern": v[2]}
                         for k, v in sorted(parsed["limits"].items())},
    }


def against_spec(contract):
    """契约 ↔ spec 的一致性。文档↔契约 由 build() 的来源保证，不需要再比一次。"""
    problems = []
    model = sorted(({"id": t.tid, "action": t.action.value, "from": t.source.value,
                     "to": t.target.value, "roles": sorted(r.value for r in t.roles),
                     "requires": sorted(t.preconditions)} for t in W.TRANSITIONS),
                   key=lambda row: row["id"])
    if model != sorted(contract["transitions"], key=lambda t: t["id"]):
        problems.append("契约的转换集合与 spec.TRANSITIONS 不一致")
    if {k: sorted(v) for k, v in contract["permissions"].items()} != \
            {a.value: sorted({r.value for t in W.TRANSITIONS if t.action == a
                              for r in t.roles}) for a in W.Action}:
        problems.append("契约的权限映射与 spec 推导结果不一致")
    if contract["visibility"] != {r.value: v for r, v in W.ROLE_VISIBILITY.items()}:
        problems.append("契约的可见性代码与 spec.ROLE_VISIBILITY 不一致")
    if contract["sla_hours"] != {p.value: h for p, h in W.SLA_HOURS.items()}:
        problems.append("契约的 SLA 与 spec.SLA_HOURS 不一致")
    if sorted(contract["preconditions"]) != sorted(W.PRECONDITIONS):
        problems.append("契约的前置条件集合与 spec.PRECONDITIONS 不一致")
    if sorted(contract["states"]) != sorted(s.value for s in W.State):
        problems.append("契约的状态集合与 spec.State 不一致")
    if contract["acceptance_grace_hours"] != W.ACCEPTANCE_GRACE_HOURS:
        problems.append(f"契约的验收宽限 {contract['acceptance_grace_hours']} 小时，"
                        f"模型 {W.ACCEPTANCE_GRACE_HOURS} 小时")
    limits = {k: (v["min"], v["max"], v["pattern"]) for k, v in contract["field_limits"].items()}
    if limits != {k: tuple(v) for k, v in W.FIELD_LIMITS.items()}:
        problems.append("契约的校验参数表与 spec.FIELD_LIMITS 不一致："
                        f"契约 {sorted(limits.items())} vs 模型 "
                        f"{sorted((k, tuple(v)) for k, v in W.FIELD_LIMITS.items())}")
    order_fields = {f.name for f in dataclasses.fields(W.Order)}
    unknown = sorted(row["field"] for row in contract["field_effects"]
                     if row["field"] not in order_fields)
    if unknown:
        problems.append(f"契约的字段写入时机里有 `Order` 没有的字段：{unknown}")
    # 写入时机的"由哪条测试钉住"必须解析得到真实测试——否则这张表只是另一篇散文
    for row in contract["field_effects"]:
        error = check_docs.resolve_test(row["test"])
        if error:
            problems.append(f"字段 {row['field']} 的写入时机测试不可用：{error}")
    return problems


def text_of(contract) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    contract = build()
    problems = against_spec(contract) + check_docs.check()[0]
    if problems:
        print("契约不能生成，因为发现不一致：")
        for p in problems:
            print("  -", p)
        return 1
    payload = text_of(contract)
    if "--write" in argv:
        CONTRACT.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT.write_text(payload, encoding="utf-8", newline="\n")   # LF：契约是文本产物，不带 CRLF
        print(f"已写出 {CONTRACT.relative_to(ROOT)}")
        return 0
    if "--check" in argv:
        if not CONTRACT.is_file():
            print("contracts/workflow.json 不存在，跑：python tools/export_contract.py --write")
            return 1
        committed = CONTRACT.read_text(encoding="utf-8").replace("\r\n", "\n")
        if committed != payload:
            print("契约已过期（文档或模型改过了），跑：python tools/export_contract.py --write")
            return 1
        print("契约与文档、模型三方一致")
        return 0
    print(f"契约核对通过：转换 {len(contract['transitions'])} 条 · 动作 {len(contract['actions'])} 个 · "
          f"权限 {len(contract['permissions'])} 项 · 错误码 {len(contract['field_errors'])} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
