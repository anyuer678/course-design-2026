"""B15 的可执行核对：需求模型的行为 + 文档↔模型一致性。

跑法：

```
python -m unittest discover -s tests -v
pytest tests -q
```

**期望值的出处**（PLAN 第 6 节要求）写在每条测试的注释里：
要么来自 `docs/02-srs.md` 的某张表（我在测试里重新誊一遍），要么是手算并写出算式。
凭印象写的期望值在这几轮里已经反复证明既会误伤实现，也会把真 bug 盖成"预期行为"。
"""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec import workorder as W                        # noqa: E402

STUDENT, WORKER, ADMIN = W.Role.STUDENT, W.Role.WORKER, W.Role.ADMIN

#: 出处：docs/02-srs.md 第 3 节状态转换表（逐行重新誊写，不是从代码里读出来的）
SRS_TRANSITIONS = [
    ("submit", "DRAFT", "SUBMITTED", {"STUDENT"}, ("owner", "valid_fields")),
    ("assign", "SUBMITTED", "ASSIGNED", {"ADMIN"}, ("assignee_required",)),
    ("reassign", "ASSIGNED", "ASSIGNED", {"ADMIN"}, ("assignee_required",)),
    ("return_pool", "ASSIGNED", "SUBMITTED", {"ADMIN"}, ("reason",)),
    ("accept", "ASSIGNED", "IN_PROGRESS", {"WORKER"}, ("assignee",)),
    ("decline", "ASSIGNED", "SUBMITTED", {"WORKER"}, ("assignee",)),
    ("resolve", "IN_PROGRESS", "RESOLVED", {"WORKER"}, ("assignee", "resolution_note")),
    ("confirm", "RESOLVED", "CLOSED", {"STUDENT"}, ("owner",)),
    ("reject_check", "RESOLVED", "IN_PROGRESS", {"STUDENT"}, ("owner", "reason")),
    ("force_close", "RESOLVED", "CLOSED", {"ADMIN"}, ("acceptance_timeout",)),
    ("cancel", "DRAFT", "CANCELLED", {"STUDENT"}, ("owner",)),
    ("cancel", "SUBMITTED", "CANCELLED", {"STUDENT"}, ("owner",)),
    ("cancel", "SUBMITTED", "CANCELLED", {"ADMIN"}, ("reason",)),
    ("cancel", "ASSIGNED", "CANCELLED", {"ADMIN"}, ("reason",)),
    ("escalate", "IN_PROGRESS", "SUBMITTED", {"ADMIN"}, ("reason",)),
]

#: 出处：docs/02-srs.md 第 5 节角色权限矩阵（逐行重新誊写）
SRS_PERMISSIONS = {
    "submit": {"STUDENT"},
    "assign": {"ADMIN"},
    "reassign": {"ADMIN"},
    "return_pool": {"ADMIN"},
    "accept": {"WORKER"},
    "decline": {"WORKER"},
    "resolve": {"WORKER"},
    "confirm": {"STUDENT"},
    "reject_check": {"STUDENT"},
    "force_close": {"ADMIN"},
    "cancel": {"STUDENT", "ADMIN"},
    "escalate": {"ADMIN"},
}

#: 出处：docs/02-srs.md 第 8 节 SLA 表
SRS_SLA = {"LOW": 72, "NORMAL": 24, "HIGH": 8, "URGENT": 2}

#: 出处：docs/02-srs.md 第 6 节可见性矩阵（AQ-12 于 2026-10-01 裁决后新增 RESOLVED 一段）
SRS_VISIBILITY = {"STUDENT": "OWN", "WORKER": "OWN_OR_POOL_OR_RESOLVED", "ADMIN": "ALL"}


def draft(**over):
    """一张合法草稿；字段与 US-01 的样例一致。"""
    base = dict(id="W1", reporter="stu-1", room="A01-101", category="WATER_ELEC",
                priority="NORMAL", description="水管漏水", contact="13800000000",
                created_at=100.0)
    base.update(over)
    return W.Order(**base)


def submitted(now=1000.0):
    return W.apply_transition(draft(), STUDENT, "stu-1", W.Action.SUBMIT, now=now)


def assigned(worker="w-1", now=2000.0):
    return W.apply_transition(submitted(), ADMIN, "adm-1", W.Action.ASSIGN,
                              now=now, assignee=worker)


def resolved(worker="w-1"):
    order = assigned(worker=worker)
    order = W.apply_transition(order, WORKER, worker, W.Action.ACCEPT, now=3000.0)
    return W.apply_transition(order, WORKER, worker, W.Action.RESOLVE, now=4000.0,
                              note="换了垫圈")


class TestCreateAndValidate(unittest.TestCase):
    def test_valid_order_accepts_minimal_fixture(self):
        errors = W.validate_order("A01-101", "WATER_ELEC", "NORMAL", "水管漏水", "13800000000")
        self.assertEqual(errors, [])

    def test_create_order_normalizes_fields(self):
        order = W.create_order(id="W9", reporter=" stu-2 ", room=" b02-210 ",
                               category="NETWORK", priority="HIGH",
                               description="  网络断了  ", contact="13900000001", created_at=5.0)
        self.assertEqual((order.state, order.room, order.description, order.contact,
                          order.reporter), ("DRAFT", "B02-210", "网络断了", "13900000001", "stu-2"))
        self.assertIsNone(order.submitted_at)          # 草稿不起 SLA（BR-08）

    def test_create_order_rejects_and_lists_every_problem(self):
        with self.assertRaises(W.InvalidOrder) as caught:
            W.create_order(id="W9", reporter="stu-1", room="101", category="WIFI",
                           priority="SOMEDAY", description="   ", contact="123",
                           created_at=5.0)
        codes = [(e.field_name, e.code) for e in caught.exception.errors]
        # 出处：SRS 第 9 节的五条规则，一个都不该漏
        self.assertEqual(codes, [("room", "ROOM_FORMAT"), ("category", "CATEGORY_UNKNOWN"),
                                 ("priority", "PRIORITY_UNKNOWN"),
                                 ("description", "DESCRIPTION_LENGTH"),
                                 ("contact", "CONTACT_FORMAT")])

    def test_validation_reports_all_problems_at_once(self):
        errors = W.validate_order("101", "WIFI", "SOMEDAY", "", "123")
        self.assertEqual(len(errors), 5, "只报第一个就等于逼提交者改一处跑一次")
        self.assertTrue(all(e.reason for e in errors))

    def test_room_and_contact_formats_are_the_ones_the_srs_declares(self):
        self.assertEqual(W.validate_order("a01-101", "OTHER", "LOW", "x", "13800000000"), [])
        cases = {"A01-101": True, "A1-101": False, "A01-1001": False, "AA1-101": False,
                 "": False, "A01_101": False}
        for room, ok in cases.items():
            with self.subTest(room=room):
                self.assertEqual(not any(e.code == "ROOM_FORMAT"
                                         for e in W.validate_order(room, "OTHER", "LOW", "x",
                                                                   "13800000000")), ok)
        for contact, ok in {"13800000000": True, "1380000000": False, "23800000000": False,
                            "138000000001": False, "138-0000-0000": False}.items():
            with self.subTest(contact=contact):
                self.assertEqual(not any(e.code == "CONTACT_FORMAT"
                                         for e in W.validate_order("A01-101", "OTHER", "LOW",
                                                                   "x", contact)), ok)

    def test_description_length_boundary(self):
        # 出处：SRS 第 9 节"1..500"，边界两侧都要试
        self.assertEqual(W.validate_order("A01-101", "OTHER", "LOW", "x" * 500,
                                          "13800000000"), [])
        self.assertTrue(any(e.code == "DESCRIPTION_LENGTH"
                            for e in W.validate_order("A01-101", "OTHER", "LOW", "x" * 501,
                                                      "13800000000")))
        self.assertTrue(any(e.code == "DESCRIPTION_LENGTH"
                            for e in W.validate_order("A01-101", "OTHER", "LOW", "   ",
                                                      "13800000000")))


class TestTransitionTable(unittest.TestCase):
    def test_transition_table_matches_srs(self):
        """模型的转换集合必须等于 SRS 第 3 节那张表（测试里重新誊了一遍作为出处）。"""
        got = {(t.action.value, t.source.value, t.target.value,
                frozenset(r.value for r in t.roles), t.preconditions) for t in W.TRANSITIONS}
        expected = {(a, s, d, frozenset(roles), tuple(sorted(p)))
                    for a, s, d, roles, p in SRS_TRANSITIONS}
        self.assertEqual(got, expected)
        self.assertEqual(len(W.TRANSITIONS), len(SRS_TRANSITIONS), "转换行数不能被悄悄增删")

    def test_permission_matrix_matches_srs(self):
        """出处：SRS 第 5 节。模型里"每个动作允许哪些角色"必须与那张表逐格相同。

        这张表和第 3 节的转换表是同一件事的两种说法，检查器还会再比对它们彼此一致——
        需求文档里"两处说法不一样"正是缺陷的高发形态，所以宁可写三遍来互相盯住。
        """
        derived = {a.value: set() for a in W.Action}
        for tr in W.TRANSITIONS:
            derived[tr.action.value] |= {r.value for r in tr.roles}
        self.assertEqual(derived, SRS_PERMISSIONS)
        self.assertEqual(set(SRS_PERMISSIONS), {a.value for a in W.Action},
                         "权限矩阵必须覆盖所有动作，一个都不能漏")
        # 反向也要成立：表里说"不允许"的角色，模型里任何状态都不该给它这个动作
        for action, roles in SRS_PERMISSIONS.items():
            for role in W.Role:
                if role.value in roles:
                    continue
                blocked = all(role not in tr.roles for tr in W.TRANSITIONS
                              if tr.action.value == action)
                self.assertTrue(blocked, f"{role.value} 不该能发起 {action}")

    def test_no_action_is_allowed_from_a_terminal_state(self):
        order = resolved()
        order = W.apply_transition(order, STUDENT, "stu-1", W.Action.CONFIRM, now=5000.0)
        self.assertEqual(order.state, "CLOSED")
        for action in W.Action:
            for role, who in ((STUDENT, "stu-1"), (WORKER, "w-1"), (ADMIN, "adm-1")):
                with self.subTest(action=action.value, role=role.value, state="CLOSED"):
                    with self.assertRaises(W.TransitionError) as caught:
                        W.apply_transition(order, role, who, action, now=6000.0,
                                           assignee="w-1", note="n", reason="r")
                    self.assertEqual(caught.exception.code, "NO_SUCH_TRANSITION",
                                     "终态有任何出边就违反 BR-02")

    def test_terminal_states_have_no_exits(self):
        # 出处：BR-02 与第 3 节的推论——两个终态在表里只作为目标出现
        sources = {t.source.value for t in W.TRANSITIONS}
        self.assertEqual(sources & {"CLOSED", "CANCELLED"}, set())
        targets = {t.target.value for t in W.TRANSITIONS}
        self.assertTrue({"CLOSED", "CANCELLED"} <= targets)

    def test_illegal_transition_leaves_order_unchanged(self):
        order = assigned()
        snapshot = order
        for role, who, action, kwargs in [
            (WORKER, "w-9", W.Action.ACCEPT, {}),                        # 不是本人
            (STUDENT, "stu-2", W.Action.CANCEL, {}),                     # 不是报修人
            (ADMIN, "adm-1", W.Action.RETURN_POOL, {"reason": "  "}),    # 理由空白
            (ADMIN, "adm-1", W.Action.ASSIGN, {"assignee": ""}),         # 没给工号
            (WORKER, "w-1", W.Action.RESOLVE, {"note": ""}),             # 不在 IN_PROGRESS
        ]:
            with self.subTest(action=action.value):
                with self.assertRaises(W.TransitionError):
                    W.apply_transition(order, role, who, action, now=9000.0, **kwargs)
                self.assertEqual(order, snapshot, "被拒绝的调用必须一点都没碰到原工单")

    def test_validation_failure_leaves_state_unchanged(self):
        bad = draft(description="   ")
        with self.assertRaises(W.TransitionError) as caught:
            W.apply_transition(bad, STUDENT, "stu-1", W.Action.SUBMIT, now=1000.0)
        self.assertEqual(caught.exception.code, "INVALID_FIELDS")
        self.assertEqual(bad.state, "DRAFT")
        self.assertEqual(bad.history, ())

    def test_owner_and_assignee_are_checked_in_model_not_caller(self):
        """出处：BR-09 / NFR-02——身份由模型比对，调用方"声称"是本人不算数。"""
        order = resolved()
        with self.assertRaises(W.TransitionError) as caught:
            W.apply_transition(order, STUDENT, "stu-9", W.Action.CONFIRM, now=5000.0)
        self.assertEqual(caught.exception.code, "OWNER")
        with self.assertRaises(W.TransitionError) as caught:
            W.apply_transition(assigned(worker="w-1"), WORKER, "w-2", W.Action.ACCEPT, now=2500.0)
        self.assertEqual(caught.exception.code, "ASSIGNEE")
        # 模型不接受任何"我声称我是报修人"的参数
        params = set(inspect.signature(W.apply_transition).parameters)
        self.assertNotIn("reporter", params)

    def test_assignee_required_blocks_assign(self):
        order = submitted()
        for bad in ("", "   ", None, "w" * 33):
            with self.subTest(assignee=bad):
                with self.assertRaises(W.TransitionError) as caught:
                    W.apply_transition(order, ADMIN, "adm-1", W.Action.ASSIGN,
                                       now=2000.0, assignee=bad)
                self.assertEqual(caught.exception.code, "ASSIGNEE_REQUIRED")

    def test_reassign_keeps_state_and_appends_history(self):
        order = assigned(worker="w-1")
        moved = W.apply_transition(order, ADMIN, "adm-1", W.Action.REASSIGN,
                                   now=2500.0, assignee="w-2")
        self.assertEqual((moved.state, moved.assignee), ("ASSIGNED", "w-2"))
        self.assertEqual(len(moved.history), len(order.history) + 1)
        last = moved.history[-1]
        self.assertEqual((last.source, last.target, last.action), ("ASSIGNED", "ASSIGNED",
                                                                   "reassign"))

    def test_cancel_and_return_pool_need_reason(self):
        order = assigned()
        for action, kwargs in [(W.Action.RETURN_POOL, {}), (W.Action.CANCEL, {"reason": " "}),
                               (W.Action.CANCEL, {})]:
            with self.subTest(action=action.value):
                with self.assertRaises(W.TransitionError) as caught:
                    W.apply_transition(order, ADMIN, "adm-1", action, now=3000.0, **kwargs)
                self.assertEqual(caught.exception.code, "REASON_REQUIRED")
        done = W.apply_transition(order, ADMIN, "adm-1", W.Action.CANCEL, now=3000.0,
                                  reason="误报")
        self.assertEqual((done.state, done.assignee, done.history[-1].reason),
                         ("CANCELLED", "", "误报"))

    def test_student_cannot_cancel_after_assignment(self):
        """出处：UC-06 异常流 1a 与 AQ-09 的收紧。"""
        with self.assertRaises(W.TransitionError) as caught:
            W.apply_transition(assigned(), STUDENT, "stu-1", W.Action.CANCEL, now=3000.0,
                               reason="不想了")
        self.assertEqual(caught.exception.code, "ROLE_NOT_ALLOWED")

    def test_reject_check_keeps_assignee(self):
        order = resolved()
        back = W.apply_transition(order, STUDENT, "stu-1", W.Action.REJECT_CHECK,
                                  now=5000.0, reason="还是漏")
        self.assertEqual((back.state, back.assignee), ("IN_PROGRESS", "w-1"))

    def test_assignee_cleared_when_leaving_assigned(self):
        """出处：SRS 第 12 节数据字典——待派单与终态都不该挂着维修员。"""
        for action, kwargs in [(W.Action.RETURN_POOL, {"reason": "派错"}),
                               (W.Action.DECLINE, {}),
                               (W.Action.CANCEL, {"reason": "不修了"})]:
            order = assigned()
            if action == W.Action.DECLINE:
                result = W.apply_transition(order, WORKER, "w-1", action, now=2500.0, **kwargs)
            else:
                result = W.apply_transition(order, ADMIN, "adm-1", action, now=2500.0, **kwargs)
            with self.subTest(action=action.value):
                self.assertEqual(result.assignee, "")

    def test_closing_clears_the_current_assignee(self):
        """回归：穷举走查抓到 confirm / force_close 走到 CLOSED 却留着 assignee，
        与 SRS 第 12 节数据字典（终态下 assignee 为空）矛盾。谁修过的在历史里，
        `assignee` 是"当前负责人"而不是审计字段。
        """
        by_student = W.apply_transition(resolved(), STUDENT, "stu-1", W.Action.CONFIRM, now=9000.0)
        self.assertEqual((by_student.state, by_student.assignee), ("CLOSED", ""))
        # 手算：resolved() 在 now=4000.0 进入 RESOLVED，宽限 168 小时 = 604800 秒
        # → 到期时刻 4000 + 604800 = 608800.0（出处：SRS 第 8 节 + 这段算式，不是"代码算出来多少就写多少"）
        by_admin = W.apply_transition(resolved(), ADMIN, "adm-1", W.Action.FORCE_CLOSE,
                                      now=608800.0)
        self.assertEqual((by_admin.state, by_admin.assignee), ("CLOSED", ""))
        self.assertEqual(by_admin.history[-1].actor_role, "ADMIN")   # 痕迹仍然记着是谁关的
        self.assertEqual(by_admin.resolved_by, "w-1",                 # BR-11：清空 assignee 但保留处理人
                         '终态清空的是当前负责人，不是谁修的')

    def test_acceptance_grace_is_configurable_and_blocks_force_close(self):
        """AC-24（AQ-03 于 2026-10-01 裁决后从"待验证"转为可执行）。

        出处：SRS 第 8 节手算样例——resolved() 在 now=4000.0 进入 RESOLVED，
        168 小时 = 604800 秒，到期时刻 = 4000 + 604800 = 608800.0。
        这条测试要证明的不是"168 这个数对"，而是**阈值是个参数**：
        换成 1 小时，同一时刻的判定就会翻转。硬编码在实现里的魔法数做不到这件事。
        """
        order = resolved()
        self.assertEqual(order.resolved_at, 4000.0)
        self.assertEqual(W.acceptance_due(order), 608800.0)        # 4000 + 168*3600
        self.assertFalse(W.is_acceptance_stale(order, 608799.9))
        self.assertTrue(W.is_acceptance_stale(order, 608800.0))    # 达到即算，与 is_overdue 同口径
        with self.subTest("未满宽限期：关闭被拒，且工单原封不动"):
            with self.assertRaises(W.TransitionError) as ctx:
                W.apply_transition(order, ADMIN, "adm-1", W.Action.FORCE_CLOSE, now=608799.9)
            self.assertEqual(ctx.exception.code, "ACCEPTANCE_NOT_MATURE")
            self.assertEqual(order.state, "RESOLVED")
            self.assertEqual(len(order.history), 4)
        with self.subTest("阈值改成 1 小时：同一个 now 判定翻转"):
            # 手算：默认 168h → 到期 608800.0，now=8000.0 未到 → 拒；
            #       换成 1h → 到期 4000 + 3600 = 7600.0，now=8000.0 已过 → 放行。
            # 这条断言要证明的是"阈值是参数"，不是"1 小时这个数对"。
            with self.assertRaises(W.TransitionError):
                W.apply_transition(order, ADMIN, "adm-1", W.Action.FORCE_CLOSE, now=8000.0)
            closed = W.apply_transition(order, ADMIN, "adm-1", W.Action.FORCE_CLOSE,
                                        now=8000.0, grace_hours=1)
            self.assertEqual(closed.state, "CLOSED")
            self.assertEqual(closed.assignee, "")
            self.assertEqual(closed.resolved_by, "w-1",                 # BR-11：宽限期只影响能不能关
                             '宽限期改的是时机，不是谁修的')

    def test_grace_hours_default_comes_from_the_model_not_the_caller(self):
        """默认值必须有出处：SRS 第 8 节写的 168 小时，而不是"代码里正好是这个数"。"""
        self.assertEqual(W.ACCEPTANCE_GRACE_HOURS, 168)
        self.assertEqual(W.ACCEPTANCE_GRACE_HOURS * 3600, 604800)       # 7 天
        # 没进过 RESOLVED 的单没有到期时刻；None 意味着"宽限期不适用"，不是"立刻可关"
        self.assertIsNone(W.acceptance_due(submitted()))

    def test_overdue_excludes_resolved_and_terminal(self):
        """出处：SRS 第 8 节——已完工待验收不算逾期，终态也不算。"""
        order = submitted(now=1000.0)                        # NORMAL → 到期 87400.0
        self.assertTrue(W.is_overdue(order, 87400.0))       # 恰好到期算逾期（>=）
        self.assertFalse(W.is_overdue(order, 87399.9))
        self.assertFalse(W.is_overdue(resolved(), 999999.0))
        closed = W.apply_transition(resolved(), STUDENT, "stu-1", W.Action.CONFIRM, now=90000.0)
        self.assertFalse(W.is_overdue(closed, 999999.0))


class TestSla(unittest.TestCase):
    def test_sla_hours_match_srs_table(self):
        self.assertEqual({p.value: h for p, h in W.SLA_HOURS.items()}, SRS_SLA)
        # 手算算式（出处：SRS 第 8 节 + 小学算术），不是"代码算出多少就写多少"
        expected = {  # submitted_at = 1000.0
            "LOW": 1000.0 + 72 * 3600,       # = 260200.0
            "NORMAL": 1000.0 + 24 * 3600,    # = 87400.0
            "HIGH": 1000.0 + 8 * 3600,       # = 29800.0
            "URGENT": 1000.0 + 2 * 3600,     # = 8200.0
        }
        for priority, due in expected.items():
            with self.subTest(priority=priority):
                order = W.apply_transition(draft(priority=priority), STUDENT, "stu-1",
                                           W.Action.SUBMIT, now=1000.0)
                self.assertEqual(order.sla_due_at, due)
                self.assertEqual(order.sla_due_at, 1000.0 + W.SLA_HOURS[W.Priority(priority)] * 3600)

    def test_sla_starts_at_first_submission(self):
        """出处：BR-08——起算点是**首次**进入待派单，不是建单，也不是每次回到公共池。"""
        order = W.apply_transition(draft(created_at=100.0), STUDENT, "stu-1", W.Action.SUBMIT,
                                   now=5000.0)
        self.assertEqual(order.submitted_at, 5000.0)      # 不是 100.0
        self.assertEqual(order.sla_due_at, 5000.0 + 86400)
        order = W.apply_transition(order, ADMIN, "adm-1", W.Action.ASSIGN,
                                   now=6000.0, assignee="w-1")
        back = W.apply_transition(order, ADMIN, "adm-1", W.Action.RETURN_POOL,
                                  now=7000.0, reason="先放放")
        again = W.apply_transition(back, ADMIN, "adm-1", W.Action.ASSIGN, now=8000.0,
                                   assignee="w-2")
        self.assertEqual(again.submitted_at, 5000.0, "退回公共池不能把时限洗回原点")
        self.assertEqual(again.sla_due_at, 91400.0)

    def test_time_is_injected_not_read(self):
        """出处：NFR-05。模型自己读时钟的话，逾期测试就得靠 sleep 或者赌运气。"""
        source = (ROOT / "spec" / "workorder.py").read_text(encoding="utf-8")
        self.assertNotIn("import time", source)
        self.assertNotIn("time.time", source)
        self.assertNotIn("datetime.now", source)
        self.assertNotIn("sleep(", source)


class TestHistory(unittest.TestCase):
    def test_history_is_append_only(self):
        chain = draft()
        steps = [
            (STUDENT, "stu-1", W.Action.SUBMIT, {}),
            (ADMIN, "adm-1", W.Action.ASSIGN, {"assignee": "w-1"}),
            (WORKER, "w-1", W.Action.ACCEPT, {}),
            (WORKER, "w-1", W.Action.RESOLVE, {"note": "好了"}),
            (STUDENT, "stu-1", W.Action.CONFIRM, {}),
        ]
        prefix = ()
        for i, (role, who, action, kwargs) in enumerate(steps, start=1):
            chain = W.apply_transition(chain, role, who, action, now=1000.0 * i, **kwargs)
            self.assertEqual(len(chain.history), i)
            self.assertEqual(chain.history[: len(prefix)], prefix, "旧条目不许被改动")
            prefix = chain.history
        self.assertEqual(chain.state, "CLOSED")

    def test_history_entries_carry_the_five_fields(self):
        """出处：AC-35 与 FR-15——谁、何时、从哪、到哪、理由。"""
        change = assigned().history[-1]
        for name in ("at", "source", "target", "action", "actor_role", "actor_id", "reason"):
            self.assertTrue(hasattr(change, name), name)

    def test_rejected_action_adds_no_history(self):
        order = submitted()
        before = len(order.history)                   # 提交本身已经留了一条痕
        with self.assertRaises(W.TransitionError):
            W.apply_transition(order, WORKER, "w-1", W.Action.ACCEPT, now=2000.0)
        self.assertEqual(len(order.history), before)
        self.assertEqual(order.state, "SUBMITTED")
        self.assertEqual(order.history[0].action, "submit")


class TestVisibility(unittest.TestCase):
    def hand_visible(self, order, role, actor_id):
        """独立誊写自 SRS 第 6 节的散文规则（不是调用被测函数）。"""
        if role == "STUDENT":
            return order.reporter == actor_id
        if role == "WORKER":
            # 出处：SRS 第 6 节 OWN_OR_POOL_OR_RESOLVED（AQ-12）——手写第三遍，不看实现
            return (order.state == "SUBMITTED" or order.assignee == actor_id
                    or order.resolved_by == actor_id)
        return True

    def test_visibility_matrix_matches_srs(self):
        self.assertEqual({r.value: v for r, v in W.ROLE_VISIBILITY.items()}, SRS_VISIBILITY)
        orders = W.sample_orders()
        for role, who, expected in [
            ("STUDENT", "stu-1", ["W01", "W03", "W05", "W07", "W09", "W10", "W12"]),
            ("STUDENT", "stu-2", ["W02", "W04", "W06", "W08", "W11"]),
            ("WORKER", "w-1", ["W03", "W04", "W05", "W07", "W09", "W10", "W12"]),
            ("WORKER", "w-2", ["W03", "W04", "W06", "W08", "W12"]),
            ("ADMIN", "adm-1", [f"W{i:02d}" for i in range(1, 13)]),
        ]:
            got = [o.id for o in orders if W.visible_to(o, W.Role(role), who)]
            with self.subTest(role=role, actor=who):
                self.assertEqual(got, expected)
            self.assertEqual(got, [o.id for o in orders if self.hand_visible(o, role, who)])

    def test_drafts_are_invisible_to_workers(self):
        """出处：第 6 节说明——草稿内容可能连宿舍号都没填对，不该进公共池。"""
        drafts = [o.id for o in W.sample_orders() if o.state == "DRAFT"]
        self.assertTrue(drafts)
        for who in ("w-1", "w-2"):
            seen = [o.id for o in W.sample_orders() if W.visible_to(o, WORKER, who)
                    and o.state == "DRAFT"]
            with self.subTest(worker=who):
                self.assertEqual(seen, [])

    def test_filters_narrow_the_fixture_set(self):
        """出处：04 用户故事 US-11 与样例数据本身（期望集合逐条推得）。"""
        orders = W.sample_orders()
        cases = [
            ({"category": "NETWORK"}, ["W12"]),
            ({"room": "A01-101"}, ["W01", "W12"]),
            ({"room": "a01-101"}, ["W01", "W12"]),                  # 大小写归一
            ({"state": "SUBMITTED"}, ["W03", "W04", "W12"]),
            ({"priority": "URGENT"}, ["W08"]),
            ({"state": "SUBMITTED", "priority": "NORMAL"}, ["W03", "W04", "W12"]),
            ({"state": "SUBMITTED", "category": "NETWORK"}, ["W12"]),
            ({"overdue_only": True, "now": 20000.0}, ["W08"]),
            ({"overdue_only": True, "now": 88000.0},
             ["W03", "W04", "W05", "W06", "W07", "W08"]),
        ]
        for kwargs, expected in cases:
            with self.subTest(**kwargs):
                got = [o.id for o in W.filter_orders(orders, actor_role=ADMIN, **kwargs)]
                self.assertEqual(got, expected)

    def test_visibility_is_applied_before_filters(self):
        """越权泄漏最容易发生在这里：先筛选再收口，别人的草稿就会出现在结果里。"""
        orders = W.sample_orders()
        got = [o.id for o in W.filter_orders(orders, actor_role=STUDENT, actor_id="stu-1",
                                             state="DRAFT")]
        self.assertEqual(got, ["W01"], "stu-1 只能看见自己的草稿，不是所有草稿")

    def test_worker_cannot_see_others_assigned_orders(self):
        orders = W.sample_orders()
        self.assertIn("W05", [o.id for o in W.filter_orders(orders, actor_role=WORKER,
                                                            actor_id="w-1")])
        self.assertNotIn("W05", [o.id for o in W.filter_orders(orders, actor_role=WORKER,
                                                              actor_id="w-2")])


    def test_resolved_history_is_visible_but_inert(self):
        """AC-40（AQ-12 于 2026-10-01 裁决）：看得见 ≠ 点得动。

        出处：SRS 第 6 节 OWN_OR_POOL_OR_RESOLVED + BR-11（`resolved_by` 不参与权限判定）。
        这条测试盯的是最容易写错的那一步——顺手把"我修过"当成"我还能改"，
        那等于让维修员把已关闭的单再拖回流程里。
        """
        order = W.apply_transition(resolved(worker="w-1"), ADMIN, "adm-1",
                                  W.Action.FORCE_CLOSE, now=608800.0)     # 4000 + 604800
        self.assertEqual((order.state, order.assignee, order.resolved_by),
                         ("CLOSED", "", "w-1"))
        self.assertTrue(W.visible_to(order, WORKER, "w-1"), "修过的人应能查到这张历史单")
        self.assertFalse(W.visible_to(order, WORKER, "w-2"), "别人的历史不该出现在我的列表里")
        self.assertEqual(W.attemptable(order, WORKER), (), "终态不该有任何可点动作")
        self.assertEqual(W.attemptable(order, STUDENT), ())
        # 可见性放宽之后，"看得见但无用"必须是真的：重放 resolve 也要被拒
        with self.assertRaises(W.TransitionError) as ctx:
            W.apply_transition(order, WORKER, "w-1", W.Action.RESOLVE, now=700000.0,
                               note="再改一次")
        self.assertEqual(ctx.exception.code, "NO_SUCH_TRANSITION")

    def test_cancelled_orders_have_no_handler(self):
        """出处：第 12 节数据字典——`resolved_by` 只在经过 RESOLVED 时才写入。
        样例里的 W11 从 SUBMITTED 直接取消，所以它不该有处理人。"""
        cancelled = [o for o in W.sample_orders() if o.id == "W11"]
        self.assertEqual(cancelled[0].resolved_by, "")
        never_resolved = W.apply_transition(submitted(), ADMIN, "adm-1", W.Action.CANCEL,
                                           now=2000.0, reason="误报")
        self.assertEqual(never_resolved.resolved_by, "")


class TestDuplicate(unittest.TestCase):
    def test_duplicate_open_order_detected(self):
        """出处：BR-07——同宿舍 + 同分类 + 未进终态。"""
        orders = W.sample_orders()
        hit = W.find_duplicate(orders, "A01-101", W.Category.WATER_ELEC)
        self.assertEqual(hit.id, "W01")                       # W01 是 DRAFT，未完成
        self.assertIsNone(W.find_duplicate(orders, "A01-101", W.Category.FURNITURE))
        self.assertIsNotNone(W.find_duplicate(orders, "a01-101", W.Category.WATER_ELEC),
                            "宿舍编号大小写不该影响重复判定")

    def test_closed_order_does_not_block_a_new_report(self):
        order = W.Order(id="W50", reporter="stu-1", room="B02-201", category="NETWORK",
                        priority="NORMAL", description="网断了", contact="13800000000",
                        state="CLOSED", submitted_at=1.0, sla_due_at=100.0)
        self.assertIsNone(W.find_duplicate([order], "B02-201", W.Category.NETWORK))
        again = W.apply_transition(order.changed(state="DRAFT", submitted_at=None,
                                                sla_due_at=None, history=()),
                                   STUDENT, "stu-1", W.Action.SUBMIT, now=200.0)
        self.assertEqual(again.state, "SUBMITTED", "上一单已关闭就应该能重新报")


class TestExhaustiveWalk(unittest.TestCase):
    def test_exhaustive_walk_keeps_invariants(self):
        """从草稿出发穷举所有合法动作序列（深度 6），核对四条全局不变式。

        出处：BR-02（终态无出边）、BR-03 与数据字典（assignee 何时必须为空）、
        BR-08（submitted_at 不回退）、BR-06（历史条数等于成功转换次数）。
        """
        pool = {(STUDENT, "stu-1"), (WORKER, "w-1"), (WORKER, "w-2"), (ADMIN, "adm-1")}
        seen_states, nodes, max_depth = set(), 0, 0
        LIMIT = 6

        def walk(order, depth, path):
            nonlocal nodes, max_depth
            nodes += 1
            max_depth = max(max_depth, depth)
            seen_states.add(order.state)
            self.assertTrue(len(order.history) == depth, f"历史条数应等于成功步数：{path}")
            self.assertTrue(order.state in {s.value for s in W.State}, path)
            if order.state in ("SUBMITTED", "CLOSED", "CANCELLED"):
                self.assertEqual(order.assignee, "", f"{order.state} 不该挂着维修员：{path}")
            # BR-11 的全局形式：resolved_by 恰好等价于"历史里进过 RESOLVED"，
            # 既不能少（漏记处理人就查不到自己修过的单），也不能多（没修过却挂着名字）。
            ever_resolved = any(c.target == "RESOLVED" for c in order.history)
            self.assertEqual(order.resolved_by != "", ever_resolved,
                             f"resolved_by 与历史不一致：{path}")
            if ever_resolved:
                self.assertIsNotNone(order.resolved_at, f"进过 RESOLVED 却没有起算时刻：{path}")
            if depth >= LIMIT:
                return
            for role, who in pool:
                for action in W.Action:
                    try:
                        nxt = W.apply_transition(order, role, who, action, now=1000.0 + depth,
                                                 assignee="w-1", note="好了", reason="理由")
                    except W.TransitionError:
                        continue
                    self.assertEqual(len(nxt.history), depth + 1)
                    if order.submitted_at is not None:
                        self.assertEqual(nxt.submitted_at, order.submitted_at,
                                         f"submitted_at 被重置：{path} + {action.value}")
                    walk(nxt, depth + 1, path + [action.value])

        walk(draft(), 0, [])
        self.assertEqual(seen_states, {s.value for s in W.State}, "有状态穷举不到，说明表里有死需求")
        self.assertLess(nodes, 200000, "穷举规模失控，需要重新设计深度")
        self.assertGreater(max_depth, 3, "深度太浅，走不到验收与关闭")

    def test_the_pingpong_loop_is_reachable_and_is_a_risk(self):
        """AQ-10：状态机允许"退回—改派—再开工"无限循环。测试钉住它**可达**，
        这样将来加了上限之后测试会红，逼着改动同步回文档而不是悄悄消失。"""
        order = assigned()
        order = W.apply_transition(order, WORKER, "w-1", W.Action.ACCEPT, now=1.0)
        order = W.apply_transition(order, ADMIN, "adm-1", W.Action.ESCALATE, now=2.0,
                                   reason="先退回")
        order = W.apply_transition(order, ADMIN, "adm-1", W.Action.ASSIGN, now=3.0,
                                   assignee="w-2")
        order = W.apply_transition(order, WORKER, "w-2", W.Action.ACCEPT, now=4.0)
        self.assertEqual(order.state, "IN_PROGRESS")
        # assigned() 本身已有 2 条（submit、assign），再加 accept/escalate/assign/accept = 6
        self.assertEqual(len(order.history), 6)
        self.assertEqual(order.submitted_at, 1000.0, "来回推诿不能把时限洗掉（BR-08）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
