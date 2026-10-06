"""webframe —— 站在本仓库自己的 netlab 协议层之上的微框架（PRODUCTS.md 共享地基 #1）。

定位与纪律：
    - **只做协议层之上的事**：HTTP 解析、多路复用、硬上限仍是 B11 netlab 的职责，
      本包不重写第二套——重写第二套正是 PLAN §6 反对的事；
    - **零依赖文化**：不引入 Flask；标准库 + netlab；
    - **框架本身是可测试交付物**：tests/ 双入口，公开向量式的性质断言；
    - 被它服务的产品：studio（P0），后续 P1/P4/P6（见 PRODUCTS.md §四）。

能力清单（对应 PRODUCTS.md §四.1 的五项）：
    1. 路由装饰器：@app.get("/api/x/<param>")，<param> 编译成命名分组；
    2. 静态文件：类型白名单 + 真实路径必须留在根里（B31 的守卫照搬）；
    3. Cookie 会话：HMAC-SHA256 签名 JSON（无服务端存储，恒时比较验签）；
    4. JSON 体校验：schema 类型表（bool 不算 int——B23/B31 教出来的规矩）；
    5. 模板片段：${name} 自动转义，Raw() 显式放行，缺键报错不静默。
"""
from __future__ import annotations

import sys
from pathlib import Path

# netlab 桥接：本仓库 B11 的协议层（幂等；入口脚本不再各自搬运）
_B11 = Path(__file__).resolve().parents[1] / "projects" / "B11-net-lab"
if str(_B11) not in sys.path:
    sys.path.insert(0, str(_B11))

from .app import Ctx, HttpFail, MicroApp, Response           # noqa: E402,F401
from .server import MicroServer                              # noqa: E402,F401
from .template import Raw, esc, render                       # noqa: E402,F401
from .validate import ValidationError, validate              # noqa: E402,F401

__all__ = ["MicroApp", "MicroServer", "Ctx", "Response", "HttpFail",
           "validate", "ValidationError", "render", "esc", "Raw"]
