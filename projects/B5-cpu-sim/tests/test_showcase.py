"""tests/test_showcase.py —— B5 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、时空图解析正确性（行数/S、F 计数与汇总一致）、双模型对拍数值、
改坏必红、页面标记与零外链。解析器是重点——它要对抗"超宽单元格"的列漂移。
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
        with tempfile.TemporaryDirectory(prefix="b5-showcase-") as tmp:
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

    def test_selftest_and_dual_model_numbers(self):
        self.assertEqual(self.payload["assertions"], 42)
        self.assertEqual(self.payload["failures"], 0)
        b = self.payload["bubble"]
        self.assertEqual(b["single_cycles"], 159)
        self.assertEqual(b["pipeline_cycles"], 219)
        self.assertEqual(b["stalls"], 10)
        self.assertEqual(b["sorted"], "1 2 3 4 5")
        self.assertTrue(b["consistent"], "双模型寄存器必须逐字节一致")

    def test_chart_parse_matches_summary(self):
        for key in ("chart_bubble", "chart_loop"):
            chart = self.payload[key]
            cells = [c for row in chart["rows"] for c in row]
            stalls = cells.count("S")
            flushes = cells.count("F")
            m = re.search(r"停顿 (\d+) 次、冲刷 (\d+) 次", chart["summary"])
            self.assertIsNotNone(m, chart["summary"])
            self.assertEqual(stalls, int(m.group(1)), key)
            # 每次冲刷会同时"洗掉"两条在途指令，各占一格 → F 格数 = 冲刷次数 × 2
            # （bubble 58=29×2、loop 4=2×2 实测如此；两张图口径一致）
            self.assertEqual(flushes, 2 * int(m.group(2)), key)

    def test_chart_shapes(self):
        self.assertEqual(len(self.payload["chart_bubble"]["rows"]), 219)
        self.assertEqual(len(self.payload["chart_loop"]["rows"]), 16)
        for row in self.payload["chart_bubble"]["rows"]:
            self.assertEqual(len(row), 5)
        first = self.payload["chart_bubble"]["rows"][0]
        self.assertEqual(first[0], "addi")
        self.assertEqual(self.payload["chart_bubble"]["rows"][-1][4], "halt")


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B5-cpu-sim"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
