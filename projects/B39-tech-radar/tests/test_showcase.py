"""tests/test_showcase.py —— B39 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、demo 现算事实（检查器 PASS / 指针计数 / 负面对照 3 条全红 / CRDT 收敛性质）、
示例记录内嵌、改坏必红、标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b39-showcase-") as tmp:
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

    def test_checker_and_negative_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("PASS（0 个问题）", facts["示例记录检查"])
        self.assertIn("路径 4 条 + 提交 1 个", facts["示例记录检查"])
        self.assertIn("3 条改坏全部报红", facts["负面对照（检查器有没有牙齿）"])

    def test_crdt_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("全部一致 = True", facts["CRDT 收敛复现"])
        self.assertIn("交换 50/50；结合 50/50；幂等 1/1", facts["性质抽查"])

    def test_example_record_embedded(self):
        page = sc.OUT.read_text(encoding="utf-8")
        snippet = self.payload["example"].split("## 原理", 1)[0].strip().splitlines()[-1]
        self.assertIn(snippet, page)


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B39-tech-radar"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_demo_sections_present(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for token in ("模板与检查器", "负面对照", "最小复现", "怎么用它"):
            self.assertIn(token, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
