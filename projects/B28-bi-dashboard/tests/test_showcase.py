"""tests/test_showcase.py —— B28 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、看板原位提升后的合规补齐（DOCTYPE 大写/双引号/三个锚点）、
六指标与洞察的现算数字、血缘图（SVG+脚本）真的内嵌且来源说明已修正如实、
改坏必红、零外链。
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
        with tempfile.TemporaryDirectory(prefix="b28-showcase-") as tmp:
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

    def test_metric_numbers(self):
        facts = dict(self.payload["facts"])
        self.assertIn("765,880", facts["六指标两路对拍"])
        self.assertIn("41.7%（204/489 客户）", facts["六指标两路对拍"])
        self.assertIn("0.563", facts["洞察"])
        self.assertIn("1.528", facts["洞察"])
        self.assertIn("无", facts["六指标两路对拍"][-3:])  # 对拍异常清单

    def test_demo_temp_dir_normalized(self):
        self.assertNotIn("b28-dash", self.payload["demo"])
        self.assertIn("<临时目录>", self.payload["demo"])

    def test_lineage_source_note_is_fixed(self):
        # 2026-10-03 修正：血缘页来源必须是 lineage 自己的定义，不是 B27 的课程 CSV
        self.assertIn("数据来源：bi/lineage.py", self.payload["lineage_note"])
        self.assertNotIn("data/courses.csv", self.payload["lineage_note"])


class TestRenderedPage(unittest.TestCase):
    def test_promoted_dashboard_compliance(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!DOCTYPE html>"))
        self.assertIn('lang="zh-CN"', text)
        self.assertIn('<meta charset="utf-8">', text)
        self.assertEqual(text.count("<svg"), 4)  # 看板 3 + 血缘 1

    def test_required_markers_and_lineage_script(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B28-bi-dashboard"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", "指标血缘图"):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
