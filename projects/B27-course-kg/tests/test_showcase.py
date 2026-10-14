"""tests/test_showcase.py —— B27 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、交互图（38 节点/42 边）与闭包/解锁/缺口/路径的现算事实、
演示输出的 GBK 扫净（[ok]/[fail] 取代 Unicode 对勾/叉号）、改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b27-showcase-") as tmp:
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

    def test_graph_and_queries(self):
        self.assertEqual(self.payload["n_nodes"], 38)
        self.assertEqual(self.payload["n_edges"], 42)
        facts = dict(self.payload["facts"])
        self.assertIn("B1 / B2 / B5 / B6 / B8", facts["闭包查询"])
        self.assertEqual(self.payload["des_b11"], 14)
        self.assertEqual(len(self.payload["miss8"]), 8)
        self.assertEqual(len(self.payload["miss5"]), 5)
        self.assertEqual(len(self.payload["path"]), 14)
        self.assertEqual(self.payload["path"][0], "B1")
        self.assertEqual(self.payload["path"][-1], "B18")

    def test_demo_gbk_swept_and_temp_normalized(self):
        demo = self.payload["demo"]
        self.assertNotIn("\u2714", demo)
        self.assertNotIn("\u2718", demo)
        self.assertIn("[ok] 38 个任务节点", demo)
        self.assertNotIn("AppData", demo)


class TestRenderedPage(unittest.TestCase):
    def test_interactive_graph_is_embedded(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertEqual(text.count('class="node"'), 38)
        self.assertEqual(text.count('class="edge"'), 42)
        self.assertIn("CLOSURE", text)

    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B27-course-kg"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
