"""tests/test_showcase.py —— B31 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、demo 现算事实（base62 边界 / 关卡计数 / 12 条状态码 / 影子模型）、
三条规范化规则（端口 / Date / 创建响应长度）、改坏必红、标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b31-showcase-") as tmp:
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

    def test_codec_and_gate_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("'PDZI5'", facts["短码从哪来"])
        self.assertIn("'5UfZOVH2ZO3'（11 位）", facts["短码从哪来"])
        self.assertIn("收下并规范化 6 条", facts["目标地址关卡"])
        self.assertIn("拒收 10 条 + 自指环 1 条", facts["目标地址关卡"])

    def test_status_and_shadow_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("12 条全对", facts["状态码语义"])
        self.assertIn("累计命中 75 ==", facts["统计与影子模型"])

    def test_norm_rules(self):
        self.assertEqual(sc._norm("绝对地址 http://127.0.0.1:51198/l/1"),
                         "绝对地址 http://127.0.0.1:<端口>/l/1")
        self.assertEqual(sc._norm("    | Date: Sat, 03 Oct 2026 08:20:01 GMT"),
                         "    | Date: <当场> GMT")
        self.assertEqual(sc._norm("    | Content-Length: 140"),
                         "    | Content-Length: <随 created_at 位数>")

    def test_demo_fully_normalized(self):
        demo = self.payload["demo"]
        self.assertIsNone(re.search(r"127\.0\.0\.1:\d+", demo), "端口未规范化")
        self.assertIsNotNone(re.search(r"Date: <当场> GMT", demo), "Date 未规范化")
        self.assertNotIn("| Content-Length: 140", demo)
        self.assertNotIn("| Content-Length: 139", demo)


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B31-shorturl"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
