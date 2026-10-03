"""tests/test_showcase.py —— B35 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、协议字节手算表逐条一致（实现 == 手算）、RL 边界字典、规范化规则
真的抹掉了两处【实测】数字、SVG 是 build/ 里的同一份产物、改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b35-showcase-") as tmp:
            fake = Path(tmp) / "showcase.html"
            fake.write_text("手改过的页面", encoding="utf-8")
            sc.OUT = fake
            try:
                self.assertEqual(quiet_main(["showcase", "--check"]), 1)
            finally:
                sc.OUT = original


class TestNormalization(unittest.TestCase):
    def test_measured_values_are_masked(self):
        raw = sc._run([sys.executable, "demo.py"])
        self.assertRegex(raw, r"吞吐【实测】\s+\d+ 条/秒")
        masked = sc._norm(raw)
        self.assertIsNone(re.search(r"吞吐【实测】\s+\d+ 条/秒", masked), "吞吐未规范化")
        self.assertIsNone(re.search(r"重连耗时【实测】\s+\d+ ms", masked), "重连耗时未规范化")
        self.assertIn("吞吐【实测】 <当场> 条/秒", masked)


class TestPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = sc.collect()

    def test_protocol_bytes_impl_equals_hand(self):
        rows = self.payload["protocol"]["rows"]
        self.assertEqual(len(rows), 3)
        for name, impl, hand in rows:
            self.assertEqual(impl, hand, f"{name} 实现与手算不一致")
        self.assertEqual(rows[0][1], "10 0e 00 04 4d 51 54 54 04 02 00 3c 00 02 63 31")
        self.assertEqual(self.payload["protocol"]["rl"],
                         {127: "7f", 128: "80 01", 16383: "ff 7f", 16384: "80 80 01"})

    def test_link_ledger_numbers(self):
        facts = dict(self.payload["facts"])
        self.assertIn("590 == 实收 590", facts["链路完整性"])
        self.assertIn("解析失败 0", facts["链路完整性"])
        self.assertIn("True / False / True", facts["断线重连"])

    def test_svg_is_the_real_artifact(self):
        svg_path = sc.BUILD / "dev01_temperature.svg"
        self.assertEqual(self.payload["svg_bytes"], svg_path.stat().st_size)
        self.assertTrue(self.payload["svg_text"].startswith("<svg"))
        self.assertEqual(self.payload["svg_text"].rstrip(),
                         svg_path.read_text(encoding="utf-8").strip())


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B35-iot-mqtt"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_inline_svg_and_pinned_values(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertIn("<svg xmlns=", text)
        for token in ("590", "80 80 01", "逐字节一致"):
            self.assertIn(token, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
