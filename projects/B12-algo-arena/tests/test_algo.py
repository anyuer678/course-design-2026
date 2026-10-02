"""B12-algo-arena 自测：五个范式算法逐一与"把定义直接翻译成代码"的参照实现对拍。

跑法：
    python tests\\test_algo.py
    pytest tests\\test_algo.py -q

对拍的原则：参照实现不参与优化、不共享技巧，错了也能指出是哪一边错。
穷举规模都压到毫秒级，让整套测试能在一次点击里跑完。
"""
from __future__ import annotations

import itertools
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algo import backtrack, bench, dp, divide, greedy, graph      # noqa: E402


class TestDivideAndConquer(unittest.TestCase):
    """分治：逆序对。命门是"相等不算逆序"和跨块计数的时机。"""

    def test_exhaustive_over_small_alphabets(self):
        for length in range(6):
            for arr in itertools.product(range(3), repeat=length):
                with self.subTest(arr=arr):
                    self.assertEqual(divide.count_inversions(arr),
                                     divide.brute_force_inversions(arr))

    def test_random_against_brute_force(self):
        rng = random.Random(20260930)
        for _ in range(500):
            arr = [rng.randint(-20, 20) for _ in range(rng.randint(0, 40))]
            self.assertEqual(divide.count_inversions(arr),
                             divide.brute_force_inversions(arr))

    def test_merge_sort_count_sorts_and_counts(self):
        rng = random.Random(7)
        for _ in range(100):
            arr = [rng.randint(-9, 9) for _ in range(rng.randint(0, 25))]
            ordered, count = divide.merge_sort_count(arr)
            self.assertEqual(ordered, sorted(arr))
            self.assertEqual(count, divide.brute_force_inversions(arr))

    def test_equal_elements_are_not_inversions(self):
        self.assertEqual(divide.count_inversions([5] * 200), 0)
        self.assertEqual(divide.count_inversions([1, 1, 2, 2, 3, 3]), 0)

    def test_descending_is_the_maximum(self):
        for n in range(1, 12):
            self.assertEqual(divide.count_inversions(list(range(n, 0, -1))),
                             n * (n - 1) // 2)

    def test_ascending_is_zero(self):
        self.assertEqual(divide.count_inversions(sorted(range(300))), 0)

    def test_empty_and_singleton(self):
        for seq in ([], [42], ()):
            self.assertEqual(divide.count_inversions(seq), 0)
        self.assertEqual(divide.merge_sort_count([]), ([], 0))

    def test_big_count_is_exact_not_overflowing(self):
        # Python 整数不会溢出，但这里核对的是公式而不是类型：n=2000 降序
        self.assertEqual(divide.count_inversions(list(range(2000, 0, -1))),
                         2000 * 1999 // 2)

    def test_stability_of_equivalence_on_duplicates(self):
        # 左块 <= 右块时不计数：这条断言直接钉住 a[i] <= a[j] 的等号方向
        self.assertEqual(divide.count_inversions([2, 1, 2, 1]), 3)
        self.assertEqual(divide.brute_force_inversions([2, 1, 2, 1]), 3)


class TestDynamicProgramming(unittest.TestCase):
    """DP：0/1 背包。命门是一维滚动的循环方向与方案还原。"""

    def test_against_subset_brute_force(self):
        rng = random.Random(1234)
        for _ in range(400):
            n = rng.randint(0, 7)
            capacity = rng.randint(0, 12)
            weights = [rng.randint(0, 6) for _ in range(n)]
            values = [rng.randint(0, 9) for _ in range(n)]
            best, chosen = dp.knapsack(weights, values, capacity)
            brute_best, _ = dp.knapsack_brute(weights, values, capacity)
            self.assertEqual(best, brute_best, (weights, values, capacity))
            self.assertEqual(dp.knapsack_rolling(weights, values, capacity), best)
            self.assertLessEqual(sum(weights[i] for i in chosen), capacity)
            self.assertEqual(sum(values[i] for i in chosen), best)

    def test_chosen_plan_is_unique_feasible_and_optimal(self):
        weights, values, capacity = [2, 2, 3, 5], [3, 4, 4, 6], 7
        best, chosen = dp.knapsack(weights, values, capacity)
        self.assertEqual(len(set(chosen)), len(chosen))
        self.assertEqual(best, 11)                       # 前三件刚好装满 7，价值 3+4+4
        self.assertEqual(chosen, (0, 1, 2))
        self.assertEqual(sum(weights[i] for i in chosen), capacity)
        self.assertEqual(sum(values[i] for i in chosen), best)

    def test_rolling_direction_matters(self):
        # 一件物品重 2 值 3、容量 5：倒序只能用一次，正序能塞两次
        self.assertEqual(dp.knapsack([2], [3], 5)[0], 3)
        self.assertEqual(dp.knapsack_rolling([2], [3], 5), 3)
        self.assertEqual(dp.knapsack_rolling_wrong_way([2], [3], 5), 6)

    def test_zero_weight_items_are_taken(self):
        best, chosen = dp.knapsack([0, 4], [7, 5], 3)
        self.assertEqual((best, chosen), (7, (0,)))

    def test_capacity_zero(self):
        self.assertEqual(dp.knapsack([1, 2], [3, 4], 0), (0, ()))

    def test_items_heavier_than_capacity(self):
        self.assertEqual(dp.knapsack([10, 20], [5, 9], 7), (0, ()))

    def test_no_items(self):
        self.assertEqual(dp.knapsack([], [], 5), (0, ()))
        self.assertEqual(dp.knapsack_rolling([], [], 5), 0)
        self.assertEqual(dp.knapsack_brute([], [], 5), (0, ()))

    def test_invalid_inputs_rejected(self):
        cases = [
            (([1], [2, 3], 5), "长度不一致"),
            (([1], [1], -1), "负容量"),
            (([1], [-2], 5), "负价值"),
            (([-1], [2], 5), "负重量"),
        ]
        for (weights, values, capacity), label in cases:
            with self.subTest(case=label):
                with self.assertRaises(dp.DpError):
                    dp.knapsack(weights, values, capacity)

    def test_value_is_monotone_in_capacity(self):
        weights, values = [3, 4, 5, 2], [4, 5, 6, 3]
        previous = -1
        for capacity in range(15):
            best = dp.knapsack(weights, values, capacity)[0]
            self.assertGreaterEqual(best, previous, f"容量 {capacity} 变大了价值反而变小")
            previous = best


class TestGreedy(unittest.TestCase):
    """贪心：区间调度。命门是"哪个排序键才是被论证过的那个"。"""

    def test_by_end_matches_brute_force(self):
        rng = random.Random(99)
        for _ in range(600):
            count = rng.randint(0, 7)
            pairs = set()
            while len(pairs) < count:
                start = rng.randint(0, 9)
                pairs.add((start, start + rng.randint(1, 4)))
            intervals = list(pairs)
            chosen = greedy.schedule(intervals)
            self.assertEqual(len(chosen), greedy.schedule_count_brute(intervals), intervals)
            self.assertTrue(greedy.is_feasible(chosen), intervals)
            self.assertTrue(set(chosen) <= set(intervals))

    def test_exhaustive_small_universe_never_breaks_by_end_greedy(self):
        universe = [(s, e) for s in range(5) for e in range(s + 1, 6)]
        for size in range(1, 4):
            for combo in itertools.combinations(universe, size):
                self.assertEqual(len(greedy.schedule(combo)),
                                 greedy.schedule_count_brute(combo), combo)

    def test_other_intuitions_have_counterexamples(self):
        found = greedy.smallest_counterexample()
        self.assertIsNone(found["by_end_fails"], "被论证过的策略不该有反例")
        self.assertIsNotNone(found["by_start"])
        self.assertIsNotNone(found["by_shortest"])
        for key in ("by_start", "by_shortest"):
            combo = found[key]
            optimum = greedy.schedule_count_brute(combo)
            strategy = greedy.greedy_by_start if key == "by_start" else greedy.greedy_by_shortest
            self.assertNotEqual(len(strategy(combo)), optimum, f"{key} 竟然没失败")
            self.assertTrue(greedy.is_feasible(strategy(combo)),
                            f"{key} 选出的区间竟然互相冲突")

    def test_touching_endpoints_do_not_conflict(self):
        self.assertEqual(len(greedy.schedule([(1, 2), (2, 3), (3, 4)])), 3)
        self.assertTrue(greedy.is_feasible([(1, 2), (2, 3)]))

    def test_nested_intervals_pick_the_inner(self):
        self.assertEqual(greedy.schedule([(0, 10), (2, 3), (4, 5)]), ((2, 3), (4, 5)))

    def test_identical_intervals(self):
        self.assertEqual(len(greedy.schedule([(1, 2)] * 5)), 1)

    def test_empty_input(self):
        self.assertEqual(greedy.schedule(()), ())
        self.assertEqual(greedy.schedule_count_brute(()), 0)
        self.assertTrue(greedy.is_feasible(()))

    def test_invalid_interval_rejected(self):
        with self.assertRaises(ValueError):
            greedy.schedule([(3, 3)])
        with self.assertRaises(ValueError):
            greedy.schedule([(0, 2), (5, 1)])

    def test_ratio_greedy_is_not_optimal_for_zero_one(self):
        # 教材（CLRS）反例：性价比最高的先占容量，剩下的空间刚好装不下第二好的组合
        weights, values, capacity = [10, 20, 30], [60, 100, 120], 50
        greedy_value, chosen = greedy.ratio_greedy_01(weights, values, capacity)
        optimum = dp.knapsack(weights, values, capacity)[0]
        self.assertEqual((greedy_value, chosen), (160, (0, 1)))
        self.assertEqual(optimum, 220)
        self.assertLess(greedy_value, optimum, "比值贪心在 0/1 背包上必须可能失败")

    def test_ratio_greedy_never_exceeds_optimum(self):
        rng = random.Random(5)
        for _ in range(120):
            n = rng.randint(1, 6)
            weights = [rng.randint(1, 6) for _ in range(n)]
            values = [rng.randint(1, 9) for _ in range(n)]
            capacity = rng.randint(1, 12)
            got, chosen = greedy.ratio_greedy_01(weights, values, capacity)
            optimum = dp.knapsack(weights, values, capacity)[0]
            self.assertLessEqual(got, optimum)
            self.assertLessEqual(sum(weights[i] for i in chosen), capacity)


class TestBacktracking(unittest.TestCase):
    """回溯：N 皇后。命门是对角线公式与撤销的配对。"""

    def test_known_counts(self):
        for n, expected in backtrack.KNOWN_COUNTS.items():
            with self.subTest(n=n):
                self.assertEqual(backtrack.count_n_queens(n), expected)
                self.assertEqual(len(backtrack.solve_n_queens(n)), expected)

    def test_permutation_reference_agrees(self):
        for n in range(1, 9):
            self.assertEqual(backtrack.count_by_permutations(n),
                             backtrack.KNOWN_COUNTS[n])

    def test_two_and_three_have_no_solution(self):
        self.assertEqual(backtrack.solve_n_queens(2), [])
        self.assertEqual(backtrack.solve_n_queens(3), [])

    def test_every_solution_is_valid_and_distinct(self):
        for n in (5, 6, 7):
            solutions = backtrack.solve_n_queens(n)
            self.assertEqual(len(set(solutions)), len(solutions))
            for placement in solutions:
                self.assertTrue(backtrack.is_solution(n, placement), placement)

    def test_solution_uses_each_column_once(self):
        for placement in backtrack.solve_n_queens(6):
            self.assertEqual(sorted(placement), list(range(6)))

    def test_is_solution_rejects_invalid(self):
        self.assertFalse(backtrack.is_solution(4, (0, 1, 2, 3)))     # 共主对角线
        self.assertFalse(backtrack.is_solution(4, (0, 0, 1, 3)))     # 列重复
        self.assertFalse(backtrack.is_solution(4, (1, 3, 0)))        # 少一行

    def test_edge_sizes(self):
        self.assertEqual(backtrack.count_n_queens(0), 1)
        self.assertEqual(backtrack.solve_n_queens(0), [()])
        self.assertEqual(backtrack.solve_n_queens(1), [(0,)])
        with self.assertRaises(ValueError):
            backtrack.count_n_queens(-1)
        with self.assertRaises(ValueError):
            backtrack.solve_n_queens(-1)


class TestGraphAlgorithms(unittest.TestCase):
    """图：Dijkstra 对 Bellman-Ford 与 Floyd。命门是三种实现必须同一图约定。"""

    def test_all_three_agree_random_undirected(self):
        rng = random.Random(31)
        for _ in range(200):
            n = rng.randint(1, 9)
            edges = graph.build_random_graph(n, rng.randint(0, 16), rng)
            src = rng.randrange(n)
            dist, _ = graph.dijkstra(n, edges, src)
            self.assertEqual(dist, graph.floyd(n, edges)[src], edges)
            self.assertEqual(dist, graph.bellman_ford(n, edges, src)[0], edges)

    def test_all_three_agree_random_directed(self):
        rng = random.Random(32)
        for _ in range(200):
            n = rng.randint(1, 9)
            edges = graph.build_random_graph(n, rng.randint(0, 16), rng, directed=True)
            src = rng.randrange(n)
            dist, _ = graph.dijkstra(n, edges, src)
            self.assertEqual(dist, graph.floyd(n, edges)[src], edges)
            self.assertEqual(dist, graph.bellman_ford(n, edges, src)[0], edges)

    def test_direction_is_respected(self):
        one_way = [(0, 1, 5)]
        self.assertEqual(graph.dijkstra(2, one_way, 1)[0], [float("inf"), 0])
        self.assertEqual(graph.dijkstra(2, graph.undirected(one_way), 1)[0], [5, 0])

    def test_classic_textbook_graph(self):
        edges = graph.undirected([(0, 1, 4), (0, 2, 8), (1, 2, 11), (1, 3, 5),
                                  (2, 4, 19), (3, 4, 2)])
        dist, prev = graph.dijkstra(5, edges, 0)
        self.assertEqual(dist, [0, 4, 8, 9, 11])
        self.assertEqual(graph.path_of(prev, 0, 4), [0, 1, 3, 4])

    def test_unreachable_stays_infinite(self):
        dist, prev = graph.dijkstra(4, [(0, 1, 3)], 0)
        self.assertEqual(dist[2], float("inf"))
        self.assertIsNone(graph.path_of(prev, 0, 2))
        self.assertEqual(graph.path_of(prev, 0, 0), [0])

    def test_parallel_edges_take_the_shortest(self):
        dist, _ = graph.dijkstra(2, [(0, 1, 9), (0, 1, 2), (0, 1, 5)], 0)
        self.assertEqual(dist, [0, 2])

    def test_zero_weight_edges_are_fine(self):
        dist, _ = graph.dijkstra(3, graph.undirected([(0, 1, 0), (1, 2, 0)]), 0)
        self.assertEqual(dist, [0, 0, 0])

    def test_negative_weight_is_refused_then_handled_by_bellman_ford(self):
        edges = [(0, 1, 4), (1, 2, -3), (0, 2, 2)]
        with self.assertRaises(graph.NegativeWeight):
            graph.dijkstra(3, edges, 0)
        self.assertEqual(graph.bellman_ford(3, edges, 0)[0], [0, 4, 1])

    def test_negative_cycle_detected(self):
        cases = {
            "自环和为负": [(0, 1, -3), (1, 0, 2)],
            "三元环为负": [(0, 1, 1), (1, 2, -5), (2, 0, 1)],
        }
        for label, edges in cases.items():
            with self.subTest(case=label):
                n = len(set([e[0] for e in edges] + [e[1] for e in edges]))
                with self.assertRaises(graph.NegativeCycle):
                    graph.bellman_ford(n, edges, 0)
                with self.assertRaises(graph.NegativeCycle):
                    graph.floyd(n, edges)

    def test_negative_cycle_unreachable_from_source_is_not_reported(self):
        # 负环存在但源点到不了：Bellman-Ford 不该报警，这是"可达"两个字的分量
        edges = [(0, 1, 1), (2, 3, -5), (3, 2, 1)]
        dist, _ = graph.bellman_ford(4, edges, 0)
        self.assertEqual(dist, [0, 1, float("inf"), float("inf")])
        with self.assertRaises(graph.NegativeCycle):
            graph.floyd(4, edges)                      # 全源视角必然看见它

    def test_out_of_range_inputs(self):
        with self.assertRaises(ValueError):
            graph.dijkstra(2, [(0, 5, 1)], 0)
        with self.assertRaises(ValueError):
            graph.dijkstra(3, [(0, 1, 1)], 9)

    def test_empty_graph(self):
        self.assertEqual(graph.dijkstra(1, [], 0)[0], [0])
        self.assertEqual(graph.floyd(0, []), [])


class TestBench(unittest.TestCase):
    """计时工具本身也要测：数字长得像不像样，取决于这几行有没有写错。"""

    def test_measure_repeats_and_counts_calls(self):
        calls = []
        timing = bench.measure(lambda n: calls.append(n), 3, repeats=5, warmup=2)
        self.assertEqual(len(calls), 7)               # 2 次预热 + 5 次计时
        self.assertEqual(timing.repeats, 5)
        self.assertLessEqual(timing.fastest, timing.median)
        self.assertLessEqual(timing.median, timing.slowest)

    def test_measure_rejects_zero_repeats(self):
        with self.assertRaises(ValueError):
            bench.measure(lambda n: None, None, repeats=0)

    def test_slope_recovers_quadratic(self):
        sizes = [50, 100, 200, 400]
        times = [n * n / 1e6 for n in sizes]
        self.assertAlmostEqual(bench.log_log_slope(sizes, times), 2.0, places=6)

    def test_slope_recovers_linearithmic_is_between_one_and_two(self):
        sizes = [100, 1000, 10000, 100000]
        times = [n * math.log2(n) / 1e5 for n in sizes]
        slope = bench.log_log_slope(sizes, times)
        self.assertGreater(slope, 1.0)
        self.assertLess(slope, 1.2)

    def test_slope_rejects_degenerate_input(self):
        with self.assertRaises(ValueError):
            bench.log_log_slope([1, 1], [2.0, 3.0])          # 规模没变
        with self.assertRaises(ValueError):
            bench.log_log_slope([1, 2], [0.0, 1.0])          # 耗时非正
        with self.assertRaises(ValueError):
            bench.log_log_slope([1], [1.0])                  # 点太少
        with self.assertRaises(ValueError):
            bench.log_log_slope([1, 2], [1.0])               # 长度不齐

    def test_growth_reports_ratio(self):
        rows = bench.growth(lambda n: divide.count_inversions(list(range(n, 0, -1))),
                            [200, 400], repeats=2)
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0][2])
        self.assertGreater(rows[1][2], 1.0, "降序规模翻倍，耗时该涨")

    def test_machine_info_is_complete(self):
        info = bench.machine_info()
        for key in ("系统", "Python", "CPU 逻辑核", "计时源"):
            self.assertIn(key, info)
        self.assertTrue(info["Python"].startswith("3."))

    def test_format_rows_is_readable_text(self):
        rows = bench.growth(lambda n: divide.count_inversions([1, 3, 2] * n),
                            [50, 100], repeats=2)
        text = bench.format_rows(rows)
        self.assertEqual(len(text.splitlines()), 3)
        self.assertIn("ms", text)


class TestCrossChecks(unittest.TestCase):
    """跨范式的同一性检查：同一批输入，不同范式的答案不能互相打脸。"""

    def test_dp_and_brute_force_on_a_shared_random_stream(self):
        rng = random.Random(2026)
        for _ in range(80):
            n = rng.randint(1, 6)
            weights = [rng.randint(1, 5) for _ in range(n)]
            values = [rng.randint(1, 8) for _ in range(n)]
            capacity = rng.randint(1, 10)
            self.assertEqual(dp.knapsack(weights, values, capacity)[0],
                             dp.knapsack_brute(weights, values, capacity)[0])

    def test_inversions_third_independent_view(self):
        """树状数组版是第三条独立路径：既不是归并也不是双重循环。

        按值域离散化，从左往右数"前面已经有多少个比它大"。
        三种实现两两吻合，才说明"逆序对"这个概念被真的算出来了，而不是三份同样的错。
        """
        def fenwick_count(seq):
            values = list(seq)
            order = sorted(set(values))
            rank = {v: i + 1 for i, v in enumerate(order)}          # 值域压到 1..m
            tree = [0] * (len(order) + 1)

            def add(i):
                while i < len(tree):
                    tree[i] += 1
                    i += i & -i

            def prefix(i):
                total = 0
                while i:
                    total += tree[i]
                    i -= i & -i
                return total

            seen = total = 0
            for value in values:
                add(rank[value])
                seen += 1
                total += seen - prefix(rank[value])     # 严格大于：等于自己的不算
            return total

        rng = random.Random(8)
        for _ in range(200):
            arr = [rng.randint(0, 5) for _ in range(rng.randint(0, 14))]
            self.assertEqual(fenwick_count(arr), divide.count_inversions(arr), arr)
            self.assertEqual(fenwick_count(arr), divide.brute_force_inversions(arr), arr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
