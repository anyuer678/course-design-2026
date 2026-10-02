"""algo/dp.py —— 动态规划：0/1 背包，含最优方案还原。

**状态与转移**：``f[i][w]`` = 只考虑前 i 件物品、容量 w 时的最大价值。

    f[i][w] = max(f[i-1][w], f[i-1][w - wt_i] + val_i)      # 不选 / 选第 i 件
    f[0][w] = 0

**为什么这个顺序对**：``f[i]`` 只依赖 ``f[i-1]``，所以 i 从小到大填即可；
每个 w 彼此独立，一个循环内可任意顺序。

**一维滚动必须让 w 从大到小**：正向遍历会让 ``f[w - wt]`` 已经是"本轮更新过"的值，
同一件物品被重复装入——那正好是完全背包的写法。同一个循环方向决定了两种不同的问题，
这是 DP 最典型的"看不见的状态依赖"。

**方案还原**：从 ``f[n][capacity]`` 往回走，若 ``f[i][w] != f[i-1][w]`` 说明第 i 件被选了。
前提是价值非负且转移只取 max；有负价值时"不相等"不再等价于"被选中"，
本实现直接拒绝负价值（见校验）。
"""
from __future__ import annotations

from itertools import combinations


class DpError(ValueError):
    pass


def _check(weights, values, capacity):
    if len(weights) != len(values):
        raise DpError("物品数不一致：weights 与 values 长度不同")
    if capacity < 0:
        raise DpError(f"容量不能为负：{capacity}")
    if any(w < 0 for w in weights):
        raise DpError("物品重量不能为负")
    if any(v < 0 for v in values):
        raise DpError("物品价值不能为负：还原方案依赖非负价值的单调性")


def knapsack_table(weights, values, capacity):
    """完整 DP 表，``table[i][w]`` = 前 i 件、容量 w 的最大价值。演示与自查用。"""
    _check(weights, values, capacity)
    table = [[0] * (capacity + 1) for _ in range(len(weights) + 1)]
    for i, (wt, val) in enumerate(zip(weights, values), start=1):
        row, prev = table[i], table[i - 1]
        for w in range(capacity + 1):
            take = prev[w - wt] + val if w >= wt else -1
            row[w] = take if take > prev[w] else prev[w]
    return table


def knapsack(weights, values, capacity):
    """返回 (最优价值, 选中的物品下标元组)。用 O(n·W) 的表，为的是能还原方案。"""
    table = knapsack_table(weights, values, capacity)
    chosen = []
    w = capacity
    for i in range(len(weights), 0, -1):
        if table[i][w] != table[i - 1][w]:
            chosen.append(i - 1)
            w -= weights[i - 1]
    return table[-1][capacity], tuple(sorted(chosen))


def knapsack_rolling(weights, values, capacity) -> int:
    """一维滚动数组：容量倒序是"每件只能用一次"的全部秘密。"""
    _check(weights, values, capacity)
    best = [0] * (capacity + 1)
    for wt, val in zip(weights, values):
        for w in range(capacity, wt - 1, -1):       # 正序就会重复装同一件
            if best[w - wt] + val > best[w]:
                best[w] = best[w - wt] + val
    return best[capacity]


def knapsack_rolling_wrong_way(weights, values, capacity) -> int:
    """故意写错的方向：完全背包。留着它是因为"错误也该能被看见"。"""
    best = [0] * (capacity + 1)
    for wt, val in zip(weights, values):
        for w in range(wt, capacity + 1):           # 正序 = 同一件可重复选
            if best[w - wt] + val > best[w]:
                best[w] = best[w - wt] + val
    return best[capacity]


def knapsack_brute(weights, values, capacity):
    """参照实现：枚举所有子集。O(2^n)，只用于小规模对拍。"""
    _check(weights, values, capacity)
    best, chosen = 0, ()
    for size in range(len(weights) + 1):
        for combo in combinations(range(len(weights)), size):
            total_w = sum(weights[i] for i in combo)
            total_v = sum(values[i] for i in combo)
            if total_w <= capacity and (total_v, -size) > (best, -len(chosen)):
                best, chosen = total_v, combo
    return best, chosen
