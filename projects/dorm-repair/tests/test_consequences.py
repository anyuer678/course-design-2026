"""tests/test_consequences.py —— 后果测量的测试（B20）。

这类测试最容易自欺：跑出一个数、写死它、以后永远绿。
所以每条断言都配一个"它凭什么会红"的问题，并至少有一条**响应性测试**：
改窄 SLA 表，逾期率必须跟着变——否则测的就不是那件事。

数字出处：`python tools/consequences.py` 的实测输出（2026-10-01）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec import workorder as W                        # noqa: E402
from tools import consequences as C                    # noqa: E402


class TestAq10Loop(unittest.TestCase):
    """AQ-10：推诿循环的上界。今天没有上界，所以它必须"能测出来"。"""

    @classmethod
    def setUpClass(cls):
        cls.data = C.measure()["aq10"]

    def test_shortest_loop_exists_and_qualifies(self):
        loop = self.data["shortest_loop"]
        self.assertEqual(6, self.data["loop_len"], f"最短循环实测 6 步，实际 {loop}")
        steps = [tuple(x.split("/")) for x in loop]
        self.assertTrue(C._loop_predicate(steps), "收缩出来的见证必须真的满足谓词")

    def test_sla_never_moves_while_work_pingpongs(self):
        """时限起算点与到期时刻全程不动——这就是 AQ-02 不重置 + AQ-10 无上界的组合后果。"""
        rounds = self.data["after_rounds"]
        due = {rounds[k]["sla_due_at"] for k in ("1", "3", "6")}
        self.assertEqual({87400.0}, due, "NORMAL 从 1000 起算：1000 + 24×3600 = 87400")
        self.assertTrue(self.data["sla_frozen"])

    def test_history_grows_but_nothing_is_flagged(self):
        lens = self.data["history_grows"]
        self.assertEqual([6, 12, 21], lens, "留痕每轮 +3：escalate/assign/accept")
        self.assertEqual([], self.data["any_rejection"],
                         "循环里没有任何一步被拒——所以系统不会自动发现这事")

    def test_loop_can_be_extended_further(self):
        """「无上界」要说得出证据：再多绕几圈仍然合法，且状态回到 IN_PROGRESS。"""
        row = C.loop_repeated(10)
        self.assertEqual("IN_PROGRESS", row["state"])
        self.assertEqual(3 + 3 * 10, row["history_len"])


class TestAq11PriorityInflation(unittest.TestCase):
    """AQ-11：优先级自选 + 无人能降级的后果。**参数是我拟的假设**。"""

    @classmethod
    def setUpClass(cls):
        cls.grid = C.measure()["aq11"]["grid"]

    def test_within_a_day_only_the_inflated_case_breaches(self):
        tight = self.grid["紧·一天"]
        self.assertEqual(0.0, tight["all_normal"]["overdue_rate"])
        self.assertGreater(tight["all_urgent"]["overdue_rate"], 0.8)
        self.assertEqual(20, tight["all_urgent"]["overdue"], "实测 24 张里 20 张逾期")

    def test_the_zero_is_a_horizon_artifact_not_a_clean_bill(self):
        """同一负载拉长到 168 张，NORMAL 也开始大片逾期——所以"0%"只是窗口不够长。
        这条测试存在的意义就是阻止我把上一段的 0% 写成结论。"""
        week = self.grid["紧·一周"]
        self.assertGreater(week["all_normal"]["overdue_rate"], 0.4)
        self.assertGreater(week["all_urgent"]["overdue_rate"], week["all_normal"]["overdue_rate"])

    def test_ordering_holds_across_every_setting(self):
        for name, row in self.grid.items():
            with self.subTest(setting=name):
                self.assertLessEqual(row["all_normal"]["overdue_rate"],
                                     row["assumed_mix"]["overdue_rate"])
                self.assertLessEqual(row["assumed_mix"]["overdue_rate"],
                                     row["all_urgent"]["overdue_rate"])

    def test_measurement_responds_to_the_thing_it_claims_to_measure(self):
        """响应性：把 URGENT 的时限从 2 小时放宽到 24 小时，全 urgent 的逾期率必须掉下来。
        不掉，就说明我测的根本不是 SLA 的后果。"""
        original = dict(W.SLA_HOURS)
        try:
            W.SLA_HOURS[W.Priority.URGENT] = 24
            widened = C.priority_inflation({"URGENT": 1.0}, arrival_min=45, service_min=60,
                                           total=24)
        finally:
            W.SLA_HOURS.clear()
            W.SLA_HOURS.update(original)
        self.assertEqual(0.0, widened["overdue_rate"], f"放宽到 24h 后仍逾期说明模型没在响应：{widened}")
        self.assertGreater(self.grid["紧·一天"]["all_urgent"]["overdue_rate"], 0.8,
                           "对照：基线仍然是紧的")

    def test_interleaving_is_what_kills_the_artifact(self):
        """占比 10% 的 URGENT 若被排在队首，逾期会被排成 0%。穿插之后必须不为 0。"""
        slots = C._interleaved({"URGENT": 0.1, "NORMAL": 0.9}, 24)
        self.assertEqual(24, len(slots))
        self.assertGreater(slots.index("URGENT"), 0, "URGENT 不该全挤在最前面")
        self.assertEqual(2, slots.count("URGENT"))

    def test_assumptions_are_declared_in_the_output(self):
        """数字必须自带"这是假设"的标签，否则复制到汇报里就变成事实了。"""
        data = C.measure()["aq11"]
        self.assertIn("AI 拟的假设", data["assumptions"]["source"])


class TestDeterminism(unittest.TestCase):
    def test_two_runs_are_identical(self):
        """没有随机源：不同跑必须逐字段相同，否则流水线不能拿它当基线。"""
        self.assertEqual(C.measure(), C.measure())


if __name__ == "__main__":
    unittest.main()
