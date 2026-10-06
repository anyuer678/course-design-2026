"""simlab/engines/b12_dijkstra.py —— B12 真实引擎（algo.graph.dijkstra）的帧适配。

不重写算法：直接调用 B12 的 dijkstra(n, edges, src, on_settle)，
on_settle(u, d, dist快照) 是引擎自带的"每轮选点"回调（教材那张表的来源）——
帧 = 回调快照，原样转 JSON（inf → None，JSON 没有无穷大）。
结果 metrics 与直接调用引擎的返回值同源，适配层不改语义。
"""
from __future__ import annotations

from algo.graph import dijkstra, path_of, undirected

from ..record import finite

ENGINE = "B12 algo.graph.dijkstra（原项目 import，未重写）"

# 参数表单描述（前端据此生成控件；default 即可跑通的示例参数）
PARAM_SCHEMA = {
    "n": {"type": "int", "default": 6, "min": 1, "label": "顶点数"},
    "edges": {"type": "edge-list",
              "default": [[0, 1, 2], [0, 2, 5], [1, 2, 1], [1, 3, 4],
                          [2, 3, 2], [3, 4, 3], [4, 5, 1]],
              "label": "边 [u, v, w]"},
    "src": {"type": "int", "default": 0, "min": 0, "label": "源点"},
    "dst": {"type": "int", "default": 5, "min": 0, "label": "目标点（可空）"},
    "directed": {"type": "bool", "default": False, "label": "有向边"},
}


def _check_params(params: dict) -> None:
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")
    n = params.get("n")
    edges = params.get("edges")
    src = params.get("src")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError("n 必须是正整数（顶点数）")
    if not isinstance(edges, list) or any(
            not isinstance(e, list) or len(e) != 3 for e in edges):
        raise ValueError("edges 必须是 [u, v, w] 三元组的数组")
    if not isinstance(src, int) or isinstance(src, bool):
        raise ValueError("src 必须是整数")
    dst = params.get("dst")
    if dst is not None and (not isinstance(dst, int) or isinstance(dst, bool)):
        raise ValueError("dst 必须是整数或 null")


def run(params: dict) -> dict:
    _check_params(params)
    n = params["n"]
    edges = [tuple(e) for e in params["edges"]]
    src = params["src"]
    dst = params.get("dst")
    edge_list = edges if params.get("directed") else undirected(edges)

    frames = []
    settled: list[int] = []

    def on_settle(u: int, d: float, dist_snapshot: list) -> None:
        settled.append(u)
        frames.append({
            "t": len(frames),
            "caption": f"永久确定顶点 {u}（距离 {d}）",
            "state": {"current": u, "current_dist": finite(d),
                      "dist": finite(dist_snapshot), "settled": list(settled)},
            "highlights": [u],
        })

    dist, prev = dijkstra(n, edge_list, src, on_settle=on_settle)
    path = None
    if dst is not None:
        try:
            path = path_of(prev, src, dst)
            path = None if not path else path
        except ValueError:
            path = None                     # 目标不可达：如实记录
    metrics = {
        "dist": {v: finite(d) for v, d in enumerate(dist)},
        "path": list(path) if path else None,
        "settled_count": len(settled),
    }
    if not frames:                          # 源点出不来：引擎一次都没 settle
        frames.append({"t": 0, "caption": "没有任何顶点被确定（源点不可用）",
                       "state": {}, "highlights": []})
    return {
        "experiment": "b12-dijkstra",
        "title": f"Dijkstra 最短路：从 {src}" + (f" 到 {dst}" if dst is not None else ""),
        "engine": ENGINE,
        "params": params,
        "frames": frames,
        "metrics": metrics,
        "notes": "帧 = on_settle 回调的 dist 快照（B12 引擎自带钩子，教材同款）",
    }
