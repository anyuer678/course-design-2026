"""tests/test_showcase.py —— B32 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、四组对照的结构化解析（SQL/XSS/穿越/扫描器）、第 3 段计时脱敏规则
真的抹掉了会过期的数字、改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b32-showcase-") as tmp:
            fake = Path(tmp) / "showcase.html"
            fake.write_text("手改过的页面", encoding="utf-8")
            sc.OUT = fake
            try:
                self.assertEqual(quiet_main(["showcase", "--check"]), 1)
            finally:
                sc.OUT = original


class TestMasking(unittest.TestCase):
    def test_live_measurements_are_masked(self):
        raw = sc._run([sys.executable, "demo.py"])
        masked = sc._mask_live_measurements(raw)
        # 原始输出里存在吞吐/耗时数字，脱敏后必须一个不剩
        self.assertRegex(raw, r"\d[\d,]*(\.\d+)? 次/秒")
        self.assertIsNone(re.search(r"\d[\d,]*(\.\d+)? 次/秒", masked), "次/秒 未脱敏")
        self.assertIsNone(re.search(r"慢 [\d,]+ 倍", masked), "倍数 未脱敏")
        self.assertIsNone(re.search(r"[\d.]+ 小时", masked), "字典估算 未脱敏")
        self.assertIn("[现场] 次/秒", masked)
        self.assertIn("PBKDF2 迭代   1,000", masked, "阶梯数字（稳定）不该被脱敏")


class TestPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = sc.collect()

    def test_sql_table(self):
        sql = self.payload["sql"]
        self.assertEqual(len(sql), 14)
        self.assertEqual(sql[0][0], "登录·正常口令")
        self.assertIn("修复版：被拒", sql[1][2])
        row = next(r for r in sql if r[0].startswith("查询·UNION 取凭据"))
        self.assertIn("泄漏 2 行", row[1])

    def test_xss_table(self):
        xss = self.payload["xss"]
        self.assertEqual(len(xss), 8)
        payloads = [r for r in xss if "真起服务" not in r[0]]
        self.assertEqual(len(payloads), 6)
        self.assertTrue(all(f == 0 for _l, _v, f in payloads if f is not None))
        self.assertEqual(sum(v for _l, v, _f in payloads), 11)

    def test_traversal_and_scanner(self):
        t = self.payload["traversal"]
        self.assertEqual(len(t["load_rows"]), 15)
        self.assertTrue(any("标准库参照" in ln for ln in t["ref_lines"]))
        s = self.payload["scanner"]
        sqli = next(x for x in s["files"] if x["file"] == "sqli.py")
        self.assertEqual(sqli["count"], 8)
        self.assertEqual(len(sqli["sites"]), 8)
        self.assertIn("login_concat", sqli["sites"])
        self.assertIn("order_whitelist", sqli["sites"])

    def test_test_count_includes_showcase_file(self):
        # 50 核心 + 本文件 10 个方法（tests/ def test_ 现数会把自己数进来，B12 同款口径）
        self.assertEqual(self.payload["method_total"], 50 + 10)


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B32-sec-lab"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_masked_placeholder_in_page(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertIn("[现场]", text)
        self.assertIsNone(re.search(r"\d[\d,]+ 次/秒", text.split("</pre>")[0]),
                          "页面原文区不应残留实时吞吐数字")

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
