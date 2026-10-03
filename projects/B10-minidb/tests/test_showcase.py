"""tests/test_showcase.py —— B10 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、真实跑库的现算事实（WAL 回放 3 条/恢复 [1,2]、CHECKPOINT 清 WAL、
ROLLBACK 还原、sqlite3 对拍 300 轮）、数据内嵌（const DATA）、改坏必红、标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b10-showcase-") as tmp:
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
        self.assertEqual(facts["WAL 恢复"], "重启回放 3 条日志，2 行完整（模拟崩溃）")
        self.assertEqual(facts["sqlite3 对拍"], "300 轮随机 SQL 逐行一致（mini vs sqlite3）")
        self.assertEqual(facts["测试方法"], "62 个（tests/ 里 def test_ 现数）")

    def test_demo_and_checks_pins(self):
        payload = self.payload
        self.assertEqual(payload["demo"]["wal"]["recovered_ids"], [1, 2])
        self.assertFalse(payload["demo"]["checkpoint"]["wal_alive"])
        self.assertEqual(payload["demo"]["rollback"]["kept"], [1])
        self.assertEqual(payload["checks"],
                         {"recovery": True, "checkpoint": True, "rollback": True, "agree": 300})

    def test_data_embedded(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertIn("const DATA = {", text)
        self.assertIn('"recovered_ids":[1,2]', text)


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B10-minidb"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_badges_and_chips(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertIn("recovery: ok", text)
        for token in ("WAL 恢复", "CHECKPOINT", "事务回滚", "sqlite 对拍"):
            self.assertIn(token, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
