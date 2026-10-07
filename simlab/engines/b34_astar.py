"""simlab/engines/b34_astar.py —— B34 真实引擎（planner.search.best_first）的帧适配。

不重写搜索：直接调用 B34 的 astar/dijkstra（同一个 best_first 循环，h=0 就是
Dijkstra——B34 的核心教学点），SearchResult.expanded（展开顺序）是引擎产出的
确定性序列（B34 保证了同图两次运行逐字节一致），逐格成帧。
"""
from __future__ import annotations

import planner.heuristics as heur
from planner.grid import Grid
from planner.search import astar, dijkstra

ENGINE = "B34 planner.search.best_first（原项目 import，未重写）"

_HEURISTICS = {"manhattan": heur.manhattan, "euclidean": heur.euclidean,
               "octile": heur.octile, "zero": heur.zero}

PARAM_SCHEMA = {
    "width": {"type": "int", "default": 12, "min": 1, "label": "网格宽"},
    "height": {"type": "int", "default": 8, "min": 1, "label": "网格高"},
    "walls": {"type": "cell-list",
              "default": [[2, 1], [2, 2], [2, 3], [2, 4], [5, 4], [5, 5],
                          [5, 6], [8, 1], [8, 2], [8, 3]],
              "label": "障碍格 [x, y]"},
    "start": {"type": "cell", "default": [0, 0], "label": "起点"},
    "goal": {"type": "cell", "default": [11, 7], "label": "终点"},
    "diagonal": {"type": "bool", "default": False, "label": "允许斜走"},
    "heuristic": {"type": "enum", "options": sorted(_HEURISTICS),
                  "default": "manhattan", "label": "启发函数"},
}


def _cell(value) -> bool:
    return (isinstance(value, list) and len(value) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in value))


def _check_params(params: dict) -> None:
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")
    for name in ("width", "height"):
        value = params.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 200:
            raise ValueError(f"{name} 必须是 1..200 的整数（网格规模上限，防实时重算被大参数拖死）")
    walls = params.get("walls", [])
    if not isinstance(walls, list) or any(not _cell(c) for c in walls):
        raise ValueError("walls 必须是 [x, y] 的数组")
    if len(walls) > 40000:
        raise ValueError("walls 数量上限 40000（网格规模上限）")
    for name in ("start", "goal"):
        if not _cell(params.get(name)):
            raise ValueError(f"{name} 必须是 [x, y]")
    h = params.get("heuristic", "manhattan")
    if h not in _HEURISTICS:
        raise ValueError(f"heuristic 只能是 {sorted(_HEURISTICS)}，收到 {h!r}")


def run(params: dict) -> dict:
    _check_params(params)
    width, height = params["width"], params["height"]
    walls = {tuple(c) for c in params.get("walls", [])}
    start = tuple(params["start"])
    goal = tuple(params["goal"])
    grid = Grid(width=width, height=height, obstacles=walls,
                allow_diagonal=bool(params.get("diagonal")))
    heuristic = _HEURISTICS[params.get("heuristic", "manhattan")]

    if params.get("heuristic") == "zero":
        result = dijkstra(grid, start, goal)      # h=0 的 best_first 就是 Dijkstra
    else:
        result = astar(grid, start, goal, heuristic)

    # 帧 = 引擎的展开序列逐格前缀（真实产出，确定性由 B34 保证）
    frames = []
    for i, node in enumerate(result.expanded):
        frames.append({
            "t": i,
            "caption": f"展开第 {i + 1} 格 {node}"
                       + ("——到达目标！" if node == goal else ""),
            "state": {"current": list(node), "expanded": [list(c) for c in result.expanded[:i + 1]]},
            "highlights": [list(node)],
        })
    metrics = {
        "found": result.found,
        "cost": result.cost if result.found else None,
        "path": [list(c) for c in result.path] if result.found else None,
        "expanded_count": result.expanded_count,
    }
    algo_name = "Dijkstra（h=0）" if params.get("heuristic") == "zero" else \
        f"A*（h={params.get('heuristic', 'manhattan')}）"
    return {
        "experiment": "b34-astar",
        "title": f"{algo_name} 网格寻路：{width}×{height}，{len(walls)} 个障碍",
        "engine": ENGINE,
        "params": params,
        "frames": frames,
        "metrics": metrics,
        "notes": "帧 = SearchResult.expanded 逐格前缀（B34 保证同图两次运行逐字节一致）",
    }
