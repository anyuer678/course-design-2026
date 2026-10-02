"""B31-shorturl —— 短链系统。HTTP 层直接复用 B11 的 netlab，不写第二套解析器。

这里做一件小事：把 B11 的目录挂进 `sys.path`，让 `netlab` 可以被 import。
之所以用路径而不是复制一份：短链系统要验证的是"Web 应用那一层"（状态码、重定向语义、
输入校验、前后端职责），HTTP/1.1 子集的边界 B11 已经逐条测过了。复制一份代码
就会有两份可以各自烂掉的解析器，那正是这个仓库明令禁止的事。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECTS_DIR = Path(__file__).resolve().parents[2]      # b31/ → B31-shorturl/ → projects/
B11_DIR = PROJECTS_DIR / "B11-net-lab"

if not (B11_DIR / "netlab" / "http1.py").is_file():
    raise RuntimeError(
        f"没找到 B11 的 netlab（期望 {B11_DIR / 'netlab'}）。"
        "B31 是构建在它上面的：要么两个目录不在同一个 projects/ 下，要么 B11 被移动过。")

if str(B11_DIR) not in sys.path:
    sys.path.insert(0, str(B11_DIR))
