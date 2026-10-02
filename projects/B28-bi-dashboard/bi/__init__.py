"""B28-bi-dashboard —— 商务智能仪表盘，零依赖。

三件复用（本仓库的规矩：能用已有的就不写第二份）：
    B26-datamining `mining.clean`   清洗链与账本（缺陷注入 → 逐步清洗 → 计数逐数对账）
    B26-datamining `mining.apriori` / `mining.kmeans`   共购规则与客户分群
    B27-course-kg  `kg.graph` / `kg.viz`               指标血缘图与分层 SVG 渲染

这里做一件事：把两个项目的目录挂进 `sys.path`。之所以用路径而不是复制一份代码：
复制就会产生两份可以各自烂掉实现的东西，正是 PLAN §6 明令禁止的事
（B19 的"同一份解析逻辑不许写两遍"、B31 复用 B11 的 netlab 都是同一条纪律）。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECTS_DIR = Path(__file__).resolve().parents[2]        # bi/ → B28-bi-dashboard/ → projects/
B26_DIR = PROJECTS_DIR / "B26-datamining"
B27_DIR = PROJECTS_DIR / "B27-course-kg"

_REQUIRED = ((B26_DIR / "mining" / "clean.py", "B26-datamining/mining"),
             (B27_DIR / "kg" / "viz.py", "B27-course-kg/kg"))

for path, label in _REQUIRED:
    if not path.is_file():
        raise RuntimeError(
            f"没找到 {label}（期望 {path}）。B28 是构建在 B26/B27 之上的："
            "要么两个目录不在同一个 projects/ 下，要么它们被移动过。")

for directory in (B26_DIR, B27_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
