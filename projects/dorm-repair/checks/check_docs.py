"""checks/check_docs.py —— 需求文档与可执行模型的一致性检查器。

它存在的理由只有一句话：**两份东西只要靠人手工保持一致，就一定会不一致。**
需求阶段尤其如此——状态表、权限矩阵、可见性矩阵、追踪矩阵分散在四个文件里，
改了一处忘了另一处，读文档的人看不出来，直到 B18 实现时才发现"文档说的和要的"不是一回事。

所以这里做三件事：

1. **把 `docs/02-srs.md` 里的规范表解析出来**，与 `spec/workorder.py` 逐条比对。
   两边谁改了都会被抓到，因为断言的是"集合相等"，不是"看起来差不多"。
2. **核对追踪性**：每条功能需求至少被一个用例或用户故事引用；每条验收标准要么
   指向一个**确实存在**的测试（`T:文件::方法`，会去源码里核实这个方法在不在），
   要么明确写"待验证(轮次)"。留空和写一个不存在的测试都算失败。
3. **从文档重新生成追踪矩阵**，与仓库里提交的 `traceability.csv` 比对。
   矩阵因此是产物而不是手工维护的账本（PLAN 批次 5 里这条本来被列为"选做扩展"）。

用法：

```
python checks/check_docs.py            跑检查，有问题就打印并返回非 0
python checks/check_docs.py --write    按当前文档重写 traceability.csv
```
"""
from __future__ import annotations

import csv
import dataclasses
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec import workorder as spec                       # noqa: E402

DOCS = ROOT / "docs"
ID_RE = re.compile(r"^(FR|BR|NFR|IF|UC|US|AC|AQ|TR|ACT)-\d{2}$")
REF_RE = re.compile(r"\b(?:FR|BR|NFR|IF|UC|US|AC|AQ)-\d{2}\b")
TEST_REF_RE = re.compile(r"`?T:([\w./\\]+\.py)::(\w+)`?")
PENDING_RE = re.compile(r"待验证\s*[（(]\s*(B\d{1,2})\s*[)）]")
MANUAL_RE = re.compile(r"人工确认\s*[（(]\s*(B\d{1,2})\s*[)）]")
FORBIDDEN = ("TODO", "待补", "TBD", "FIXME")


# ------------------------------------------------------------------ markdown 表格解析

def tables_in(text: str):
    """按"表头第一格"索引所有表格。只认 GFM 竖线表，行列数不一致直接记为问题。"""
    problems, out = [], []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$",
                                                                        lines[i + 1].strip()):
            header = cells(lines[i])
            rows, i = [], i + 2
            while i < len(lines) and lines[i].startswith("|"):
                row = cells(lines[i])
                if len(row) != len(header):
                    problems.append(f"表格 {header[0]} 第 {i + 1} 行列数 {len(row)} 与表头 {len(header)} 不符")
                rows.append(row)
                i += 1
            out.append((tuple(header), rows))
            continue
        i += 1
    return out, problems


def cells(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def pick(tables, header):
    """按表头前缀找表；同一个头出现多次就用错的会是"两张表"，直接算问题。"""
    hits = [rows for (head, rows) in tables if head[:len(header)] == tuple(header)]
    return hits


def one(tables, header, what):
    hits = pick(tables, header)
    if not hits:
        raise Problem(f"找不到表格：{what}（表头 {header}）")
    if len(hits) > 1:
        raise Problem(f"表头 {header} 匹配到 {len(hits)} 张表，检查器无法判断哪张是规范表")
    return hits[0]


class Problem(Exception):
    pass


# ------------------------------------------------------------------ 读取文档

def load():
    srs = (DOCS / "02-srs.md").read_text(encoding="utf-8")
    uc = (DOCS / "03-use-cases.md").read_text(encoding="utf-8")
    us = (DOCS / "04-user-stories.md").read_text(encoding="utf-8")
    aq = (DOCS / "05-open-questions.md").read_text(encoding="utf-8")
    scope = (DOCS / "01-scope.md").read_text(encoding="utf-8")
    return {"srs": srs, "uc": uc, "us": us, "aq": aq, "scope": scope}


def parse(docs):
    tables, problems = [], []
    for name, text in docs.items():
        found, bad = tables_in(text)
        tables.extend(found)
        problems.extend(f"{name}: {p}" for p in bad)
    out = {"table_problems": problems}

    out["enums"] = {}
    for row in one(tables, ["枚举", "取值", "说明"], "第 1 节枚举表"):
        key = re.search(r"`(\w+)`", row[0])
        # 动作是小写（submit），状态与角色是大写（SUBMITTED / STUDENT），两种都要收
        out["enums"][key.group(1) if key else row[0]] = re.findall(r"`([A-Za-z_]+)`", row[1])

    out["frs"] = {r[0]: r for r in one(tables, ["ID", "需求", "来源", "验证入口"], "FR 表")}
    out["fr_verify"] = {k: v[3] for k, v in out["frs"].items()}
    out["brs"] = {r[0]: r for r in one(tables, ["ID", "规则", "出处/理由"], "BR 表")}
    out["nfrs"] = {r[0]: r for r in one(tables, ["ID", "需求", "验证方式"], "NFR 表")}
    out["ifs"] = {r[0]: r for r in one(tables, ["ID", "对手方", "我需要它什么", "本期是否实现"], "IF 表")}
    out["trans"] = [dict(zip(["tid", "action", "source", "target", "roles", "pre"], r))
                    for r in one(tables, ["转换 ID", "动作", "起始状态", "目标状态", "允许角色", "前置条件"],
                                 "状态转换表")]
    out["perm"] = {r[0]: r[1:] for r in one(tables, ["动作", "STUDENT", "WORKER", "ADMIN"], "权限矩阵")}
    out["vis"] = {r[0]: r[1] for r in one(tables, ["角色", "可见范围", "说明"], "可见性矩阵")}
    out["sla"] = {r[0]: int(r[1]) for r in one(tables, ["优先级", "响应时限（小时）"], "SLA 表")}
    # B18 追加的两张表：时限参数（168 小时那个数不许只活在代码里）与字段写入时机
    out["params"] = {}
    for row in one(tables, ["参数", "值（小时）", "出处"], "时限参数表"):
        key = re.search(r"`(\w+)`", row[0])
        out["params"][key.group(1) if key else row[0]] = int(row[1])
    out["field_effects"] = [dict(zip(["field", "when", "verify"], r))
                            for r in one(tables, ["字段", "写入时机", "由哪条测试钉住"],
                                         "字段写入时机表")]
    out["limits"] = {row[0].strip().strip("`"): (int(row[1]), int(row[2]), row[3].strip())
                     for row in one(tables, ["字段", "最小长度", "最大长度", "格式代码"],
                                    "校验参数表")}
    out["legend"] = {r[0].strip("`") for r in one(tables, ["代码", "含义", "谁保证"], "前置条件图例")}

    out["ucs"] = refs_by_heading(docs["uc"], "UC", ("覆盖需求",))
    out["uss"] = refs_by_heading(docs["us"], "US", ("需求", "用例"))
    out["acs"] = acs_under_stories(docs["us"])
    out["aqs"] = {m for m in re.findall(r"\bAQ-\d{2}\b", docs["aq"])}
    return out


def refs_by_heading(text, kind, wanted):
    """按 `### US-01 · 标题` 切块，抓出 `- 需求：FR-01, FR-02` 这类引用行。"""
    blocks = {}
    current = None
    for line in text.splitlines():
        head = re.match(r"^###\s+(%s-\d{2})\b" % kind, line)
        if head:
            current = head.group(1)
            blocks[current] = {k: [] for k in wanted}
            continue
        if current is None:
            continue
        labeled = re.match(r"^-\s*([^：:]+)[：:]\s*(.+)$", line.strip())
        if labeled and labeled.group(1).strip() in wanted:
            blocks[current][labeled.group(1).strip()] = REF_RE.findall(labeled.group(2))
    return blocks


def acs_under_stories(text):
    """每个 US 小节里的 AC 表：`| AC ID | 验收标准（Given/When/Then） | 验证 |`。"""
    acs, current = {}, None
    for line in text.splitlines():
        head = re.match(r"^###\s+(US-\d{2})\b", line)
        if head:
            current = head.group(1)
            acs.setdefault(current, [])
            continue
        if current is None or not line.startswith("|"):
            continue
        row = cells(line)
        if len(row) == 3 and ID_RE.match(row[0]) and row[0].startswith("AC"):
            acs[current].append({"ac": row[0], "text": row[1], "verify": row[2]})
    return acs


# ------------------------------------------------------------------ 交叉核对

def resolve_test(ref: str):
    """`T:tests/test_x.py::method` 必须真的在源码里存在，否则追踪矩阵是在骗人。"""
    match = TEST_REF_RE.search(ref or "")
    if not match:
        return None
    path, name = ROOT / match.group(1), match.group(2)
    if not path.is_file():
        return f"引用的测试文件不存在：{path.name}"
    if not re.search(r"^\s*def %s\(" % re.escape(name), path.read_text(encoding="utf-8"), re.M):
        return f"{path.name} 里没有 {name}() 这个方法"
    return None


def verify_slot(value, what, problems):
    """验证入口只允许三种：已有测试、待后续轮次验证、需人工确认。

    写了 `T:` 就必须能解析到真实存在的测试方法——"引用一个不存在的测试"比留空更坏，
    因为看起来像已经验过了。
    """
    text = (value or "").strip()
    if not text:
        problems.append(f"{what} 的验证入口是空的（不许留空）")
        return "empty"
    if TEST_REF_RE.search(text):
        error = resolve_test(text)
        if error:
            problems.append(f"{what} 的验证入口不可用：{error}")
            return "broken"
        return "executable"
    if MANUAL_RE.search(text):
        return "manual"
    if PENDING_RE.search(text):
        return "pending"
    problems.append(f"{what} 既没有 T: 测试引用，也没写 待验证(Bxx) 或 人工确认(Bxx)：{text!r}")
    return "unknown"


def param_problems(data, spec):
    """时限参数表（SRS 第 8 节）↔ 模型常量。抽成函数是为了能被单独喂假数据测"有没有牙齿"。"""
    problems = []
    if set(data["params"]) != {"ACCEPTANCE_GRACE_HOURS"}:
        problems.append(f"时限参数表的参数集合应是 "
                        f"{{'ACCEPTANCE_GRACE_HOURS'}}，实际是 {sorted(data['params'])}")
    for name, hours in data["params"].items():
        if getattr(spec, name, None) != hours:
            problems.append(f"参数 {name}：文档 {hours} 小时，模型 {getattr(spec, name, None)} 小时")
    return problems


def field_effect_problems(data, spec):
    """字段写入时机表（SRS 第 12.1 节）：字段必须真的存在，且每行必须挂一条**存在的**测试。"""
    problems = []
    order_fields = {f.name for f in dataclasses.fields(spec.Order)}
    documented = {row["field"].strip().strip("`") for row in data["field_effects"]}
    invented = sorted(documented - order_fields)
    if invented:
        problems.append(f"字段写入时机表里有 `Order` 不存在的字段：{invented}")
    # 写入时机最容易各说一遍的那几个字段，必须出现在表里
    must = {"state", "assignee", "resolved_by", "resolved_at", "submitted_at",
            "sla_due_at", "history"}
    if not must <= documented:
        problems.append(f"字段写入时机表缺行：{sorted(must - documented)}")
    for row in data["field_effects"]:
        verify_slot(row["verify"], f"字段 {row['field'].strip().strip('`')} 的写入时机", problems)
    return problems


def limit_problems(data, spec):
    """校验参数表（SRS 第 9 节）↔ `spec.FIELD_LIMITS`。

    这张表是 B18 的 Java 侧唯一能拿到长度上限的地方。数字抄歪一格，
    两边就会出现"A01-101 在这边合法、在那边 400"这种谁也说不清的行为。
    """
    problems = []
    allowed_patterns = {"NONE", "ROOM_PATTERN", "CONTACT_PATTERN"}
    if set(data["limits"]) != set(spec.FIELD_LIMITS):
        problems.append(f"校验参数表的字段集合与模型不一致：文档 {sorted(data['limits'])} "
                        f"vs 代码 {sorted(spec.FIELD_LIMITS)}")
    for field, value in data["limits"].items():
        model = spec.FIELD_LIMITS.get(field)
        if model is not None and tuple(model) != tuple(value):
            problems.append(f"字段 {field} 的校验参数：文档 {tuple(value)} vs 模型 {tuple(model)}")
        if value[2] not in allowed_patterns:
            problems.append(f"字段 {field} 的格式代码 {value[2]!r} 不在 "
                            f"{sorted(allowed_patterns)} 里")
        if value[0] > value[1]:
            problems.append(f"字段 {field} 的最小长度 {value[0]} 大于最大长度 {value[1]}")
    return problems


def check():
    docs = load()
    data = parse(docs)
    problems = list(data["table_problems"])

    # --- 枚举表 ↔ 代码
    expected_enum = {
        "Role": [r.value for r in spec.Role], "State": [s.value for s in spec.State],
        "Action": [a.value for a in spec.Action], "Category": [c.value for c in spec.Category],
        "Priority": [p.value for p in spec.Priority],
    }
    for name, legal in expected_enum.items():
        listed = data["enums"].get(name)
        if listed is None:
            problems.append(f"枚举表里找不到 {name}")
        elif set(listed) != set(legal):
            problems.append(f"文档枚举 {name} 与代码不一致：文档 {sorted(set(listed))} vs 代码 {sorted(legal)}")

    # --- 状态转换表 ↔ 模型：按转换 ID 逐字段比，"哪一格不一样"要说得出来
    doc_rows = {t["tid"]: t for t in data["trans"]}
    model_rows = {t.tid: t for t in spec.TRANSITIONS}
    for tid in sorted(set(model_rows) - set(doc_rows)):
        problems.append(f"转换 {tid} 只在模型里，文档没有（跑 --write 并回写文档）")
    for tid in sorted(set(doc_rows) - set(model_rows)):
        problems.append(f"转换 {tid} 只在文档里，模型没有实现")
    for tid in sorted(set(doc_rows) & set(model_rows)):
        doc, model = doc_rows[tid], model_rows[tid]
        for label, doc_value, model_value in (
                ("动作", doc["action"], model.action.value),
                ("起始状态", doc["source"], model.source.value),
                ("目标状态", doc["target"], model.target.value),
                ("允许角色", ",".join(sorted(x.strip() for x in doc["roles"].split(","))),
                 ",".join(sorted(r.value for r in model.roles))),
                ("前置条件", ",".join(sorted(x.strip() for x in doc["pre"].split(","))),
                 ",".join(sorted(model.preconditions)))):
            if doc_value != model_value:
                problems.append(f"{tid} 的{label}不一致：文档 {doc_value!r} vs 模型 {model_value!r}")
    tids = [t["tid"] for t in data["trans"]]
    if len(tids) != len(set(tids)):
        problems.append(f"转换 ID 重复：{[t for t in tids if tids.count(t) > 1]}")
    for t in data["trans"]:
        for token in t["roles"].split(","):
            if token.strip() not in {r.value for r in spec.Role}:
                problems.append(f"{t['tid']} 的允许角色有未知值 {token!r}")
        for code in t["pre"].split(","):
            if code.strip() not in spec.PRECONDITIONS:
                problems.append(f"{t['tid']} 的前置条件代码 {code.strip()!r} 不在图例里")

    # 终态必须没有出边（BR-02）——文档层面先查一遍，不依赖模型
    for t in data["trans"]:
        if t["source"] in {s.value for s in spec.TERMINAL}:
            problems.append(f"{t['tid']} 从终态 {t['source']} 出发，违反 BR-02")

    # --- 权限矩阵 ↔ 转换表（两处说法必须一致，这正是缺陷高发点）
    derived = {}
    for t in data["trans"]:
        derived.setdefault(t["action"], set()).update(x.strip() for x in t["roles"].split(","))
    for action, cells_row in data["perm"].items():
        if action not in {a.value for a in spec.Action}:
            problems.append(f"权限矩阵里有未知动作 {action!r}")
            continue
        claimed = {spec.Role(r).value for (i, r) in enumerate(("STUDENT", "WORKER", "ADMIN"))
                   if cells_row[i].strip() == "允许"}
        if claimed != derived.get(action, set()):
            problems.append(f"动作 {action} 的权限矩阵说 {sorted(claimed)}，"
                            f"状态转换表聚合出来是 {sorted(derived.get(action, set()))}")
        for i, value in enumerate(cells_row):
            if value.strip() not in ("允许", "—", "-"):
                problems.append(f"权限矩阵 {action} 第 {i + 2} 列的值 {value!r} 不是 允许/—")
    for action in derived:
        if action not in data["perm"]:
            problems.append(f"动作 {action} 出现在转换表里，但权限矩阵没有这一行")

    # --- 可见性、SLA、图例
    doc_vis = {spec.Role(k.strip()).value: v.strip() for k, v in data["vis"].items()}
    for role in spec.Role:
        declared = spec.ROLE_VISIBILITY[role]
        if doc_vis.get(role.value) != declared:
            problems.append(f"可见性矩阵 {role.value} = {doc_vis.get(role.value)!r}，模型声明 = {declared!r}")
        if declared not in ("OWN", "OWN_OR_POOL", "OWN_OR_POOL_OR_RESOLVED", "ALL"):
            problems.append(f"模型里 {role.value} 的可见范围代码非法：{declared}")
    if {p.value for p in spec.Priority} != set(data["sla"]):
        problems.append("SLA 表的优先级集合与代码不一致")
    for prio, hours in data["sla"].items():
        if spec.SLA_HOURS[spec.Priority(prio)] != hours:
            problems.append(f"SLA {prio}：文档 {hours} 小时，模型 {spec.SLA_HOURS[spec.Priority(prio)]} 小时")
    if data["legend"] != set(spec.PRECONDITIONS):
        problems.append(f"前置条件图例与代码不一致：文档 {sorted(data['legend'])} "
                        f"vs 代码 {sorted(spec.PRECONDITIONS)}")

    # --- B18：时限参数与字段写入时机（Java 侧要读这两张表，所以它们必须能被机器咬住）
    problems.extend(param_problems(data, spec))
    problems.extend(field_effect_problems(data, spec))
    problems.extend(limit_problems(data, spec))

    # --- 追踪性：FR → 用例/故事 → 验收标准 → 测试
    referenced = set()
    for refs in data["ucs"].values():
        referenced.update(refs.get("覆盖需求", []))
    for refs in data["uss"].values():
        referenced.update(refs.get("需求", []))
    for fid in sorted(data["frs"]):
        if fid not in referenced:
            problems.append(f"{fid} 没有被任何用例或用户故事引用（孤儿需求）")
        verify_slot(data["fr_verify"][fid], fid, problems)

    # 非功能需求也要交代怎么验，否则它就只是一句愿望
    for nid, row in sorted(data["nfrs"].items()):
        verify_slot(row[2], nid, problems)

    for uid in sorted(data["uss"]):
        if not data["acs"].get(uid):
            problems.append(f"{uid} 没有验收标准")
    ac_ids = [a["ac"] for items in data["acs"].values() for a in items]
    if len(ac_ids) != len(set(ac_ids)):
        problems.append(f"验收标准 ID 重复：{[x for x in ac_ids if ac_ids.count(x) > 1]}")
    known_ids = (set(data["frs"]) | set(data["brs"]) | set(data["nfrs"]) | set(data["ifs"])
                 | set(data["ucs"]) | set(data["uss"])
                 | {a["ac"] for items in data["acs"].values() for a in items} | data["aqs"])

    for uid, items in data["acs"].items():
        for a in items:
            verify_slot(a["verify"], a["ac"], problems)
            for ref in REF_RE.findall(a["text"]):
                if ref not in known_ids:
                    problems.append(f"{a['ac']} 引用了不存在的 ID {ref}")

    for table_name, ids in (("UC 表", set(data["ucs"])), ("US 表", set(data["uss"]))):
        for uid in sorted(ids):
            if not ID_RE.match(uid):
                problems.append(f"{table_name} 的 {uid} 编号不合格式")
    for ref in sorted(REF_RE.findall("\n".join(docs.values()))):
        if ref not in known_ids:
            problems.append(f"文档引用了不存在的 ID {ref}")
    for kind, pool in (("FR", set(data["frs"])), ("BR", set(data["brs"])), ("NFR", set(data["nfrs"])),
                       ("IF", set(data["ifs"])), ("UC", set(data["ucs"])), ("US", set(data["uss"])),
                       ("AQ", data["aqs"])):
        for known in sorted(pool):
            if not re.match(rf"^{kind}-\d{{2}}$", known):
                problems.append(f"编号 {known} 不符合 {kind}-NN 格式")

    # --- 规范表里不许留占位词
    for name in ("srs", "uc", "us"):
        for line in docs[name].splitlines():
            if line.startswith("|") and any(word in line for word in FORBIDDEN):
                problems.append(f"{name} 的规范表格里仍有占位词：{line[:60]}")

    problems.extend(matrix_problems(data))
    return problems, data


def build_matrix_text(data):
    """追踪矩阵从文档现算，而不是手工维护。

    列的归属规则说清楚，免得看起来像"作者随手分的"：
    * `用例` = 覆盖需求里出现该 FR 的 UC；`故事` = 需求行里出现该 FR 的 US；
    * `验收标准` = 正文引用了该 FR 的 AC；
    * `业务规则` / `接口` = **与同一 FR 在同一条 AC 或同一个用例引用行里同时出现**的 BR / IF。
      共现是有据可查的关系；再往上就只能靠人了。
    """
    rows = [["需求ID", "名称", "用例", "故事", "验收标准", "业务规则", "接口", "验证入口", "状态"]]
    uc_refs, us_refs, ac_refs, br_refs, if_refs = {}, {}, {}, {}, {}
    for uid, refs in data["ucs"].items():
        for fid in refs.get("覆盖需求", []):
            uc_refs.setdefault(fid, set()).add(uid)
            for other in refs.get("覆盖需求", []):
                if other.startswith("BR"):
                    br_refs.setdefault(fid, set()).add(other)
                if other.startswith("IF"):
                    if_refs.setdefault(fid, set()).add(other)
    for uid, refs in data["uss"].items():
        for fid in refs.get("需求", []):
            us_refs.setdefault(fid, set()).add(uid)
    for items in data["acs"].values():
        for a in items:
            found = set(REF_RE.findall(a["text"]))
            for fid in found:
                if fid.startswith("FR"):
                    ac_refs.setdefault(fid, set()).add(a["ac"])
                    br_refs.setdefault(fid, set()).update(x for x in found if x.startswith("BR"))
                    if_refs.setdefault(fid, set()).update(x for x in found if x.startswith("IF"))
    for fid in sorted(data["frs"]):
        verify = data["fr_verify"][fid].strip()
        if MANUAL_RE.search(verify):
            status = f"人工确认({MANUAL_RE.search(verify).group(1)})"
        elif PENDING_RE.search(verify):
            status = f"待验证({PENDING_RE.search(verify).group(1)})"
        else:
            status = "已可执行"
        rows.append([fid, data["frs"][fid][1],
                     " ".join(sorted(uc_refs.get(fid, ()))), " ".join(sorted(us_refs.get(fid, ()))),
                     " ".join(sorted(ac_refs.get(fid, ()))), " ".join(sorted(br_refs.get(fid, ()))),
                     " ".join(sorted(if_refs.get(fid, ()))), verify.strip("`"), status])
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def matrix_problems(data):
    """矩阵是生成物：与文档重算的结果不一致就是过期了。"""
    path = ROOT / "traceability.csv"
    if not path.is_file():
        return ["traceability.csv 不存在（跑 python checks/check_docs.py --write）"]
    committed = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    fresh = build_matrix_text(data)
    if committed.strip() != fresh.strip():
        return ["traceability.csv 与文档不一致，已过期。跑：python checks/check_docs.py --write"]
    return []


def main(argv=None):
    argv = argv or sys.argv[1:]
    problems, data = check()
    if "--write" in argv:
        text = build_matrix_text(data)
        (ROOT / "traceability.csv").write_text(text, encoding="utf-8")
        print("已按当前文档重写 traceability.csv")
        problems, data = check()
    if problems:
        print(f"文档一致性检查发现 {len(problems)} 处问题：")
        for p in problems:
            print(f"  - {p}")
        return 1
    counts = (f"FR {len(data['frs'])} / BR {len(data['brs'])} / NFR {len(data['nfrs'])} / "
              f"IF {len(data['ifs'])} / UC {len(data['ucs'])} / US {len(data['uss'])} / "
              f"AC {sum(len(v) for v in data['acs'].values())} / 转换 {len(data['trans'])} / "
              f"待决 {len(data['aqs'])}")
    print(f"文档一致性通过：{counts}")
    print("  追踪矩阵与文档一致；每个 T: 引用都能在源码里找到对应测试方法")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
