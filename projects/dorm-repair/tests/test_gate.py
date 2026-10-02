"""tests/test_gate.py —— 门禁口径必须收口，且不许被悄悄降级（B21）。

这里测的**不是**"跑一遍门禁看它绿不绿"——那种断言只证明今天没事，不证明它会拦。
每一组都喂一份"改歪了的口径"给真实的生成函数（`export_gate.problems()`），
看它是否报出**预期的那句话**。它为什么能被信任：登记变异 `gate-downgrade`
与 `triage-rule-dropped` 就是同一件事在整棵树上的版本（`tools/triage.py --selftest` 逐条验）。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks import check_qa                            # noqa: E402
from tools import export_gate, pipeline                # noqa: E402


def fresh():
    return export_gate.build()


class Policy(unittest.TestCase):
    def test_layer_sets_are_exactly_equal(self):
        """出处：docs/12 第 1 节 ↔ tools/pipeline.py 的 LAYERS。多一层少一层都算口径失效。"""
        data = fresh()
        self.assertEqual(export_gate.problems(data), [], "干净口径应当零问题")
        self.assertEqual({row["id"] for row in data["layers"]},
                         {layer.id for layer in pipeline.LAYERS})
        self.assertEqual(len(data["layers"]), len(pipeline.LAYERS))

    def test_every_layer_says_what_it_catches_and_what_to_do(self):
        for row in fresh()["layers"]:
            with self.subTest(layer=row["id"]):
                self.assertTrue(row["catches"].strip(), "没写拦下的是什么")
                self.assertTrue(row["next"].strip(), "没写红了先做什么")

    def test_missing_layer_is_refused(self):
        data = fresh()
        data["layers"] = [row for row in data["layers"] if row["id"] != "verdict"]
        self.assertIn("门禁表与流水线的层集合不等", "\n".join(export_gate.problems(data)))

    def test_extra_layer_is_refused(self):
        data = fresh()
        data["layers"].append({"id": "made-up", "blocking": True, "catches": "x", "next": "y"})
        self.assertIn("门禁表与流水线的层集合不等", "\n".join(export_gate.problems(data)))

    def test_duplicated_layer_is_refused(self):
        data = fresh()
        data["layers"].append(dict(data["layers"][0]))
        joined = "\n".join(export_gate.problems(data))
        self.assertIn("门禁表有重复层", joined)

    def test_downgrade_attack_is_refused(self):
        """把 mutation 层降成 advisory：这正是"门禁被虚化"的形态，必须被拒。"""
        data = fresh()
        for row in data["layers"]:
            if row["id"] in export_gate.MUST_BLOCK:
                row["blocking"] = False
        joined = "\n".join(export_gate.problems(data))
        self.assertIn("被降级成 advisory", joined)

    def test_blocking_majority_and_the_advisory_pair(self):
        """口径不许被整体推翻：advisory 只允许那两个"工具与假设"层。"""
        data = fresh()
        advisory = sorted(row["id"] for row in data["layers"] if not row["blocking"])
        self.assertEqual(advisory, ["consequences", "shrink"],
                         "把别的层降成 advisory 会让门禁失去意义；要改就先改这张表的理由")


class TriageRules(unittest.TestCase):
    def test_fallback_is_last_and_every_rule_has_a_sample(self):
        data = fresh()
        cats = [rule["category"] for rule in data["triage"]]
        self.assertEqual(cats[-1], export_gate.FALLBACK)
        from tools import mutation_check
        samples = [m["bucket"] for m in mutation_check.MUTATIONS if m.get("bucket")]
        for cat in cats:
            with self.subTest(category=cat):
                self.assertIn(cat, samples, "这个类别没有任何真实样本，规则没被验证过")

    def test_rule_without_pattern_can_never_hit(self):
        data = fresh()
        data["triage"][0]["patterns"] = []
        self.assertIn("没有触发特征，永远不会命中", "\n".join(export_gate.problems(data)))

    def test_sample_claiming_an_unknown_category_is_refused(self):
        data = fresh()
        data["triage"] = data["triage"][:-1]          # 连兜底一起删掉：结构就不合格
        joined = "\n".join(export_gate.problems(data))
        self.assertIn(f"分诊表最后一类必须是兜底的 {export_gate.FALLBACK}", joined)


class Contract(unittest.TestCase):
    def test_exported_file_matches_doc_derived_data(self):
        """已导出的 JSON 必须是文档的现算结果——手改 JSON 会被这一条抓到。"""
        saved = json.loads(export_gate.OUT.read_text(encoding="utf-8"))
        self.assertEqual(saved, fresh())

    def test_hand_edited_json_is_detected(self):
        saved = fresh()
        saved["layers"][0]["blocking"] = not saved["layers"][0]["blocking"]
        self.assertNotEqual(saved, fresh())

    def test_triage_input_is_split_on_both_separators(self):
        """特征串用顿号或逗号分隔都得能切开：写表的人迟早会用错一个。"""
        self.assertEqual(export_gate.strip_ticks("`A`、`B`"), ["A", "B"])
        self.assertEqual(export_gate.strip_ticks("`A`，`B`"), ["A", "B"])
        self.assertEqual(export_gate.strip_ticks("（兜底，不命中以上任何特征）"), [])


class WalkthroughEvidence(unittest.TestCase):
    """`docs/07` 第 4 列（自动证据）不许吹牛：写出来的测试必须真在，人工的就明说人工。"""

    def setUp(self):
        self.rows, self.problems = check_qa.walk_rows()
        self.assertEqual(self.problems, [], "走查表本身应能解析")

    def test_current_file_is_clean(self):
        self.assertEqual(check_qa.walk_problems(self.rows), [])

    def test_count_is_twenty_and_result_column_is_untouched(self):
        self.assertEqual(len(self.rows), 20)
        stats = check_qa.walk_stats(self.rows)
        self.assertEqual(stats["步数"], 20)
        self.assertEqual(stats["纯自动"] + stats["自动+人工"] + stats["只能人工"], 20)
        self.assertGreaterEqual(stats["只能人工"], 1, "若全是自动证据，等于宣称人不必走查")

    def test_fake_test_reference_is_caught(self):
        rows = [list(r) for r in self.rows]
        rows[0][3] = "T:tests/test_prototype.py::test_this_one_does_not_exist"
        joined = "\n".join(check_qa.walk_problems(rows))
        self.assertIn("test_this_one_does_not_exist", joined)
        self.assertIn("没有", joined)

    def test_gibberish_evidence_is_caught(self):
        rows = [list(r) for r in self.rows]
        rows[4][3] = "看过了，没问题"
        self.assertIn("看不懂", "\n".join(check_qa.walk_problems(rows)))

    def test_checker_may_not_fill_the_users_column(self):
        """"你的结果"被填成"通过"必须红——那一列是用户的验收，不是我的。"""
        rows = [list(r) for r in self.rows]
        rows[0][4] = "通过"
        joined = "\n".join(check_qa.walk_problems(rows))
        self.assertIn("被填成了", joined)
        self.assertIn("不许代填", joined)

    def test_missing_evidence_is_caught(self):
        rows = [list(r) for r in self.rows]
        rows[9][3] = ""
        self.assertIn("没有自动证据说明", "\n".join(check_qa.walk_problems(rows)))


if __name__ == "__main__":
    unittest.main()
