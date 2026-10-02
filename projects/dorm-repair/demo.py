"""B15+B16 演示：需求走查 + 原型走查。

跑法：`python demo.py`（不到 2 秒，不写任何文件）。

七段：
  1) 追踪旅程：一条需求怎么落到用例、故事、验收标准和**真的能跑的测试**
  2) 状态机走一遍：提单 → 派单 → 接单 → 完工 → 验收，逐步打印状态与留痕
  3) 权限矩阵现场核对：同一个动作，三种角色三种结果
  4) 可见性：三个人对同一批 12 单看到三种列表
  5) 检查器有没有牙齿：故意在内存里改坏模型，看它报不报错
  6) 歧义登记：哪些验收标准已经能跑，哪些明确还跑不了
  7) 原型走查（B16，headless）：界面四态与按钮可用性全部来自模型

第 1、5 段说明"需求不是写完就完"；第 7 段说明"界面不自己推规则"。
"""
from __future__ import annotations

import collections
import io
import importlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from checks import check_docs, check_pm, check_qa       # noqa: E402
from spec import workorder as W                        # noqa: E402
from tools import (consequences, export_gate, mutation_check, pipeline,  # noqa: E402
                      project_ledger, shrink, triage)

WIDTH = 78


def section(index: int, title: str) -> None:
    print()
    print("=" * WIDTH)
    print(f"{index}) {title}")
    print("=" * WIDTH)


def show(label: str, value) -> None:
    print(f"  {label:<20} {value}")


def resolve_and_run(ref: str):
    """把 `T:tests/test_x.py::method` 变成一次**真实执行**。

    不能直接把 `method` 拼成 `module.method`：测试方法是写在 TestCase 类里的，
    少一层类名 unittest 就会以"找不到测试"告终——而它报的是 error 不是 fail，
    演示里如果只打印"ran=1"，看上去像是跑过了（这一条我踩过，见 README 踩坑）。
    """
    path, _, method = ref.strip("`").removeprefix("T:").partition("::")
    module = importlib.import_module(path[:-3].replace("/", "."))
    for name, obj in vars(module).items():
        if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and hasattr(obj, method):
            suite = unittest.TestLoader().loadTestsFromName(f"{module.__name__}.{name}.{method}")
            stream = io.StringIO()
            result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
            return f"{name}.{method}", result
    raise LookupError(f"{path} 里找不到方法 {method}")


def main() -> int:
    section(1, "追踪旅程：FR-03 从文档走到一次真实测试")
    _problems, data = check_docs.check()
    row = data["frs"]["FR-03"]
    show("需求原文", row[1])
    show("来源", row[2])
    show("验证入口", row[3].strip("`"))
    where, result = resolve_and_run(row[3])
    show("现场执行结果", f"{where}：ran={result.testsRun} failures={len(result.failures)} "
                          f"errors={len(result.errors)} was_ok={result.wasSuccessful()}")
    if not result.wasSuccessful():
        print("  追踪入口指向的测试没过，演示到此为止，别往下假装成功")
        return 1
    covered = sorted({uid for uid, refs in data["ucs"].items() if "FR-03" in refs.get("覆盖需求", [])})
    stories = sorted({uid for uid, refs in data["uss"].items() if "FR-03" in refs.get("需求", [])})
    acs = sorted(a["ac"] for items in data["acs"].values() for a in items
                 if "FR-03" in a["text"] or a["ac"] in {"AC-03", "AC-04"})
    show("覆盖它的用例", covered)
    show("覆盖它的故事", stories)
    show("它的验收标准", acs[:4])

    section(2, "状态机走一遍")
    order = W.create_order(id="W42", reporter="stu-9", room="c03-305", category="WATER_ELEC",
                           priority="HIGH", description="洗手池下水管漏水，麻烦尽快",
                           contact="13800001234", created_at=1000.0)
    show("建单", f"{order.state}（room 已规范化为 {order.room}）")
    order = W.apply_transition(order, W.Role.STUDENT, "stu-9", W.Action.SUBMIT, now=2000.0)
    show("提交", f"{order.state}，submitted_at={order.submitted_at}，"
                 f"SLA 到期={order.sla_due_at}（HIGH 8h：2000 + 8×3600）")
    order = W.apply_transition(order, W.Role.ADMIN, "adm-1", W.Action.ASSIGN,
                               now=2500.0, assignee="w-7")
    show("派单", f"{order.state} → {order.assignee}")
    order = W.apply_transition(order, W.Role.WORKER, "w-7", W.Action.ACCEPT, now=3000.0)
    show("接单", order.state)
    order = W.apply_transition(order, W.Role.WORKER, "w-7", W.Action.RESOLVE, now=4000.0,
                               note="更换下水管接头并试水无渗漏")
    show("完工", f"{order.state}（待验收）")
    order = W.apply_transition(order, W.Role.STUDENT, "stu-9", W.Action.CONFIRM, now=5000.0)
    show("验收", f"{order.state}，assignee 已清空为 {order.assignee!r}")
    print("\n  留痕（FR-15 / BR-06）：")
    for c in order.history:
        print(f"    t={c.at:<8g} {c.source:<12} → {c.target:<12} {c.action:<13} "
              f"{c.actor_role}/{c.actor_id}" + (f"  理由={c.reason}" if c.reason else ""))

    section(3, "权限矩阵现场核对：同一个动作，三种角色")
    target = W.apply_transition(W.create_order(id="W43", reporter="stu-9", room="A01-101",
                                               category="NETWORK", priority="NORMAL",
                                               description="网口松动", contact="13800001234",
                                               created_at=0.0),
                                W.Role.STUDENT, "stu-9", W.Action.SUBMIT, now=1000.0)
    for role, who in [(W.Role.STUDENT, "stu-9"), (W.Role.WORKER, "w-7"), (W.Role.ADMIN, "adm-1")]:
        try:
            W.apply_transition(target, role, who, W.Action.ASSIGN, now=1500.0, assignee="w-7")
            result = "允许（进入 ASSIGNED）"
        except W.TransitionError as exc:
            result = f"拒绝：{exc.code}"
        show(f"{role.value} 发起 assign", result)

    section(4, "可见性：三个人三种列表")
    orders = W.sample_orders()
    for role, who in [(W.Role.STUDENT, "stu-1"), (W.Role.WORKER, "w-1"), (W.Role.ADMIN, "adm-1")]:
        ids = [o.id for o in W.filter_orders(orders, actor_role=role, actor_id=who)]
        drafts = [o.id for o in orders if o.state == "DRAFT" and o.id in ids]
        show(f"{role.value} {who}", f"{len(ids):>2} 单  {ids}" +
             (f"   （含草稿 {drafts}）" if drafts else "   （一张草稿都看不见）"))
    late = [o.id for o in W.filter_orders(orders, actor_role=W.Role.ADMIN,
                                         overdue_only=True, now=88000.0)]
    show("管理员只看逾期（t=88000）", f"{late}　← RESOLVED 与终态都不算逾期（SRS 第 8 节）")

    section(5, "检查器有没有牙齿：把模型改坏，看它抓不抓")
    keep = dict(W.SLA_HOURS)
    W.SLA_HOURS[W.Priority.URGENT] = 1
    caught = [p for p in check_docs.check()[0] if "SLA" in p]
    show("把 URGENT 从 2 小时改成 1 小时", caught[0] if caught else "没抓到（那检查器就是摆设）")
    W.SLA_HOURS.clear()
    W.SLA_HOURS.update(keep)
    missing = tuple(t for t in W.TRANSITIONS if t.tid != "TR-15")
    original, W.TRANSITIONS = W.TRANSITIONS, missing
    caught = [p for p in check_docs.check()[0] if "TR-15" in p]
    show("把 escalate 这条转换删掉", caught[0] if caught else "没抓到")
    W.TRANSITIONS = original
    problems, _ = check_docs.check()
    show("恢复之后", f"{'仍有问题：' + str(problems[:2]) if problems else '一致性检查通过'}")

    section(6, "歧义登记与“跑不了的部分”")
    executable = pending = manual = 0
    for items in data["acs"].values():
        for a in items:
            kind = check_docs.verify_slot(a["verify"], a["ac"], [])
            executable += kind == "executable"
            pending += kind == "pending"
            manual += kind == "manual"
    total = executable + pending + manual
    show("验收标准总数", f"{total} 条：已可执行 {executable}、待后续轮次 {pending}、需人工 {manual}")
    show("待决问题", f"{len(data['aqs'])} 条（{', '.join(sorted(data['aqs']))}）")
    print("\n  这几条我替真实用户做了判断，但只有他们能定：")
    for line in ("AQ-02 SLA 时长与是否重置", "AQ-03 验收悬挂多久算超时、谁有权关闭",
                 "AQ-09 已派单后学生能否自己取消", "AQ-10 反复退回公共池要不要设上限",
                 "AQ-11 优先级由学生自选会不会通胀"):
        print(f"    · {line}")
    print("\n  没把默认值写成“校方规定”，是这份需求文档唯一的诚实底线。")

    section(7, "原型走查（B16，headless）：四态与按钮都来自模型")
    from prototype.server import PrototypeServer        # 先导这个：它负责把 B11 挂进 sys.path
    from netlab.client import Connection                # 复用 B11，不引新依赖

    proto = PrototypeServer(port=0)
    port = proto.start()
    try:
        with Connection(port=port) as c:
            def api(path):
                response = c.request("GET", path)
                return response.status, json.loads(response.text() or "{}")

            for role, who in [("STUDENT", "stu-1"), ("WORKER", "w-1"), ("ADMIN", "adm-1")]:
                _status, data = api(f"/api/orders?role={role}&actor={who}")
                ids = [o["id"] for o in data["orders"]]
                show(f"{role}/{who} 看到", f"{data['count']} 张  {ids}")
            _status, mine = api("/api/orders?role=STUDENT&actor=stu-1&state=CLOSED")
            _status, none = api("/api/orders?role=STUDENT&actor=stu-1&category=FURNITURE")
            show("正常态有结果", f"{len(mine['orders'])} 张（stu-1 的已关闭单）")
            show("空态", f"count={none['count']} empty={none['empty']} → 界面走空状态分支，"
                         "不是报错也不是残留上一次的行")
            status, err = api("/api/orders?role=HACKER&actor=x")
            show("错误态", f"HTTP {status}：{err.get('error')}")

            _status, detail = api("/api/orders/R001?role=STUDENT&actor=stu-1")
            show("R001 学生可点", detail["attemptable"])
            show("  要点的内容", detail["required_inputs"])
            _status, admin_view = api("/api/orders/R001?role=ADMIN&actor=adm-1")
            show("R001 管理员可点", admin_view["attemptable"])
            _status, closed = api("/api/orders/R005?role=ADMIN&actor=adm-1")
            show("已关闭的单可点", f"{closed['attemptable']}（空数组：BR-02，界面显示解释而不是按钮）")
            _status, draft = api("/api/orders/R004?role=STUDENT&actor=stu-2")
            show("自己的草稿可点", f"{draft['attemptable']}，SLA 未起算："
                                    f"submitted_at={draft['submitted_at']}")
            hidden, _body = api("/api/orders/R004?role=WORKER&actor=w-1")
            show("维修员看这张草稿", f"HTTP {hidden}　← 第 6 节：草稿不进公共池，也不替他透露有这张单")

            response = c.request("POST", "/api/orders?role=STUDENT&actor=stu-1",
                                 body=json.dumps({"room": "101", "category": "WIFI",
                                                  "priority": "NORMAL", "description": "   ",
                                                  "contact": "1"}).encode(),
                                 headers=[("Content-Type", "application/json")])
            payload = json.loads(response.text())
            show("表单一次报全", f"HTTP {response.status} "
                                  f"{[f['field'] for f in payload['fields']]}")
            show("  界面落点", "每个字段旁边各一条 + 汇总条数 + 焦点送第一个（V2 约定）")
    finally:
        proto.stop()
    show("原型已停止", "数据在内存里，退出即清空；项目目录没有留下文件")
    print("\n  剩下的只能你来：观感、手感、键盘与读屏的真实表现——见 docs/07-walkthrough.md，"
          "那张表的每一行我都没替你填。")

    section(8, "架构核对（B17）：依赖图是测出来的，契约是导出来的")
    from arch import style_probe
    from checks import check_arch
    from tools import export_contract

    doc_text = (ROOT / "docs" / "08-architecture.md").read_text(encoding="utf-8")
    declared = check_arch.declared_edges(doc_text)
    actual = check_arch.actual_edges()
    show("组件", f"{len(actual)} 个，真实 import 边 {sum(len(v) for v in actual.values())} 条")
    for comp in ("spec", "prototype", "arch"):
        show(f"{comp} 的出边", f"实测 {sorted(actual[comp]) or ['（无）']} / "
                                f"文档声明 {sorted(declared[comp]) or ['（无）']}")
    show("判定源份数", f"{style_probe.sources_of_the_state_machine()} —— 换风格不等于复制状态机")
    data = style_probe.metrics()
    for name in ("A 分层单体", "B 端口-适配器", "C 两服务+事件总线"):
        row = data[name]
        show(name, f"参与者={row['参与者']} 事务边界={row['事务边界']} "
                   f"消息={row['总线消息']} 重复状态点={row['重复状态点']}")
    show("C 为什么多一个重复点", "那条 submitted 事件迟到投递一次，副本从 ASSIGNED 被写回 SUBMITTED")
    contract = export_contract.build()
    show("契约", f"{len(contract['transitions'])} 条转换 · {len(contract['permissions'])} 项权限 · "
                 f"{len(contract['field_errors'])} 个字段错误码（B18/B20 读它，不抄表）")
    problems = check_arch.check()
    show("架构核对", "通过" if not problems else f"{len(problems)} 处问题：" + str(problems[:3]))
    if problems:
        return 1

    section(9, "平台层（B18）：Java 读同一份契约，判定逐格相同")
    table = json.loads((ROOT / "contracts" / "verdict_table.json").read_text(encoding="utf-8"))
    show("判定表", f"{table['count']} 格 = 状态 × 动作 × 身份 × 输入齐全/缺失 × 时刻")
    codes = collections.Counter(v.split(":")[1] for v in table["verdicts"].values()
                                if v.startswith("ERR"))
    show("拒绝码分布", dict(codes.most_common()))
    early = "RESOLVED|force_close|ADMIN|adm-1|empty|5000.0"
    late = "RESOLVED|force_close|ADMIN|adm-1|empty|608800.0"
    show("宽限期边界（BR-10）", f"5000.0 → {table['verdicts'][early]}；"
                                f"608800.0 → {table['verdicts'][late]}"
                                "　（4000 + 168×3600 = 608800，达到即算）")
    java_layers = check_arch.java_layer_table(
        (ROOT / "docs" / "09-platform.md").read_text(encoding="utf-8"))
    measured = check_arch.java_measured_imports()
    show("Java 分层", f"{len(java_layers)} 层，扫出 {sum(len(v) for v in measured.values())} 条 import，"
                      f"层间边与文档双向相等")
    show("领域层依赖", f"{sorted(measured.get('course.dormrepair.domain', set()))}")
    print("  ↑ domain 只 import java.util 与 contract：没有 Spring、没有 SQL、没有 Jackson。")
    print("  换存储、换框架都不用动判定逻辑——这是 B17 那张图在 Java 里的兑现。")
    show("怎么自己跑", "cd java && （用本机 Maven 3.9.12）mvn -o -B test　→　23 项，含 1680 格对拍")
    show("本轮没有下载任何东西",
         "Spring Boot 3.3.5 / H2 2.2.224 / JUnit 5.10.5 / Maven 3.9.12 都在 ~/.m2 里，-o 离线可构建")
    section(10, "两种接口（B19）：为什么是 SOAP，以及谁被禁止自己判断状态")
    repo = Path.home() / ".m2" / "repository"
    cached = {}
    for label, rel in (("Spring WS", "org/springframework/boot/spring-boot-starter-web-services"),
                       ("SAAJ", "com/sun/xml/messaging/saaj"),
                       ("JAX-WS", "jakarta/xml/ws"), ("gRPC", "io/grpc"),
                       ("JDK java.xml", None)):
        cached[label] = "（JDK 自带）" if rel is None else (repo / rel).is_dir()
    show("本机依赖实测", " ".join(f"{k}={'有' if v else '无'}" for k, v in cached.items()))
    show("为什么手写 SOAP 信封", "gRPC 与 Spring WS 都没缓存 → 需要下载；"
                                  "JDK 自带 java.xml 足够 → 本轮零下载（PLAN 第 8 节）")
    literals = check_arch.java_state_literals()
    declared = check_arch.state_literal_allow_list(
        (ROOT / "docs" / "10-soa.md").read_text(encoding="utf-8"))
    show("状态字面量白名单", f"{len(declared)} 个文件被允许；实测 {len(literals)} 个文件真的出现，"
                             f"双向一致={check_arch.state_literal_problems(declared, literals) == []}")
    for rel, hits in sorted(literals.items()):
        show("  " + rel.split("/")[-1], "、".join(sorted(hits)))
    show("为什么注释要先剥掉", 'soap 层的注释里写着 state.equals("SUBMITTED") 作为反例；'
                              "不剥注释就会把它误报成那里长出了一套自己的规则")
    show("双接口对拍在哪跑", "run.bat 第 6 步（Java 侧 SoapInterfaceTest：同一身份的可见集合、"
                             "按钮、错误码必须逐字相同；往 SOAP 层塞一条自己的规则会立刻分叉）")

    section(11, "验证工程（B20）：这些核对器自己会不会失效，失效了谁会响")
    witnesses = shrink.find_witnesses()
    print("  收缩器：给一个反例序列，缩到最小，再用 BFS 独立算一遍最短——两个必须相等")
    print(f"  {'状态':<12}{'种子':>5}{'ddmin':>7}{'BFS':>6}{'单步不可删':>12}{'达到最优':>10}")
    for state, row in witnesses.items():
        if not row.get("reachable"):
            show("  " + state, "不可达")
            continue
        print(f"  {state:<12}{row['seed_len']:>6}{row['ddmin_len']:>7}{row['bfs_len']:>6}"
              f"{str(row['one_minimal']):>13}{str(row['matched_optimum']):>11}")
    show("为什么先试空序列", "DRAFT 空序列就满足谓词，最短见证是 0 步；"
                             "第一版停在 1 就宣布最小，把这个事实盖住了")

    m = consequences.measure()
    aq10, aq11 = m["aq10"], m["aq11"]
    print()
    show("AQ-10 循环", f"{aq10['loop_len']} 步：{' → '.join(aq10['shortest_loop'])}")
    show("重复 6 遍后", f"状态 {aq10['after_rounds']['6']['state']}、痕迹 {aq10['after_rounds']['6']['history_len']} 条、"
                        f"时限没动过={aq10['sla_frozen']}")
    show("为什么这是闭式", "它不依赖我拟的参数，是模型性质：循环合法、时限不重算、痕迹只增不减")
    grid = aq11["grid"]
    worst = max(((name, cell) for name, cfg in grid.items()
                 for key, cell in cfg.items() if key == "assumed_mix"),
                key=lambda kv: kv[1]["overdue_rate"])
    show("AQ-11 参数", f"{len(grid)} 档 × 3 种配比；假设来源：{aq11['assumptions']['source'][:24]}…")
    show("最难那档", f"{worst[0]}：逾期 {worst[1]['overdue']}/{worst[1]['orders']} = "
                     f"{worst[1]['overdue_rate']:.1%}（数字是这次算出来的，不是文档抄的）")

    print()
    show("变异登记表", f"{len(mutation_check.MUTATIONS)} 条变异（其中 1 条是内联探针，不复制文件树），"
                       f"另有 1 条阴性对照——它要求的是**不**变红；真跑：python tools/mutation_check.py")
    show("为什么要它", "前面每轮我都手写过几条『故意改坏看它抓不抓』；代码继续改，牙齿会掉，"
                       "掉的时候没东西会响。登记表让这件事变成一条可反复跑的命令")
    print(f"\n  分层流水线 {len(pipeline.LAYERS)} 层：" + "、".join(layer.id for layer in pipeline.LAYERS))
    show("流水线自带的规则", "退出码 0 但读不到数＝这层红（B18 那次 BUILD SUCCESS 但 0 个测试的教训）")
    show("它不覆盖", "浏览器里的人工走查（docs/07-walkthrough.md 的 20 步）只有你眼睛能验")

    print("\n  以上全部由 `checks/check_arch.py` 与 `checks/check_docs.py` 持续核对："
          "改了代码不改文档、或改了文档不重生成契约，下一步就是红灯。")
    section(12, "质量门禁（B21）：什么算不合格、红了先做什么、谁必须拦")
    gate = json.loads(export_gate.OUT.read_text(encoding="utf-8"))
    layers = gate["layers"]
    blocking = [row for row in layers if row["blocking"]]
    show("口径来源", f"docs/12 第 1 节 → {export_gate.OUT.name}："
                     f"{len(layers)} 层，blocking {len(blocking)}、advisory {len(layers) - len(blocking)}")
    for row in layers:
        show("  " + ("拦 " if row["blocking"] else "放 ") + row["id"], row["catches"][:52])
    show("为什么 mutation 必须拦", "它管『核对器还有没有牙齿』；这条一松整套门禁就成装饰"
                                  "（登记变异 gate-downgrade 验的就是这个）")

    print()
    samples = {}
    for mutation in mutation_check.MUTATIONS:
        samples[mutation["bucket"]] = samples.get(mutation["bucket"], 0) + 1
    show("分诊类别", f"{len(gate['triage'])} 类；规则按顺序取第一条命中，最后一类兜底")
    for rule in gate["triage"]:
        show("  " + rule["category"], f"真实样本 {samples.get(rule['category'], 0)} 条｜{rule['meaning'][:30]}")
    real_message = check_docs.param_problems({"params": {"ACCEPTANCE_GRACE_HOURS": 24}}, W)[0]
    verdict = triage.classify(real_message)
    show("现场分诊一条", real_message[:44] + "…（这句话由 check_docs 自己打印）")
    show("  归为", f"{verdict['category']}（命中特征 {verdict['matched']!r}）")
    show("  下一步", verdict["confirm"])
    show("  15 条样本全验", "python tools/triage.py --selftest（真跑变异自检台，约 10 秒）")

    rows, bad = check_qa.walk_rows()
    stats = check_qa.walk_stats(rows)
    print()
    show("走查清单对齐", f"{stats['步数']} 步＝纯自动 {stats['纯自动']} + "
                         f"自动但仍需眼看 {stats['自动+人工']} + 只能人工 {stats['只能人工']}")
    show("我不代勾", "『你的结果』那一列仍是『未验证』；检查器若把它填成『通过』，qa 层立刻红")
    show("门禁怎么跑", "run.bat gate 或 python tools/quality_gate.py（本地判定，不是服务端分支保护）")

    section(13, "项目管理（B22）：数字不许手抄，风险与复盘要对得上事实")
    facts = project_ledger.public(project_ledger.facts())
    show("台账", f"{len(facts)} 个键，全部由事实源现算（docs/13 第 8 节逐条引用）")
    for key in ("rounds_done", "rounds_dorm", "rounds_dates", "aq_total", "aq_ruled", "aq_open",
                "pitfalls", "gate_layers", "gate_blocking", "mutations", "verdict_cells"):
        show("  " + key, facts[key])
    show("为什么不收测试数与耗时", "那是某一次跑的结果，归流水线每次重测；"
                                   "抄进台账就再造了一份需要人维护的副本")
    problems, _f = check_pm.check()
    show("管理文档核对", "通过" if not problems else f"{len(problems)} 处过期/缺登记")
    for line in problems[:3]:
        show("  -", line[:70])
    text = Path("docs/15-retrospective.md").read_text(encoding="utf-8")
    cats = re.findall(r"^\| (一|二|三) · [^|]*\| (\d+) \| ([^|]+) \|$", text, re.M)
    for name, count, numbers in cats:
        show(f"  复盘第{name}类", f"{count} 条（{numbers[:46]}…）")
    show("重复模式（复盘最有价值的部分）", "A 退出码/假绿、B 数字没重算、C 语法通过≠能跑——"
                                          "同类错误跨轮复发，说明上一轮修的不是根因")
    show("怎么复核", "python tools/project_ledger.py --dump && python checks/check_pm.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
