"""tests/test_showcase.py —— B30 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、模拟现算事实（选举时间线、§5.4.2 ghost 泄漏=无、一致性哈希
23.9% vs 81.0%）、改坏必红、标记与零外链。
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
        self.assertEqual(quiet_main(["--check"]), 0)

    def test_tampered_page_turns_red(self):
        original = sc.OUT
        with tempfile.TemporaryDirectory(prefix="b30-showcase-") as tmp:
            fake = Path(tmp) / "showcase.html"
            fake.write_text("手改过的页面", encoding="utf-8")
            sc.OUT = fake
            try:
                self.assertEqual(quiet_main(["--check"]), 1)
            finally:
                sc.OUT = original

    def test_default_mode_reports_fresh(self):
        self.assertEqual(quiet_main([]), 0)


class TestPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = sc.collect()

    def test_facts_pins(self):
        facts = dict(self.payload["facts"])
        self.assertIn("ghost 泄漏：无", facts["§5.4.2 场景"])
        self.assertEqual(facts["一致性哈希"], "扩容 4→5 搬移 23.9%（朴素取模 81.0%）")
        self.assertEqual(facts["测试方法"], "37 个（tests/ 里 def test_ 现数）")

    def test_elect_pins(self):
        elect = self.payload["elect"]
        self.assertEqual(elect["leader"], 2)
        self.assertEqual(elect["elections"], 1)
        self.assertEqual(elect["timeline"][0], "t=18 节点2 发起选举 (term=1)")
        self.assertTrue(any("当选 leader" in ln for ln in elect["timeline"]))

    def test_raft_and_hash_pins(self):
        raft = self.payload["raft"]
        self.assertFalse(raft["ghost_leaked"])
        self.assertTrue(raft["real_ok"])
        self.assertEqual((raft["old_term"], raft["new_term"]), (1, 2))
        self.assertEqual((raft["old_leader"], raft["new_leader"]), (2, 1))
        self.assertEqual(self.payload["hash"], {"cons": 0.239, "naive": 0.809})


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B30-mini-raft"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_timeline_rendered(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertIn("承认 leader 节点2", text)
        self.assertIn("搬移 23.9%", text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
