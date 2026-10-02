"""B12-algo-arena 演示：五个范式各看一个代表算法，边看边和"笨办法"对账。

    python demo.py
"""
from __future__ import annotations

import itertools
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from algo import backtrack, dp, divide, greedy, graph       # noqa: E402
from math import inf                                        # noqa: E402

import experiments                                          # noqa: E402

BAR = "=" * 78


def title(index: int, text: str) -> None:
    print(f"\n{BAR}\n[{index}/6] {text}\n{BAR}")


def fmt(value) -> str:
    return "∞" if value == inf else str(value)


def fmt_list(values) -> str:
    return "[" + ", ".join(fmt(v) for v in values) + "]"


def section(text: str) -> None:
    print(f"\n-- {text} " + "-" * max(0, 70 - len(text)))


def demo_divide() -> None:
    rng = random.Random(11)
    arr = [rng.randint(0, 30) for _ in range(12)]
    ordered, count = divide.merge_sort_count(arr)
    print(f"  数组    : {arr}")
    print(f"  排序结果: {ordered}")
    print(f"  逆序对数: 分治 {count} / 暴力 {divide.brute_force_inversions(arr)} / "
          f"降序上限 n(n-1)/2 = {len(arr) * (len(arr) - 1) // 2}")

    section("穷举核对：长度 ≤4、值域 {0,1,2} 的全部数组")
    mismatch = 0
    total = 0
    for length in range(5):
        for case in itertools.product(range(3), repeat=length):
            total += 1
            if divide.count_inversions(case) != divide.brute_force_inversions(case):
                mismatch += 1
    print(f"  穷举 {total} 个输入，与暴力定义不一致：{mismatch} 个")

    section("等号方向就是正确性")
    same = [7, 7, 7, 7]
    print(f"  {same} 的逆序对数 = {divide.count_inversions(same)}"
          "（相等不算逆序：合并时写成 a[i] < a[j] 就会把它算成 6 对）")


def demo_dp() -> None:
    weights, values, capacity = [2, 3, 4, 5], [3, 4, 5, 6], 7
    best, chosen = dp.knapsack(weights, values, capacity)
    print(f"  物品 重量={weights} 价值={values} 容量={capacity}")
    print("  DP 表（行=考虑到前 i 件，列=容量 w）：")
    table = dp.knapsack_table(weights, values, capacity)
    for i, (wt, val) in enumerate(zip(weights, values), start=1):
        print(f"    i={i} (w={wt},v={val}): " + " ".join(f"{x:3d}" for x in table[i]))
    print(f"  最优价值={best} 选择下标={chosen} "
          f"合计重量={sum(weights[i] for i in chosen)} 合计价值={sum(values[i] for i in chosen)}")
    print(f"  枚举所有子集的参照答案：{dp.knapsack_brute(weights, values, capacity)[0]}")

    section("一维滚动的循环方向：同一行代码决定是 0/1 背包还是完全背包")
    print(f"  一件物品 重 2 值 3，容量 5：0/1 应该只拿一次 → {dp.knapsack([2], [3], 5)[0]}")
    print(f"    滚动数组（容量倒序）  : {dp.knapsack_rolling([2], [3], 5)}")
    print(f"    滚动数组（容量正序=错）: {dp.knapsack_rolling_wrong_way([2], [3], 5)}"
          " ← 同一件被塞了两次")

    section("随机对拍 500 组")
    rng = random.Random(4)
    mismatch = 0
    for _ in range(500):
        n = rng.randint(0, 6)
        w = [rng.randint(0, 6) for _ in range(n)]
        v = [rng.randint(0, 9) for _ in range(n)]
        cap = rng.randint(0, 10)
        got, plan = dp.knapsack(w, v, cap)
        if got != dp.knapsack_brute(w, v, cap)[0] or sum(w[i] for i in plan) > cap:
            mismatch += 1
    print(f"  与子集枚举不一致 / 方案超重：{mismatch} 组")


def demo_greedy() -> None:
    intervals = [(0, 5), (1, 3), (3, 6), (5, 7), (6, 8), (2, 4)]
    print(f"  区间: {intervals}")
    print(f"  最早结束贪心选中: {greedy.schedule(intervals)} → {len(greedy.schedule(intervals))} 个")
    print(f"  按开始时间选中  : {greedy.greedy_by_start(intervals)} → "
          f"{len(greedy.greedy_by_start(intervals))} 个")
    print(f"  按时长最短选中  : {greedy.greedy_by_shortest(intervals)} → "
          f"{len(greedy.greedy_by_shortest(intervals))} 个")
    print(f"  枚举所有子集的最优: {greedy.schedule_count_brute(intervals)} 个"
          " ← 只有第一种每次都对")

    section("自动搜出的最小反例（穷举所有端点 ≤4、区间数 ≤4 的集合）")
    found = greedy.smallest_counterexample()
    for key, label in (("by_start", "按开始时间"), ("by_shortest", "按时长最短")):
        combo = found[key]
        optimum = greedy.schedule_count_brute(combo)
        strategy = greedy.greedy_by_start if key == "by_start" else greedy.greedy_by_shortest
        print(f"  {label:8s} 最小反例 {combo}：它选 {len(strategy(combo))} 个，最优 {optimum} 个")
    print(f"  最早结束贪心在同样的穷举里失败过吗：{found['by_end_fails']} "
          "← 交换论证说的就是这件事")

    section("贪心的边界：0/1 背包上比值法会亏")
    w, v, cap = [10, 20, 30], [60, 100, 120], 50
    got, plan = greedy.ratio_greedy_01(w, v, cap)
    print(f"  物品 (w,v)={list(zip(w, v))} 容量 {cap}")
    print(f"  比值贪心: 选 {plan} 价值 {got}；DP 最优: {dp.knapsack(w, v, cap)[0]}"
          " ← 有子结构才谈得上贪心")


def demo_backtrack() -> None:
    section("解数对照表（三种独立实现 + 教材已知值）")
    print("   n   已知   集合版   位运算版   全排列参照")
    for n, known in backtrack.KNOWN_COUNTS.items():
        set_count = len(backtrack.solve_n_queens(n))
        bit_count = backtrack.count_n_queens(n)
        perm_count = backtrack.count_by_permutations(n) if n <= 8 else "（8 以上太慢）"
        print(f"  {n:3d} {known:7d} {set_count:8d} {bit_count:10d}   {perm_count}")

    section("摆一个出来看")
    placement = backtrack.solve_n_queens(6)[0]
    print(f"  placement[r] = 第 r 行的皇后所在列: {placement}")
    for row in range(6):
        line = "".join("Q" if placement[row] == col else "·" for col in range(6))
        print(f"    {line}")


def demo_graph() -> None:
    edges = graph.undirected([(0, 1, 4), (0, 2, 8), (1, 2, 11), (1, 3, 5),
                              (2, 4, 19), (3, 4, 2)])
    rounds = []
    dist, prev = graph.dijkstra(5, edges, 0, on_settle=lambda u, d, snap: rounds.append((u, d, snap)))
    print("  教材那张表：每轮永久确定一个点，确定时的 dist 快照")
    print("   轮次  确定  长度    dist 快照")
    for index, (u, d, snap) in enumerate(rounds, 1):
        print(f"  {index:5d} {u:4d} {d:6d}   {fmt_list(snap)}")
    print(f"  最终 dist: {fmt_list(dist)}")
    print(f"  Bellman-Ford: {fmt_list(graph.bellman_ford(5, edges, 0)[0])}")
    print(f"  Floyd 第 0 行: {fmt_list(graph.floyd(5, edges)[0])}")
    print(f"  0 → 4 的最短路径: {graph.path_of(prev, 0, 4)}")

    section("Dijkstra 的前提是非负权；越界就拒绝，而不是给个错答案")
    with_negative = [(0, 1, 4), (1, 2, -3), (0, 2, 2)]
    try:
        graph.dijkstra(3, with_negative, 0)
        print("  !! 竟然没拒绝")
    except graph.NegativeWeight as exc:
        print(f"  Dijkstra: {exc}")
    print(f"  Bellman-Ford 同图: {fmt_list(graph.bellman_ford(3, with_negative, 0)[0])}")

    section("负环：可达性决定要不要报警")
    quiet = [(0, 1, 1), (2, 3, -5), (3, 2, 1)]
    print(f"  源点 0 到不了负环 → BF: "
          f"{fmt_list(graph.bellman_ford(4, quiet, 0)[0])}")
    try:
        graph.floyd(4, quiet)
    except graph.NegativeCycle as exc:
        print(f"  但全源视角必然看见它 → Floyd: {exc}")


def main() -> int:
    print("B12-algo-arena 演示：五个范式，每个都和'把定义直接翻译成代码'的笨办法对账")
    title(1, "分治：逆序对（归并顺便数出来）")
    demo_divide()
    title(2, "动态规划：0/1 背包（填表、还原方案、循环方向的坑）")
    demo_dp()
    title(3, "贪心：区间调度，以及三种直觉哪一种才被论证过")
    demo_greedy()
    title(4, "回溯：N 皇后（三种实现互相印证）")
    demo_backtrack()
    title(5, "图：Dijkstra 的每轮确定点，与非负权这个前提")
    demo_graph()
    title(6, "规模计时（quick 档）：只给趋势，不给证明")
    print(experiments.run_all(quick=True))
    print("\n完整档：python experiments.py（约 45 秒）")
    return 0


if __name__ == "__main__":
    # 直接 python demo.py 时中文控制台默认按 GBK 写，∞ 和 · 会当场编码失败
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
