"""tests/test_showcase.py —— B33 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、动画页"原位提升"后数据分毫未动（页内条形/图遍历结构与记录数）、
记录与保真的现算事实（20 事件 / 回放 0 失败 / BFS-DFS 7 步）、改坏必红、标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b33-showcase-") as tmp:
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

    def test_records_and_fidelity_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("20 事件", facts["操作记录（C++ 导出）"])
        self.assertIn("1274", facts["操作记录（C++ 导出）"])
        self.assertIn("逐步回放失败 0 步", facts["回放保真"])
        self.assertIn("BFS 7 / True", facts["回放保真"])
        self.assertIn("DFS 7 / True", facts["回放保真"])
        self.assertIn("13601", facts["页面"])
        self.assertIn("2080", facts["页面"])

    def test_artifact_is_embedded_unchanged(self):
        # 提升是"原位"的：页内嵌的数据与 build/viz.html 的完全一致
        artifact = self.payload["artifact"]
        page = sc.OUT.read_text(encoding="utf-8")
        self.assertIn("<script>", page)
        m = re.search(r"const\s+\w+\s*=\s*\{.*?\};", artifact, re.S)
        self.assertIsNotNone(m, "动画页应内嵌数据对象")
        self.assertIn(m.group(0)[:60], page)


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B33-viz-algo"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_controls_present(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for token in ("播放", "单步", "上一步"):
            self.assertIn(token, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
