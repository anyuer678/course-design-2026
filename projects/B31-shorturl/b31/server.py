"""b31/server.py —— 把短链应用挂到 netlab 的事件循环上。

复用而不是重写：协议解析、多路复用、keep-alive、各类硬上限都在 B11 里，
本项目只补两件 B11 故意不管的应用层事情——

* **路由表换成短链的**；
* **对已知资源用错方法要回 405 + Allow**，而不是 404。
  B11 的默认路由只对"全局不支持的方法"判 405；`DELETE /l/abc` 这种"路径存在、方法不对"
  在它那里落到 404。REST 语义上 405 才有信息量：客户端能从 `Allow` 知道该怎么调。

入口 `python -m b31.server` 只绑回环地址（B11 的构造函数里就是这么要求的）。
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import signal
import threading
import time
from pathlib import Path

from netlab.server import Server

from .app import JSON_TYPE, ShortUrlApp
from .store import Store

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"


class ShortUrlServer(Server):
    def __init__(self, app: ShortUrlApp, *, host: str = "127.0.0.1", port: int = 0, **kwargs):
        super().__init__(host=host, port=port, **kwargs)
        self.app = app
        self.routes = app.routes()          # 覆盖掉 B11 演示用的键值路由

    def _dispatch(self, request):
        status, headers, body = super()._dispatch(request)
        if status != 404:
            return status, headers, body
        # 路由项是 ((方法, 模式), 处理函数)：解包时要把外层那对也拆开，
        # 写成 `for method, pattern in self.routes` 会让 pattern 变成处理函数本身。
        allowed = sorted({method for (method, pattern), _ in self.routes
                          if fnmatch.fnmatch(request.path, pattern)})
        # 只在"这个路径存在、但当前方法不在许可里"时升级成 405。
        # 无条件升级会把 404 吞掉：GET 一个不存在的短码会被报成"GET 不支持"，
        # 而那恰恰是客户端最需要听清的一句话——码不存在。
        if allowed and request.method not in allowed:
            payload = json.dumps({"error": f"{request.path} 不支持 {request.method}，可用方法：{allowed}",
                                  "allow": allowed}, ensure_ascii=False).encode("utf-8") + b"\n"
            return 405, [("Allow", ", ".join(allowed)), JSON_TYPE], payload
        return status, headers, body

    def start(self) -> int:
        port = super().start()
        self.app.port = port          # 短链绝对地址要带真实端口
        return port


def build_server(*, db_path: str = ":memory:", web_root: Path = WEB_ROOT,
                 host: str = "127.0.0.1", port: int = 0,
                 idle_timeout: float = 5.0, clock=time.time) -> ShortUrlServer:
    store = Store(db_path)
    app = ShortUrlApp(store, web_root, self_hosts=(host, "localhost"), clock=clock)
    return ShortUrlServer(app, host=host, port=port, idle_timeout=idle_timeout)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="B31 短链系统（只绑回环，教学用）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "shorturl.sqlite"))
    parser.add_argument("--memory", action="store_true", help="不落盘，退出即忘")
    args = parser.parse_args(argv)

    server = build_server(db_path=":memory:" if args.memory else args.db, port=args.port)
    port = server.start()
    print(f"短链服务已启动： http://127.0.0.1:{port}/   （Ctrl+C 退出）")
    if not args.memory:
        print(f"数据库： {args.db}")
    print("接口： POST /api/links 建短链 · GET /l/<码> 跳转 · GET /api/links 列表 · GET /api/stats 汇总")
    stop = threading.Event()

    def on_signal(signum, frame):
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    try:
        stop.wait()
    finally:
        server.stop()
        server.app.store.close()
        print("已关闭。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
