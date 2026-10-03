"""tests/test_planner.py —— B34 自测：手算基准 + 三算法对拍 + 可采纳性 + 反例。

纪律（和本仓库其它项目一致）：
  1. 期望值来自手算或独立参照：走廊/小图的手算代价写进注释，随机图用
     **Dijkstra 当参照**（h≡0 的 A* 自身又有 BFS 一侧做锚）；
  2. "启发式可采纳"是**量出来**的：max(h - 真实距离) ≤ 0，用从目标回溯的
     Dijkstra 直接算真实距离；
  3. 教学反例要**真的撞得到**：曼哈顿 × 8 邻域在种子搜索里找出次优实例并钉住；
  4. 页面/记录：搜索过程可回放、可构建、可 node --check（同 B33 分界）。
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from planner import grid as G           # noqa: E402
from planner import heuristics as H     # noqa: E402
from planner import search as S         # noqa: E402
from planner import viz                 # noqa: E402

TINY = 1e-9


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b34-{name}-"))
    if str(base.resolve()).lower().startswith(str(ROOT.parent.parent.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


class TestHandComputed(unittest.TestCase):
    def test_corridor(self):
        # 1×3 走廊：两格直走，代价 2，路径逐格
        r = S.dijkstra(G.corridor(3), (0, 0), (2, 0))
        self.assertTrue(r.found)
        self.assertAlmostEqual(r.cost, 2.0)
        self.assertEqual(r.path, [(0, 0), (1, 0), (2, 0)])

    def test_small_map_with_wall(self):
        # 4×3，墙 {(1,1),(2,1)}；必经绕行 → 手算最短 5 步：
        #   下绕：(0,0)(0,1)(0,2)(1,2)(2,2)(3,2) 或 上绕：(0,0)(1,0)(2,0)(3,0)(3,1)(3,2)
        g = G.Grid(width=4, height=3, obstacles={(1, 1), (2, 1)})
        for algo in (lambda: S.dijkstra(g, (0, 0), (3, 2)),
                     lambda: S.astar(g, (0, 0), (3, 2), H.manhattan)):
            r = algo()
            self.assertTrue(r.found)
            self.assertAlmostEqual(r.cost, 5.0)
            self.assertEqual(len(r.path), 6)
            self.assertEqual(S.validate_path(g, r.path, (0, 0), (3, 2)), [])

    def test_diagonal_hand_case(self):
        # 3×3 全通，8 邻域：对角线直达代价 √2 ≈ 1.4142
        g = G.Grid(width=3, height=3, allow_diagonal=True)
        r = S.astar(g, (0, 0), (2, 2), H.octile)
        self.assertAlmostEqual(r.cost, 2 * G.SQRT2)
        self.assertEqual(r.path, [(0, 0), (1, 1), (2, 2)])

    def test_no_corner_cutting(self):
        # (1,0) 与 (0,1) 都是障碍时，斜穿 (0,0)->(1,1) 必须被禁止
        g = G.Grid(width=2, height=2, obstacles={(1, 0), (0, 1)}, allow_diagonal=True)
        nbrs = {n for n, _c in g.neighbors((0, 0))}
        self.assertEqual(nbrs, set())
        r = S.dijkstra(g, (0, 0), (1, 1))
        self.assertFalse(r.found)

    def test_start_equals_goal(self):
        g = G.corridor(1)
        r = S.dijkstra(g, (0, 0), (0, 0))
        self.assertTrue(r.found)
        self.assertAlmostEqual(r.cost, 0.0)
        self.assertEqual(r.path, [(0, 0)])


class TestFailures(unittest.TestCase):
    def test_walled_goal_unreachable_deterministic(self):
        g, start, goal = G.walled_scene()
        first = S.dijkstra(g, start, goal)
        self.assertFalse(first.found)
        self.assertTrue(first.reason)
        second = S.dijkstra(g, start, goal)
        self.assertEqual(first.expanded, second.expanded)     # 确定性返回
        self.assertEqual(first.reason, second.reason)

    def test_bad_endpoints_raise(self):
        g = G.Grid(width=3, height=3, obstacles={(1, 1)})
        with self.assertRaises(ValueError):
            S.dijkstra(g, (1, 1), (0, 0))                     # 起点在障碍上
        with self.assertRaises(ValueError):
            S.dijkstra(g, (0, 0), (5, 5))                     # 终点越界

    def test_bfs_refuses_diagonal(self):
        g = G.Grid(width=3, height=3, allow_diagonal=True)
        with self.assertRaises(ValueError):
            S.bfs(g, (0, 0), (2, 2))


class TestCrossChecks(unittest.TestCase):
    def test_astar_equals_dijkstra_4nb(self):
        for seed in range(1, 31):
            g = G.random_grid(24, 18, 0.28, seed=seed)
            d = S.dijkstra(g, (0, 0), (23, 17))
            a = S.astar(g, (0, 0), (23, 17), H.manhattan)
            self.assertEqual(d.found, a.found, msg=f"seed={seed}")
            if d.found:
                self.assertAlmostEqual(d.cost, a.cost, msg=f"seed={seed}")

    def test_astar_expands_no_more_than_dijkstra(self):
        for seed in range(1, 31):
            g = G.random_grid(24, 18, 0.28, seed=seed)
            d = S.dijkstra(g, (0, 0), (23, 17))
            a = S.astar(g, (0, 0), (23, 17), H.manhattan)
            self.assertLessEqual(a.expanded_count, d.expanded_count, msg=f"seed={seed}")

    def test_astar_equals_dijkstra_8nb(self):
        for seed in range(1, 31):
            g = G.random_grid(24, 18, 0.28, seed=seed, allow_diagonal=True)
            d = S.dijkstra(g, (0, 0), (23, 17))
            a = S.astar(g, (0, 0), (23, 17), H.octile)
            self.assertEqual(d.found, a.found, msg=f"seed={seed}")
            if d.found:
                self.assertAlmostEqual(d.cost, a.cost, msg=f"seed={seed}")

    def test_bfs_equivalence_when_unit_cost(self):
        for seed in range(1, 21):
            g = G.random_grid(16, 12, 0.25, seed=seed)         # 4 邻域 = 每步同价
            d = S.dijkstra(g, (0, 0), (15, 11))
            b = S.bfs(g, (0, 0), (15, 11))
            self.assertEqual(d.found, b.found, msg=f"seed={seed}")
            if d.found:
                self.assertAlmostEqual(d.cost, b.cost, msg=f"seed={seed}")

    def test_paths_are_valid_on_random_maps(self):
        for seed in (2, 6, 11):
            for diagonal in (False, True):
                g = G.random_grid(18, 14, 0.3, seed=seed, allow_diagonal=diagonal)
                r = S.astar(g, (0, 0), (17, 13),
                            H.octile if diagonal else H.manhattan)
                if r.found:
                    self.assertEqual(S.validate_path(g, r.path, (0, 0), (17, 13)), [],
                                     msg=f"seed={seed} diag={diagonal}")


class TestHeuristics(unittest.TestCase):
    def test_admissible_pairings(self):
        # 4 邻域 × 曼哈顿：松紧恰好（slack = 0）
        g4 = G.random_grid(16, 12, 0.25, seed=5)
        self.assertLessEqual(S.max_admissibility_slack(g4, (15, 11), H.manhattan), TINY)
        # 8 邻域 × 对角(octile)：可采纳
        g8 = G.random_grid(16, 12, 0.25, seed=5, allow_diagonal=True)
        self.assertLessEqual(S.max_admissibility_slack(g8, (15, 11), H.octile), TINY)
        # 8 邻域 × 欧氏：更松，也可采纳
        self.assertLessEqual(S.max_admissibility_slack(g8, (15, 11), H.euclidean), TINY)

    def test_manhattan_inadmissible_on_8nb(self):
        # 8 邻域里斜步只花 √2 < 2，曼哈顿会**高估**——slack 必须显著为正
        g8 = G.random_grid(16, 12, 0.25, seed=5, allow_diagonal=True)
        slack = S.max_admissibility_slack(g8, (15, 11), H.manhattan)
        self.assertGreater(slack, 0.5)                        # 实测 ≈ 4.69

    def test_inadmissible_heuristic_suboptimal_counterexample(self):
        # 教学点：不可采纳的启发式会给出**次优**路径——在种子搜索里真找一条出来
        found = None
        for seed in range(1, 50):
            g = G.random_grid(10, 8, 0.25, seed=seed, allow_diagonal=True)
            d = S.dijkstra(g, (0, 0), (9, 7))
            a = S.astar(g, (0, 0), (9, 7), H.manhattan)
            if d.found and a.found and a.cost > d.cost + TINY:
                found = (seed, d.cost, a.cost)
                break
        self.assertIsNotNone(found, "50 个种子里没找到反例——应该至少撞到一个")
        seed, best, greedy = found
        self.assertAlmostEqual(best, 14.242640687119286, msg=f"seed={seed}")  # 10 + 3√2
        self.assertAlmostEqual(greedy, 14.828427124746190, msg=f"seed={seed}")  # 差 2-√2


class TestViz(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = make_tmp("viz")
        g = G.random_grid(20, 14, 0.25, seed=7, allow_diagonal=True)
        result = S.astar(g, (0, 0), (19, 13), H.octile)
        cls.trace = viz.export_trace(g, (0, 0), (19, 13), result, "octile")
        cls.path = cls.tmp / "plan.html"
        cls.size = viz.build_page(cls.trace, cls.path)
        cls.html = cls.path.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_trace_matches_result(self):
        for cell in self.trace["steps"] + self.trace["path"]:
            self.assertIsInstance(cell, list)                 # JSON 里必须是 [x, y]
            self.assertEqual(len(cell), 2)
            self.assertTrue(0 <= cell[0] < self.trace["grid"]["width"])
            self.assertTrue(0 <= cell[1] < self.trace["grid"]["height"])
        self.assertTrue(self.trace["path"])
        self.assertEqual(self.trace["path"][0], [0, 0])
        self.assertEqual(self.trace["path"][-1], [19, 13])
        self.assertEqual(self.trace["meta"]["expanded"], len(self.trace["steps"]))

    def test_page_structure_and_embedded_data(self):
        self.assertIn("const TRACE = ", self.html)
        for element_id in ("scene", "play", "next", "prev", "finish", "speed", "status"):
            self.assertIn(f'id="{element_id}"', self.html, msg=element_id)
        match = re.search(r"const TRACE = (\{.*?\});\n", self.html, re.S)
        self.assertEqual(json.loads(match.group(1)), self.trace)
        self.assertGreater(self.size, 6000)                   # 实测 7644（20×14 的小图）

    def test_page_deterministic(self):
        again = self.tmp / "plan2.html"
        viz.build_page(self.trace, again)
        self.assertEqual(self.path.read_bytes(), again.read_bytes())

    @unittest.skipUnless(shutil.which("node"), "本机没有 node，跳过 JS 语法体检")
    def test_javascript_syntax_with_node_check(self):
        script = re.search(r"<script>\n(.*)</script>", self.html, re.S).group(1)
        js_path = self.tmp / "extracted.js"
        js_path.write_text(script, encoding="utf-8")
        try:
            result = subprocess.run(["node", "--check", str(js_path)],
                                    capture_output=True, text=True)
        except OSError as err:
            self.skipTest(f"node 不可执行：{err}")
        self.assertEqual(result.returncode, 0, msg=result.stderr[:500])


if __name__ == "__main__":
    unittest.main()
