"""cachekv —— P3 自托管键值缓存（PRODUCTS.md §五 轮五之一）。

零件库纪律：**KV 引擎与快照持久化直接 import B38 mini-redis 的真实实现**——
redislite.store.Store（SET/GET/DEL/EXPIRE/TTL/INCR、惰性+主动过期双策略、
clock 可注入）与 redislite.dbsnap（原子快照写）。CacheKV 只做产品层：
统计计数、HTTP API（webframe）、快照调度。零重写。
"""
from __future__ import annotations

import sys
from pathlib import Path

_B38 = Path(__file__).resolve().parents[1] / "projects" / "B38-mini-redis"
if str(_B38) not in sys.path:
    sys.path.insert(0, str(_B38))

from .engine import CacheKV, SnapshotSaver      # noqa: E402,F401

__all__ = ["CacheKV", "SnapshotSaver"]
