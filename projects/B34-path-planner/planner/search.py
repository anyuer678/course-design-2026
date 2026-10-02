"""planner/search.py —— 统一 best-first 搜索框架：A* / Dijkstra / BFS 同源

课程要点：
    - **A* 与 Dijkstra 是同一个循环**，只差启发式：f = g（Dijkstra） vs f = g + h（A*）。
      一个 `best_first()` 就把两者连同"扩展数对比"一起给了——对拍不需要两套代码，
      只需要一个参数（h=0）；
    - **BFS 只在"每步同价"时与它们等价**：4 邻域每步 1 时 BFS 按层扩散 = Dijkstra；
      8 邻域斜步 √2 一出现，BFS 的"层数"就不再是代价——所以本实现**明确拒绝**
      在对角模式下用 BFS，而不是悄悄给个错答案；
    - 展开顺序做**确定性**处理：邻居顺序固定 + 堆内并列用插入序号破平——同一张图
      两次运行逐字节一致（可视化的"重放"与"对拍"都吃这条）。
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from math import inf

from planner.grid import Grid
from planner.heuristics import zero


@dataclass
class SearchResult:
    found: bool
    cost: float = inf
    path: list = field(default_factory=list)     # [start, ..., goal]
    expanded: list = field(default_factory=list)  # 展开顺序（地图上的结点序列）
    reason: str = ""

    @property
    def expanded_count(self) -> int:
        return len(self.expanded)


def best_first(grid: Grid, start, goal, heuristic=zero, name: str = "best-first") -> SearchResult:
    """A*/Dijkstra 的共同循环。heuristic(a, b) 必须估计"a→b 的剩余代价"。"""
    grid.require_free(start, goal)
    counter = 0
    open_heap = [(heuristic(start, goal), counter, start)]
    g = {start: 0.0}
    parent: dict = {}
    closed = set()
    expanded: list = []
    while open_heap:
        _f, _tie, node = heapq.heappop(open_heap)
        if node in closed:
            continue
        closed.add(node)
        expanded.append(node)
        if node == goal:
            return SearchResult(found=True, cost=g[goal], path=_reconstruct(parent, start, goal),
                                expanded=expanded)
        for nbr, step in grid.neighbors(node):
            tentative = g[node] + step
            if tentative < g.get(nbr, inf) - 1e-9:
                g[nbr] = tentative
                parent[nbr] = node
                counter += 1
                heapq.heappush(open_heap, (tentative + heuristic(nbr, goal), counter, nbr))
    return SearchResult(found=False, reason=f"{name}: 目标不可达（开放表耗尽）", expanded=expanded)


def dijkstra(grid: Grid, start, goal) -> SearchResult:
    """h ≡ 0 的 best-first。"""
    return best_first(grid, start, goal, heuristic=zero, name="dijkstra")


def astar(grid: Grid, start, goal, heuristic) -> SearchResult:
    return best_first(grid, start, goal, heuristic=heuristic,
                      name=f"astar-{getattr(heuristic, '__name__', '?')}")


def bfs(grid: Grid, start, goal) -> SearchResult:
    """真 BFS（按层扩散）。仅 4 邻域（每步同价）时与 Dijkstra 等价——否则拒绝。"""
    if grid.allow_diagonal:
        raise ValueError("8 邻域斜步价 √2，不是'每步同价'——BFS 的层数不等于代价，拒绝执行")
    grid.require_free(start, goal)
    from collections import deque
    frontier = deque([start])
    seen = {start}
    parent: dict = {}
    order: list = []
    while frontier:
        node = frontier.popleft()
        order.append(node)
        if node == goal:
            return SearchResult(found=True, cost=float(len(_reconstruct(parent, start, goal)) - 1),
                                path=_reconstruct(parent, start, goal), expanded=order)
        for nbr, _step in grid.neighbors(node):
            if nbr not in seen:
                seen.add(nbr)
                parent[nbr] = node
                frontier.append(nbr)
    return SearchResult(found=False, reason="bfs: 目标不可达（队列耗尽）", expanded=order)


def true_distances_to(grid: Grid, goal) -> dict:
    """从 goal 出发的 Dijkstra，得到每个格子到目标的**真实最短代价**。

    网格边价与方向无关（无向图），所以"从 goal 出发"与"到 goal 的距离"等价——
    这是可采纳性检查（h ≤ 真实）的参照来源。"""
    grid.require_free(goal)
    counter = 0
    open_heap = [(0.0, counter, goal)]
    dist = {goal: 0.0}
    closed = set()
    while open_heap:
        d, _tie, node = heapq.heappop(open_heap)
        if node in closed:
            continue
        closed.add(node)
        for nbr, step in grid.neighbors(node):
            nd = d + step
            if nd < dist.get(nbr, inf) - 1e-9:
                dist[nbr] = nd
                counter += 1
                heapq.heappush(open_heap, (nd, counter, nbr))
    return dist


def max_admissibility_slack(grid: Grid, goal, heuristic) -> float:
    """max over 可达格子 (h(格子→goal) − 真实距离)。≤ 0 才算可采纳；> 0 的量就是"撒谎幅度"。"""
    dist = true_distances_to(grid, goal)
    worst = -inf
    for cell, d in dist.items():
        worst = max(worst, heuristic(cell, goal) - d)
    return worst


def validate_path(grid: Grid, path: list, start, goal) -> list[str]:
    """路径合法性检查，返回问题列表（空 = 合法）：端点、逐步相邻、格子在邻域合法。"""
    problems = []
    if not path:
        problems.append("空路径")
        return problems
    if path[0] != start:
        problems.append(f"起点不对：{path[0]} != {start}")
    if path[-1] != goal:
        problems.append(f"终点不对：{path[-1]} != {goal}")
    for prev, cur in zip(path, path[1:]):
        allowed = {nbr for nbr, _c in grid.neighbors(prev)}
        if cur not in allowed:
            problems.append(f"不允许的移动：{prev} -> {cur}")
    for cell in path:
        if not grid.free(cell):
            problems.append(f"路径穿过障碍物：{cell}")
    return problems


def _reconstruct(parent: dict, start, goal) -> list:
    if goal == start:
        return [start]
    if goal not in parent:
        return []
    path = [goal]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    return path
