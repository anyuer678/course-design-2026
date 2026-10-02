"""prototype/server.py —— B16 的可交互原型（走查用，不是产品实现）。

三条硬约束决定了它的形状：

* **不写第三套 HTTP**：直接复用 B11 的 `netlab.server.Server`（B31 也复用它）。
  静态文件读取只是十几行路径包含检查，不是协议实现。
* **不在前端重写业务规则**：按钮能不能出现，来自 `spec.attemptable()`；
  要点哪个动作需要额外填工号/理由/完工说明，来自 `spec.required_inputs()`。
  界面读的是模型的结论，所以第 3/5 节那两张表改了，原型自己会跟着变。
* **身份是假的，而且页面要这么说**：本期用角色切换器模拟登录（B18 才接统一身份）。
  切换器只改变"服务端用哪个身份判定"，不改变判定规则本身——这正是 NFR-02 想让人看见的点：
  按钮藏起来不是防线，越权动作照样得被服务端拒绝（原型测试里就是这么断言的）。

数据是内存的：进程退出就没了，不在项目目录留任何文件。种子数据是**用模型跑出来的**
（建单→提交→派单→接单→完工），所以留痕和 SLA 字段都是真实推导的结果，不是手写的样子货。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT.parent
B11_DIR = PROJECTS / "B11-net-lab"
if not (B11_DIR / "netlab" / "server.py").is_file():
    raise RuntimeError(f"没找到 B11 的 netlab（期望 {B11_DIR / 'netlab'}）："
                       "本原型构建在它上面，复制一份 netlab 就等于允许两套协议实现各自烂掉")
for path in (str(ROOT), str(B11_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from netlab.server import Server                       # noqa: E402

from spec import workorder as W                        # noqa: E402

WEB_ROOT = (Path(__file__).resolve().parent / "web").resolve()
JSON_TYPE = ("Content-Type", "application/json; charset=utf-8")
HTML_TYPE = ("Content-Type", "text/html; charset=utf-8")
NO_STORE = ("Cache-Control", "no-store")
MAX_BODY = 4096

#: 走查用的身份池。真实认证属 B18，这里只是让评审者切换"服务端拿谁判定"。
IDENTITIES = {
    "STUDENT": ["stu-1", "stu-2"],
    "WORKER": ["w-1", "w-2"],
    "ADMIN": ["adm-1"],
}


def read_static(name: str):
    """只许读 prototype/web 里的文件；解析后的真实路径必须仍在里面。"""
    candidate = (WEB_ROOT / name).resolve()
    if not candidate.is_relative_to(WEB_ROOT) or candidate.suffix not in (".html", ".js", ".css",
                                                                          ".svg"):
        return None
    return candidate.read_bytes() if candidate.is_file() else None


class Seed:
    """用模型跑出种子数据：状态、留痕、SLA 都是推导出来的，不是手写假象。"""

    def __init__(self):
        self.orders = {}
        self.counter = 0
        self.clock = 1000.0

    def tick(self, seconds=60.0):
        self.clock += seconds
        return self.clock

    def jump(self, seconds):
        """把模型自己的时钟往前拨，用来演示"逾期"这种需要时间跨度的状态。
        不读真实时钟（NFR-05），所以走查每次看到的都是同一份数据。"""
        self.clock += seconds
        return self.clock

    def make(self, *, reporter, room, category, priority, description, contact):
        self.counter += 1
        oid = f"R{self.counter:03d}"
        order = W.create_order(id=oid, reporter=reporter, room=room, category=category,
                               priority=priority, description=description, contact=contact,
                               created_at=self.tick())
        self.orders[oid] = order
        return order

    def act(self, oid, role, actor, action, **kw):
        kw.setdefault("now", self.tick())
        self.orders[oid] = W.apply_transition(self.orders[oid], W.Role(role), actor,
                                              W.Action(action), **kw)
        return self.orders[oid]


def build_seed() -> Seed:
    seed = Seed()
    # R001：已完工待验收（学生能验收，也能退回维修）
    seed.make(reporter="stu-1", room="A01-101", category="WATER_ELEC", priority="HIGH",
              description="洗手池下水管漏水，水漫到台面", contact="13800001111")
    seed.act("R001", "STUDENT", "stu-1", "submit")
    seed.act("R001", "ADMIN", "adm-1", "assign", assignee="w-1")
    seed.act("R001", "WORKER", "w-1", "accept")
    seed.act("R001", "WORKER", "w-1", "resolve", note="更换下水管接头，试水三分钟无渗漏")
    # R002：维修中（同一间宿舍、不同分类，用来演示重复检测的口径边界）
    seed.make(reporter="stu-1", room="A01-101", category="NETWORK", priority="NORMAL",
              description="书桌网口松动，插上不通", contact="13800001111")
    seed.act("R002", "STUDENT", "stu-1", "submit")
    seed.act("R002", "ADMIN", "adm-1", "assign", assignee="w-1")
    seed.act("R002", "WORKER", "w-1", "accept")
    # R003：待派单 + 已逾期（URGENT 只有 2 小时，所以下面把时钟拨过它的到期点）
    seed.make(reporter="stu-2", room="B02-205", category="FURNITURE", priority="URGENT",
              description="床架螺丝松脱，晃动明显", contact="13900002222")
    seed.act("R003", "STUDENT", "stu-2", "submit")
    # R004：别人的草稿（演示"草稿对维修员不可见"，SRS 第 6 节）
    seed.make(reporter="stu-2", room="B02-205", category="OTHER", priority="LOW",
              description="衣柜门合页响（还没写完）", contact="13900002222")
    # R005：已关闭（演示终态没有任何可点动作，BR-02）
    seed.make(reporter="stu-1", room="A01-103", category="WATER_ELEC", priority="NORMAL",
              description="厨房水龙头滴水", contact="13800001111")
    seed.act("R005", "STUDENT", "stu-1", "submit")
    seed.act("R005", "ADMIN", "adm-1", "assign", assignee="w-2")
    seed.act("R005", "WORKER", "w-2", "accept")
    seed.act("R005", "WORKER", "w-2", "resolve", note="更换阀芯，观察无渗漏")
    seed.act("R005", "STUDENT", "stu-1", "confirm")
    # R006：已派单但没接单（演示拒单与"只有被派的人能接单"）
    seed.make(reporter="stu-2", room="C03-301", category="NETWORK", priority="LOW",
              description="走廊网口没信号", contact="13900002222")
    seed.act("R006", "STUDENT", "stu-2", "submit")
    seed.act("R006", "ADMIN", "adm-1", "assign", assignee="w-2")
    # 把时钟拨到 R003 的到期点之后：URGENT = 2 小时，这里拨 5 小时，逾期态才有东西可看
    seed.jump(5 * 3600)
    return seed


class PrototypeServer(Server):
    """挂在 B11 服务器上的原型路由。工单表是内存 dict，单线程事件循环访问它无需加锁。"""

    def __init__(self, *, host="127.0.0.1", port=0, **kwargs):
        super().__init__(host=host, port=port, **kwargs)
        self.seed = build_seed()
        self.routes = [
            (("GET", "/"), self.index),
            (("GET", "/app.js"), self.make_static("app.js")),
            (("GET", "/style.css"), self.make_static("style.css")),
            (("GET", "/favicon.svg"), self.make_static("favicon.svg")),
            (("GET", "/api/meta"), self.meta),
            (("GET", "/api/orders"), self.list_orders),
            (("POST", "/api/orders"), self.create_order),
            (("GET", "/api/orders/*"), self.order_detail),
            (("POST", "/api/orders/*"), self.order_action),
        ]

    # ------------------------------------------------------------------ 页面

    def index(self, request):
        page = read_static("index.html")
        if page is None:
            return 500, [JSON_TYPE], b'{"error":"prototype/web/index.html missing"}'
        return 200, [HTML_TYPE, NO_STORE], page

    def make_static(self, name):
        def handler(request):
            data = read_static(name)
            if data is None:
                return 404, [JSON_TYPE], self._json({"error": "资源不存在"})
            mime = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}[
                Path(name).suffix]
            return 200, [("Content-Type", f"{mime}; charset=utf-8" if mime != "image/svg+xml"
                          else mime), NO_STORE], data
        return handler

    # ------------------------------------------------------------------ 元数据

    def meta(self, request):
        return 200, [JSON_TYPE, NO_STORE], self._json({
            "states": [s.value for s in W.State],
            "terminal": [s.value for s in W.TERMINAL],
            "categories": [c.value for c in W.Category],
            "priorities": {p.value: W.SLA_HOURS[p] for p in W.Priority},
            "roles": {r.value: IDENTITIES[r.value] for r in W.Role},
            "visibility": {str(r): v for r, v in W.ROLE_VISIBILITY.items()},
            "notice": "原型身份由页面切换器模拟，不是登录；真实认证属 B18。切换身份只改变服务端用来判定的角色，不改变判定规则。",
        })

    # ------------------------------------------------------------------ 列表

    def list_orders(self, request):
        role, actor, error = self._identity(request)
        if error:
            return 400, [JSON_TYPE], self._json({"error": error})
        values = dict(request.query)
        orders = [o for o in self.seed.orders.values()]
        visible = W.filter_orders(orders, actor_role=W.Role(role), actor_id=actor,
                                 **self._filters(values))
        # 逾期判定需要一个"现在"，原型的"现在"就是模型自己的时钟（不读真实时钟，NFR-05）
        now = self.seed.clock
        return 200, [JSON_TYPE, NO_STORE], self._json({
            "identity": {"role": role, "actor": actor},
            "now": now,
            "count": len(visible),
            "empty": not visible,
            "orders": [self.view(o, W.Role(role), actor, now) for o in
                       sorted(visible, key=lambda o: (-1 if W.is_overdue(o, now) else 0, o.id))],
        })

    # ------------------------------------------------------------------ 详情与动作

    def order_detail(self, request):
        role, actor, error = self._identity(request)
        if error:
            return 400, [JSON_TYPE], self._json({"error": error})
        oid = request.path[len("/api/orders/"):]
        order = self.seed.orders.get(oid)
        if order is None or not W.visible_to(order, W.Role(role), actor):
            return 404, [JSON_TYPE], self._json({"error": f"看不到这张单：{oid}"})
        return 200, [JSON_TYPE, NO_STORE], self._json(
            self.view(order, W.Role(role), actor, self.seed.clock))

    def order_action(self, request):
        tail = request.path[len("/api/orders/"):]
        parts = tail.split("/")
        oid = parts[0]
        if len(parts) != 2 or parts[1] != "act" or not oid:
            return 400, [JSON_TYPE], self._json({"error": "路径应为 /api/orders/<编号>/act"})
        role, actor, error = self._identity(request, body=request.body)
        if error:
            return 400, [JSON_TYPE], self._json({"error": error})
        order = self.seed.orders.get(oid)
        if order is None:
            return 404, [JSON_TYPE], self._json({"error": f"没有这张单：{oid}"})
        try:
            payload = json.loads(request.body.decode("utf-8") or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return 400, [JSON_TYPE], self._json({"error": f"请求体不是合法 JSON：{exc}"})
        if not isinstance(payload, dict):
            return 400, [JSON_TYPE], self._json({"error": "请求体必须是 JSON 对象"})
        action = payload.get("action")
        if action not in {a.value for a in W.Action}:
            return 400, [JSON_TYPE], self._json({"error": f"未知动作 {action!r}",
                                                 "attemptable": list(W.attemptable(order, W.Role(role)))})
        try:
            moved = W.apply_transition(order, W.Role(role), actor, W.Action(action),
                                       now=self.seed.tick(),
                                       assignee=payload.get("assignee"),
                                       note=payload.get("note"), reason=payload.get("reason"))
        except W.TransitionError as exc:
            # 服务端判定：前端按钮只是便利，绕过它也一样被拒（NFR-02）
            return 400, [JSON_TYPE, NO_STORE], self._json({"code": exc.code, "error": exc.reason,
                                                           "attemptable": list(W.attemptable(order, W.Role(role)))})
        self.seed.orders[oid] = moved
        return 200, [JSON_TYPE, NO_STORE], self._json(
            self.view(moved, W.Role(role), actor, self.seed.clock))

    def create_order(self, request):
        role, actor, error = self._identity(request, body=request.body)
        if error:
            return 400, [JSON_TYPE], self._json({"error": error})
        if len(request.body) > MAX_BODY:
            return 413, [JSON_TYPE], self._json({"error": f"请求体超过 {MAX_BODY} 字节"})
        try:
            payload = json.loads(request.body.decode("utf-8") or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return 400, [JSON_TYPE], self._json({"error": f"请求体不是合法 JSON：{exc}"})
        if not isinstance(payload, dict):
            return 400, [JSON_TYPE], self._json({"error": "请求体必须是 JSON 对象"})
        fields = {k: payload.get(k) for k in
                  ("room", "category", "priority", "description", "contact")}
        try:
            order = self.seed.make(reporter=actor, **{k: v or "" for k, v in fields.items()})
        except W.InvalidOrder as exc:
            return 400, [JSON_TYPE, NO_STORE], self._json({
                "code": "INVALID_FIELDS",
                "error": "字段校验未通过，一次报全（FR-03）",
                "fields": [{"field": e.field_name, "code": e.code, "reason": e.reason}
                           for e in exc.errors]})
        if payload.get("action") == "submit":
            try:
                order = self.seed.act(order.id, "STUDENT", actor, "submit")
            except W.TransitionError as exc:
                return 400, [JSON_TYPE, NO_STORE], self._json({"code": exc.code,
                                                              "error": exc.reason})
        return 201, [JSON_TYPE, ("Location", f"/api/orders/{order.id}"), NO_STORE], \
            self._json(self.view(order, W.Role(role), actor, self.seed.clock))

    # ------------------------------------------------------------------ 视图模型

    def view(self, order: W.Order, role: W.Role, actor: str, now: float) -> dict:
        actions = list(W.attemptable(order, role))
        return {
            "id": order.id, "room": order.room, "category": order.category,
            "priority": order.priority, "description": order.description,
            "contact": order.contact, "reporter": order.reporter, "assignee": order.assignee,
            "state": order.state, "created_at": order.created_at,
            "submitted_at": order.submitted_at, "sla_due_at": order.sla_due_at,
            "sla_hours": W.SLA_HOURS[W.Priority(order.priority)],
            "overdue": W.is_overdue(order, now),
            "mine": order.reporter == actor,
            "attemptable": actions,
            "required_inputs": {a: list(W.required_inputs(W.Action(a))) for a in actions},
            "history": [{"at": c.at, "from": c.source, "to": c.target, "action": c.action,
                         "role": c.actor_role, "actor": c.actor_id, "reason": c.reason}
                        for c in order.history],
        }

    # ------------------------------------------------------------------ 小工具

    def _identity(self, request, body=None):
        """身份来自查询串或请求体，**但判定规则始终在服务端**（NFR-02）。"""
        role = None
        actor = None
        for name, value in request.query:
            if name == "role":
                role = value
            elif name in ("actor", "who"):
                actor = value
        if body:
            try:
                payload = json.loads(body.decode("utf-8") or b"{}")
                if isinstance(payload, dict):
                    role = payload.get("role", role)
                    actor = payload.get("actor", actor)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        if role not in {r.value for r in W.Role}:
            return None, None, f"role 必须是 {sorted(r.value for r in W.Role)} 之一，收到 {role!r}"
        if not actor or actor not in IDENTITIES[W.Role(role)]:
            return None, None, f"{role} 的身份要从 {IDENTITIES[W.Role(role)]} 里选，收到 {actor!r}"
        return role, actor, None

    def _filters(self, values):
        out = {}
        for key, enum in (("state", W.State), ("category", W.Category), ("priority", W.Priority)):
            raw = values.get(key)
            if raw:
                out[key] = enum(raw)
        if values.get("room"):
            out["room"] = values["room"]
        if values.get("overdue") in ("1", "true", "yes"):
            out["overdue_only"] = True
            out["now"] = self.seed.clock
        return out

    @staticmethod
    def _json(payload) -> bytes:
        return json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"


def main(argv=None) -> int:
    import argparse
    import signal
    import threading

    parser = argparse.ArgumentParser(description="B16 可交互原型（只绑回环，走查用）")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)

    server = PrototypeServer(port=args.port)
    port = server.start()
    print(f"原型已启动： http://127.0.0.1:{port}/   （Ctrl+C 退出）")
    print("工单数据在内存里，退出即清空；业务判断全部来自 B15 的 spec/workorder.py")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()
    server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
