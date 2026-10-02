"""tests/test_viz.py —— B33 自测：操作记录的回放保真 + 页面结构 + 语法体检。

纪律（和本仓库其它项目一致）：
  1. "动画演的是真算法"必须可验证：把导出记录用**独立 Python 回放器**逐步对上——
     排序按 B2 的 pop 协议重建、BFS/DFS 与独立参照逐访问一致；
  2. 负面自证：故意改坏一条记录，回放器必须报错（证明它不是橡皮图章）；
  3. 页面检查做到"能自动的"/"不能自动的"分界：结构、内嵌数据、确定性、JS 语法
     （node --check）全自动；**动画观感**留给用户实跑（README 明确）。
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

from vizlab import page, replay   # noqa: E402

TRACES = ROOT / "build" / "traces"
B2_INCLUDE = ROOT.parent / "B2-datastruct-lab" / "include"
EXPECTED_EDGES = [[0, 1], [0, 2], [1, 3], [2, 4], [2, 5], [5, 6]]


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b33-{name}-"))
    if str(base.resolve()).lower().startswith(str(ROOT.parent.parent.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


class TestTraces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not TRACES.exists():
            raise unittest.SkipTest(
                "缺 build/traces/*.json —— 先跑 run.bat 的编译/导出步（或手工："
                "g++ -I../B2-datastruct-lab/include tools/export_trace.cpp -o build/export_trace.exe"
                " && build/export_trace.exe build/traces）")
        cls.sort = replay.load_trace(TRACES / "sort.json")
        cls.bfs = replay.load_trace(TRACES / "bfs.json")
        cls.dfs = replay.load_trace(TRACES / "dfs.json")

    def test_sort_trace_shape(self):
        self.assertEqual(self.sort["type"], "sort")
        self.assertEqual(len(self.sort["input"]), 8)
        ops = [s["op"] for s in self.sort["steps"]]
        self.assertIn("build", ops)
        self.assertEqual(ops.count("pop"), len(self.sort["input"]))   # 每个元素取一次
        self.assertEqual(set(ops) <= {"build", "swap", "pop"}, True)

    def test_sort_replay_fidelity(self):
        checks = replay.replay_sort(self.sort)
        failures = [c for c in checks if not c["ok"]]
        self.assertEqual(failures, [], msg=f"逐步回放失败：{failures[:3]}")
        self.assertEqual(len(checks), len(self.sort["steps"]))

    def test_sort_final_state_is_sorted(self):
        self.assertEqual(replay.sort_final_state(self.sort), sorted(self.sort["input"]))

    def test_bfs_matches_independent_reference(self):
        got = [{"op": s["op"], "a": s["a"], "state": s["state"]} for s in self.bfs["steps"]]
        self.assertEqual(got, replay.reference_bfs(self.bfs))
        dist = replay.bfs_distances(self.bfs)
        for step in self.bfs["steps"]:
            self.assertEqual(step["b"], dist[step["a"]])              # b 字段 = 距离
        self.assertEqual(len(self.bfs["steps"]), 7)                   # 单连通分量全覆盖

    def test_dfs_matches_independent_reference(self):
        got = [{"op": s["op"], "a": s["a"], "state": s["state"]} for s in self.dfs["steps"]]
        self.assertEqual(got, replay.reference_dfs(self.dfs))

    def test_graph_declared_edges(self):
        for trace in (self.bfs, self.dfs):
            self.assertEqual(trace["edges"], EXPECTED_EDGES)
            self.assertEqual(trace["nodes"], 7)
            self.assertEqual(trace["from"], 0)

    def test_negative_control_corrupted_trace_is_caught(self):
        # 负面自证：改坏一条 swap 快照，回放器必须报错（不然它只是橡皮图章）
        import copy
        corrupted = copy.deepcopy(self.sort)
        for step in corrupted["steps"]:
            if step["op"] == "swap":
                step["state"] = list(reversed(step["state"]))
                break
        checks = replay.replay_sort(corrupted)
        self.assertTrue(any(not c["ok"] for c in checks))


class TestPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not TRACES.exists():
            raise unittest.SkipTest("缺 build/traces/*.json —— 先跑 run.bat 的导出步")
        cls.tmp = make_tmp("page")
        cls.path = cls.tmp / "viz.html"
        cls.size = page.build_page(TRACES, cls.path)
        cls.html = cls.path.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_html_structure(self):
        self.assertIn("<!DOCTYPE html>", self.html)
        self.assertIn("const TRACES = ", self.html)
        for element_id in ("sort-bars", "graph", "sort-play", "sort-next",
                           "sort-prev", "sort-speed", "graph-play", "graph-next", "graph-prev"):
            self.assertIn(f'id="{element_id}"', self.html, msg=element_id)
        self.assertGreater(self.size, 8000)

    def test_embedded_data_equals_trace_files(self):
        match = re.search(r"const TRACES = (\{.*?\});\n", self.html, re.S)
        self.assertIsNotNone(match)
        embedded = json.loads(match.group(1))
        for name in ("sort", "bfs", "dfs"):
            self.assertEqual(embedded[name], replay.load_trace(TRACES / f"{name}.json"))

    def test_page_build_is_deterministic(self):
        again = self.tmp / "viz2.html"
        page.build_page(TRACES, again)
        self.assertEqual(self.path.read_bytes(), again.read_bytes())

    @unittest.skipUnless(shutil.which("node"), "本机没有 node，跳过 JS 语法体检")
    def test_javascript_syntax_with_node_check(self):
        script = re.search(r"<script>\n(.*)</script>", self.html, re.S).group(1)
        js_path = self.tmp / "extracted.js"
        js_path.write_text(script, encoding="utf-8")
        try:
            result = subprocess.run(["node", "--check", str(js_path)],
                                    capture_output=True, text=True)
        except OSError as err:                 # PATH 上的 shim/伪文件（如误建的同名垃圾）
            self.skipTest(f"node 不可执行：{err}")
        self.assertEqual(result.returncode, 0, msg=result.stderr[:500])


if __name__ == "__main__":
    unittest.main()
