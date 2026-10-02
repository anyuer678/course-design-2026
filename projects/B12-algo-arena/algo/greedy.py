"""algo/greedy.py —— 贪心：区间调度，以及"贪心什么时候不管用"。

**问题**：给一批带起止时间的任务，选出尽可能多的互不重叠任务。

**贪心策略**：每次都选"结束最早"的那个，然后跳过与它冲突的。

**交换论证（正确性）**：设贪心解第一个选的是 g，某个最优解第一个选的是 o。
按结束最早，``end(g) <= end(o)``。把最优解的第一个换成 g：g 结束得不比 o 晚，
原来排在 o 之后的任务照样放得下，所以存在一个"以 g 开头"的最优解。
剩下的区间构成同一个子问题，归纳即可。

**三条会失败的直觉**（本项目把它们写成可执行的对照，而不是嘴上说说）：
按开始时间最早 —— 一个长任务会挡住后面一串；
按时长最短 —— 短任务插在两个长任务中间会浪费整段；
按"价值/重量比" —— 0/1 背包里没有子结构，装不下就作废。
`smallest_counterexample` 会枚举小规模输入，把最早失败的那组找出来。
"""
from __future__ import annotations

from itertools import combinations


def is_feasible(intervals) -> bool:
    """一组区间两两不重叠（端点相接不算冲突：[1,2] 与 [2,3] 可以都选）。"""
    ordered = sorted(intervals, key=lambda iv: (iv[0], iv[1]))
    return all(ordered[i][1] <= ordered[i + 1][0] for i in range(len(ordered) - 1))


def schedule(intervals):
    """最早结束优先。返回选中的区间元组（按结束时间升序）。"""
    remaining = sorted(intervals, key=lambda iv: (iv[1], iv[0]))
    chosen, free_until = [], None
    for start, end in remaining:
        if end <= start:
            raise ValueError(f"区间非法：起点 {start} 不早于终点 {end}")
        if free_until is None or start >= free_until:
            chosen.append((start, end))
            free_until = end
    return tuple(chosen)


def greedy_by_start(intervals):
    """会失败的对照：按开始时间最早。"""
    remaining = sorted(intervals, key=lambda iv: (iv[0], iv[1]))
    chosen, free_until = [], None
    for start, end in remaining:
        if free_until is None or start >= free_until:
            chosen.append((start, end))
            free_until = end
    return tuple(chosen)


def greedy_by_shortest(intervals):
    """会失败的对照：按时长最短。"""
    remaining = sorted(intervals, key=lambda iv: (iv[1] - iv[0], iv[0]))
    chosen, free_until = [], None
    for start, end in remaining:
        if free_until is None or start >= free_until:
            chosen.append((start, end))
            free_until = end
    return tuple(chosen)


def schedule_count_brute(intervals) -> int:
    """参照实现：枚举所有子集，取可行的最大个数。O(2^n)，只做小规模验证。"""
    items = list(intervals)
    for size in range(len(items), -1, -1):
        for combo in combinations(items, size):
            if is_feasible(combo):
                return size           # 从大到小枚举，第一个可行就是最优
    return 0


def ratio_greedy_01(weights, values, capacity):
    """0/1 背包上的"性价比贪心"：按 val/weight 降序，装得下就拿。"""
    order = sorted(range(len(weights)), key=lambda i: values[i] / weights[i],
                   reverse=True)
    used, total, chosen = 0, 0, []
    for i in order:
        if weights[i] == 0:
            total += values[i]
            chosen.append(i)
            continue
        if used + weights[i] <= capacity:
            used += weights[i]
            total += values[i]
            chosen.append(i)
    return total, tuple(sorted(chosen))


def smallest_counterexample(max_end=4, max_items=4):
    """枚举所有小规模区间集合，找出两条"直觉贪心"最先失败的那一组。

    返回 ``{"by_start": 反例, "by_shortest": 反例, "by_end_fails": None}``。
    ``by_end_fails`` 应当永远是 None：那是被交换论证过的策略，一旦不为 None
    就说明实现或论证出问题了，测试里会直接断言这一点。
    """
    universe = [(s, e) for s in range(max_end + 1) for e in range(s + 1, max_end + 1)]
    found = {"by_start": None, "by_shortest": None, "by_end_fails": None}
    for size in range(1, max_items + 1):
        for combo in combinations(universe, size):
            optimum = schedule_count_brute(combo)
            if found["by_start"] is None and len(greedy_by_start(combo)) != optimum:
                found["by_start"] = combo
            if found["by_shortest"] is None and len(greedy_by_shortest(combo)) != optimum:
                found["by_shortest"] = combo
            if found["by_end_fails"] is None and len(schedule(combo)) != optimum:
                found["by_end_fails"] = combo
        if found["by_start"] and found["by_shortest"]:
            break                     # 两条反例都拿到了，继续枚举只是浪费时间
    return found
