"""tests/test_walkthrough_pack.py —— B16 backlog ① 的自测：走查期望值生成器。

三类：
1. **重放的自测**：20 步对齐、规范值逐项钉住（这些值就是 docs/07 走查时要对的东西）、
   两次重放逐字节一致、两列留空不许被代填；
2. **docs/07 交叉核对的自测**：真文档过、四种改坏各红在步号上（数字/单号/删行/旧口径）、
   与 check_qa 的解析器结果一致（同一份表两处解析不许漂移）；
3. **生成物新鲜度的自测**：docs/16 与现算一致；喂旧文本即红。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from checks import check_docs                          # noqa: E402
from checks import check_qa                            # noqa: E402

import walkthrough_pack as wp                          # noqa: E402

STEPS = None


def setUpModule():
    global STEPS
    STEPS = wp.replay()


def facts(no: int) -> dict:
    return next(s.facts for s in STEPS if s.no == no)


class TestReplay(unittest.TestCase):
    def test_twenty_steps_aligned_with_walkthrough(self):
        self.assertEqual([s.no for s in STEPS], list(range(1, 21)))
        for s in STEPS:
            self.assertTrue(s.inputs, f"第 {s.no} 步没有口径")
            self.assertTrue(s.expect, f"第 {s.no} 步没有现算期望")

    def test_canonical_values_pinned(self):
        """规范序列的机器值逐项钉住——种子/计数器/规则一改，这里先红。"""
        pin = {
            1: dict(count=3, ids=["R001", "R002", "R005"]),
            2: dict(count=3, ids=["R003", "R001", "R002"]),
            3: dict(count=5, codes=["ROOM_FORMAT", "CATEGORY_UNKNOWN", "PRIORITY_UNKNOWN",
                                    "DESCRIPTION_LENGTH", "CONTACT_FORMAT"]),
            4: dict(id="R008", state="DRAFT", room="A01-101"),
            5: dict(delta=86400.0, state="SUBMITTED"),
            6: dict(id="R009", duplicate="R002"),
            7: dict(refused="ASSIGNEE_REQUIRED", state="ASSIGNED", id="R009", first_row="R003"),
            8: dict(refused="REASON_REQUIRED", state="SUBMITTED", id="R009"),
            9: dict(state="IN_PROGRESS", detail_status=404, hard_code="NO_SUCH_TRANSITION"),
            10: dict(refused="NOTE_REQUIRED", state="RESOLVED"),
            11: dict(refused="REASON_REQUIRED", final="CLOSED", history_len=7,
                     assignee_kept="w-2"),
            12: dict(status=404, error="看不到这张单：R003"),
            13: dict(code="ACCEPTANCE_NOT_MATURE"),
            14: dict(state="CLOSED", attemptable=[]),
            15: dict(count=2, ids=["R008", "R009"], closed_count=1, closed_ids=["R006"],
                     empty_count=0, stu1_count=0),
            16: dict(count=1, ids=["R003"], overdue=True),
        }
        for no, expected in pin.items():
            with self.subTest(step=no):
                self.assertEqual(facts(no), expected)

    def test_manual_steps_are_marked_and_explained(self):
        for no in (17, 18, 19):
            self.assertTrue(facts(no).get("manual"), f"第 {no} 步应标为只能人工")
            self.assertTrue(any("只能人工" in e for e in
                                next(s.expect for s in STEPS if s.no == no)))

    def test_meta_labels_come_from_sla_table(self):
        labels = facts(20)["labels"]
        self.assertEqual(labels["URGENT"], "URGENT（2 小时内响应）")
        self.assertEqual(labels["LOW"], "LOW（72 小时内响应）")

    def test_replay_is_deterministic(self):
        again = wp.replay()
        self.assertEqual(wp.render(again), wp.render(STEPS))

    def test_result_columns_stay_blank(self):
        """「你的实际 / 一致？」两列是留给你填的——生成器不许代填。"""
        rendered = wp.render(STEPS)
        found, bad = check_docs.tables_in(rendered)
        self.assertEqual(bad, [])
        tables = [rows for head, rows in found if head[0] == "#"]
        self.assertEqual(len(tables), 1, "对照表应该只有一张")
        rows = tables[0]
        self.assertEqual(len(rows), 20)
        for row in rows:
            with self.subTest(step=row[0]):
                self.assertEqual(len(row), 5)
                self.assertEqual(row[3], "", "『你的实际』列被代填了")
                self.assertEqual(row[4], "", "『一致？』列被代填了")


class TestDocs07Claims(unittest.TestCase):
    def real_rows(self):
        return wp.rows_from(wp.WALK.read_text(encoding="utf-8"))

    def test_real_walkthrough_passes(self):
        rows, bad = self.real_rows()
        self.assertEqual(bad, [])
        self.assertEqual(wp.claims_problems(rows, STEPS), [])

    def test_pack_parser_agrees_with_check_qa(self):
        """同一张表两处解析必须一致——不一致就得先修解析，别急着信任何一边。"""
        rows, _ = self.real_rows()
        qa_rows, qa_bad = check_qa.walk_rows()
        self.assertEqual(qa_bad, [])
        self.assertEqual(rows, qa_rows)

    def _tampered(self, old: str, new: str):
        text = wp.WALK.read_text(encoding="utf-8")
        self.assertIn(old, text, f"改坏用的锚文本不在 docs/07 里了：{old!r}")
        rows, bad = wp.rows_from(text.replace(old, new))
        self.assertEqual(bad, [])
        return wp.claims_problems(rows, STEPS)

    def test_wrong_count_turns_red_on_step_1(self):
        problems = self._tampered("显示 3 张单", "显示 4 张单")
        self.assertTrue(any(p.startswith("第 1 步") and "4" in p and "3" in p
                            for p in problems), problems)

    def test_step8_back_to_r006_turns_red(self):
        """第 8 步指回 R006 就是那条断链的复发——单号不符 + 缺位断言两处都要说。"""
        problems = self._tampered("（`R009`）点\"退回公共池\"", "（`R006`）点\"退回公共池\"")
        self.assertTrue(any(p.startswith("第 8 步") for p in problems), problems)
        self.assertTrue(any("R006" in p for p in problems), problems)

    def test_old_grace_wording_turns_red_on_step_13(self):
        problems = self._tampered(
            "**AQ-03 已裁决**为 168 小时宽限期",
            "**注意：阈值未裁决（AQ-03），现在任何时刻都能关**")
        self.assertTrue(any(p.startswith("第 13 步") for p in problems), problems)

    def test_missing_step_turns_red(self):
        text = wp.WALK.read_text(encoding="utf-8")
        rows, bad = wp.rows_from("\n".join(
            line for line in text.splitlines() if not line.startswith("| 12 |")))
        self.assertEqual(bad, [])
        problems = wp.claims_problems(rows, STEPS)
        self.assertTrue(any("20 步" in p for p in problems), problems)

    def test_claims_cover_every_step(self):
        covered = {step for step, _p, _v in wp.CLAIMS}
        self.assertEqual(covered, set(range(1, 21)),
                         "每一步至少一条窄断言——否则那一步就脱管了")

    def test_result_column_still_unverified(self):
        rows, _ = self.real_rows()
        for row in rows:
            with self.subTest(step=row[0]):
                self.assertIn(row[4].strip(), {"未验证", ""},
                              "走了检查器保护的『你的结果』列")


class TestFreshness(unittest.TestCase):
    def test_docs16_is_fresh(self):
        self.assertTrue(wp.OUT.is_file(), "docs/16 不存在——跑 --write")
        self.assertEqual(wp.freshness_problems(wp.render(STEPS)), [])

    def test_stale_text_turns_red(self):
        problems = wp.freshness_problems("新内容", "旧内容")
        self.assertTrue(any("过期" in p or "不一致" in p for p in problems), problems)

    def test_same_text_is_fresh(self):
        self.assertEqual(wp.freshness_problems("同样的文本", "同样的文本"), [])

    def test_full_check_passes_on_real_tree(self):
        self.assertEqual(wp.check(), [])


if __name__ == "__main__":
    unittest.main()
