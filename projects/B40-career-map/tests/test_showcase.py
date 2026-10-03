"""tests/test_showcase.py —— B40 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、demo/JSON 现算事实（31 条证据 PASS / 22 个提交号 / 缺口 2 个）、
矩阵行结构与缺口标记、改坏必红、标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b40-showcase-") as tmp:
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

    def test_evidence_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("31 条核验 PASS（0 个问题）", facts["证据索引"])
        self.assertIn("22 个提交号逐条在 git 里存在", facts["证据索引"])

    def test_jd_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("已覆盖 11 个技能面", facts["示例 JD 映射"])
        self.assertIn("缺口 2 个（容器与云原生、消息队列与中间件）", facts["示例 JD 映射"])
        self.assertIn("未提及 2 个", facts["示例 JD 映射"])

    def test_matrix_pins(self):
        rows = self.payload["matrix"]
        self.assertEqual(len(rows), 13)
        self.assertEqual(rows[0], ["数据结构与算法", "数据结构、算法", "已覆盖（3 条）",
                                   "b2-datastruct、b12-algo、b4-algebra"])
        gaps = [r[0] for r in rows if "缺口" in r[2]]
        self.assertEqual(gaps, ["容器与云原生", "消息队列与中间件"])


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B40-career-map"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_gap_rows_marked(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertIn('class="sw-gap"', text)
        self.assertIn("消息队列与中间件", text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
