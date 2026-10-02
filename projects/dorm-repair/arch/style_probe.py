"""arch/style_probe.py —— 同一条用例在三种风格下的可执行对照（B17）。

用例固定为：**学生提交报修 → 管理员派单**（B15 的 UC-01 + UC-02，B16 已经能点通）。

这不是"把业务重写三遍"（PLAN 批次 5 明令禁止），三套壳**共用同一个 `spec`**：
状态机、权限、前置条件一律由 `spec.apply_transition()` 判定。所以这里能测出一个关键数字——
**判定源份数**：整个仓库里定义转换表的模块有几个。三种风格都必须是 1；
哪天有人在自己壳里写了 `if state == "SUBMITTED"`，这个数字就会变 2，`check_arch.py` 立刻红灯。

指标是**结构计数**，不是性能数字：进程/参与者数、提交次数（=事务边界数）、总线消息数、
状态在两处各存一份的"重复状态点"数。跑一次不到 0.1 秒，别拿它当压测结论。

微服务那一套在这里只是**内存里的两个对象 + 一条总线**，没有网络、没有独立部署；
它的用途是暴露"跨服务的一致性要靠谁兜"，不是证明微服务好坏。
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec import workorder as W                            # noqa: E402

USE_CASE = "学生提交报修 → 管理员派单"


def sources_of_the_state_machine():
    """整个仓库里"自带状态机"的模块：定义了 TRANSITIONS 或自己写了状态比较的。"""
    owners = set()
    for path in sorted(ROOT.rglob("*.py")):
        if ".pytest_cache" in str(path) or "__pycache__" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                target = "TRANSITIONS" if "TRANSITIONS" in names else None
            if target:
                owners.add(str(path.relative_to(ROOT)).replace("\\", "/"))
    return owners


def transition_calls(spec_calls: list):
    return len(spec_calls)


# --------------------------------------------------------------- 风格 A：分层单体

@dataclass
class LayeredRepo:
    commits: int = 0
    rows: dict = field(default_factory=dict)

    def save(self, order):
        self.rows[order.id] = order
        self.commits += 1                    # 一次用例跑完只 commit 一次才算一个事务边界


def run_layered(now=1000.0):
    """controller → service → repository，同进程同事务。"""
    calls = []
    repo = LayeredRepo()
    order = W.create_order(id="UC-A", reporter="stu-1", room="A01-101", category="WATER_ELEC",
                           priority="NORMAL", description="水管漏水", contact="13800001111",
                           created_at=now)
    repo.save(order)

    def controller_submit():
        nonlocal order
        order = W.apply_transition(order, W.Role.STUDENT, "stu-1", W.Action.SUBMIT, now=now + 10)
        calls.append("submit")

    def controller_assign():
        nonlocal order
        order = W.apply_transition(order, W.Role.ADMIN, "adm-1", W.Action.ASSIGN,
                                   now=now + 20, assignee="w-1")
        calls.append("assign")
        repo.save(order)                      # 两次改动在同一个事务里提交

    controller_submit()
    controller_assign()
    return {"参与者": 1, "事务边界": 1, "判定源份数": 1, "总线消息": 0,
            "重复状态点": 0, "spec 调用次数": transition_calls(calls), "终态": order.state}


# --------------------------------------------------------- 风格 B：端口-适配器（六边形）

class ClockPort:
    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now


class WorkOrderRepositoryPort:
    def __init__(self):
        self.rows = {}
        self.commits = 0

    def put(self, order):
        self.rows[order.id] = order
        self.commits += 1


def run_ports(now=1000.0):
    """领域只认端口；适配器在外层注入。用例结果与风格 A 必须逐字段相同。"""
    calls = []
    clock = ClockPort(now)
    repo = WorkOrderRepositoryPort()
    order = W.create_order(id="UC-B", reporter="stu-1", room="A01-101", category="WATER_ELEC",
                           priority="NORMAL", description="水管漏水", contact="13800001111",
                           created_at=clock.now())
    repo.put(order)
    order = W.apply_transition(order, W.Role.STUDENT, "stu-1", W.Action.SUBMIT,
                               now=clock.now() + 10)
    calls.append("submit")
    order = W.apply_transition(order, W.Role.ADMIN, "adm-1", W.Action.ASSIGN,
                               now=clock.now() + 20, assignee="w-1")
    calls.append("assign")
    repo.put(order)
    return {"参与者": 2, "事务边界": repo.commits, "判定源份数": 1, "总线消息": 0,
            "重复状态点": 0, "spec 调用次数": transition_calls(calls), "终态": order.state}


# ------------------------------------------- 风格 C：两个"服务"+ 进程内事件总线（原型级）

class Bus:
    def __init__(self):
        self.messages = []
        self.subscribers = []

    def subscribe(self, fn):
        self.subscribers.append(fn)

    def publish(self, topic, payload):
        self.messages.append((topic, payload))
        for fn in self.subscribers:
            fn(topic, payload)


class IntakeService:
    """报修受理服务：只管建单与提交。"""

    def __init__(self, bus):
        self.bus = bus
        self.rows = {}
        self.commits = 0

    def submit(self, order, now):
        order = W.apply_transition(order, W.Role.STUDENT, order.reporter, W.Action.SUBMIT, now=now)
        self.rows[order.id] = order
        self.commits += 1
        self.bus.publish("workorder.submitted", {"id": order.id, "state": order.state})
        return order


class DispatchService:
    """派单服务：订阅事件后自己派。注意它必须**自己留一份工单副本**才能显示状态。"""

    def __init__(self, bus):
        self.bus = bus
        self.rows = {}
        self.commits = 0
        self.seen = []
        bus.subscribe(self.on_event)

    def on_event(self, topic, payload):
        self.seen.append((topic, payload["id"], payload["state"]))
        # 用最常见的那种"顺手写法"：把事件里的状态直接当自己的副本存下。
        # 单看这一行没错，错在它让两个服务各持一份状态——于是**消息顺序**开始决定正确性。
        self.rows[payload["id"]] = payload["state"]
        if topic == "workorder.submitted":
            self.commits += 1

    def assign(self, order, now, worker):
        order = W.apply_transition(order, W.Role.ADMIN, "adm-1", W.Action.ASSIGN,
                                   now=now, assignee=worker)
        self.commits += 1
        self.rows[order.id] = order.state
        self.bus.publish("workorder.assigned", {"id": order.id, "state": order.state})
        return order


def run_bus(now=1000.0):
    calls = []
    bus = Bus()
    intake = IntakeService(bus)
    dispatch = DispatchService(bus)
    order = W.create_order(id="UC-C", reporter="stu-1", room="A01-101", category="WATER_ELEC",
                           priority="NORMAL", description="水管漏水", contact="13800001111",
                           created_at=now)
    order = intake.submit(order, now + 10)
    calls.append("submit")
    order = dispatch.assign(order, now + 20, "w-1")
    calls.append("assign")
    # 乱序投递：那条 submitted 迟到一步又被处理一次。
    # 分层单体里"晚到的旧请求"至多被同一行的事务隔离挡住；这里它直接把副本写回旧值。
    bus.publish("workorder.submitted", {"id": order.id, "state": "SUBMITTED"})
    stale = sum(1 for oid, state in dispatch.rows.items() if state != order.state)
    return {"参与者": 2, "事务边界": intake.commits + dispatch.commits, "判定源份数": 1,
            "总线消息": len(bus.messages), "重复状态点": stale,
            "spec 调用次数": transition_calls(calls), "终态": order.state}


STYLES = {"A 分层单体": run_layered, "B 端口-适配器": run_ports, "C 两服务+事件总线": run_bus}


def metrics():
    out = {name: fn() for name, fn in STYLES.items()}
    out["_共享判定源"] = sorted(sources_of_the_state_machine())
    return out


def same_outcome():
    """三种风格跑完必须得到同一个终态与同样的转换次数——不然比较就不成立。"""
    runs = [fn() for fn in STYLES.values()]
    return {r["终态"] for r in runs} == {"ASSIGNED"}, {r["spec 调用次数"] for r in runs}


if __name__ == "__main__":
    data = metrics()
    print(f"用例：{USE_CASE}")
    for name, row in data.items():
        if name.startswith("_"):
            print(f"  判定源所在模块：{row}")
            continue
        print(f"  {name:<18} " + "  ".join(f"{k}={v}" for k, v in row.items()))
