"""experiments.py —— 规模计时实验。README 里每一个数字都来自这个文件的实际运行。

    python experiments.py            # 完整一轮（约一分钟）
    python experiments.py --quick    # 小一档，demo 里用的就是这一档

原则：**输入在计时之外准备好**，只测算法本体；每档重复取中位数；
输出必须带机器与环境，否则数字之间没有可比性。
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from algo import backtrack, bench, dp, divide, greedy, graph      # noqa: E402

RNG_SEED = 20260930


def header() -> str:
    info = bench.machine_info()
    lines = [f"环境：{info['系统']} / {info['处理器']} / {info['CPU 逻辑核']} 核 / "
             f"Python {info['Python']}",
             f"计时：{info['计时源']}，每档取中位数；随机数据固定 seed={RNG_SEED}",
             "声明：以下数字是这台机器上的增长趋势观测，不是复杂度证明。"]
    return "\n".join(lines)


def _show(title: str, rows, extra: str = "") -> str:
    body = bench.format_rows(rows)
    return f"\n◆ {title}\n{body}" + (f"\n  {extra}" if extra else "")


def experiment_inversions(quick=False, repeats=3) -> str:
    sizes = [10_000, 20_000, 40_000, 80_000] if not quick else [5_000, 10_000, 20_000]
    rng = random.Random(RNG_SEED)
    inputs = [(n, [rng.randrange(n) for _ in range(n)]) for n in sizes]   # 乱序、值域宽
    rows = bench.sweep(lambda data: divide.count_inversions(data), inputs, repeats=repeats)
    slope = bench.log_log_slope([n for n, _ in inputs], [r[1].median for r in rows])
    brute_sizes = [200, 400, 800, 1600] if not quick else [200, 400, 800]
    brute_inputs = [(n, [rng.randrange(n) for _ in range(n)]) for n in brute_sizes]
    brute_rows = bench.sweep(divide.brute_force_inversions, brute_inputs, repeats=2)
    brute_slope = bench.log_log_slope(brute_sizes, [r[1].median for r in brute_rows])
    return (_show("逆序对 · 分治（归并）", rows, f"log-log 斜率 ≈ {slope:.2f}（理论 n log n → 1 多一点）")
            + _show("逆序对 · 双重循环暴力", brute_rows,
                    f"log-log 斜率 ≈ {brute_slope:.2f}（理论 n² → 2）"))


def experiment_knapsack(quick=False, repeats=3) -> str:
    capacity = 2000 if not quick else 800
    rng = random.Random(RNG_SEED)
    sizes = [200, 400, 800, 1600] if not quick else [100, 200, 400]
    cases = []
    for n in sizes:
        weights = [rng.randint(1, 50) for _ in range(n)]
        values = [rng.randint(1, 100) for _ in range(n)]
        cases.append((f"n={n}, W={capacity}", (weights, values, capacity)))
    rows = bench.sweep(lambda arg: dp.knapsack(*arg), cases, repeats=repeats)
    slope = bench.log_log_slope(sizes, [r[1].median for r in rows])

    small = [10, 12, 14, 16, 18] if not quick else [10, 12, 14, 16]
    brute_cases = []
    for n in small:
        weights = [rng.randint(1, 50) for _ in range(n)]
        values = [rng.randint(1, 100) for _ in range(n)]
        brute_cases.append((f"n={n}", (weights, values, capacity)))
    brute_rows = bench.sweep(lambda arg: dp.knapsack_brute(*arg), brute_cases, repeats=2)
    ratios = [f"{r[2]:.1f}×" for r in brute_rows[1:]]
    return (_show(f"0/1 背包 · DP 填表（W 固定 {capacity}）", rows,
                  f"log-log 斜率 ≈ {slope:.2f}（n·W 里 W 不变，所以 ≈ 1）")
            + _show("0/1 背包 · 枚举所有子集", brute_rows,
                    f"n 每 +2 的耗时倍率：{', '.join(ratios)}（2^n 应该是 4× 一档）"))


def experiment_intervals(quick=False, repeats=3) -> str:
    rng = random.Random(RNG_SEED)
    sizes = [5_000, 10_000, 20_000, 40_000] if not quick else [2_000, 5_000, 10_000]
    cases = []
    for n in sizes:
        pairs = [(s, s + rng.randint(1, 50)) for s in range(0, n * 3, 3)]
        rng.shuffle(pairs)
        cases.append((n, pairs))
    rows = bench.sweep(lambda pairs: len(greedy.schedule(pairs)), cases, repeats=repeats)
    slope = bench.log_log_slope(sizes, [r[1].median for r in rows])
    return _show("区间调度 · 最早结束贪心", rows,
                 f"log-log 斜率 ≈ {slope:.2f}（排序主导，理论 n log n）")


def experiment_queens(quick=False, repeats=2) -> str:
    ns = list(range(7, 12)) if not quick else list(range(6, 10))
    rows = bench.growth(lambda n: len(backtrack.solve_n_queens(n)), ns, repeats=repeats)
    bit_ns = list(range(9, 15)) if not quick else list(range(9, 13))
    bit_rows = bench.growth(backtrack.count_n_queens, bit_ns, repeats=repeats)
    return (_show("N 皇后 · 集合剪枝（列举全部解）", rows)
            + _show("N 皇后 · 位运算（只计数）", bit_rows,
                    "指数增长的代价：集合版多两档就要等好几十秒，位运算版多三档还能忍"))


def experiment_shortest_paths(quick=False, repeats=2) -> str:
    rng = random.Random(RNG_SEED)
    sparse = [2_000, 4_000, 8_000, 16_000] if not quick else [1_000, 2_000, 4_000]
    dense = [300, 600, 900] if not quick else [200, 400, 600]

    def make(n, edges):
        return graph.build_random_graph(n, edges, rng, max_weight=1000)

    sparse_cases = [(f"V={n}, E≈2V", (n, make(n, 2 * n), 0)) for n in sparse]
    sparse_rows = bench.sweep(lambda arg: graph.dijkstra(*arg), sparse_cases, repeats=repeats)
    sparse_slope = bench.log_log_slope(sparse, [r[1].median for r in sparse_rows])

    dense_cases = [(f"V={n}, E≈V²/4", (n, make(n, n * n // 4), 0)) for n in dense]
    dense_rows = bench.sweep(lambda arg: graph.dijkstra(*arg), dense_cases, repeats=repeats)
    dense_slope = bench.log_log_slope(dense, [r[1].median for r in dense_rows])

    # 同一批随机图上跑 Bellman-Ford：它"一整轮没改进就收敛"，
    # 随机稀疏图往往两三轮就完了——于是实测斜率远小于理论的 V·E。
    bf_small = [400, 800, 1600, 3200] if not quick else [400, 800, 1600]
    bf_cases = [(f"V={n}, E≈2V 随机", (n, make(n, 2 * n), 0)) for n in bf_small]
    bf_rows = bench.sweep(lambda arg: graph.bellman_ford(*arg), bf_cases, repeats=repeats)
    bf_slope = bench.log_log_slope(bf_small, [r[1].median for r in bf_rows])

    # 想让 Θ(V·E) 现形，就得给一个"每轮只能推进一个顶点"的输入：
    # 链式图 + 边倒序排列。这才是最坏界真正的样子。
    chain = [300, 600, 1200, 2400] if not quick else [200, 400, 800]

    def chain_graph(n):
        return [(i, i + 1, 1) for i in range(n - 2, -1, -1)]

    chain_cases = [(f"V={n} 链式·边倒序", (n, chain_graph(n), 0)) for n in chain]
    chain_bf = bench.sweep(lambda arg: graph.bellman_ford(*arg), chain_cases, repeats=repeats)
    chain_dij = bench.sweep(lambda arg: graph.dijkstra(*arg), chain_cases, repeats=repeats)
    chain_slope = bench.log_log_slope(chain, [r[1].median for r in chain_bf])
    speedup = chain_bf[-1][1].median / chain_dij[-1][1].median
    return (_show("单源最短路 · Dijkstra（随机稀疏图 E≈2V）", sparse_rows,
                  f"log-log 斜率 ≈ {sparse_slope:.2f}（理论 E log V → 略大于 1）")
            + _show("单源最短路 · Dijkstra（随机稠密图 E≈V²/4）", dense_rows,
                    f"log-log 斜率 ≈ {dense_slope:.2f}（V 翻倍时 E 变四倍）")
            + _show("单源最短路 · Bellman-Ford（同一批随机图）", bf_rows,
                    f"log-log 斜率 ≈ {bf_slope:.2f} —— 比理论 V·E 小得多，"
                    "因为它一轮没改进就提前收敛了")
            + _show("单源最短路 · Bellman-Ford（链式图·边倒序，最坏输入）", chain_bf,
                    f"log-log 斜率 ≈ {chain_slope:.2f}（V·E 中 E≈V → 理论上 ≈2）；"
                    f"最大一档上 Dijkstra 比它快 {speedup:.0f} 倍"))


def run_all(quick=False) -> str:
    parts = [header(),
             experiment_inversions(quick),
             experiment_knapsack(quick),
             experiment_intervals(quick),
             experiment_queens(quick),
             experiment_shortest_paths(quick)]
    return "\n".join(parts)


if __name__ == "__main__":
    print(run_all(quick="--quick" in sys.argv))
