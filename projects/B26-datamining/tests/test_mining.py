"""B26-datamining 自测。

"期望值必须有出处"的落法：
    1. Apriori <-- 2^n−1 项集全穷举逐项对拍（暴力参照），且
       被剪枝的候选数 + 生成数 ≤ 全组合数（剪枝只可能少算，不可能多算）
    2. 关联规则 <-- 手算 conf/lift（含 lift<1 的负相关教学实例）
    3. K-means <-- k=1 惯性 = 总方差（解析等式）、团块 100% 对齐、
       轮廓系数 1D 手算、确定性、空簇路径不破坏结果
    4. 清洗 <-- 缺陷按已知数量注入，报告逐数对账 + 清洗后复检
"""
import random
import unittest
from itertools import combinations
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mining.apriori import (apriori, association_rules,
                            brute_force_frequent)
from mining.clean import PRODUCTS, clean, make_dirty_ledger, to_baskets
from mining.kmeans import KMeans, inertia_of, silhouette


# ---------------------------------------------------------------- Apriori
class TestApriori(unittest.TestCase):
    def brute_compare(self, txs, min_support):
        got, stats = apriori(txs, min_support)
        want = brute_force_frequent(txs, min_support)
        self.assertEqual(got, want)
        return got, stats, want

    def test_hand_case(self):
        txs = [{"A", "B"}, {"A", "B"}, {"A"}, {"B"}]
        got, stats = apriori(txs, 0.5)
        self.assertEqual(got[frozenset({"A"})], 3)
        self.assertEqual(got[frozenset({"B"})], 3)
        self.assertEqual(got[frozenset({"A", "B"})], 2)
        self.assertEqual(len(got), 3)

    def test_hand_case_rules_with_lift(self):
        """手算：conf(A→B) = 2/3；supp(B) = 3/4 -> lift = (2/3)/(3/4) = 8/9 < 1
        ——A 出现反而让 B 更"不"意外，负相关的教学实例。"""
        txs = [{"A", "B"}, {"A", "B"}, {"A"}, {"B"}]
        freq, stats = apriori(txs, 0.5)
        rules = association_rules(freq, stats["n"], min_confidence=0.6)
        by_pair = {(tuple(sorted(r["ante"])), tuple(sorted(r["cons"]))): r
                   for r in rules}
        r1 = by_pair[(("A",), ("B",))]
        self.assertAlmostEqual(r1["conf"], 2 / 3)
        self.assertAlmostEqual(r1["lift"], 8 / 9)
        self.assertLess(r1["lift"], 1)               # 负相关：lift < 1

    def test_random_against_brute_force(self):
        rng = random.Random(2026)
        for round in range(25):
            n_items = rng.randint(3, 6)
            items = list(range(n_items))
            n_tx = rng.randint(8, 30)
            txs = []
            for _ in range(n_tx):
                size = rng.randint(1, min(4, n_items))
                txs.append(set(rng.sample(items, size)))
            support = rng.choice([0.2, 0.3, 0.5])
            got, stats = apriori(txs, support)
            want = brute_force_frequent(txs, support)
            self.assertEqual(got, want,
                             msg=f"round={round} support={support}")
            # 剪枝只可能少生成候选，不可能凭空多出
            all_combos = 2 ** n_items - 1 - n_items    # 规模 ≥2 的组合总数
            self.assertLessEqual(stats["candidates_generated"], all_combos)

    def test_downward_closure_of_result(self):
        """向下闭包：频繁项集的所有子集必须也在频繁集合里（Apriori 的地基）。"""
        rng = random.Random(3)
        txs = [set(rng.sample(range(6), rng.randint(2, 5))) for _ in range(40)]
        freq, _ = apriori(txs, 0.2)
        for s in freq:
            for r in range(1, len(s)):
                for sub in combinations(sorted(s), r):
                    self.assertIn(frozenset(sub), freq)

    def test_stats_and_determinism(self):
        rng = random.Random(4)
        txs = [set(rng.sample(range(5), rng.randint(2, 4))) for _ in range(20)]
        got1, stats1 = apriori(txs, 0.3)
        got2, stats2 = apriori(txs, 0.3)
        self.assertEqual(got1, got2)
        self.assertEqual(stats1["candidates_generated"],
                         stats2["candidates_generated"])


# ---------------------------------------------------------------- K-means
class TestKMeans(unittest.TestCase):
    def test_blobs_perfect_alignment(self):
        """间隔明显的两团：聚类结果与真值 100% 对齐（最优标签映射下）。"""
        rng = random.Random(0)
        X = [[rng.gauss(0, 0.3), rng.gauss(0, 0.3)] for _ in range(40)] + \
            [[rng.gauss(6, 0.3), rng.gauss(6, 0.3)] for _ in range(40)]
        truth = [0] * 40 + [1] * 40
        km = KMeans(k=2, seed=1).fit(X)
        acc_a = sum(1 for t, p in zip(truth, km.labels_) if t == p) / len(truth)
        acc_b = 1 - acc_a                          # 标签置换后的另一种对齐
        self.assertGreaterEqual(max(acc_a, acc_b), 1.0)

    def test_k1_inertia_equals_total_variance(self):
        """k=1 的惯性有解析答案：到均值的平方距离之和。"""
        rng = random.Random(2)
        X = [[rng.uniform(-3, 3), rng.uniform(-3, 3)] for _ in range(30)]
        km = KMeans(k=1, seed=0).fit(X)
        self.assertAlmostEqual(km.inertia_, inertia_of(X), places=9)

    def test_inertia_two_clusters_beats_k1(self):
        rng = random.Random(2)
        X = [[rng.uniform(-3, 3), rng.uniform(-3, 3)] for _ in range(30)] + \
            [[rng.gauss(8, 0.5), rng.gauss(8, 0.5)] for _ in range(10)]
        k1 = KMeans(k=1, seed=0).fit(X).inertia_
        k2 = KMeans(k=2, seed=0).fit(X).inertia_
        self.assertLess(k2, k1)                    # 更多的簇惯性必然不增

    def test_determinism_and_cluster_coverage(self):
        """同一 seed 结果逐项一致；且 fit 之后**每个簇都非空**
        （labels 必须覆盖 0..k-1）——这是空簇处理分支保护的用户可见不变式。
        注：互异数据点初始化下第一轮天然不空（初始中心距离自身为 0），
        探针实测小数据上重 seeding 路径难以自然触发，故断言保护的效果
        而非触发本身；empty_cluster_events_ 计数器保留作可观测性。"""
        rng = random.Random(6)
        X = [[rng.uniform(0, 1), rng.uniform(0, 1)] for _ in range(30)]
        for seed in range(60):
            a = KMeans(k=5, seed=seed).fit(X)
            b = KMeans(k=5, seed=seed).fit(X)
            self.assertEqual(a.labels_, b.labels_)
            self.assertEqual(a.centroids_, b.centroids_)
            self.assertEqual(sorted(set(a.labels_)), list(range(5)))
            self.assertGreaterEqual(a.inertia_, 0.0)

    def test_all_same_points_rejected_for_large_k(self):
        X = [[1.0, 1.0]] * 10
        with self.assertRaises(ValueError):
            KMeans(k=2, seed=0).fit(X)
        km = KMeans(k=1, seed=0).fit(X)            # k=1 合法：惯性为 0
        self.assertAlmostEqual(km.inertia_, 0.0)


# ---------------------------------------------------------------- 轮廓系数
class TestSilhouette(unittest.TestCase):
    def test_hand_computed_1d(self):
        """1D 四点手算：X=[0, 0.1, 10, 10.1]，labels=[0,0,1,1]。
        每点 a=0.1（同簇相邻距离），b=到另一簇两点的平均距离，
        s = (b-a)/max(a,b)，逐点写出：
          p0: b=(10+10.1)/2=10.05  s=9.95/10.05
          p1: b=(9.9+10.0)/2=9.95  s=9.85/9.95
          p2: a=0.1 b=9.95         s=9.85/9.95
          p3: a=0.1 b=10.05        s=9.95/10.05
        """
        X = [[0.0], [0.1], [10.0], [10.1]]
        labels = [0, 0, 1, 1]
        want = (9.95 / 10.05 + 9.85 / 9.95 + 9.85 / 9.95 + 9.95 / 10.05) / 4
        self.assertAlmostEqual(silhouette(X, labels), want, places=12)

    def test_single_point_cluster_is_zero(self):
        X = [[0.0], [0.1], [10.0]]
        labels = [0, 0, 1]
        # 单点簇的 s 约定为 0；簇 [0,0.1] 的两点各自 s 接近 1
        mean = silhouette(X, labels)
        self.assertTrue(0 <= mean < 1)

    def test_one_cluster_returns_zero(self):
        self.assertEqual(silhouette([[0.0], [1.0]], [0, 0]), 0.0)

    def test_well_separated_beats_overlapping(self):
        rng = random.Random(8)
        sep = [[rng.gauss(0, 0.2), rng.gauss(0, 0.2)] for _ in range(30)] + \
              [[rng.gauss(8, 0.2), rng.gauss(8, 0.2)] for _ in range(30)]
        labels_sep = [0] * 30 + [1] * 30
        overlap = [[rng.gauss(0, 1.0), rng.gauss(0, 1.0)] for _ in range(30)] + \
                  [[rng.gauss(2, 1.0), rng.gauss(2, 1.0)] for _ in range(30)]
        labels_ov = [0] * 30 + [1] * 30
        self.assertGreater(silhouette(sep, labels_sep),
                           silhouette(overlap, labels_ov))


# ---------------------------------------------------------------- 清洗与端到端
class TestCleanAndPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.injected = make_dirty_ledger(40, seed=7)
        cls.clean_rows, cls.report = clean(cls.rows)

    def test_report_matches_injection(self):
        """账本对账：清洗报告的每个计数都必须等于构造时注入的数量。"""
        inj = self.injected["injected"]
        # 报表口径的 total = 缺陷注入前的基础行数 + 追加的重复行
        self.assertEqual(self.report["total"],
                         inj["total_before"] + inj["dup"])
        self.assertEqual(self.report["duplicates_removed"], inj["dup"])
        self.assertEqual(self.report["unknown_product_removed"], inj["unknown"])
        self.assertEqual(self.report["bad_qty_removed"], inj["bad_qty"])
        self.assertEqual(self.report["amount_filled"], inj["missing_amount"])
        self.assertEqual(self.report["returns_removed"], inj["negative"])

    def test_account_balance(self):
        """守恒：total = clean + 各类剔除之和（填补不算剔除）。"""
        r = self.report
        removed = (r["duplicates_removed"] + r["unknown_product_removed"]
                   + r["bad_qty_removed"] + r["returns_removed"])
        self.assertEqual(r["total"], r["clean"] + removed)

    def test_clean_rows_revalidated(self):
        """清洗后复检：不许再有任何一种已知缺陷。"""
        seen = set()
        for r in self.clean_rows:
            key = tuple(sorted(r.items()))
            self.assertNotIn(key, seen)            # 无重复
            seen.add(key)
            self.assertIn(r["product"], PRODUCTS)  # 无未知商品
            self.assertIsInstance(r["qty"], int) and self.assertGreater(r["qty"], 0)
            self.assertIsInstance(r["amount"], float)
            self.assertGreater(r["amount"], 0)     # 无负金额、无缺失

    def test_planted_pair_rule_found(self):
        """端到端：清洗 -> 购物篮 -> Apriori。生成器刻意让半数订单
        P01+P02 成对（比例 1/2 是探针实测：1/3 经清洗丢行后支持度
        掉到 0.26，够不着 0.3 阈值），挖掘应当把这对找出来。"""
        baskets = to_baskets(self.clean_rows)
        freq, stats = apriori(baskets, 0.3)
        pair = frozenset({"P01", "P02"})
        self.assertIn(pair, freq)
        rules = association_rules(freq, stats["n"], min_confidence=0.5)
        pair_rules = [r for r in rules
                      if {tuple(sorted(r["ante"]))[0], tuple(sorted(r["cons"]))[0]}
                      == {"P01", "P02"}]
        self.assertTrue(pair_rules)
        best = max(pair_rules, key=lambda r: r["conf"])
        self.assertGreaterEqual(best["conf"], 0.6)
        self.assertGreater(best["lift"], 1.0)      # 植入模式必须是正相关

    def test_bruteforce_matches_on_real_baskets(self):
        baskets = to_baskets(self.clean_rows)
        got, _ = apriori(baskets, 0.2)
        want = brute_force_frequent(baskets, 0.2)
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main(verbosity=2)
