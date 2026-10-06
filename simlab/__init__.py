"""simlab —— P5 仿真馆的地基：统一运行记录格式 + 真实引擎适配器（PRODUCTS.md §五 轮三之一）。

立场（零件库原则，PLAN §6）：
    - **引擎一律 import 原项目的真实实现**，本包绝不重写第二套算法——
      simlab 只做"参数进 → 引擎跑 → 帧序列出"的适配层；
    - 帧的全部内容来自引擎的真实产出（回调快照 / 返回的表与展开序列），
      播放器播的是计算过程本身，不是第二套实现；
    - 运行记录格式 simlab-run/v1 可校验、可版本化，是后续播放器/对比器的公共契约。

已接入引擎：b12-dijkstra（B12 on_settle 回调）、b12-knapsack（B12 DP 表）、
b34-astar（B34 best_first 展开序列）。B9 是 C 项目没有可 import 的
Python 引擎，按"不重写第二套"纪律不接入（如实登记）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO / "projects" / "B12-algo-arena",
           _REPO / "projects" / "B34-path-planner"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from .record import RecordError, build, load, save, validate   # noqa: E402,F401
from .engines import ENGINES, param_schema, run_experiment     # noqa: E402,F401

__all__ = ["RecordError", "build", "load", "save", "validate",
           "ENGINES", "run_experiment", "param_schema"]
