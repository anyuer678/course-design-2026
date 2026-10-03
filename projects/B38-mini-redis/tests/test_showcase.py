"""tests/test_showcase.py —— B38 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、RESP2 逐条 wire 字节（编码即协议）、命令链读数、坏帧跳过、
改坏必红、标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b38-showcase-") as tmp:
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
        self.assertIn("5 种类型前缀（+/-/:/$/*）", facts["RESP2 协议"])
        self.assertEqual(facts["复制协议"], "PSYNC → FULLRESYNC → RDB 快照 + 增量传播")
        self.assertEqual(facts["测试方法"], "58 个（tests/ 里 def test_ 现数）")

    def test_wire_trace_pins(self):
        trace = self.payload["resp_trace"]
        self.assertEqual(trace[0]["cmd"], "SET greeting hello")
        self.assertEqual(trace[0]["wire"],
                         "*3\r\n$3\r\nSET\r\n$8\r\ngreeting\r\n$5\r\nhello")
        self.assertEqual(trace[0]["reply"], "OK")
        self.assertEqual(trace[1]["reply"], "hello")

    def test_command_chain_pins(self):
        self.assertEqual(self.payload["commands"],
                         ["SET greeting hello", "GET greeting", "INCR counter",
                          "INCR counter (again)", "EXPIRE greeting 60", "TTL greeting",
                          "GET missing (nil)", "DEL counter", "GET counter (已删，nil)"])


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B38-mini-redis"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_wire_and_chain_rendered(self):
        text = sc.OUT.read_text(encoding="utf-8")
        # 页面内嵌的 DATA 是 JSON 转义后的文本：wire 里的 CRLF 以 `\r\n`（反斜杠 r n）出现
        for token in ("SET greeting hello", "FULLRESYNC", "TTL greeting",
                      r"\r\n$3\r\nSET", "RESP2 编解码与命令"):
            self.assertTrue(token in text, f"页面缺少 {token!r}")

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
