"""tests/test_showcase.py —— B14 展示页生成器自测（口径：showcase/SPEC.md）。

B14 没有 Python 测试框架（Java 项目，自检入口是 PaintTests）——本文件直跑：
`python tests\\test_showcase.py`（口径同批次③的 C++ 项目）。

钉住：页面新鲜度、Java 现算事实（7106 项 / 9 组 / 像素统计）、PNG 内嵌与确定性 sha1、
规范化规则（临时文件名）、改坏必红、标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b14-showcase-") as tmp:
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

    def test_selftest_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("7106 项检查、0 失败", facts["自检（headless）"])
        self.assertIn("9 组", facts["自检（headless）"])
        self.assertIn("随机操作 vs 快照模型", facts["自检（headless）"])
        self.assertEqual(len(self.payload["modules"]), 9)

    def test_offscreen_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("红 1160 / 蓝 834 / 绿 642", facts["离屏演示"])
        self.assertIn("[rect, ellipse, line]", facts["离屏演示"])
        self.assertIn("21 个源文件", facts["类体系"])

    def test_png_deterministic(self):
        facts = dict(self.payload["facts"])
        self.assertIn("内嵌 PNG 3404 字节", facts["真画出来的图"])
        self.assertEqual(self.payload["png_sha"],
                         "a2b8218b2571beaaf1db5c9e597619a127769a67")

    def test_demo_path_normalized(self):
        demo = self.payload["demo"]
        self.assertIn("<临时目录>b14-demo<随机>.png", demo)
        self.assertIsNone(re.search(r"b14-demo\d+\.png", demo), "随机文件名未规范化")


class TestRenderedPage(unittest.TestCase):
    def test_png_embedded(self):
        text = sc.OUT.read_text(encoding="utf-8")
        m = re.search(r'data:image/png;base64,([A-Za-z0-9+/=]+)', text)
        self.assertIsNotNone(m, "页面应内嵌 PNG data URI")
        self.assertGreater(len(m.group(1)), 4000, "内嵌 PNG 的 base64 长度不合常理（3404 字节→约 4.5k 字符）")

    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B14-java-paint"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
