"""simlab/engines/b12_knapsack.py —— B12 真实引擎（algo.dp.knapsack_table）的帧适配。

不重写算法：直接调用 B12 的 knapsack_table 拿**完整 DP 表**，
每行（前 i 件、各容量下的最优价值）就是引擎产出的一部分——逐行成帧；
方案还原直接用 B12 的 knapsack()（表回溯），不自己再写一遍。
"""
from __future__ import annotations

from algo.dp import knapsack, knapsack_table

ENGINE = "B12 algo.dp.knapsack_table + knapsack（原项目 import，未重写）"

PARAM_SCHEMA = {
    "weights": {"type": "int-list", "default": [2, 3, 4, 5], "label": "重量数组"},
    "values": {"type": "int-list", "default": [3, 4, 5, 8], "label": "价值数组"},
    "capacity": {"type": "int", "default": 9, "min": 0, "label": "背包容量"},
}


def _check_params(params: dict) -> None:
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")
    weights = params.get("weights")
    values = params.get("values")
    capacity = params.get("capacity")
    for name, value in (("weights", weights), ("values", values)):
        if not isinstance(value, list) or any(
                not isinstance(x, int) or isinstance(x, bool) for x in value):
            raise ValueError(f"{name} 必须是整数数组")
    if not isinstance(capacity, int) or isinstance(capacity, bool):
        raise ValueError("capacity 必须是整数")
    if not 0 <= capacity <= 5000:
        raise ValueError("capacity 必须是 0..5000（DP 表规模上限，防实时重算被大参数拖死）")
    if len(weights) != len(values):
        raise ValueError("weights 与 values 长度必须一致")
    if len(weights) > 200:
        raise ValueError("物品数上限 200（DP 表规模上限，防实时重算被大参数拖死）")
    if not weights:
        raise ValueError("至少要有一件物品")


def run(params: dict) -> dict:
    _check_params(params)
    weights = params["weights"]
    values = params["values"]
    capacity = params["capacity"]

    table = knapsack_table(weights, values, capacity)   # 引擎的整张 DP 表
    frames = [{
        "t": 0,
        "caption": "第 0 行：一件都没放，全容量价值 0",
        "state": {"row": list(table[0]), "rows": [list(table[0])], "item": None},
        "highlights": [],
    }]
    for i, (wt, val) in enumerate(zip(weights, values), start=1):
        frames.append({
            "t": len(frames),
            "caption": f"第 {i} 行：考虑第 {i - 1} 件物品（重 {wt}，值 {val}）",
            # rows = 引擎表的前 i+1 行（回放器要画累积表；全是 knapsack_table 产出）
            "state": {"row": list(table[i]), "rows": [list(r) for r in table[:i + 1]],
                      "item": i - 1, "weight": wt, "value": val},
            "highlights": [],
        })

    best, chosen = knapsack(weights, values, capacity)  # 引擎的方案还原
    frames.append({
        "t": len(frames),
        "caption": f"回溯完成：最优价值 {best}，选中物品 {list(chosen)}",
        "state": {"chosen": list(chosen), "best": best},
        "highlights": list(chosen),
    })
    return {
        "experiment": "b12-knapsack",
        "title": f"0-1 背包：{len(weights)} 件物品，容量 {capacity}",
        "engine": ENGINE,
        "params": params,
        "frames": frames,
        "metrics": {"best": best, "chosen": list(chosen),
                    "table_rows": len(table), "capacity": capacity},
        "notes": "帧 = DP 表的行（knapsack_table 真实产出）；方案 = knapsack 回溯",
    }
