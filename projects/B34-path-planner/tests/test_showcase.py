"""tests/test_showcase.py —— B34 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、耗时列规范化真生效（合成样例 + 页面无残留 ms 数字）、
对拍/可采纳性/反例/动画页的现算事实、五行走廊对比表、改坏必红、标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b34-showcase-") as tmp:
            fake = Path(tmp) / "showcase.html"
            fake.write_text("手改过的页面", encoding="utf-8")
            sc.OUT = fake
            try:
                self.assertEqual(quiet_main(["showcase", "--check"]), 1)
            finally:
                sc.OUT = original


class TestNormalization(unittest.TestCase):
    def test_ms_column_masked(self):
        sample = "   Dijkstra（4 邻域）           56.000    517       1.3 ms\n"
        masked = sc._norm(sample)
        self.assertIsNone(re.search(r"\d+(\.\d+)? ms", masked))
        self.assertIn("<当场> ms", masked)


class TestPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = sc.collect()

    def test_parity_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("30/30", facts["同源对拍"])
        self.assertIn("29/30", facts["同源对拍"])
        self.assertIn("+4.686", facts["可采纳性（是量出来的）"])
        self.assertIn("0.585786", facts["反例（seed=3）"])
        self.assertIn("218 步", facts["动画页"])
        self.assertIn("10179", facts["动画页"])

    def test_compare_table_rows(self):
        rows = self.payload["compare_rows"]
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0], ["Dijkstra（4 邻域）", "56.000", "517"])
        self.assertEqual(rows[1], ["A* 曼哈顿（4 邻域）", "56.000", "211"])

    def test_demo_ms_masked(self):
        self.assertIsNone(re.search(r"\d+(\.\d+)? ms", self.payload["demo"]))


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B34-path-planner"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
