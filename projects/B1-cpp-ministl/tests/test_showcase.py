"""tests/test_showcase.py —— B1 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、真跑出来的自测/对拍数字（268 断言、253086 项对拍检查）、
五段演示的分段解析、改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b1-showcase-") as tmp:
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

    def test_selftest_and_cross_check_numbers(self):
        p = self.payload
        self.assertEqual(p["passed"], 268)
        self.assertEqual(p["cross_total"], 253086)
        self.assertEqual(p["cross_asserts"], 141)
        self.assertEqual(p["demo_total"], 64306)

    def test_per_module_assertions(self):
        modules = {name: int(count) for name, count in self.payload["per_module"]}
        self.assertEqual(modules, {
            "vector 边界": 29, "list 边界": 20, "string 边界": 37,
            "RAII": 9, "待办 CRUD/回读": 32,
        })

    def test_demo_cross_types(self):
        self.assertEqual(self.payload["cross_types"],
                         {"vector": 14907, "list": 22960, "string": 26439})

    def test_demo_has_five_sections(self):
        sections = self.payload["sections"]
        self.assertEqual(len(sections), 5)
        self.assertIn("vector：增长曲线", sections[0]["title"])
        self.assertIn("对拍", sections[-1]["title"])


class TestRenderedPage(unittest.TestCase):
    def test_pinned_numbers_appear_in_page(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for number in ("268", "253086", "64306", "14907", "22960", "26439"):
            self.assertIn(number, text)

    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B1-cpp-ministl"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
