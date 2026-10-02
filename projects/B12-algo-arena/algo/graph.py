"""algo/graph.py —— 图：Dijkstra 单源最短路（非负权），另配两个参照实现。

**一个约定先讲清**：`edges` 一律按**有向**理解，谁的松弛都只按 `(u, v, w)` 的方向走。
无向图用 `undirected(edges)` 显式展开成双向边。这条规矩是用对拍换来的——
三个实现各自决定"要不要双向"时，比的就不是算法而是约定。

**Dijkstra 的正确性论证**（非负权是全部前提）：
每次从优先队列取出的 ``u`` 是"未确定点里估计最小的"。假设它的最短路还没找到，
真实最短路必然先经过另一个未确定点 ``x``；而 ``dist[x] >= dist[u]``（u 当时最小），
边权又非负，绕路不可能比 ``dist[u]`` 更短——矛盾。所以一取出就可以永久确定。

**惰性删除**：不做 decrease-key，而是把更小的估计再压一次，弹出时 ``d > dist[u]`` 就丢。
结论不变，代价是堆里最多留有 O(|E|) 条历史条目。

**参照实现**：
* Bellman-Ford：|V|-1 轮松弛，正确性只依赖"松弛足够多次"，允许负权；
  第 |V| 轮仍能松弛 ⟹ 存在可达负环。
* Floyd：``d[i][j] = min(d[i][j], d[i][k] + d[k][j])``，全源对照，对角线变负 ⟹ 负环。
"""
from __future__ import annotations

import heapq
from math import inf


class NegativeWeight(ValueError):
    """Dijkstra 在非负权之外没有正确性保证，所以直接拒绝而不是给一个错答案。"""


class NegativeCycle(ValueError):
    pass


def undirected(edges):
    """把无向边表展开成有向实现能直接吃的双向边表。"""
    expanded = []
    for u, v, w in edges:
        expanded.append((u, v, w))
        if u != v:
            expanded.append((v, u, w))
    return expanded


def _validate(n: int, edges, allow_negative: bool) -> None:
    for u, v, w in edges:
        if not (0 <= u < n and 0 <= v < n):
            raise ValueError(f"顶点越界：({u}, {v}) 不在 0..{n - 1}")
        if w < 0 and not allow_negative:
            raise NegativeWeight(f"边 {u}->{v} 权值 {w} 为负，Dijkstra 不适用，请改用 bellman_ford")


def dijkstra(n: int, edges, src: int, on_settle=None):
    """返回 (dist, prev)。不可达点 dist 为 inf、prev 为 None。

    `on_settle(u, d, dist)` 在每个顶点被**永久确定**的那一刻回调一次，
    拿到的是当时的 dist 快照——教材那张"每轮选点 + dist 表"就是这么来的。
    只用于演示与自查，不参与算法决策。
    """
    _validate(n, edges, allow_negative=False)
    if not 0 <= src < n:
        raise ValueError(f"源点越界：{src}")
    adjacency = [[] for _ in range(n)]
    for u, v, w in edges:
        adjacency[u].append((v, w))             # 方向由调用方用 undirected() 决定
    dist = [inf] * n
    prev = [None] * n
    dist[src] = 0
    heap = [(0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:                         # 惰性删除：这是被更新的旧估计
            continue
        if on_settle is not None:
            on_settle(u, d, list(dist))
        for v, w in adjacency[u]:
            if d + w < dist[v]:
                dist[v] = d + w
                prev[v] = u
                heapq.heappush(heap, (dist[v], v))
    return dist, prev


def bellman_ford(n: int, edges, src: int):
    """允许负权的参照实现；第 |V| 轮仍能松弛就说明有可达负环。"""
    _validate(n, edges, allow_negative=True)
    if not 0 <= src < n:
        raise ValueError(f"源点越界：{src}")
    dist = [inf] * n
    prev = [None] * n
    dist[src] = 0
    for round_index in range(n):
        changed = False
        for u, v, w in edges:
            if dist[u] == inf:
                continue
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                prev[v] = u
                changed = True
        if not changed:
            return dist, prev                   # 一整轮没有任何改进：已经收敛
        if round_index == n - 1:
            raise NegativeCycle(f"从源点 {src} 出发存在可达负环")
    return dist, prev


def floyd(n: int, edges):
    """全源参照实现，返回距离矩阵。"""
    _validate(n, edges, allow_negative=True)
    matrix = [[inf if i != j else 0 for j in range(n)] for i in range(n)]
    for u, v, w in edges:
        matrix[u][v] = min(matrix[u][v], w)
    for k in range(n):
        row_k = matrix[k]
        for i in range(n):
            dik = matrix[i][k]
            if dik == inf:
                continue
            row_i = matrix[i]
            for j in range(n):
                if row_k[j] != inf and dik + row_k[j] < row_i[j]:
                    row_i[j] = dik + row_k[j]
    for i in range(n):
        if matrix[i][i] < 0:
            raise NegativeCycle(f"顶点 {i} 落在负环上")
    return matrix


def path_of(prev, src: int, dst: int):
    """由前驱表还原路径；不可达（或前驱链走不到源点）返回 None。"""
    if prev[dst] is None and dst != src:
        return None
    node, route = dst, []
    while node is not None:
        route.append(node)
        if node == src:
            return route[::-1]
        node = prev[node]
    return None


def build_random_graph(n: int, edge_count: int, rng, *, directed: bool = False,
                       max_weight: int = 20):
    """随机带权图（允许重边、允许孤立点）：对拍最喜欢这种不规矩的输入。"""
    pairs = []
    for _ in range(edge_count):
        u, v = rng.randrange(n), rng.randrange(n)
        if u != v:
            pairs.append((u, v, rng.randint(1, max_weight)))
    return pairs if directed else undirected(pairs)
