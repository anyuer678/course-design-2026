"""tests/test_showcase.py —— B2 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、真跑出来的自测/对拍数字（428 断言、141228 项对拍检查）、
六段演示的分段解析、交互菜单截取的版式、改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b2-showcase-") as tmp:
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
        self.assertEqual(p["passed"], 428)
        self.assertEqual(p["cross_total"], 141228)
        self.assertEqual(p["cross_asserts"], 211)

    def test_per_module_assertions(self):
        # 七个结构 + 菜单脚本（脚本驱动菜单也算一个模块）；模块合计 217 + 对拍断言 211 = 428
        modules = {name: int(count) for name, count in self.payload["per_module"]}
        self.assertEqual(modules, {
            "顺序表边界": 17, "单链表边界": 24, "栈/队列/表达式": 42,
            "BST 边界": 26, "哈希": 36, "堆": 25, "并查集/图": 30,
            "菜单脚本": 17,
        })
        self.assertEqual(sum(modules.values()) + self.payload["cross_asserts"],
                         self.payload["passed"])

    def test_demo_has_six_sections(self):
        sections = self.payload["sections"]
        self.assertEqual(len(sections), 6)
        self.assertIn("顺序表 vs 单链表", sections[0]["title"])
        self.assertIn("并查集", sections[-1]["title"])

    def test_menu_snapshot_shape(self):
        menu = self.payload["menu"]
        self.assertGreaterEqual(len(menu), 4)
        joined = "\n".join(menu)
        self.assertIn("数据结构实验台", joined)
        self.assertIn("退出", joined)
        self.assertIn("循环队列", joined)
        self.assertTrue(menu[-1].startswith("选择"), menu[-1])


class TestRenderedPage(unittest.TestCase):
    def test_pinned_numbers_appear_in_page(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for number in ("428", "141228", "44850", "494", "1538", "390", "199"):
            self.assertIn(number, text)

    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B2-datastruct-lab"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
