"""webframe/server.py —— 把 MicroApp 挂到 netlab 事件循环上（B31 同构，更薄）。

协议层一切照旧归 netlab：解析、keep-alive、多路复用、硬上限、
HEAD 的"按 GET 体长写 Content-Length 但不发体"。OPTIONS 501 等分发语义
在 MicroApp.handle 里；本层只做两件事：委托 + start() 回填端口。
"""
from __future__ import annotations

from netlab.server import Server

from .app import MicroApp


class MicroServer(Server):
    def __init__(self, app: MicroApp, *, host: str = "127.0.0.1", port: int = 0,
                 **kwargs):
        super().__init__(host=host, port=port, **kwargs)
        self.micro = app

    def _match_ws(self, path: str):
        """桥接 MicroApp 的 <param> 规则到 netlab 的 WS 升级分发。"""
        for compiled, handler in self.micro.ws_routes:
            m = compiled.match(path)
            if m:
                return handler, m.groupdict()
        return None, None

    def _dispatch(self, request):
        return self.micro.handle(request)

    def start(self) -> int:
        port = super().start()
        self.micro.port = port
        return port
