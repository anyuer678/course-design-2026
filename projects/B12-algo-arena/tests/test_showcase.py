"""tests/test_showcase.py —— B12 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、真数据抽查（皇后解数经典值、背包三路对拍与错法亮相、
贪心对照与最小反例、最短路三方对拍与快照、逆序对分治/暴力与三档规模）、
改坏必红、页面标记与零外链。
"""
from __future__ import annotations

import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import showcase as sc  # noqa: E402


def quiet_main(argv) -> int:
    with redirect_stdout(io.StringIO()):
        return sc.main(argv)


class TestPageFreshness(unittest.TestCase):
    def test_page_exists_and_fresh(self):
        self.assertTrue(sc.OUT.is_file(), "web/showcase.html 不存在——跑 --write")
        self.assertEqual(quiet_main(["showcase", "--check"]), 0)

    def test_tampered_page_turns_red(self):
        original = sc.OUT
        with tempfile.TemporaryDirectory(prefix="b12-showcase-") as tmp:
            fake = Path(tmp) / "showcase.html"
            fake.write_text("手改过的页面", encoding="utf-8")
            sc.OUT = fake
            try:
                self.assertEqual(quiet_main(["showcase", "--check"]), 1)
            finally:
                sc.OUT = original


class TestPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = sc.collect()

    def test_queens_counts_are_classic_values(self):
        rows = self.payload["queens"]["rows"]
        self.assertEqual([(r["n"], r["bit"]) for r in rows],
                         [(6, 4), (7, 40), (8, 92), (9, 352), (10, 724)])
        self.assertTrue(all(r["agree"] for r in rows), "三条计数路必须互证")
        board = self.payload["queens"]["board6"].splitlines()
        self.assertEqual(len(board), 6)
        self.assertEqual(sum(line.count("Q") for line in board), 6)

    def test_knapsack_three_way_and_wrong_way_shows_up(self):
        k = self.payload["knapsack"]
        self.assertEqual(k["best"], 9)
        self.assertEqual(k["rolling"], k["best"], "滚动数组必须与完整表相同")
        self.assertEqual(k["brute_value"], k["best"], "暴力参照必须相同")
        self.assertNotEqual(k["wrong"], k["best"], "滚动写反的错法必须当场露馅")
        total_w = sum(k["weights"][i] for i in k["chosen"])
        total_v = sum(k["values"][i] for i in k["chosen"])
        self.assertLessEqual(total_w, k["capacity"])
        self.assertEqual(total_v, k["best"])

    def test_greedy_beats_two_naive_ones_and_counterexamples_found(self):
        g = self.payload["greedy"]
        self.assertEqual(g["best"], g["optimum"], "最早结束必须等于暴力最优")
        self.assertLess(g["by_start"], g["optimum"], "按开始必须被反例打败")
        self.assertLess(g["by_shortest"], g["optimum"], "按最短必须被反例打败")
        self.assertIsNone(g["by_end_fails"], "最早结束的反例应当不存在（交换论证）")
        self.assertTrue(g["counter_by_start"] and g["counter_by_shortest"])

    def test_graph_three_way_and_snapshots(self):
        gr = self.payload["graph"]
        self.assertTrue(gr["three_way"])
        self.assertEqual(gr["dist"], [0, 3, 1, 8, 10, 11])
        self.assertEqual(gr["path"], [0, 2, 5])
        settled = [u for u, d, s in gr["snapshots"]]
        dists = [d for u, d, s in gr["snapshots"]]
        self.assertEqual(sorted(settled), list(range(gr["n"])), "每个节点恰好定标一次")
        self.assertEqual(dists, sorted(dists), "定标顺序必须按距离非降")

    def test_inversions_dual_and_scale(self):
        iv = self.payload["inversions"]
        self.assertEqual(iv["count"], iv["brute"], "分治必须等于暴力")
        self.assertEqual(iv["count"], 17)
        self.assertTrue(all(s["agree"] for s in iv["scale"]))
        self.assertGreater(iv["scale"][0]["merge"], 0, "规模数组不能是退化的（全同值会恒 0）")


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B12-algo-arena"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
