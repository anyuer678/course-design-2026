"""planner/heuristics.py —— 启发式函数：曼哈顿 / 欧氏 / 对角(octile) / 零

课程要点（无人系统）：
    - 启发式就是"往目标还差多远"的**乐观估计**：A* 的正确性挂在两条性质上——
      **可采纳**（h ≤ 真实代价，不撒谎）与**一致/单调**（h(n) ≤ 步价 + h(n')，
      保证每个结点最多展开一次）；
    - 三档启发式不是随便列的，是与**运动模型配对**的：
        曼哈顿  只对 4 邻域可采纳（8 邻域里斜步只花 √2 < 2，曼哈顿会高估——反例见测试）
        欧氏    两边都可采纳（最松，h=直线距离 ≤ 任何实际路径）
        对角    与 8 邻域配套的最紧选择（octile = (dx+dy) + (√2-2)·min(dx,dy)）
    - `zero` 不是凑数：h≡0 的 A* **就是** Dijkstra——这给了"对拍参照"一个不花成本的实现。
"""
from __future__ import annotations

from planner.grid import SQRT2


def manhattan(a, b) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def euclidean(a, b) -> float:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return (dx * dx + dy * dy) ** 0.5


def octile(a, b) -> float:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    lo, hi = (dx, dy) if dx <= dy else (dy, dx)
    return (hi - lo) + SQRT2 * lo          # 先斜走 lo 步，再直走


def zero(a, b) -> float:
    return 0.0


HEURISTICS = {"manhattan": manhattan, "euclidean": euclidean,
              "octile": octile, "zero": zero}
