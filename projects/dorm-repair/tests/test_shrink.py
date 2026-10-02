"""tests/test_shrink.py —— 收缩器的测试（B20）。

三条纪律写在这里：
1. 断言的期望值**来自实测**（本文件里那些长度是 `python tools/shrink.py` 打出来的），
   不是"我以为应该是几"。
2. 每个度量都要能被证伪：`is_one_minimal` 对冗余序列必须返回 False，
   `ddmin` 对不满足谓词的输入必须报错。
3. 收缩出来的见证不许逃出需求：每一步都得是 SRS 第 3 节转换表里的合法转换。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec import workorder as W                       # noqa: E402
from tools import shrink as S                         # noqa: E402


class TestReplay(unittest.TestCase):
    def test_replay_records_both_sides(self):
        """接受的记 `->状态`，被拒的记 `!错误码`——收缩要看的就是这两类信息。"""
        seq = [("STUDENT", "stu-1", "submit"), ("WORKER", "w-1", "accept")]
        trace = S.replay(seq)
        self.assertEqual(trace.codes[0], "->SUBMITTED")
        self.assertEqual(trace.codes[1], "!NO_SUCH_TRANSITION", "没派单就不能接单")
        self.assertEqual(len(trace.ok_steps), 1)
        self.assertEqual(trace.final.state, "SUBMITTED")

    def test_final_state_survives_rejected_steps(self):
        seq = [("STUDENT", "stu-1", "submit"), ("ADMIN", "adm-1", "force_close")]
        self.assertEqual(S.replay(seq).final.state, "SUBMITTED")


class TestMinimality(unittest.TestCase):
    def test_witnesses_are_as_short_as_brute_force(self):
        """出处：`python tools/shrink.py` 的实测表——七个状态 ddmin 与 BFS 全等。
        如果哪天实现或字母表改动导致二者分叉，这里会红，而那正是我要看的信号。"""
        data = S.find_witnesses()
        for state, row in data.items():
            with self.subTest(state=state):
                self.assertTrue(row["reachable"], f"{state} 竟然不可达，说明模型退化")
                self.assertTrue(row["one_minimal"], f"{state}: 收缩结果还能再删，ddmin 失职")
                self.assertTrue(row["matched_optimum"],
                                f"{state}: ddmin={row['ddmin_len']} 而全局最短={row['bfs_len']}")

    def test_measured_lengths_are_the_documented_ones(self):
        """这些数字写死是为了：**文档里那张表如果与实现分叉，测试会指着两边说不清**。"""
        data = S.find_witnesses()
        expected = {"DRAFT": 0, "SUBMITTED": 1, "ASSIGNED": 2, "IN_PROGRESS": 3,
                    "RESOLVED": 4, "CLOSED": 5, "CANCELLED": 1}
        self.assertEqual({k: v["bfs_len"] for k, v in data.items()}, expected)

    def test_empty_sequence_is_tried_before_any_deletion(self):
        """"空序列也单独试一次"这句话必须有条断言撑着，不能只写在实现注释里。

        出处：`tools/shrink.py` 的实测表——DRAFT 的 ddmin/BFS 都是 **0**（新草稿本来就停在
        DRAFT，空序列就满足谓词）。第一版 ddmin 的 while 在长度 1 就退出、又不回头试空，
        于是返回 1 步序列并自称最小；实测那一栏是 `单步不可删=False`。

        用的种子是 `[ADMIN/adm-1/escalate]`：这一步在 DRAFT 上本来就被拒，走完仍停在 DRAFT，
        所以谓词成立而**真正最短是 0 步**——正是"能删到空"的那个形状。
        下面两组反向断言保证这条捷径没被放宽：只有非空才满足的谓词，两个函数都得返回 1 步。
        """
        reaches_draft = S.reaches("DRAFT")
        self.assertTrue(reaches_draft(()), "前提：空序列确实停在 DRAFT")
        self.assertEqual(S.ddmin([("ADMIN", "adm-1", "escalate")], reaches_draft), (),
                         "ddmin 必须回头试删到空，不能停在 1 就宣布最小")
        self.assertEqual(S.shortest_by_bfs(reaches_draft), (), "BFS 必须把深度 0 也算一次")
        reaches_submitted = S.reaches("SUBMITTED")
        self.assertFalse(reaches_submitted(()))
        self.assertEqual(S.ddmin([("STUDENT", "stu-1", "submit")], reaches_submitted),
                         (("STUDENT", "stu-1", "submit"),))
        self.assertEqual(S.shortest_by_bfs(reaches_submitted),
                         (("STUDENT", "stu-1", "submit"),))

    def test_redundant_seed_is_not_one_minimal(self):
        """反向：没收缩过的冗余序列必须被 `is_one_minimal` 判 False，否则它是个摆设。"""
        padded = list([("WORKER", "w-1", "resolve"), ("STUDENT", "stu-1", "submit"),
                       ("ADMIN", "adm-1", "escalate")])
        self.assertTrue(S.reaches("SUBMITTED")(padded), "前提：这条冗余序列确实到达 SUBMITTED")
        self.assertFalse(S.is_one_minimal(padded, S.reaches("SUBMITTED")))

    def test_ddmin_refuses_a_sequence_that_does_not_qualify(self):
        with self.assertRaises(ValueError):
            S.ddmin([("WORKER", "w-1", "resolve")], S.reaches("CLOSED"))


class TestWitnessesStayInsideTheSpec(unittest.TestCase):
    def test_every_witness_step_is_a_row_in_the_transition_table(self):
        """收缩器只能删步骤，不能凭空发明步骤。
        出处：docs/02-srs.md 第 3 节 + 第 5 节权限矩阵。"""
        for state, row in S.find_witnesses().items():
            for step in row["witness"]:
                role, actor, action = step.split("/")
                legal = [t for t in W.TRANSITIONS if t.action.value == action]
                with self.subTest(state=state, step=step):
                    self.assertTrue(legal, f"{action} 根本不在转换表里")

    def test_closed_witness_follows_the_real_lifecycle(self):
        w = S.find_witnesses()["CLOSED"]["witness"]
        self.assertEqual([x.split("/")[2] for x in w],
                         ["submit", "assign", "accept", "resolve", "confirm"])
        self.assertTrue(all(x.startswith(("STUDENT/", "ADMIN/", "WORKER/")) for x in w))


class TestDeterminism(unittest.TestCase):
    def test_two_runs_agree(self):
        """没有随机源就必须完全可复现——流水线会拿这个数当基线。"""
        self.assertEqual(S.find_witnesses(), S.find_witnesses())


if __name__ == "__main__":
    unittest.main()
