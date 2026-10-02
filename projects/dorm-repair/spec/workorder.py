"""spec/workorder.py —— 需求阶段的可执行模型（不是产品实现）。

为什么需求阶段要写代码：状态机、权限、可见性这类规则用散文写十遍也可能互相矛盾，
写成可执行的形式则**当场就能矛盾**——而 `checks/check_docs.py` 会把
`docs/02-srs.md` 里那三张规范表解析出来与这里逐条比对，两边不一致就红灯。
这就是 B15 的"需求 ID 对应接口/测试"落到实处的方式：不是画一张追踪表骗自己。

三条刻意的设计选择：

* **工单不可变**（`apply` 返回新对象）。非法转换"不改状态"于是变成一句可断言的话，
  而不是靠实现者记得先校验再赋值——这是 B14 撤销栈那轮学到的同一课。
* **时间一律由调用方注入**。本模块不 import `time`，所以测试不需要 sleep，
  SLA 与逾期判定都是纯函数（NFR-05）。
* **校验一次报全**。逐条报错会逼提交者"改一处跑一次"，而改一处常常引入另一处
  （B13 的编译器、B14 的文件格式都是这么改出来的）。

规范出处：`docs/02-srs.md` 第 3、5、6、8 节。改这里之前先改那里。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum

SPEC = "dorm-repair/workorder-spec/1"


class Role(StrEnum):
    STUDENT = "STUDENT"
    WORKER = "WORKER"
    ADMIN = "ADMIN"


class State(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Action(StrEnum):
    SUBMIT = "submit"
    ASSIGN = "assign"
    REASSIGN = "reassign"
    RETURN_POOL = "return_pool"
    ACCEPT = "accept"
    DECLINE = "decline"
    RESOLVE = "resolve"
    CONFIRM = "confirm"
    REJECT_CHECK = "reject_check"
    FORCE_CLOSE = "force_close"
    CANCEL = "cancel"
    ESCALATE = "escalate"


class Category(StrEnum):
    WATER_ELEC = "WATER_ELEC"
    NETWORK = "NETWORK"
    FURNITURE = "FURNITURE"
    OTHER = "OTHER"


class Priority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


TERMINAL = (State.CLOSED, State.CANCELLED)

#: SRS 第 8 节 SLA 表的镜像（小时）。检查器会比对两边，写歪一边立刻发现。
SLA_HOURS = {Priority.LOW: 72, Priority.NORMAL: 24, Priority.HIGH: 8, Priority.URGENT: 2}

#: SRS 第 8 节的验收宽限期（小时）。AQ-03 于 2026-10-01 裁决为 168 小时 = 7 天。
#: 它是**默认值**，调用方可以传 `grace_hours=` 覆盖——AC-24 考的就是"能不能覆盖"。
#: 这个数仍然只是我拟的假设（用户当时回答"无偏好"），不是校方规定。
ACCEPTANCE_GRACE_HOURS = 168
#: SRS 第 4 节的前置条件代码图例。文档里出现图例外的代码 = 红灯。
PRECONDITIONS = frozenset({
    "none", "owner", "assignee", "assignee_required", "valid_fields",
    "resolution_note", "reason", "acceptance_timeout",
})

#: SRS 第 6 节可见性矩阵的镜像。取值只允许 OWN / OWN_OR_POOL /
#: OWN_OR_POOL_OR_RESOLVED / ALL，且必须与文档里的代码逐字相同。
ROLE_VISIBILITY = {
    Role.STUDENT: "OWN",
    Role.WORKER: "OWN_OR_POOL_OR_RESOLVED",
    Role.ADMIN: "ALL",
}


@dataclass(frozen=True)
class Transition:
    tid: str
    action: Action
    source: State
    target: State
    roles: frozenset
    preconditions: tuple

    @property
    def key(self):
        return (self.action.value, self.source.value, self.target.value,
                frozenset(r.value for r in self.roles), self.preconditions)


def _tr(tid, action, source, target, roles, preconditions):
    return Transition(tid, Action(action), State(source), State(target),
                      frozenset(Role(r) for r in roles.split(",")),
                      tuple(sorted(p.strip() for p in preconditions.split(","))))


#: SRS 第 3 节状态转换表的逐行镜像。顺序按文档，方便人工对照。
TRANSITIONS = (
    _tr("TR-01", "submit", "DRAFT", "SUBMITTED", "STUDENT", "owner,valid_fields"),
    _tr("TR-02", "assign", "SUBMITTED", "ASSIGNED", "ADMIN", "assignee_required"),
    _tr("TR-03", "reassign", "ASSIGNED", "ASSIGNED", "ADMIN", "assignee_required"),
    _tr("TR-04", "return_pool", "ASSIGNED", "SUBMITTED", "ADMIN", "reason"),
    _tr("TR-05", "accept", "ASSIGNED", "IN_PROGRESS", "WORKER", "assignee"),
    _tr("TR-06", "decline", "ASSIGNED", "SUBMITTED", "WORKER", "assignee"),
    _tr("TR-07", "resolve", "IN_PROGRESS", "RESOLVED", "WORKER", "assignee,resolution_note"),
    _tr("TR-08", "confirm", "RESOLVED", "CLOSED", "STUDENT", "owner"),
    _tr("TR-09", "reject_check", "RESOLVED", "IN_PROGRESS", "STUDENT", "owner,reason"),
    _tr("TR-10", "force_close", "RESOLVED", "CLOSED", "ADMIN", "acceptance_timeout"),
    _tr("TR-11", "cancel", "DRAFT", "CANCELLED", "STUDENT", "owner"),
    _tr("TR-12", "cancel", "SUBMITTED", "CANCELLED", "STUDENT", "owner"),
    _tr("TR-13", "cancel", "SUBMITTED", "CANCELLED", "ADMIN", "reason"),
    _tr("TR-14", "cancel", "ASSIGNED", "CANCELLED", "ADMIN", "reason"),
    _tr("TR-15", "escalate", "IN_PROGRESS", "SUBMITTED", "ADMIN", "reason"),
)


class TransitionError(Exception):
    """转换被拒绝。`code` 是给上层与测试用的稳定标识，`reason` 是给人看的话。"""

    def __init__(self, code: str, reason: str):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class Change:
    at: float
    source: str
    target: str
    action: str
    actor_role: str
    actor_id: str
    reason: str = ""


@dataclass(frozen=True)
class FieldError:
    field_name: str
    code: str
    reason: str


@dataclass(frozen=True)
class Order:
    id: str
    reporter: str
    room: str
    category: str
    priority: str
    description: str
    contact: str
    state: str = State.DRAFT.value
    assignee: str = ""
    resolved_by: str = ""
    created_at: float = 0.0
    submitted_at: float | None = None
    sla_due_at: float | None = None
    resolved_at: float | None = None
    history: tuple = ()

    def changed(self, **updates) -> "Order":
        return replace(self, **updates)


# ---------------------------------------------------------------- 校验（SRS 第 9 节）

ROOM_RE = re.compile(r"^[A-Z]\d{2}-\d{3}$")
CONTACT_RE = re.compile(r"^1\d{10}$")
DESCRIPTION_MAX = 500
REASON_MAX = 200
ASSIGNEE_MAX = 32

#: SRS 第 9 节"校验参数"表的镜像。B18 的 Java 侧读契约里的同一张表，
#: 所以这些数字只能有一处出处——这里。检查器逐格比对文档与它，`validate_order`
#: 的边界行为由 `test_field_limits_table_is_actually_enforced` 钉住。
#: 第三项是"格式代码"：NONE 表示只看长度，其余表示还要过对应的正则。
FIELD_LIMITS = {
    "room": (8, 8, "ROOM_PATTERN"),
    "description": (1, DESCRIPTION_MAX, "NONE"),
    "contact": (11, 11, "CONTACT_PATTERN"),
    "reason": (1, REASON_MAX, "NONE"),
    "resolution_note": (1, DESCRIPTION_MAX, "NONE"),
    "assignee": (1, ASSIGNEE_MAX, "NONE"),
}

def normalize_room(raw: str) -> str:
    return (raw or "").strip().upper()


#: 枚举字段的错误码：与文档第 9 节的 CATEGORY_UNKNOWN / PRIORITY_UNKNOWN 对齐
ENUM_FIELDS = (("category", "CATEGORY_UNKNOWN", Category), ("priority", "PRIORITY_UNKNOWN", Priority))


def validate_order(room, category, priority, description, contact) -> list:
    """返回**全部**问题，按字段顺序稳定排列（FR-03、NFR-03）。"""
    values = {"category": category, "priority": priority}
    errors = []
    if not ROOM_RE.match(normalize_room(room)):
        errors.append(FieldError("room", "ROOM_FORMAT", "宿舍编号要形如 A01-101"))
    for name, code, enum in ENUM_FIELDS:
        legal = sorted(e.value for e in enum)
        if values[name] not in legal:
            errors.append(FieldError(name, code, f"必须是 {legal} 之一"))
    text = (description or "").strip()
    lo, hi, _pattern = FIELD_LIMITS["description"]
    if not lo <= len(text) <= hi:
        errors.append(FieldError("description", "DESCRIPTION_LENGTH",
                                 f"描述去掉首尾空白后长度要在 {lo}..{hi}"))
    if not CONTACT_RE.match((contact or "").strip()):
        errors.append(FieldError("contact", "CONTACT_FORMAT", "联系方式要形如 11 位数字且以 1 开头"))
    return errors


def _require_text(value, field_name, code, limit, label) -> list:
    text = (value or "").strip()
    if not 1 <= len(text) <= limit:
        return [FieldError(field_name, code, f"{label}必填，长度 1..{limit}")]
    return []


class InvalidOrder(Exception):
    """建单字段校验未通过。`errors` 是**全部**问题，不是第一个（FR-03）。"""

    def __init__(self, errors):
        super().__init__("字段校验未通过：" + ", ".join(f"{e.field_name}({e.code})" for e in errors))
        self.errors = list(errors)


def create_order(*, id, reporter, room, category, priority, description, contact,
                 created_at) -> Order:
    """FR-01：建一张草稿。校验不通过就一条工单都不产生（NFR-03）。

    规范化在建单这一刻做完（编号大写、去首尾空白），而不是等到查询时两边各normalize一次——
    存进去的和查出来的必须是同一份写法，否则第 6 节的可见性和第 12 节的字典都会各自解释一遍。
    """
    errors = validate_order(room, category, priority, description, contact)
    if errors:
        raise InvalidOrder(errors)
    return Order(id=id, reporter=reporter.strip(), room=normalize_room(room),
                 category=str(Category(category)), priority=str(Priority(priority)),
                 description=description.strip(), contact=contact.strip(),
                 state=State.DRAFT.value, created_at=created_at)


# ---------------------------------------------------------------- 权限与转换

def transitions_for(action, state):
    return [t for t in TRANSITIONS if t.action == action and t.source == State(state)]


def allowed_roles(action, state):
    return frozenset(r for t in transitions_for(action, state) for r in t.roles)


def attemptable(order: Order, actor_role: Role) -> tuple:
    """当前角色在这个状态下**能尝试**的动作（只看状态与角色，不看前置条件）。

    界面需要它来画按钮，但它是"可点"而不是"会成功"：`owner`、`reason` 这类前置条件
    仍然由服务端在提交时判定（NFR-02）。把这套判断复制到前端就是第二个规则引擎，
    两边迟早分叉——前端只读这个函数给的结果，不自己推。
    """
    out = []
    for action in Action:
        if any(tr.action == action and actor_role in tr.roles
               for tr in transitions_for(action, order.state)):
            out.append(action.value)
    return tuple(out)


def required_inputs(action: Action) -> tuple:
    """这个动作需要用户额外填什么（工号 / 完工说明 / 理由）。

    同样是模型说话，界面照着渲染：第 3 节的 `前置条件` 列改了，表单自己跟着变，
    不需要有人记得去改前端。
    """
    need = set()
    for tr in TRANSITIONS:
        if tr.action != action:
            continue
        for code in tr.preconditions:
            if code == "assignee_required":
                need.add("assignee")
            elif code == "resolution_note":
                need.add("note")
            elif code == "reason":
                need.add("reason")
    return tuple(sorted(need))


def check_transition(order: Order, actor_role: Role, actor_id: str, action: Action, *,
                     now: float, assignee=None, note=None, reason=None, grace_hours=None):
    """只回答"这次转换行不行"，不改动任何东西。返回被选中的转换；不行就抛 TransitionError。

    `now` 是必填的：`acceptance_timeout` 这类前置条件要看时钟（BR-10），
    而本模块不许自己读时间（NFR-05）——让调用方忘记传钟，等于给逾期判定留一个后门。
    """
    actor_role = Role(actor_role)
    matched = [t for t in transitions_for(action, order.state) if actor_role in t.roles]
    if not transitions_for(action, order.state):
        raise TransitionError("NO_SUCH_TRANSITION", f"{order.state} 下没有 {action} 这个动作")
    if not matched:
        raise TransitionError("ROLE_NOT_ALLOWED",
                              f"{actor_role} 不能在 {order.state} 发起 {action}"
                              f"（允许的角色：{sorted(r.value for r in allowed_roles(action, order.state))}）")
    # 同动作多行（例如 cancel 在 DRAFT/SUBMITTED/ASSIGNED 各有归属规则）时按前置条件筛
    chosen = None
    last_error = None
    for candidate in matched:
        problems = _precondition_problems(candidate, order, actor_id, assignee, note, reason,
                                          grace_hours, now)
        if not problems:
            chosen = candidate
            break
        last_error = problems[0]
    if chosen is None:
        raise last_error
    return chosen


def _precondition_problems(tr: Transition, order: Order, actor_id: str, assignee, note, reason,
                           grace_hours, now):
    for code in tr.preconditions:
        if code == "owner" and order.reporter != actor_id:
            return [TransitionError("OWNER", "只能操作自己提的工单（BR-09）")]
        if code == "assignee" and order.assignee != actor_id:
            return [TransitionError("ASSIGNEE", "只有当前维修员能推进这一单（BR-04）")]
        if code == "assignee_required":
            problems = _require_text(assignee, "assignee", "ASSIGNEE_REQUIRED", ASSIGNEE_MAX, "维修员工号")
            if problems:
                return [TransitionError(problems[0].code, problems[0].reason)]
        if code == "resolution_note":
            problems = _require_text(note, "resolution_note", "NOTE_REQUIRED", DESCRIPTION_MAX, "完工说明")
            if problems:
                return [TransitionError(problems[0].code, problems[0].reason)]
        if code == "reason":
            problems = _require_text(reason, "reason", "REASON_REQUIRED", REASON_MAX, "理由")
            if problems:
                return [TransitionError(problems[0].code, problems[0].reason)]
        if code == "acceptance_timeout":
            due = acceptance_due(order, grace_hours)
            if due is None or now < due:
                return [TransitionError("ACCEPTANCE_NOT_MATURE",
                                        f"该单停留 RESOLVED 未满宽限期"
                                        f"（到期时刻 {due}，现在 {now}）——BR-10")]
        if code == "valid_fields":
            problems = validate_order(order.room, order.category, order.priority,
                                      order.description, order.contact)
            if problems:
                codes = ",".join(p.code for p in problems)
                return [TransitionError("INVALID_FIELDS", f"字段校验未通过：{codes}")]
    return []


def apply_transition(order: Order, actor_role: Role, actor_id: str, action: Action, *,
                     now: float, assignee=None, note=None, reason=None,
                     grace_hours=None) -> Order:
    """执行转换，返回**新**工单。任何被拒绝的调用都不会碰到原对象（BR-02、NFR-03）。"""
    tr = check_transition(order, actor_role, actor_id, action, now=now,
                          assignee=assignee, note=note, reason=reason, grace_hours=grace_hours)
    updates = {"state": tr.target.value,
               "history": order.history + (Change(at=now, source=tr.source.value,
                                                  target=tr.target.value, action=tr.action.value,
                                                  actor_role=str(actor_role), actor_id=actor_id,
                                                  reason=(reason or "").strip()),)}
    if tr.action in (Action.ASSIGN, Action.REASSIGN):
        updates["assignee"] = (assignee or "").strip()
    elif tr.action in (Action.RETURN_POOL, Action.DECLINE, Action.ESCALATE) or tr.target in TERMINAL:
        # 数据字典规定：待派单与终态都不挂着"当前维修员"。
        # 谁修的已经在历史里，assignee 是"当前负责人"而不是审计字段——终态还不清空就会留下
        # 一个正在维修并不存在的人（穷举走查抓到的正是 confirm / force_close 这两条路径）。
        # AQ-12 裁决后"谁修的"有了正式字段 resolved_by，所以这里可以放心清空。
        updates["assignee"] = ""
    if tr.target == State.RESOLVED:
        # 完工那一刻记下"最后处理人 + 完工时刻"：前者只喂可见性（BR-11），
        # 后者是验收宽限期的起算点（BR-10），且**每次**进入 RESOLVED 都重算——
        # 学生退回再修之后，宽限期必须重新起算，否则第一次验收就吃掉了学生的退回权。
        updates["resolved_by"] = actor_id
        updates["resolved_at"] = now
    if tr.target == State.SUBMITTED and order.submitted_at is None:
        updates["submitted_at"] = now                 # BR-08：只在首次进入时起算，改派不重置
        updates["sla_due_at"] = now + SLA_HOURS[Priority(order.priority)] * 3600
    return order.changed(**updates)


# ---------------------------------------------------------------- 查询（SRS 第 6 节）

def visible_to(order: Order, actor_role: Role, actor_id: str) -> bool:
    mode = ROLE_VISIBILITY[Role(actor_role)]
    if mode == "ALL":
        return True
    if mode == "OWN":
        return order.reporter == actor_id
    if mode == "OWN_OR_POOL":
        return order.state == State.SUBMITTED.value or order.assignee == actor_id
    # OWN_OR_POOL_OR_RESOLVED（AQ-12）：公共池 + 当前派给我的 + 我完工过的历史单。
    # 命中 resolved_by 只给"看得见"，不给"点得动"——attemptable() 仍然只看 assignee 与角色。
    return (order.state == State.SUBMITTED.value
            or order.assignee == actor_id
            or order.resolved_by == actor_id)


def filter_orders(orders, *, actor_role=None, actor_id="", state=None, category=None,
                  room=None, priority=None, overdue_only=False, now=None):
    """FR-12~14：先按可见性收口，再按筛选条件收窄。顺序不能反——否则越权可见。"""
    out = []
    for order in orders:
        if actor_role is not None and not visible_to(order, Role(actor_role), actor_id):
            continue
        if state is not None and order.state != State(state).value:
            continue
        if category is not None and order.category != Category(category).value:
            continue
        if priority is not None and order.priority != Priority(priority).value:
            continue
        if room is not None and normalize_room(order.room) != normalize_room(room):
            continue
        if overdue_only and not is_overdue(order, now):
            continue
        out.append(order)
    return out


def acceptance_due(order: Order, grace_hours=None) -> float | None:
    """验收宽限期的到期时刻（BR-10）。没进入过 `RESOLVED` 就没有这个时刻，返回 None。

    默认值来自 `ACCEPTANCE_GRACE_HOURS`，但**故意留一个参数让调用方覆盖**：
    AC-24 要证明"阈值是配置而不是魔法数"，唯一诚实的办法就是让它真的能被换掉并改变判定。
    """
    if order.resolved_at is None:
        return None
    hours = ACCEPTANCE_GRACE_HOURS if grace_hours is None else grace_hours
    return order.resolved_at + hours * 3600


def is_acceptance_stale(order: Order, now: float, grace_hours=None) -> bool:
    """`RESOLVED` 是否已悬挂到可以被管理员强制关闭。与 `is_overdue` 同一口径：达到即算。"""
    due = acceptance_due(order, grace_hours)
    return due is not None and now >= due


def is_overdue(order: Order, now: float) -> bool:
    """SRS 第 8 节：已完工待验收与终态都不算逾期。"""
    if order.sla_due_at is None or order.state in {s.value for s in TERMINAL}:
        return False
    if order.state == State.RESOLVED.value:
        return False
    return now >= order.sla_due_at


def find_duplicate(orders, room: str, category: Category):
    """BR-07：同宿舍同分类且未进终态。"""
    for order in orders:
        if (normalize_room(order.room) == normalize_room(room)
                and order.category == Category(category).value
                and order.state not in {s.value for s in TERMINAL}):
            return order
    return None


# ---------------------------------------------------------------- 样例数据（测试穷举用）

def sample_orders() -> list:
    """12 单，覆盖 7 个状态、3 个角色、2 个学生、2 个维修员，以及"草稿不该被维修员看见"。

    注意 `resolved_by` / `resolved_at`：这份样例是**直接构造**的，不走转换，
    所以这两个字段必须手工填对，否则 AQ-12 的可见性测试就是在考一份违反数据字典的数据。
    填法规则与 `apply_transition` 一致：只有经过 `RESOLVED` 的单（W09 正在待验收、W10 已关闭）
    才有处理人；`CANCELLED`（W11）是从 `SUBMITTED` 直接取消的，永远没有。
    """
    def new(i, state, reporter, assignee="", submitted=None, priority="NORMAL",
            category="WATER_ELEC", room=None, resolved_by="", resolved_at=None):
        return Order(id=f"W{i:02d}", reporter=reporter, room=room or f"A01-{100 + i}",
                     category=category, priority=priority, description="测试描述",
                     contact="13800000000", state=state, assignee=assignee,
                     created_at=float(i), submitted_at=submitted,
                     resolved_by=resolved_by, resolved_at=resolved_at,
                     sla_due_at=(submitted + SLA_HOURS[Priority(priority)] * 3600)
                     if submitted is not None else None)

    return [
        new(1, "DRAFT", "stu-1"),                                    # 我的草稿
        new(2, "DRAFT", "stu-2"),                                    # 别人的草稿
        new(3, "SUBMITTED", "stu-1", submitted=1000.0),               # 我的、待派单
        new(4, "SUBMITTED", "stu-2", submitted=1100.0),               # 公共池
        new(5, "ASSIGNED", "stu-1", assignee="w-1", submitted=1200.0),
        new(6, "ASSIGNED", "stu-2", assignee="w-2", submitted=1300.0),
        new(7, "IN_PROGRESS", "stu-1", assignee="w-1", submitted=1400.0),
        new(8, "IN_PROGRESS", "stu-2", assignee="w-2", submitted=1500.0, priority="URGENT"),
        new(9, "RESOLVED", "stu-1", assignee="w-1", submitted=1600.0,
            resolved_by="w-1", resolved_at=1600.0),                   # 待学生验收
        new(10, "CLOSED", "stu-1", submitted=1700.0,
            resolved_by="w-1", resolved_at=1700.0),                   # w-1 修完、学生已确认
        new(11, "CANCELLED", "stu-2", submitted=1800.0),               # 没修过，不该有处理人
        new(12, "SUBMITTED", "stu-1", submitted=1900.0, room="A01-101",
            category="NETWORK"),                                      # 同房间不同分类
    ]
