"""tests/test_triage.py —— 分诊规则必须能被**真实失败文本**验，不许喂假日志（B21）。

本轮立的规矩是"每条规则都要有真实样本"。整条链路上 15 个样本的完整验证在
`python tools/triage.py --selftest`（它真跑一遍变异自检台，约 10 秒，所以不放进 pytest）。
这里放的是**便宜但同样真实**的那一批：每段文本都由生产代码自己打印出来
（`check_docs` / `check_arch` / `export_gate` / `java_build` / `mutation_check` 的纯函数或守卫），
我没有手写任何一条"看起来像错误输出"的句子——那种字符串正是 B19 之后要避免的东西。

`behavior-regression` 是**兜底类**，它没有"专属消息"，所以这里只能验它的结构性质
（不命中任何特征时必须落到最后一类）；它的真实样本是 `prototype-overdue-sort`
那条变异产生的 unittest 失败输出，由 --selftest 覆盖。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks import check_arch, check_docs              # noqa: E402
from spec import workorder as W                        # noqa: E402
from tools import export_gate, mutation_check, triage  # noqa: E402

RULES = triage.load_rules()


class RealMessages(unittest.TestCase):
    def test_doc_model_divergence_from_check_docs(self):
        """把文档侧的宽限期改成 24、模型仍是 168 → 核对器自己打出来的那句话。"""
        data = {"params": {"ACCEPTANCE_GRACE_HOURS": 24}}
        message = check_docs.param_problems(data, W)[0]
        self.assertIn("：文档", message)
        self.assertEqual(triage.classify(message, RULES)["category"], "doc-model-divergence")

    def test_artifact_stale_from_matrix_generator(self):
        """追踪矩阵是生成物：改一份现算数据，报的就是那句"已过期"。"""
        problems, data = check_docs.check()
        self.assertEqual(problems, [], "前提：工作树现在是一致的")
        first = sorted(data["frs"])[0]
        row = list(data["frs"][first])
        row[1] = row[1] + "（改了名字没重生成矩阵）"
        data["frs"][first] = row
        message = check_docs.matrix_problems(data)[0]
        self.assertIn("已过期", message)
        self.assertEqual(triage.classify(message, RULES)["category"], "artifact-stale")

    def test_architecture_violation_from_java_edge_checker(self):
        declared = {"domain": [], "contract": [], "infra": [], "app": [], "web": [], "config": []}
        measured = {"domain": {"org.springframework.jdbc.core.JdbcTemplate"},
                    "contract": set(), "infra": set(), "app": set(), "web": set(), "config": set()}
        problems = check_arch.java_edge_problems(declared, measured)
        joined = "\n".join(problems)
        self.assertIn("依赖越界", joined)
        self.assertEqual(triage.classify(joined, RULES)["category"], "architecture-violation")

    def test_policy_tampering_from_gate_exporter(self):
        data = export_gate.build()
        for row in data["layers"]:
            if row["id"] == "mutation":
                row["blocking"] = False
        message = "\n".join(export_gate.problems(data))
        self.assertIn("被降级成 advisory", message)
        self.assertEqual(triage.classify(message, RULES)["category"], "policy-tampering")

    def test_toolchain_from_java_build_guards(self):
        """文本由 `java_build.main()` 自己打印（只 stub 掉 mvn 这个外部边界）。"""
        ok, text = mutation_check.inline_probe()
        self.assertTrue(ok, text)
        result = triage.classify(text, RULES)
        self.assertEqual(result["category"], "toolchain", text)
        self.assertIn(result["matched"], ("BUILD SUCCESS", "找不到 Maven"))

    def test_harness_broken_from_anchor_guard(self):
        with tempfile.TemporaryDirectory(prefix="b21-") as tmp:
            copy = Path(tmp) / "tree"
            mutation_check._copy_tree(copy)
            bogus = dict(mutation_check.MUTATIONS[0], find="这段文本早就被重构掉了-B21")
            message = ""
            try:
                mutation_check._apply(copy, bogus)
                self.fail("锚点失效应抛 RuntimeError")
            except RuntimeError as exc:
                message = str(exc)
        self.assertIn("变异锚点命中 0 次", message)
        self.assertEqual(triage.classify(message, RULES)["category"], "harness-broken", message)


class Ordering(unittest.TestCase):
    def test_first_matching_rule_wins(self):
        """同一段文本既能算"过期"又能算"文档与模型不一致"时，更具体的那条必须在前。"""
        text = "文档一致性检查发现 1 处问题：\n  - traceability.csv 与文档不一致，已过期"
        self.assertEqual(triage.classify(text, RULES)["category"], "artifact-stale")

    def test_unmatched_text_falls_back_to_the_last_category(self):
        result = triage.classify("AssertionError: 期望 5 实际 4", RULES)
        self.assertEqual(result["category"], export_gate.FALLBACK)
        self.assertIsNone(result["matched"], "兜底不该报告命中了哪个特征")

    def test_rules_come_from_the_contract_not_from_code(self):
        """规则如果硬编码在代码里，文档那张表就成了装饰——所以两边必须同源。"""
        self.assertEqual([rule["category"] for rule in RULES],
                         [rule["category"] for rule in export_gate.build()["triage"]])


if __name__ == "__main__":
    unittest.main()
