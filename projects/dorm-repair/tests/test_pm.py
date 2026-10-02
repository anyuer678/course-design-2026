"""tests/test_pm.py —— 台账与管理文档的核对必须可失败（B22）。

这一层防的不是代码 bug，是**管理文档慢慢变成假话**：数字抄在正文里、风险登记不全、
复盘漏条目——这些都不会让任何测试变红。所以这里的每条断言都是"把某处改坏，看它红不红"，
而且全部喂**内存里的坏副本**，不去改工作树里的文档（改了工作树就等于我在给自己造红）。

出处：`tools/project_ledger.py` 的 `facts()`/`refresh_text()`、`checks/check_pm.py` 的三个文档级函数。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks import check_pm                              # noqa: E402
from tools import project_ledger as L                    # noqa: E402


class Ledger(unittest.TestCase):
    def test_current_tree_is_consistent(self):
        problems, facts = check_pm.check()
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertEqual(facts["pitfalls"], facts["pitfall_max"], "条数应等于最大编号（无重号）")
        self.assertEqual(facts["pitfall_gaps"], 0)

    def test_marker_must_match_the_computed_value(self):
        """值对不上就要点名"写 X 现算 Y"。走真实核对器（临时文件），不复现解析逻辑。"""
        real = L.facts()["aq_open"]
        joined = "\n".join(_markers_in_text(f"未决的有 `L:aq_open={real + 3}` 条"))
        self.assertIn(f"写 L:aq_open={real + 3}", joined)
        self.assertIn(f"台账现算 {real}", joined)

    def test_unknown_key_is_refused(self):
        key = "made_up_metric"
        self.assertIn(key, "\n".join(_markers_in_text(f"L:{key}=1")))

    def test_refresh_rewrites_only_wrong_values(self):
        facts = L.public(L.facts())
        text = (f"a L:pitfalls={facts['pitfalls']} b L:aq_open={facts['aq_open'] + 3} "
                f"c L:made_up=7")
        fresh, n = L.refresh_text(text, facts)
        self.assertEqual(n, 1, "只应改动对不上的那一个")
        self.assertIn(f"L:aq_open={facts['aq_open']}", fresh)
        self.assertIn(f"L:pitfalls={facts['pitfalls']}", fresh)
        self.assertIn("L:made_up=7", fresh, "未知键不许被悄悄改掉——它该由 markers_in 报错")
        again, n2 = L.refresh_text(fresh, facts)
        self.assertEqual(n2, 0, "刷新必须幂等")

    def test_ledger_self_inconsistency_is_reported(self):
        f = L.facts()
        f["gate_layers"] += 1
        self.assertIn("层 ≠ 流水线", "\n".join(L.problems(f)))
        f2 = L.facts()
        f2["aq_open"] += 1
        self.assertIn("待决问题的已裁决/未决数目对不上总数", "\n".join(L.problems(f2)))


class RiskRegister(unittest.TestCase):
    def setUp(self):
        self.facts = L.facts()
        self.text = Path("docs/14-risk-register.md").read_text(encoding="utf-8")

    def test_every_open_aq_is_registered(self):
        for qid in self.facts["_open_aq_ids"]:
            with self.subTest(aq=qid):
                self.assertIn(f"| {qid} |", self.text)

    def test_dropping_a_row_is_caught(self):
        broken = "\n".join(l for l in self.text.splitlines() if not l.startswith("| AQ-06 |"))
        joined = "\n".join(check_pm.risk_problems(self.facts, broken))
        self.assertIn("AQ-06 没有登记进风险登记册", joined)

    def test_listing_a_ruled_question_as_open_is_caught(self):
        ruled = self.facts["_ruled_aq_ids"][0]
        broken = self.text.replace("| AQ-01 |", f"| {ruled} |", 1)
        joined = "\n".join(check_pm.risk_problems(self.facts, broken))
        self.assertIn(f"{ruled} 已裁决", joined)

    def test_missing_section_is_caught(self):
        joined = "\n".join(check_pm.risk_problems(self.facts, "没有小节的文档"))
        self.assertIn("找不到『1. 需求风险』小节", joined)


class Retrospective(unittest.TestCase):
    def setUp(self):
        self.facts = L.facts()
        self.text = Path("docs/15-retrospective.md").read_text(encoding="utf-8")

    def test_partition_covers_every_pitfall(self):
        self.assertEqual(check_pm.retrospective_problems(self.facts, self.text), [])

    def test_dropping_one_number_is_caught(self):
        broken = self.text.replace(", 12, 19,", ", 19,", 1)
        joined = "\n".join(check_pm.retrospective_problems(self.facts, broken))
        self.assertIn("复盘漏了", joined)

    def test_duplicate_number_is_caught(self):
        """把第二类的第一个编号也塞进第一类 → 分类不再是划分。
        从表里现取，不写死数字：上一版写死了"12 | 1, 8, 11, 12,"，B22 一补分类这两条探针就自己失效了
        ——这正好说明"探针依赖具体数字"和"文档依赖手抄数字"是同一个毛病。"""
        rows = re.findall(r"^\| [一二三] · [^|]*\| (\d+) \| ([^|]+)\|$", self.text, re.M)
        self.assertGreaterEqual(len(rows), 2, "前提：分类表至少两类")
        first_claim, first_nums = rows[0][0], rows[0][1].strip()
        borrowed = re.findall(r"\d+", rows[1][1])[0]
        broken = self.text.replace(f"| {first_claim} | {first_nums} |",
                              f"| {int(first_claim) + 1} | {first_nums}, {borrowed} |", 1)
        joined = "\n".join(check_pm.retrospective_problems(self.facts, broken))
        self.assertIn("重号", joined)
        self.assertIn(borrowed, joined)

    def test_claimed_count_must_match_the_list(self):
        """条数写少一个（编号列表没变）→ 必须报"实际列出几个"。同样不写死数字。"""
        rows = re.findall(r"^\| ([一二三]) · [^|]*\| (\d+) \| ([^|]+)\|$", self.text, re.M)
        name, claim, nums = rows[0]
        nums = nums.strip()
        real = len(re.findall(r"\d+", nums))
        broken = self.text.replace(f"| {claim} | {nums} |", f"| {real - 1} | {nums} |", 1)
        joined = "\n".join(check_pm.retrospective_problems(self.facts, broken))
        self.assertIn(f"实际列出 {real} 个编号", joined)


class IndicatorTable(unittest.TestCase):
    def test_every_ledger_key_is_cited(self):
        facts = L.facts()
        self.assertEqual(check_pm.indicator_problems(facts), [],
                         "docs/13 第 8 节必须引用台账每个键，没人读的键就该删")

    def test_dropping_a_row_is_caught(self):
        text = Path("docs/13-project-plan.md").read_text(encoding="utf-8")
        # `verdict_cells` 在 docs/13 出现两处（指标表 + 第 4 节正文），
        # 核对器看的是"整篇有没有引用"，所以要全删才算没人读——上一版我只删了表格行。
        broken = "\n".join(l for l in text.splitlines() if "verdict_cells" not in l)
        joined = "\n".join(check_pm.indicator_problems(L.facts(), broken))
        self.assertIn("verdict_cells 没有被 docs/13 第 8 节引用", joined)


def _markers_in_text(text: str) -> list:
    """把一段文本写到临时文件里再走真实核对器——不复现解析逻辑，避免第二份实现。

    只把**文档**写歪，不去改 `facts()` 的返回值：改现算值等于在测试里造假现场，
    报出来的差异就不再是真实差异了（这条是我上一版写错时踩到的）。
    """
    import tempfile
    with tempfile.TemporaryDirectory(prefix="b22-") as tmp:
        path = Path(tmp) / "docs" / "14-risk-register.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return L.markers_in(path, L.facts())


if __name__ == "__main__":
    unittest.main()
