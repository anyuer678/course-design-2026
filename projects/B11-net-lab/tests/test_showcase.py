"""tests/test_showcase.py —— B11 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、演示解析的四个结构化视图（请求旅程 / 越界拒绝表 / 搜索解析 / GBN 表）、
规范化规则真的抹掉了四处波动的数字、改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b11-showcase-") as tmp:
            fake = Path(tmp) / "showcase.html"
            fake.write_text("手改过的页面", encoding="utf-8")
            sc.OUT = fake
            try:
                self.assertEqual(quiet_main(["showcase", "--check"]), 1)
            finally:
                sc.OUT = original


class TestNormalization(unittest.TestCase):
    def test_volatile_values_are_masked(self):
        demo = sc._norm(sc._run([sys.executable, "demo.py"]))
        self.assertIsNone(re.search(r"127\.0\.0\.1:\d+", demo), "临时端口未规范化")
        self.assertNotIn("GMT", demo, "Date 头未规范化")
        self.assertNotRegex(demo, r"'open_now': \d+", "open_now 未规范化")
        self.assertNotRegex(demo, r"耗时=[\d.]+s", "回环耗时未规范化")
        self.assertIn("127.0.0.1:<临时端口>", demo)


class TestPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = sc.collect()

    def test_journey_parse(self):
        j = self.payload["journey"]
        self.assertEqual(len(j["request"]), 5)
        self.assertEqual(j["request"][0], "PUT /kv/repair HTTP/1.1")
        self.assertEqual(j["消耗字节"], "100")
        self.assertTrue(j["解析结论"].startswith("PUT '/kv/repair'"))
        self.assertEqual(len(j["response"]), 7)
        self.assertEqual(j["response"][0], "HTTP/1.1 200 OK")

    def test_boundary_tables(self):
        b = self.payload["boundaries"]
        codes = dict(b["codes"])
        self.assertEqual(len(codes), 8)
        self.assertEqual(codes["请求目标超长"], "HTTP/1.1 414 URI Too Long")
        self.assertEqual(codes["chunked（不支持也不忽略）"], "HTTP/1.1 501 Not Implemented")
        self.assertEqual(len(b["parse_errors"]), 3)
        self.assertIn("裸 LF", b["parse_errors"][0][1])

    def test_gbn_tables(self):
        g = self.payload["gbn"]
        self.assertEqual([r[0] for r in g["rows"]], [0, 10, 20, 30, 40])
        self.assertEqual(g["rows"][0][5], "100.0%")
        self.assertEqual(g["rows"][-1][2], 189)
        self.assertEqual([w[0] for w in g["windows"]], [1, 2, 4, 8])
        self.assertIn("True", g["notes"]["reproducible"])
        self.assertIn("字节一致=True", g["notes"]["real_udp"])

    def test_test_count_from_two_core_files(self):
        self.assertEqual(self.payload["method_count"], 91)


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B11-net-lab"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_pinned_numbers_appear_in_page(self):
        text = sc.OUT.read_text(encoding="utf-8")
        # 状态码表 25 条 = 原 23 + 401/410（2026-10-04 LinkBox 产品层需要，见 B11 README）
        for token in ("91 项", "状态码表 25 条", "HTTP/1.1 414 URI Too Long", "189"):
            self.assertIn(token, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
