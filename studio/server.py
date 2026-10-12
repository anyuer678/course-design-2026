"""studio/server.py —— P0 Studio 产品门户：产品目录 / 状态面板 / 一键启停 / 登录。

关键事实：**门户自己就跑在 webframe 微框架上**——路由装饰器、静态文件、
JSON 体校验、签名会话全是框架能力，这是"框架是真交付物"的现场证明。
鉴权口径：单用户（owner），目录与状态只读公开；**启停等管理动作要求登录**
（401）；实验台（showcase lab）并入门户托管，启停同权。
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
except ImportError:                     # 作为脚本直接跑（python server.py）
    from audit import AuditLog
    from auth import USERNAME, Auth
    from manager import AlreadyOnline, NotOurs, Product, ProductManager

WEB_ROOT = ROOT / "web"
DATA_DIR = ROOT / "data"
DEFAULT_PORT = 8017                # 8018 留给 LinkBox，8000 是 B31，7788 是实验台

_START_SCHEMA = {}
_LOGIN_SCHEMA = {"username": (str, True), "password": (str, True)}
_PASSWORD_SCHEMA = {"old": (str, True), "new": (str, True)}


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
        Product("studio", "Studio 门户", "产品目录 / 一键启停 / 状态面板（就是你正在看的这个）"),
        Product("linkbox", "LinkBox 工具站",
                "短链 / 文本暂存 / 二维码 / 访问口令（引擎桥接 B31/B11）",
                port=linkbox_port, command=cmd, cwd=str(REPO / "linkbox")),
        Product("lab", "展示层实验台",
                "33 页展示页的本地后端控制台：起停项目服务、发原始请求（showcase/lab.py）",
                port=lab_port,
                command=[sys.executable, "lab.py", "--port", str(lab_port)],
                cwd=str(REPO / "showcase")),
        Product("simlab", "SimLab 仿真馆",
                "真实引擎的运行记录回放：帧全来自引擎现算，不是画出来的演示",
                port=simlab_port,
                command=[sys.executable, "server.py", "--port", str(simlab_port)],
                cwd=str(REPO / "simlab")),
        Product("datascope", "DataScope 数据工作台",
                "CSV 画像 / 清洗管线 / 关联与聚类挖掘（引擎桥接 B26）",
                port=datascope_port,
                command=[sys.executable, "server.py", "--port", str(datascope_port)],
                cwd=str(REPO / "datascope")),
        Product("cachekv", "CacheKV 缓存",
                "自托管键值缓存：TTL / 快照持久化 / 统计页（引擎桥接 B38）",
                port=cachekv_port,
                command=[sys.executable, "server.py", "--port", str(cachekv_port)],
                cwd=str(REPO / "cachekv")),
        Product("sensorhub", "SensorHub 物联网监测",
                "传感器 → MQTT → SQLite → 曲线 → 告警（吸收 B35 手写 broker）",
                port=sensorhub_port,
                command=[sys.executable, "server.py", "--port", str(sensorhub_port)],
                cwd=str(REPO / "sensorhub")),
        Product("courselab", "CourseLab 课程工坊",
                "课程项目平台：课程 / 在线实验 / 任务 / 通知 / 管理端（M0-M11 全交付）",
                port=courselab_port,
                command=[sys.executable, "server.py", "--port", str(courselab_port)],
                cwd=str(REPO / "courselab")),
        Product("board", "画板桌面应用",
                "本地绘图 + PNG 导出 + 自动备份（引擎复用 B14）；门户启动即开画图窗口，"
                "手动开窗 python board/launch.py --window",
                port=board_port,
                command=[sys.executable, "launch.py", "--port", str(board_port),
                         "--managed-window"],
                cwd=str(REPO / "board"),
                kind="desktop",             # 8023 是探活行协议口（BOARD 8023 OK），不是 HTTP——门户不给"打开产品"
                boot_timeout=25.0),         # JVM 冷启动：慢 runner 上 10s 不够（2026-10-12 CI 实测）
        Product("boardweb", "画板 Web 版",
                "浏览器画板：图形工具 / 选择微调 / 贴图粘贴 / 撤销重做 / 自动备份"
                "（桌面 Swing 版并存，:8023）",
                port=boardweb_port,
                command=[sys.executable, "server.py", "--port", str(boardweb_port)],
                cwd=str(REPO / "boardweb")),
    ]
    audit = AuditLog(audit_path) if audit_path else None
    return ProductManager(products, audit=audit)


def build_app(manager: ProductManager, auth: Auth) -> MicroApp:
    app = MicroApp(session_secret=auth.secret)

    def require_user(ctx) -> None:
        """已登录且世代匹配。改口令后旧世代会话一律重新登录。"""
        if not ctx.session.get("user"):
            raise HttpFail(401, "请先登录（POST /api/login）")
        if ctx.session.get("gen") != auth.generation:
            raise HttpFail(401, "口令已更新，请重新登录")

    def get_pid(ctx) -> str:
        pid = ctx.params["pid"]
        if pid not in manager.by_id:
            raise HttpFail(404, f"没有叫 {pid!r} 的产品")
        return pid

    # ------------------------------------------------ 认证
    @app.post("/api/login")
    def login(ctx):
        body = ctx.json_body(_LOGIN_SCHEMA, allow_unknown=True)
        if body["username"] != USERNAME or not auth.verify(body["password"]):
            raise HttpFail(401, "用户名或口令不对")     # 不区分哪个错（不给猜测者喂信息）
        ctx.session["user"] = USERNAME
        ctx.session["gen"] = auth.generation           # 改口令即踢旧世代会话
        return ctx.json({"user": USERNAME})

    @app.post("/api/logout")
    def logout(ctx):
        ctx.reset_session()                   # 强制回写空会话，覆盖浏览器旧 cookie
        return ctx.json({"user": None})

    @app.get("/api/me")
    def me(ctx):
        return ctx.json({"user": ctx.session.get("user")})

    @app.post("/api/password")
    def change_password(ctx):
        require_user(ctx)
        body = ctx.json_body(_PASSWORD_SCHEMA)
        if not auth.verify(body["old"]):
            raise HttpFail(400, "旧口令不对")
        try:
            auth.set_password(body["new"])
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        auth.bump_generation()                # 旧世代会话（含本会话）全部失效
        return ctx.json({"changed": True})

    # ------------------------------------------------ 产品目录与状态（只读公开）
    @app.get("/api/products")
    def products(ctx):
        return ctx.json({"products": manager.listing(),
                         "portal": {"framework": "webframe", "port": app.port,
                                    "user": ctx.session.get("user"),
                                    "username": USERNAME}})

    @app.get("/api/products/<pid>/status")
    def product_status(ctx):
        pid = get_pid(ctx)
        return ctx.json(manager.status(pid))

    # ------------------------------------------------ 管理动作（要求登录）
    @app.post("/api/products/<pid>/start")
    def product_start(ctx):
        require_user(ctx)
        pid = get_pid(ctx)
        try:
            return ctx.json(manager.start(pid))
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        except AlreadyOnline as exc:
            raise HttpFail(409, str(exc)) from None

    @app.post("/api/products/<pid>/stop")
    def product_stop(ctx):
        require_user(ctx)
        pid = get_pid(ctx)
        try:
            return ctx.json(manager.stop(pid))
        except NotOurs as exc:
            raise HttpFail(409, str(exc)) from None

    # ------------------------------------------------ 操作审计（M2，要求登录）
    @app.get("/api/audit")
    def audit_events(ctx):
        require_user(ctx)
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

    app.static("/static", WEB_ROOT)
    return app


def build_server(*, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 linkbox_port: int = 8018, lab_port: int = 7788,
                 simlab_port: int = 8019, datascope_port: int = 8020,
                 cachekv_port: int = 8021, sensorhub_port: int = 8022,
                 board_port: int = 8023, courselab_port: int = 8024,
                 linkbox_memory: bool = False,
                 data_dir: str | Path | None = None
                 ) -> tuple[MicroServer, ProductManager, Auth]:
    auth = Auth(data_dir or DATA_DIR)
    manager = build_manager(linkbox_port, lab_port, simlab_port=simlab_port,
                            datascope_port=datascope_port,
                            cachekv_port=cachekv_port,
                            sensorhub_port=sensorhub_port,
                            board_port=board_port,
                            courselab_port=courselab_port,
                            linkbox_memory=linkbox_memory,
                            audit_path=Path(data_dir or DATA_DIR) / "audit.sqlite3")
    server = MicroServer(build_app(manager, auth), host=host, port=port)
    return server, manager, auth


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
    print(f"Studio 门户已启动： http://127.0.0.1:{port}/   （Ctrl+C 退出）")
    print(f"登录： 用户 {USERNAME}，初始口令在 {auth.dir / 'password.txt'}"
          "（首次启动自动生成，登录后请改）")
    print("管理动作（启停）需登录；目录与状态只读公开。跑在自研 webframe 上。")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n再见")
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
