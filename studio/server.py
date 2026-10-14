"""studio/server.py —— P0 Studio 产品门户：产品目录 / 状态面板 / 一键启停 / 登录。

关键事实：**门户自己就跑在 webframe 微框架上**——路由装饰器、静态文件、
JSON 体校验、签名会话全是框架能力，这是"框架是真交付物"的现场证明。
鉴权口径：单用户（owner），目录与状态只读公开；**启停等管理动作要求登录**
（401）；课程演示实验台（showcase lab）已于轮五十五移出矩阵并归档。
2026-10-12：GET /ws/status WebSocket 实时推送产品状态（首包快照 + 2s 变化检测）。
产品矩阵数据来自根 PRODUCTS.md：已实现的给启停，已规划如实标"已规划"。
只绑回环：门户和被管理的产品一样，是本机自托管。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
for p in (str(REPO), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from webframe import (HttpFail, MicroApp, MicroServer, Response,  # noqa: E402
                      )

try:                                                          # noqa: E402
    from .audit import AuditLog
    from .auth import USERNAME, Auth
    from .manager import AlreadyOnline, NotOurs, Product, ProductManager
    from .monitor import UptimeMonitor
    from .users import PERMISSIONS, UserStore
except ImportError:                     # 作为脚本直接跑（python server.py）
    from audit import AuditLog
    from auth import USERNAME, Auth
    from manager import AlreadyOnline, NotOurs, Product, ProductManager
    from monitor import UptimeMonitor
    from users import PERMISSIONS, UserStore

WEB_ROOT = ROOT / "web"
DATA_DIR = ROOT / "data"
DEFAULT_PORT = 8017                # 8018 留给 LinkBox，8000 是 B31，7788 是实验台

_START_SCHEMA = {}
_LOGIN_SCHEMA = {"username": (str, True), "password": (str, True)}
_PASSWORD_SCHEMA = {"old": (str, True), "new": (str, True)}
_USER_SCHEMA = {"name": (str, True), "password": (str, True), "role": (str, True)}
_ROLE_SCHEMA = {"role": (str, True)}
_RESET_SCHEMA = {"password": (str, True)}
_REGISTER_SCHEMA = {"name": (str, True), "password": (str, True)}
_INVITE_SCHEMA = {"role": (str, True)}


def build_manager(linkbox_port: int = 8018, lab_port: int = 7788, *,
                  simlab_port: int = 8019, datascope_port: int = 8020,
                  cachekv_port: int = 8021, sensorhub_port: int = 8022,
                  board_port: int = 8023, courselab_port: int = 8024,
                  boardweb_port: int = 8025, linkbox_memory: bool = False,
                  audit_path=None) -> ProductManager:
    """产品注册表。command=None = 已规划（矩阵名单照抄 PRODUCTS.md §二）。
    audit_path 给了才记账（M2 操作审计）；生产由 build_server 传 data 目录。"""
    cmd = [sys.executable, "server.py", "--port", str(linkbox_port)]
    if linkbox_memory:
        cmd.append("--memory")
    products = [
        Product("studio", "Studio 门户", "九个产品的统一入口：启停、控制台、审计"),
        Product("linkbox", "LinkBox 工具站",
                "短链接与文本暂存，支持二维码和访问口令",
                port=linkbox_port, command=cmd, cwd=str(REPO / "linkbox")),
        Product("simlab", "SimLab 仿真馆",
                "调度与替换算法仿真回放，数据全部来自真实引擎",
                port=simlab_port,
                command=[sys.executable, "server.py", "--port", str(simlab_port)],
                cwd=str(REPO / "simlab")),
        Product("datascope", "DataScope 数据工作台",
                "上传 CSV，完成清洗、挖掘到预测报告",
                port=datascope_port,
                command=[sys.executable, "server.py", "--port", str(datascope_port)],
                cwd=str(REPO / "datascope")),
        Product("cachekv", "CacheKV 缓存",
                "键值缓存服务：过期时间、快照持久化、命中统计",
                port=cachekv_port,
                command=[sys.executable, "server.py", "--port", str(cachekv_port)],
                cwd=str(REPO / "cachekv")),
        Product("sensorhub", "SensorHub 物联网监测",
                "传感器数据实时曲线与阈值告警",
                port=sensorhub_port,
                command=[sys.executable, "server.py", "--port", str(sensorhub_port),
                         "--interval", "2"],      # 1s 节拍空转 65% 单核（轮四十八实测），2s 减半
                cwd=str(REPO / "sensorhub")),
        Product("courselab", "CourseLab 课程工坊",
                "课程学习平台：知识点、随堂测验与成绩分析",
                port=courselab_port,
                command=[sys.executable, "server.py", "--port", str(courselab_port)],
                cwd=str(REPO / "courselab")),
        Product("board", "画板桌面应用",
                "画板的本地引擎（已后台运行）；画图请用「画板 Web 版」",
                port=board_port,
                command=[sys.executable, "launch.py", "--port", str(board_port)],
                cwd=str(REPO / "board"),
                kind="desktop",             # 8023 是探活行协议口（BOARD 8023 OK），不是 HTTP——门户不给"打开产品"
                boot_timeout=25.0),         # JVM 冷启动：慢 runner 上 10s 不够（2026-10-12 CI 实测）
        Product("boardweb", "画板 Web 版",
                "在线画板：绘图、文字、便利贴，支持多人协同",
                port=boardweb_port,
                command=[sys.executable, "server.py", "--port", str(boardweb_port)],
                cwd=str(REPO / "boardweb")),
    ]
    audit = AuditLog(audit_path) if audit_path else None
    return ProductManager(products, audit=audit)


def build_app(manager: ProductManager, auth: Auth,
              users: UserStore | None = None) -> MicroApp:
    app = MicroApp(session_secret=auth.secret)
    if users is None:                   # 测试/直跑兜底：给一个空成员册
        users = UserStore(DATA_DIR / "users-test", iterations=1000)

    def require_user(ctx) -> None:
        """已登录且世代匹配。改口令后旧世代会话一律重新登录。"""
        if not ctx.session.get("user"):
            raise HttpFail(401, "请先登录（POST /api/login）")
        if ctx.session.get("gen") != auth.generation:
            raise HttpFail(401, "密码已更新，请重新登录")

    def require_perm(ctx, perm: str) -> str:
        """用户分层（轮四十四）：按 users.PERMISSIONS 权限点把门——
        矩阵一处定义（users.py），前后端与测试三处同源。"""
        require_user(ctx)
        role = ctx.session.get("role")
        if role not in PERMISSIONS[perm]:
            raise HttpFail(403, "当前角色无权执行此操作")
        return ctx.session["user"]

    def get_pid(ctx) -> str:
        pid = ctx.params["pid"]
        if pid not in manager.by_id:
            raise HttpFail(404, f"没有叫 {pid!r} 的产品")
        return pid

    # ------------------------------------------------ 认证
    @app.post("/api/login")
    def login(ctx):
        body = ctx.json_body(_LOGIN_SCHEMA, allow_unknown=True)
        name = body["username"]
        if name == USERNAME and auth.verify(body["password"]):
            ctx.session["user"] = USERNAME
            ctx.session["role"] = "owner"
        else:
            role = users.verify(name, body["password"])
            if role is None:
                # 不区分"没有此人/口令错"（不给猜测者喂信息）
                raise HttpFail(401, "用户名或密码不对")
            ctx.session["user"] = name
            ctx.session["role"] = role
        ctx.session["gen"] = auth.generation           # 改口令即踢旧世代会话
        return ctx.json({"user": ctx.session["user"],
                         "role": ctx.session["role"]})

    @app.post("/api/logout")
    def logout(ctx):
        ctx.reset_session()                   # 强制回写空会话，覆盖浏览器旧 cookie
        return ctx.json({"user": None})

    @app.get("/api/me")
    def me(ctx):
        role = ctx.session.get("role")
        perms = [p for p, roles in PERMISSIONS.items() if role in roles]
        return ctx.json({"user": ctx.session.get("user"), "role": role,
                         "permissions": perms})

    @app.post("/api/password")
    def change_password(ctx):
        require_perm(ctx, "portal.password")  # 成员密码由 owner 重置，不自助改
        body = ctx.json_body(_PASSWORD_SCHEMA)
        if not auth.verify(body["old"]):
            raise HttpFail(400, "当前密码不正确")
        try:
            auth.set_password(body["new"])
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        auth.bump_generation()                # 旧世代会话（含本会话）全部失效
        return ctx.json({"changed": True})

    # ------------------------------------------------ 自助注册（轮四十二，公开）
    @app.post("/api/register")
    def register_self(ctx):
        body = ctx.json_body(_REGISTER_SCHEMA, allow_unknown=True)
        try:
            role = users.register_self(body["name"], body["password"],
                                       body.get("invite"))
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        except KeyError as exc:
            raise HttpFail(409, str(exc)) from None
        # 注册即登录（免二次输入）；viewer 只读无风险，operator 凭邀请码
        ctx.session["user"] = body["name"]
        ctx.session["role"] = role
        ctx.session["gen"] = auth.generation
        return ctx.json({"ok": True, "user": body["name"], "role": role},
                        status=201)

    # ------------------------------------------------ 邀请码（owner 专属）
    @app.get("/api/invites")
    def invites_list(ctx):
        require_perm(ctx, "invites.manage")
        return ctx.json({"invites": users.invites_listing()})

    @app.post("/api/invites")
    def invites_create(ctx):
        require_perm(ctx, "invites.manage")
        body = ctx.json_body(_INVITE_SCHEMA)
        try:
            code = users.create_invite(body["role"])
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        return ctx.json({"ok": True, "code": code, "role": body["role"]},
                        status=201)

    @app.delete("/api/invites/<code>")
    def invites_revoke(ctx):
        require_perm(ctx, "invites.manage")
        try:
            users.revoke_invite(ctx.params["code"])
        except KeyError as exc:
            raise HttpFail(404, str(exc)) from None
        return ctx.json({"ok": True})

    # ------------------------------------------------ 成员管理（RBAC，owner 专属）
    @app.get("/api/users")
    def users_list(ctx):
        require_perm(ctx, "users.manage")
        return ctx.json({"users": users.listing()})

    @app.post("/api/users")
    def users_add(ctx):
        require_perm(ctx, "users.manage")
        body = ctx.json_body(_USER_SCHEMA)
        try:
            users.add(body["name"], body["password"], body["role"])
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        except KeyError as exc:
            raise HttpFail(409, str(exc)) from None
        return ctx.json({"ok": True, "name": body["name"],
                         "role": body["role"]}, status=201)

    @app.post("/api/users/<name>/role")
    def users_set_role(ctx):
        require_perm(ctx, "users.manage")
        body = ctx.json_body(_ROLE_SCHEMA)
        try:
            users.set_role(ctx.params["name"], body["role"])
        except KeyError as exc:
            raise HttpFail(404, str(exc)) from None
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        return ctx.json({"ok": True, "name": ctx.params["name"],
                         "role": body["role"]})

    @app.post("/api/users/<name>/reset")
    def users_reset(ctx):
        require_perm(ctx, "users.manage")
        body = ctx.json_body(_RESET_SCHEMA)
        try:
            users.reset_password(ctx.params["name"], body["password"])
        except KeyError as exc:
            raise HttpFail(404, str(exc)) from None
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        return ctx.json({"ok": True, "name": ctx.params["name"]})

    @app.delete("/api/users/<name>")
    def users_remove(ctx):
        require_perm(ctx, "users.manage")
        try:
            users.remove(ctx.params["name"])
        except KeyError as exc:
            raise HttpFail(404, str(exc)) from None
        return ctx.json({"ok": True})

    # ------------------------------------------------ 产品目录与状态（只读公开）
    @app.get("/api/products")
    def products(ctx):
        return ctx.json({"products": manager.listing(),
                         "portal": {"framework": "webframe", "port": app.port,
                                    "user": ctx.session.get("user"),
                                    "role": ctx.session.get("role"),
                                    "username": USERNAME,
                                    "envelope_active": auth.envelope_active}})

    @app.get("/api/products/<pid>/status")
    def product_status(ctx):
        pid = get_pid(ctx)
        return ctx.json(manager.status(pid))

    # ---------------- 状态实时推送（WebSocket，2026-10-12，GAP P0 升级动作）
    # 升级握手/帧协议全在 netlab（手写 RFC 6455）。探活绝不进事件循环线程：
    # Windows 回环对未监听端口 connect_ex 每次约 0.6s，9 产品一轮 5s+，同步做
    # 会把整个循环（含其他 WS 与 HTTP）卡死——快照一律取自 UptimeMonitor 后台
    # 采样线程（起跑即采一轮），管理动作 start/stop 后 poke 立即触发新采样。
    # 变化检测：2s 一次比对 (id, online, pid) 签名——pid 覆盖启停/崩溃，
    # online 覆盖探活漂移；名称/端口这类不变量不进签名。
    @app.ws("/ws/status")
    def ws_status(session):
        import json as _json
        import time as _time
        monitor = getattr(manager, "uptime", None)
        state = {"sig": None, "due": 0.0}
        POLL_SECONDS = 2.0

        def _sig(products):
            return [(p["id"], p["online"], p["pid"]) for p in products]

        def send_status():
            if monitor is None:               # 无采样器（测试手工装配）不推
                return
            products = monitor.snapshot()
            if products is None:              # 采样器还没跑出第一轮：让前端
                return                        # 先用初始 HTTP 数据，下一轮再推
            state["sig"] = _sig(products)
            session.send(_json.dumps({"type": "status", "products": products},
                                     ensure_ascii=False))

        def on_message(text):
            send_status()                     # 任何消息（含 ping）都回最新快照

        def on_poll():
            now = _time.monotonic()
            if now < state["due"] or session.closing or monitor is None:
                return
            state["due"] = now + POLL_SECONDS
            products = monitor.snapshot()
            if products is None:
                return
            sig = _sig(products)
            if sig != state["sig"]:
                state["sig"] = sig
                session.send(_json.dumps({"type": "status", "products": products},
                                         ensure_ascii=False))

        send_status()
        session.on_message = on_message
        session.on_poll = on_poll

    # ------------------------------------------------ 探活历史（只读公开）
    @app.get("/api/history")
    def uptime_history(ctx):
        """探活历史（监控大盘时序维度）：后台采样器每 10s 一轮 TCP 探活，
        环形缓冲约 6 小时。位掩码按 products 顺序编码在线状态——10 产品
        2160 采样也只有几十 KB，前端解位画状态条。"""
        monitor = getattr(manager, "uptime", None)
        if monitor is None:
            return ctx.json({"interval": None, "products": [], "samples": []})
        return ctx.json(monitor.history())

    # ------------------------------------------------ 管理动作（要求登录）
    def _poke_monitor() -> None:
        """启停后让采样线程立刻跑一轮：/ws/status 推送延迟从 10s 降到毫秒级。"""
        monitor = getattr(manager, "uptime", None)
        if monitor is not None:
            monitor.poke()

    @app.post("/api/products/<pid>/start")
    def product_start(ctx):
        user = require_perm(ctx, "product.start")         # viewer 只读（RBAC）
        pid = get_pid(ctx)
        try:
            result = ctx.json(manager.start(pid, user=user))
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        except AlreadyOnline as exc:
            raise HttpFail(409, str(exc)) from None
        _poke_monitor()
        return result

    @app.post("/api/products/<pid>/stop")
    def product_stop(ctx):
        user = require_perm(ctx, "product.stop")
        pid = get_pid(ctx)
        try:
            result = ctx.json(manager.stop(pid, user=user))
        except NotOurs as exc:
            raise HttpFail(409, str(exc)) from None
        _poke_monitor()
        return result

    # ------------------------------------------------ 操作审计（M2，要求登录）
    @app.get("/api/audit")
    def audit_events(ctx):
        require_perm(ctx, "audit.read")
        raw = ctx.query.get("limit", "200")
        try:
            limit = int(raw)
        except ValueError:
            raise HttpFail(400, "limit 要是整数") from None
        events = manager.audit.tail(limit) if manager.audit is not None else []
        return ctx.json({"events": events})

    # ------------------------------------------------ 页面与静态
    @app.get("/")
    def index(ctx):
        page = (WEB_ROOT / "index.html").read_bytes()
        return Response(page, content_type="text/html; charset=utf-8")

    # ------------------------------------------------ 多页面（轮四十六页面分工）
    for _page in ("audit", "team", "account", "login", "console"):
        def _make_page(name):
            def page_view(ctx):
                page = (WEB_ROOT / (name + ".html")).read_bytes()
                return Response(page, content_type="text/html; charset=utf-8")
            return page_view
        app.get("/" + _page)(_make_page(_page))
        app.get("/" + _page + ".html")(_make_page(_page))   # 直接敲 .html 也达

    # ------------------------------------------------ 演示数据代理（轮四十七）
    # 控制台页与产品跨端口（跨源），门户页 JS 直接 fetch 产品会被 CORS 拦——
    # 由门户服务端同源转发。只白名单演示端点，不做成通用代理。
    def _forward(port: int, method: str, path: str, payload=None):
        import json as _json
        import urllib.error
        import urllib.request
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}))       # 项目坑：系统代理必须显式绕开
        data = _json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (port, path), data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {})
        try:
            resp = opener.open(req, timeout=10)
            return _json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError:
            return None                            # 上游 4xx：调用方按失败计数
        except urllib.error.URLError:
            return None                            # 产品瞬断

    @app.post("/api/demo/<pid>")
    def demo_inject(ctx):
        pid = get_pid(ctx)
        p = manager.by_id[pid]
        if pid == "cachekv":
            _forward(p.port, "POST", "/api/demo")
            return ctx.json({"ok": True,
                             "note": "已注入 12 个演示键（混合 TTL），统计页现在有账可看"})
        if pid == "sensorhub":
            status = _forward(p.port, "GET", "/api/status")
            devices = [d["device"] if isinstance(d, dict) else d
                       for d in (status.get("devices") or [])]
            if not devices:
                raise HttpFail(409, "broker 里还没有设备，无法注入读数")
            import math
            ok = 0
            for di, dev in enumerate(devices):
                for i in range(8):
                    # seq 省略（服务端 next_seq）；anomaly 不发——离群标记是引擎自己的语义
                    payload = {"device": dev,
                               "temp": round(40 + 12 * math.sin(i / 2 + di) + di * 3, 1),
                               "vib": round(1.5 + 0.8 * math.cos(i / 3 + di), 2)}
                    if _forward(p.port, "POST", "/api/inject", payload) is not None:
                        ok += 1
            if ok == 0:
                raise HttpFail(502, "读数注入全部被上游拒绝")
            return ctx.json({"ok": True,
                             "note": "已注入 %d 台设备 × 8 拍演示读数（成功 %d）"
                                     % (len(devices), ok)})
        raise HttpFail(409, "%s 不需要演示数据" % p.name)

    app.static("/static", WEB_ROOT)
    return app


def build_server(*, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 linkbox_port: int = 8018, lab_port: int = 7788,
                 simlab_port: int = 8019, datascope_port: int = 8020,
                 cachekv_port: int = 8021, sensorhub_port: int = 8022,
                 board_port: int = 8023, courselab_port: int = 8024,
                 linkbox_memory: bool = False,
                 uptime_interval: float = 10.0,
                 data_dir: str | Path | None = None
                 ) -> tuple["StudioServer", ProductManager, Auth]:
    auth = Auth(data_dir or DATA_DIR)
    data = Path(data_dir or DATA_DIR)
    users = UserStore(data)
    manager = build_manager(linkbox_port, lab_port, simlab_port=simlab_port,
                            datascope_port=datascope_port,
                            cachekv_port=cachekv_port,
                            sensorhub_port=sensorhub_port,
                            board_port=board_port,
                            courselab_port=courselab_port,
                            linkbox_memory=linkbox_memory,
                            audit_path=data / "audit.sqlite3")
    monitor = UptimeMonitor(manager, interval=uptime_interval)
    manager.uptime = monitor            # 探活历史挂在管理器上，/api/history 可取
    server = StudioServer(build_app(manager, auth, users=users), host=host, port=port)
    server.monitor = monitor
    return server, manager, auth


class StudioServer(MicroServer):
    """停机时收采样线程：探活线程是 daemon，不收也不会卡进程，
    但测试里先 stop 再重建 server 的路径必须保证旧线程真退出。"""

    def stop(self) -> None:
        monitor = getattr(self, "monitor", None)
        if monitor is not None:
            monitor.stop()
        super().stop()


def main(argv=None) -> int:
    import argparse
    import threading
    ap = argparse.ArgumentParser(description="Studio 产品门户（只绑回环）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--linkbox-port", type=int, default=8018)
    ap.add_argument("--lab-port", type=int, default=7788)
    args = ap.parse_args(argv)
    server, _, auth = build_server(host=args.host, port=args.port,
                                   linkbox_port=args.linkbox_port,
                                   lab_port=args.lab_port)
    port = server.start()
    server.monitor.start()
    print(f"Studio 门户已启动： http://127.0.0.1:{port}/   （Ctrl+C 退出）")
    print(f"探活历史： 每 {server.monitor.interval:.0f}s 采样一轮，"
          f"保留最近 {server.monitor.max_samples} 条（/api/history）")
    print(f"登录： 用户 {USERNAME}，初始口令在 {auth.dir / 'password.txt'}"
          "（首次启动自动生成，登录后请改）")
    print("管理动作（启停）需登录；目录与状态只读公开。跑在自研 webframe 上。")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n再见")
        server.monitor.stop()
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
