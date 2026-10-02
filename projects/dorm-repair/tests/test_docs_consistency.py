"""文档与模型的一致性测试。

这套测试的价值全在**红灯**上：它证明"文档说了一套、代码做了另一套"会被当场抓到，
而不是等 B18 实现时才发现。所以除了正向通过，我特意写了三组反向断言
（故意改坏模型，看检查器是否报错）——不能失败的检查器和不会失败的测试一样没用。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks import check_docs                          # noqa: E402
from spec import workorder as W                        # noqa: E402


class TestDocsAreConsistent(unittest.TestCase):
    def test_docs_are_consistent(self):
        problems, _data = check_docs.check()
        self.assertEqual(problems, [], "需求文档与可执行模型不一致：\n  " + "\n  ".join(problems))

    def test_every_requirement_is_covered(self):
        _problems, data = check_docs.check()
        self.assertEqual(len(data["frs"]), 15, "FR 数量变了要同步检查覆盖情况")
        self.assertEqual(len(data["ucs"]), 6)
        self.assertEqual(len(data["uss"]), 13)
        self.assertGreaterEqual(sum(len(v) for v in data["acs"].values()), 39)
        self.assertEqual(len(data["trans"]), len(W.TRANSITIONS))
        self.assertGreaterEqual(len(data["aqs"]), 11,
                                "每条暂定默认值都该登记为待决问题，不许藏在正文里")

    def test_traceability_matrix_is_current(self):
        _problems, data = check_docs.check()
        self.assertEqual(check_docs.matrix_problems(data), [],
                         "traceability.csv 已过期：跑 python checks/check_docs.py --write")

    def test_docs_files_exist_and_are_utf8(self):
        for name in ("01-scope", "02-srs", "03-use-cases", "04-user-stories", "05-open-questions"):
            path = ROOT / "docs" / f"{name}.md"
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            self.assertGreater(len(text), 400, f"{name}.md 短得不像一份需求文档")
            self.assertNotIn("锟", text, f"{name}.md 有乱码残留")


class TestCheckerActuallyHasTeeth(unittest.TestCase):
    """故意改坏模型，检查器必须报错。每条都恢复原状。"""

    def setUp(self):
        self.original_transitions = W.TRANSITIONS
        self.original_sla = dict(W.SLA_HOURS)
        self.original_vis = dict(W.ROLE_VISIBILITY)
        self.addCleanup(self.restore)

    def restore(self):
        W.TRANSITIONS = self.original_transitions
        W.SLA_HOURS.clear()
        W.SLA_HOURS.update(self.original_sla)
        W.ROLE_VISIBILITY.clear()
        W.ROLE_VISIBILITY.update(self.original_vis)

    def problems(self):
        found, _data = check_docs.check()
        return found

    def test_dropping_a_transition_from_the_model_is_caught(self):
        W.TRANSITIONS = tuple(t for t in W.TRANSITIONS if t.tid != "TR-15")
        messages = " | ".join(self.problems())
        self.assertIn("TR-15 只在文档里", messages)
        self.assertNotIn("TR-15", {t.tid for t in W.TRANSITIONS})

    def test_changing_sla_in_the_model_only_is_caught(self):
        W.SLA_HOURS[W.Priority.URGENT] = 1
        self.assertTrue(any("SLA URGENT" in p for p in self.problems()))

    def test_changing_visibility_in_the_model_only_is_caught(self):
        W.ROLE_VISIBILITY[W.Role.WORKER] = "ALL"
        self.assertTrue(any("可见性矩阵 WORKER" in p for p in self.problems()))

    def test_adding_an_unknown_precondition_is_caught(self):
        target = next(t for t in W.TRANSITIONS if t.tid == "TR-01")
        broken = W.Transition(target.tid, target.action, target.source, target.target,
                              target.roles, target.preconditions + ("teleport",))
        W.TRANSITIONS = tuple(broken if t.tid == "TR-01" else t for t in W.TRANSITIONS)
        self.assertTrue(any("teleport" in p for p in self.problems()))

    def test_fake_test_reference_is_rejected(self):
        """"引用一个不存在的测试"比留空更危险，因为它看起来像已经验过了。"""
        problems = []
        check_docs.verify_slot("`T:tests/test_workorder_spec.py::test_never_written`",
                               "AC-99", problems)
        self.assertEqual(len(problems), 1)
        self.assertIn("不可用", problems[0])
        check_docs.verify_slot("`T:tests/test_no_such_file.py::test_x`", "AC-98", problems)
        self.assertIn("不存在", problems[1])

    def test_pending_and_manual_slots_are_accepted_without_a_test(self):
        problems = []
        for value in ("`待验证（B18）`", "人工确认（B16）", "待验证(B20)"):
            kind = check_docs.verify_slot(value, "NFR-99", problems)
            with self.subTest(value=value):
                self.assertIn(kind, ("pending", "manual"))
        self.assertEqual(problems, [])

    def test_empty_slot_is_a_problem(self):
        problems = []
        self.assertEqual(check_docs.verify_slot("", "FR-99", problems), "empty")
        self.assertEqual(check_docs.verify_slot("随便说一句", "FR-99", problems), "unknown")
        self.assertEqual(len(problems), 2)

    def test_malformed_markdown_table_is_caught(self):
        bad = "| 甲 | 乙 |\n|---|---|\n| 1 | 2 | 3 |\n"
        _tables, problems = check_docs.tables_in(bad)
        self.assertTrue(problems)
        self.assertIn("列数", problems[0])

    def test_changing_grace_hours_in_the_model_only_is_caught(self):
        """B18 的 168 小时进了契约，所以"只改代码不改文档"必须被读到。"""
        original = W.ACCEPTANCE_GRACE_HOURS
        W.ACCEPTANCE_GRACE_HOURS = 24
        self.addCleanup(setattr, W, "ACCEPTANCE_GRACE_HOURS", original)
        _problems, data = check_docs.check()
        messages = " | ".join(check_docs.param_problems(data, W))
        self.assertIn("ACCEPTANCE_GRACE_HOURS", messages)
        self.assertIn("文档 168 小时，模型 24 小时", messages)

    def test_field_effect_table_rejects_invented_field_and_missing_row(self):
        """这张表是 Java 侧建列的依据，所以它既不能写不存在的字段，也不能漏掉关键字段。"""
        _problems, data = check_docs.check()
        good = data["field_effects"]
        self.assertEqual(check_docs.field_effect_problems({"field_effects": good}, W), [])

        fake = dict(good[0])
        fake["field"] = "`assignee_last`"                      # 模型里没有这个字段
        messages = " | ".join(check_docs.field_effect_problems(
            {"field_effects": good + [fake]}, W))
        self.assertIn("不存在的字段", messages)

        dropped = [row for row in good if row["field"].strip("`") != "resolved_by"]
        messages = " | ".join(check_docs.field_effect_problems({"field_effects": dropped}, W))
        self.assertIn("缺行", messages)
        self.assertIn("resolved_by", messages)

    def test_field_effect_row_must_point_at_a_real_test(self):
        """写一句"由实现保证"不算验证入口——检查器要看见一个真实存在的方法名。"""
        _problems, data = check_docs.check()
        row = dict(data["field_effects"][0])
        row["verify"] = "由实现保证"
        messages = " | ".join(check_docs.field_effect_problems({"field_effects": [row]}, W))
        self.assertIn("既没有 T: 测试引用", messages)


if __name__ == "__main__":
    unittest.main()
