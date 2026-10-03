"""tests/test_showcase.py —— B24 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、六段演示解析（失败样例原因各不相同）、三张产物缩略图真的来自
build/ 里的原产物（字节数对账 + 缩略图尺寸）、改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b24-showcase-") as tmp:
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

    def test_demo_sections_and_failures(self):
        # 16 同步核心 + 本文件 7 个方法（tests/ def test_ 现数会把自己数进来，B12 同款口径）
        self.assertEqual(self.payload["method_count"], 16 + 7)
        failures = self.payload["failures"]
        self.assertEqual(len(failures), 5)
        by_name = dict(failures)
        # 如实口径：纯背景与低对比共用"无边缘"分支（项目测试同样只要求 >= 4 种）
        self.assertGreaterEqual(len(set(by_name.values())), 4)
        self.assertIn("边缘密度过高", by_name["纯噪声"])
        self.assertIn("图像太小", by_name["图像太小"])
        self.assertIn("面积达标", by_name["文档太小"])

    def test_gallery_is_built_from_the_real_artifacts(self):
        gallery = self.payload["gallery"]
        self.assertEqual(len(gallery), 3)
        for (caption, g), name in zip(gallery, ("demo_input.png", "demo_rectified.png", "demo_binary.png")):
            real = (sc.BUILD / name).stat().st_size
            self.assertEqual(g["orig_bytes"], real, f"{caption} 的原产物字节数对不上")
            self.assertTrue(g["data_uri"].startswith("data:image/"))
        self.assertTrue(gallery[0][1]["data_uri"].startswith("data:image/jpeg"))
        self.assertTrue(gallery[2][1]["data_uri"].startswith("data:image/png"))
        self.assertEqual(gallery[0][1]["thumb_w"], 340, "缩略图应为 340px 宽（确定性缩放口径）")
        self.assertEqual(gallery[0][1]["orig_size"], "900x1200")


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B24-cv-scanner"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_gallery_and_truth_claims_in_page(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertEqual(text.count("data:image/"), 3)
        for token in ("20/20", "0.9982", "五类失败样例"):
            self.assertIn(token, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
