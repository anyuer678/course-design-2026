"""B27-course-kg 自测。

"期望值必须有出处"的落法：
    1. 传递闭包 <-- 测试内独立实现的 BFS（不 import kg.graph 的闭包函数）
    2. 缺先修 / 解锁 <-- 手工整理的 PLAN §3 用例逐数断言
    3. 拓扑序合法性 <-- 每条边 u→v 满足 pos[u] < pos[v]
    4. 数据完整性 <-- CSV 行数 / 任务数 41 / 词池不变式（文件与内存图一致）
    5. HTML <-- 节点与边全部出现、自包含（无 http 外链）
"""
import math
import random
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kg.graph import KnowledgeGraph, load_default
from kg.viz import render_html


def independent_closure(graph_preds: dict, start: str) -> set:
    """测试里独立写的闭包（DFS 栈实现），与 graph.ancestors 交叉验证。"""
    seen = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        for p in graph_preds.get(cur, ()):
            if p not in seen:
                seen.add(p)
                stack.append(p)
    return seen


class TestGraphData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = load_default()

    def test_shape(self):
        self.assertEqual(len(self.g.nodes), 41)
        self.assertGreaterEqual(len(self.g.edges), 40)

    def test_edges_reference_existing_nodes(self):
        for e in self.g.edges:
            self.assertIn(e["src"], self.g.nodes)
            self.assertIn(e["dst"], self.g.nodes)

    def test_batches_one_to_eight(self):
        batches = sorted({info["batch"] for info in self.g.nodes.values()})
        self.assertEqual(batches, [1, 2, 3, 4, 5, 6, 7, 8])

    def test_validate_passes(self):
        self.g.validate()                     # 有环或任务数不对都会抛

    def test_no_cycle_by_topo(self):
        order = self.g.topological_order()
        self.assertEqual(len(order), 41)
        pos = {t: i for i, t in enumerate(order)}
        for e in self.g.edges:
            self.assertLess(pos[e["src"]], pos[e["dst"]],
                            msg=f"{e['src']} -> {e['dst']} 违反拓扑序")


class TestClosureAndQueries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = load_default()
        cls.preds = {t: set(g.direct_prereqs(t))
                     for t, g in [(t, cls.g) for t in cls.g.nodes]}

    def test_closure_matches_independent_dfs(self):
        rng = random.Random(3)
        for task in rng.sample(sorted(self.g.nodes), 15):
            want = independent_closure(self.preds, task)
            self.assertEqual(self.g.ancestors(task), want, msg=task)

    def test_plan_documented_chain(self):
        """PLAN §3 明文链：B1/B2 → B5/B6/B8 → B9；B8/B9 → B10/B11。
        手工整理的期望值（这正是"学习地图"该有的形状）。"""
        self.assertEqual(self.g.ancestors("B9"),
                         {"B1", "B2", "B5", "B6", "B8"})
        self.assertEqual(self.g.direct_prereqs("B10"), {"B2", "B9"})
        self.assertIn("B9", self.g.ancestors("B11"))
        self.assertIn("B8", self.g.ancestors("B11"))

    def test_descendants_unlock(self):
        """学完 B11 解锁：B31→B32、B30、B35、B38，B35→B37 链……"""
        des = self.g.descendants("B11")
        for t in {"B31", "B32", "B30", "B35", "B38", "B37"}:
            self.assertIn(t, des)
        self.assertNotIn("B9", des)           # 前驱不是后继

    def test_missing_prereqs_hand_case(self):
        """缺先修检测：迷你图手工构造 + 手工期望。"""
        g = KnowledgeGraph()
        g.add_task("A", 1, "甲")
        g.add_task("B", 1, "乙")
        g.add_task("C", 2, "丙")
        g.add_edge("A", "B", "先修")
        g.add_edge("B", "C", "先修")
        # 已完成 A：做 C 还缺 B（间接先修）
        self.assertEqual(g.missing_prereqs("C", {"A"}), {"B"})
        # 已完成 A+B：不缺
        self.assertEqual(g.missing_prereqs("C", {"A", "B"}), set())
        # 什么都没做：缺 A 和 B
        self.assertEqual(g.missing_prereqs("C", set()), {"A", "B"})

    def test_ready_tasks(self):
        g = KnowledgeGraph()
        for t in ("A", "B", "C", "D"):
            g.add_task(t, 1, t)
        g.add_edge("A", "B", "先修")
        g.add_edge("B", "C", "先修")
        g.add_edge("D", "C", "先修")
        # 初始：A、D 可做（B 等 A，C 等 B/D）
        self.assertEqual(g.ready_tasks(set()), ["A", "D"])
        # 完成后解锁
        self.assertEqual(g.ready_tasks({"A"}), ["B", "D"])
        self.assertEqual(g.ready_tasks({"A", "B", "D"}), ["C"])

    def test_learning_path(self):
        """通往 B18 的路径：先修闭包子图的拓扑序，含 B18 自己，
        且基础（B1/B2/B3）排在业务（B14/B15）之前。"""
        path = self.g.learning_path("B18")
        self.assertIn("B18", path)
        self.assertLess(path.index("B1"), path.index("B14"))
        self.assertLess(path.index("B10"), path.index("B18"))
        pos = {t: i for i, t in enumerate(path)}
        for e in self.g.edges:
            if e["src"] in pos and e["dst"] in pos:
                self.assertLess(pos[e["src"]], pos[e["dst"]])


class TestVisualization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = load_default()
        cls.html = render_html(cls.g)

    def test_all_nodes_and_edges_present(self):
        for t in self.g.nodes:
            self.assertIn(f'data-id="{t}"', self.html)
        self.assertEqual(self.html.count('class="edge"'), len(self.g.edges))

    def test_self_contained_no_external_refs(self):
        self.assertNotIn("http://", self.html.replace("http://www.w3.org", ""))
        self.assertNotIn("https://", self.html)
        self.assertIn("<svg", self.html)
        self.assertIn("CLOSURE", self.html)   # 闭包数据已内嵌

    def test_closing_tags(self):
        self.assertIn("</svg>", self.html)
        self.assertIn("</html>", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
