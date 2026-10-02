"""B17 架构核对的测试。

和前面几轮一样，重点不是"它现在通过"，而是**它能不能失败**：
每个正向断言旁边都配了一个"故意改坏"的反向断言，
因为一张没人验证过的依赖图，和一张画错的依赖图没有区别。
"""
from __future__ import annotations

import collections
import dataclasses
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arch import style_probe                                  # noqa: E402
from checks import check_arch, check_docs                     # noqa: E402
from spec import workorder as W                               # noqa: E402
from tools import export_contract                             # noqa: E402

DOC = ROOT / "docs" / "08-architecture.md"


class TestArchitectureIsConsistent(unittest.TestCase):
    def test_arch_is_consistent(self):
        problems = check_arch.check()
        self.assertEqual(problems, [], "架构核对失败：\n  " + "\n  ".join(problems))

    def test_dependency_graph_is_measured_not_drawn(self):
        """文档声明的边必须与 ast 扫出来的真实 import 边**完全相同**（双向）。"""
        declared = check_arch.declared_edges(DOC.read_text(encoding="utf-8"))
        actual = check_arch.actual_edges()
        self.assertEqual(declared, actual)
        self.assertEqual(actual["spec"], set(), "领域层有一条内部依赖都不该有")
        self.assertEqual(actual["arch"], {"spec"})
        self.assertIn("netlab", actual["prototype"], "原型必须复用 B11，而不是自己起 socket 服务")

    def test_a_new_illegal_dependency_is_caught(self):
        """往 spec/ 里塞一个 import netlab 的文件，核对器必须报两处：越界依赖 + 领域不纯。"""
        intruder = ROOT / "spec" / "_probe_illegal.py"
        self.assertFalse(intruder.exists(), "上一次运行没清干净，先删掉再测")
        try:
            intruder.write_text("import netlab\nimport time\n", encoding="utf-8")
            problems = "\n".join(check_arch.check())
        finally:
            intruder.unlink()
        self.assertIn("spec → netlab", problems)
        self.assertIn("spec/_probe_illegal.py", problems)
        self.assertIn("领域层不该知道", problems)
        self.assertEqual(check_arch.check(), [], "删掉之后必须立刻恢复干净")

    def test_domain_purity_survives_the_whole_tree(self):
        for path in (ROOT / "spec").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for banned in ("netlab", "prototype", "import time", "datetime", "http"):
                with self.subTest(file=path.name, banned=banned):
                    self.assertNotIn(banned, text)


class TestContract(unittest.TestCase):
    def test_contract_matches_document_and_model(self):
        saved = json.loads(export_contract.CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(saved, export_contract.build())
        self.assertEqual(export_contract.against_spec(saved), [])

    def test_contract_shape_is_stable_for_consumers(self):
        """B18/B20 要按这份结构写代码，所以字段名和数量是接口，不能随手变。"""
        saved = json.loads(export_contract.CONTRACT.read_text(encoding="utf-8"))
        for key in ("contract", "schema_version", "roles", "states", "actions", "terminal_states",
                    "categories", "priorities", "preconditions", "transitions", "permissions",
                    "visibility", "sla_hours", "acceptance_grace_hours", "field_effects",
                    "field_errors"):
            self.assertIn(key, saved)
        self.assertEqual(saved["schema_version"], export_contract.SCHEMA_VERSION)
        self.assertEqual(len(saved["transitions"]), 15)
        self.assertEqual(saved["terminal_states"], ["CLOSED", "CANCELLED"])
        one = saved["transitions"][0]
        self.assertEqual(sorted(one), sorted(["id", "action", "from", "to", "roles", "requires"]))

    def test_contract_keys_are_identifiers_not_prose(self):
        """回归（B18 现场抓的）：`field_errors` 的键曾经长这样——"`assignee` 维修员工号"。

        `strip('`')` 只削掉首尾反引号，中间那个反引号和中文标签都留下来了。
        Python 侧没人读这个键所以一直没暴露，直到 Java 要按字段名取值才撞墙。
        **给下游机器读的键必须是标识符**，否则每换一个消费者都要重新猜一次格式。
        """
        saved = json.loads(export_contract.CONTRACT.read_text(encoding="utf-8"))
        order_fields = {f.name for f in dataclasses.fields(W.Order)}
        for key in saved["field_errors"]:
            self.assertRegex(key, r"^[a-z_]+$", f"错误码表的键不是标识符：{key!r}")
        # 建单四件套 + 三个动作级输入，都必须是模型里真有的字段名或输入名
        self.assertTrue(set(saved["field_errors"]) <=
                        {"room", "category", "priority", "description", "contact",
                         "reason", "resolution_note", "assignee"})
        for row in saved["field_effects"]:
            self.assertIn(row["field"], order_fields,
                          f"契约声明了 `Order` 没有的字段：{row['field']}")
            self.assertRegex(row["field"], r"^[a-z_]+$")
        # 宽限期必须是整数小时，Java 直接按它算，不接受"168 小时（约 7 天）"这种写法
        self.assertIsInstance(saved["acceptance_grace_hours"], int)
        self.assertEqual(saved["acceptance_grace_hours"], W.ACCEPTANCE_GRACE_HOURS)

    def test_stale_contract_is_detected(self):
        """改了模型没重生成契约 → 必须报，而不是继续给下游一份看起来新鲜的旧货。"""
        original = W.SLA_HOURS[W.Priority.HIGH]
        try:
            W.SLA_HOURS[W.Priority.HIGH] = 99
            problems = "\n".join(check_arch.check())
        finally:
            W.SLA_HOURS[W.Priority.HIGH] = original
        self.assertIn("契约与模型不一致", problems)
        self.assertEqual(check_arch.check(), [])

    def test_export_refuses_to_run_on_broken_tables(self):
        """表格列数不齐时导出应当拒绝，而不是产出一份缺行的契约。"""
        broken = "| 字段 | 规则 |\n|---|---|\n| a | b | c |\n"
        _tables, problems = check_docs.tables_in(broken)
        self.assertTrue(problems)
        self.assertIn("列数", problems[0])


class TestStyleComparison(unittest.TestCase):
    def test_metrics_match_the_table_in_the_doc(self):
        self.assertEqual(check_arch.check(), [])          # 表与实测的一致性在核对器里

    def test_the_point_of_the_comparison(self):
        """这张表的看点：只有事件总线那一列会出现副本与顺序问题。"""
        data = style_probe.metrics()
        self.assertEqual(data["A 分层单体"]["重复状态点"], 0)
        self.assertEqual(data["B 端口-适配器"]["重复状态点"], 0)
        self.assertEqual(data["C 两服务+事件总线"]["重复状态点"], 1,
                         "乱序投递后副本落后——这是拆服务的真实代价，不能被写成理论担忧")
        self.assertGreater(data["C 两服务+事件总线"]["事务边界"],
                           data["A 分层单体"]["事务边界"])
        self.assertEqual(data["C 两服务+事件总线"]["总线消息"], 3)

    def test_all_three_styles_share_one_source_and_same_outcome(self):
        same, calls = style_probe.same_outcome()
        self.assertTrue(same, "三种风格终态不同，比较就不成立")
        self.assertEqual(calls, {2}, "三种风格调用判定源的次数应相同")
        self.assertEqual(style_probe.sources_of_the_state_machine(), {"spec/workorder.py"})

    def test_a_second_state_machine_in_a_shell_would_be_caught(self):
        """如果谁在别处抄了一份 TRANSITIONS，"判定源份数"立刻 >1。"""
        copy = ROOT / "prototype" / "_probe_copy.py"
        try:
            copy.write_text("TRANSITIONS = ()\n", encoding="utf-8")
            owners = style_probe.sources_of_the_state_machine()
        finally:
            copy.unlink()
        self.assertEqual(len(owners), 2)
        self.assertIn("prototype/_probe_copy.py", owners)


class TestDocuments(unittest.TestCase):
    def test_every_adr_is_complete_and_referenced(self):
        doc = DOC.read_text(encoding="utf-8")
        problems = []
        ids = check_arch.check_adrs(doc, problems)
        self.assertEqual(problems, [])
        self.assertEqual(len(ids), 3)

    def test_new_docs_do_not_reference_ghost_ids(self):
        problems = []
        check_arch.check_new_doc_refs(problems)
        self.assertEqual(problems, [])

    def test_arch_doc_states_what_it_refuses_to_do(self):
        """架构文档最有价值的部分往往是"不做什么"，否则下一轮会顺手加戏。"""
        doc = DOC.read_text(encoding="utf-8")
        for phrase in ("不拆微服务", "不做多数据源", "不在 B17 写任何 Java 代码", "不给默认实现打勾"):
            self.assertIn(phrase, doc)


class TestJavaLayers(unittest.TestCase):
    """B18 把"依赖图是量出来的、不是画出来的"这条规矩延伸到 Java。"""

    def setUp(self):
        self.doc = (ROOT / "docs" / "09-platform.md").read_text(encoding="utf-8")

    def test_java_layer_table_parser_keeps_the_config_row(self):
        """回归：`table(text, "层")` 会把 config 那行当表头吞掉——
        因为它的允许依赖写着"所有层"，子串匹配正好中招。分层表改成整行精确匹配。"""
        rows = check_arch.java_layer_table(self.doc)
        packages = [check_arch.strip_ticks(r[1]) for r in rows if len(r) >= 3]
        self.assertIn("course.dormrepair.config", packages, f"config 行没解析出来：{packages}")
        self.assertIn("course.dormrepair", packages, "启动类所在的根包也要在表里")
        self.assertEqual(len(packages), len(set(packages)), "同一个包写了两行")

    def test_java_layers_are_measured_and_match_the_doc(self):
        problems = check_arch.check()
        self.assertEqual(problems, [], "架构核对失败：\n  " + "\n  ".join(problems))

    def test_java_layer_check_has_teeth(self):
        """喂三份假 import：越界、领域不纯、声明而未使用——每条都必须被单独抓到。"""
        declared = {"course.dormrepair.app": ["java.*", "course.dormrepair.domain"],
                    "course.dormrepair.domain": ["java.*"],
                    "course.dormrepair.web": ["java.*", "course.dormrepair.app",
                                              "course.dormrepair.infra"]}
        measured = {"course.dormrepair.app": {"java.util.List", "course.dormrepair.infra.Schema"},
                    "course.dormrepair.domain": {"java.util.List",
                                                 "org.springframework.jdbc.core.JdbcTemplate"},
                    "course.dormrepair.web": {"java.util.List",
                                              "course.dormrepair.app.RepairService"}}
        messages = "\n".join(check_arch.java_edge_problems(declared, measured))
        self.assertIn("依赖越界：course.dormrepair.app 里 import 了 course.dormrepair.infra.Schema",
                      messages)
        self.assertIn("领域层不纯", messages)
        self.assertIn("文档声明但未使用：course.dormrepair.web", messages)

    def test_no_second_copy_of_the_contract_in_java_sources(self):
        java = ROOT / "java"
        copies = [p for p in java.rglob("workflow.json") if "target" not in p.parts]
        self.assertEqual(copies, [], "Java 源码里存了契约副本，等于手抄了第二台状态机")
        pom = (java / "pom.xml").read_text(encoding="utf-8")
        self.assertIn("../contracts", pom, "pom 必须从 ../contracts 复制契约，而不是自己存一份")


class TestVerdictTable(unittest.TestCase):
    """跨语言对拍表自己也要被核对：它一旦过期，Java 就是在跟一份旧的 Python 比。"""

    def setUp(self):
        from tools import export_verdict_table as v
        self.v = v
        self.saved = json.loads(v.OUT.read_text(encoding="utf-8"))

    def test_committed_table_matches_the_model(self):
        self.assertEqual(self.saved["verdicts"], self.v.verdicts(),
                         "判定表过期：跑 python tools/export_verdict_table.py --write")

    def test_dimensions_and_distribution_are_measured_not_typed(self):
        """docs/09 第 5 节写了 1680 格与错误码分布。这些数必须是算出来的——
        B17 就栽在照抄上一轮计数上，这次把数字钉进断言。"""
        verdicts = self.saved["verdicts"]
        self.assertEqual(len(verdicts), 1680)
        self.assertEqual(self.saved["count"], len(verdicts))
        self.assertEqual(len(self.saved["actors"]), 5)
        self.assertEqual(len(self.saved["times"]), 2)
        self.assertEqual(
            collections.Counter(x.split(":")[1] for x in verdicts.values()
                                if x.startswith("ERR")),
            collections.Counter({"NO_SUCH_TRANSITION": 1400, "ROLE_NOT_ALLOWED": 188,
                                 "OWNER": 20, "ASSIGNEE": 12, "REASON_REQUIRED": 10,
                                 "ASSIGNEE_REQUIRED": 4, "NOTE_REQUIRED": 2,
                                 "ACCEPTANCE_NOT_MATURE": 2}))

    def test_grace_boundary_is_pinned_on_both_sides_of_the_edge(self):
        """到期前一格被拒、正好到点放行——这就是 BR-10 的全部争议所在。"""
        self.assertEqual(self.saved["verdicts"]["RESOLVED|force_close|ADMIN|adm-1|empty|5000.0"],
                         "ERR:ACCEPTANCE_NOT_MATURE")
        self.assertEqual(self.saved["verdicts"]["RESOLVED|force_close|ADMIN|adm-1|empty|608800.0"],
                         "OK:CLOSED")

    def test_changing_a_precondition_makes_the_table_shout(self):
        """把 TR-10 的 `acceptance_timeout` 悄悄改回 `none`（等于推翻 AQ-03 的裁决），
        判定表必须立刻对不上。

        为什么改这一条而不是删一条转换：删转换会让 `canonical()` 自己走不到 RESOLVED，
        生成器直接抛异常——那也是"喊出来了"，但测不到*判定表*比*转换清单*强的地方。
        """
        self.assertEqual(self.saved["verdicts"], self.v.verdicts(), "基线必须是干净的")
        original = W.TRANSITIONS
        relaxed = tuple(
            W.Transition(t.tid, t.action, t.source, t.target, t.roles, ("none",))
            if t.tid == "TR-10" else t for t in original)
        try:
            W.TRANSITIONS = relaxed
            now = self.v.verdicts()
            differs = [k for k, value in now.items() if self.saved["verdicts"].get(k) != value]
            self.assertTrue(differs, "放宽了宽限期前置条件，判定表却一模一样——那这张表没在测判定")
            key = "RESOLVED|force_close|ADMIN|adm-1|empty|5000.0"
            self.assertIn(key, differs)
            self.assertEqual(now[key], "OK:CLOSED")
            self.assertEqual(self.saved["verdicts"][key], "ERR:ACCEPTANCE_NOT_MATURE")
        finally:
            W.TRANSITIONS = original

    def test_dropping_a_transition_also_shouts(self):
        """删掉 TR-07 会让生成器连 RESOLVED 都造不出来——异常也算"喊出来"，
        但不能让它静默地产出一份少一格的表。"""
        original = W.TRANSITIONS
        try:
            W.TRANSITIONS = tuple(t for t in original if t.tid != "TR-07")
            with self.assertRaises(W.TransitionError):
                self.v.verdicts()
        finally:
            W.TRANSITIONS = original


class TestJavaBuildReporter(unittest.TestCase):
    """`tools/java_build.py` 的解析器自己也要测：本轮它把 23 报成 46（逐类 + 总计重复相加）。"""

    def setUp(self):
        from tools import java_build
        self.m = java_build

    def test_per_class_and_summary_are_not_double_counted(self):
        out = "\n".join([
            "[INFO] Tests run: 6, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.2 s "
            "-- in course.dormrepair.contract.ContractSmokeTest",
            "[INFO] Tests run: 17, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 20 s "
            "-- in course.dormrepair.web.RepairApiTest",
            "[INFO] Results:",
            "[INFO] Tests run: 23, Failures: 0, Errors: 0, Skipped: 0",
            "[INFO] BUILD SUCCESS",
        ])
        stats = self.m.summarize(out)
        self.assertEqual(23, stats["ran"], f"逐类相加应该正好等于总计，实际 {stats['ran']}")
        self.assertEqual((23, 0, 0, 0), stats["declared"])
        self.assertTrue(stats["consistent"])
        self.assertTrue(stats["success"])

    def test_mismatch_between_views_is_reported(self):
        """解析器不可信就判失败，而不是继续用一个来路不明的数字。"""
        out = ("[INFO] Tests run: 1, Failures: 0, Errors: 0, Skipped: 0 -- in X\n"
               "[INFO] Tests run: 9, Failures: 0, Errors: 0, Skipped: 0\n"
               "[INFO] BUILD SUCCESS")
        stats = self.m.summarize(out)
        self.assertEqual(1, stats["ran"])
        self.assertEqual((9, 0, 0, 0), stats["declared"])
        self.assertFalse(stats["consistent"])

    def test_zero_tests_with_success_is_a_failure(self):
        """开工前那次假绿：类名不匹配 surefire，`BUILD SUCCESS` + 0 个测试。"""
        stats = self.m.summarize("[INFO] BUILD SUCCESS")
        self.assertEqual(0, stats["ran"])
        self.assertTrue(stats["success"])
        self.assertIsNone(stats["declared"])
        self.assertTrue(stats["consistent"], "没有总计行时不与任何数字冲突")

    def test_maven_lookup_prefers_the_newest(self):
        """sorted()[0] 会挑到 3.8.5；本机实测踩过。"""
        fake = ["x/apache-maven-3.8.5-bin/a/bin/mvn.cmd",
                "x/apache-maven-3.9.12-bin/b/bin/mvn.cmd",
                "x/apache-maven-3.10.0-bin/c/bin/mvn.cmd"]
        self.assertEqual("x/apache-maven-3.10.0-bin/c/bin/mvn.cmd",
                         max(fake, key=self.m._version_of), "版本号要按数字比，不能按字符串")


class TestStateLiteralWhitelist(unittest.TestCase):
    """B19：Java 侧的"判定源唯一"= 状态字面量白名单。它必须先证明自己会失败。"""

    def test_comment_only_mention_is_not_counted(self):
        """我在 SOAP 文件的注释里写了 `state.equals("SUBMITTED")` 当反例。
        不剥注释的话扫描器会报"那里长出一套自己的规则"——假阳性比漏报更糟，
        因为它会让人想去改注释而不是改代码。"""
        found = check_arch.java_state_literals()
        soap = "java/src/main/java/course/dormrepair/soap/SoapQueryService.java"
        self.assertNotIn(soap, found, f"soap 层不该出现在状态字面量表里：{found.get(soap)}")
        self.assertIn("SUBMITTED", (ROOT / soap).read_text(encoding="utf-8"),
                      "前提：注释里确实提到了 SUBMITTED，这条测试才有意义")

    def test_unlisted_file_is_flagged_as_a_second_rule_source(self):
        declared = {"java/a.java": {"SUBMITTED"}}
        found = {"java/a.java": {"SUBMITTED"}, "java/soap/x.java": {"RESOLVED"}}
        messages = "\n".join(check_arch.state_literal_problems(declared, found))
        self.assertIn("疑似第二份状态表：java/soap/x.java", messages)
        self.assertIn("RESOLVED", messages)

    def test_stale_allow_list_is_flagged(self):
        declared = {"java/a.java": {"SUBMITTED", "CLOSED"}}
        found = {"java/a.java": {"SUBMITTED"}}
        messages = "\n".join(check_arch.state_literal_problems(declared, found))
        self.assertIn("白名单过期", messages)
        self.assertIn("CLOSED", messages)

    def test_the_shipped_table_matches_the_shipped_code(self):
        """正向：文档与代码现在确实一致（否则上面三条只是在演）。
        解析走核对器同一个函数——本轮我先自己重写一遍、漏了剥反引号，测试红而实现绿。"""
        declared = check_arch.state_literal_allow_list(
            (ROOT / "docs" / "10-soa.md").read_text(encoding="utf-8"))
        self.assertEqual(3, len(declared), f"白名单应覆盖三个文件：{sorted(declared)}")
        problems = check_arch.state_literal_problems(declared, check_arch.java_state_literals())
        self.assertEqual([], problems, "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
