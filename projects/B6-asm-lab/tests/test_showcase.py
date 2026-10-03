"""tests/test_showcase.py —— B6 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、真数据抽查（373 断言、四探针掩码全 0 且反面教材=1、23 项反汇编对照、
五段演示解析、序言截取含 push rbp/leave）、改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b6-showcase-") as tmp:
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

    def test_selftest_counts(self):
        self.assertEqual(self.payload["passed"], 373)
        self.assertEqual(self.payload["failed"], 0)
        per = self.payload["per_func"]
        self.assertEqual(per.get("字符串反转"), "130")
        self.assertEqual(per.get("斐波那契"), "109")
        self.assertEqual(per.get("排序"), "65")
        total = sum(int(v) for v in per.values())
        self.assertEqual(total, 373, "逐段断言数必须加起来等于总数")

    def test_abi_masks(self):
        masks = self.payload["masks"]
        for name in ("reverse", "fib", "sort", "sum"):
            self.assertEqual(masks.get(name), 0, f"{name} 的掩码必须为 0（守约）")
        self.assertEqual(masks.get("反面教材"), 1, "反面教材必须亮 bit0")

    def test_disasm_items_and_snippet(self):
        self.assertEqual(self.payload["disasm_items"], 23)
        self.assertEqual(len(self.payload["ok_items"]), 23)
        self.assertIn("push   rbp", self.payload["snippet"])
        self.assertIn("leave", self.payload["snippet"])
        self.assertIn("ret", self.payload["snippet"])

    def test_demo_sections_parsed(self):
        sections = self.payload["sections"]
        self.assertEqual(len(sections), 5)
        titles = [s["title"] for s in sections]
        self.assertTrue(any("字符串反转" in t for t in titles))
        body = "\n".join(line for s in sections for line in s["lines"])
        self.assertIn("!bal-msa ,olleH", body)
        self.assertIn("12200160415121876738", body, "fib(93) 的边界值必须在演示里")


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B6-asm-lab"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
