"""tests/test_showcase.py —— B29 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、四条规范化规则真生效（warehouse 临时目录 / 生成用时 / 耗时列 /
Spark JVM 退出清理行——PID 每次不同）、数据账与倾斜读数、改坏必红、页面标记与零外链。
注意：collect() 每次真跑约 30 秒的 Spark 演示——本文件会慢，那是设计成本。
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
        with tempfile.TemporaryDirectory(prefix="b29-showcase-") as tmp:
            fake = Path(tmp) / "showcase.html"
            fake.write_text("手改过的页面", encoding="utf-8")
            sc.OUT = fake
            try:
                self.assertEqual(quiet_main(["showcase", "--check"]), 1)
            finally:
                sc.OUT = original


class TestNormalization(unittest.TestCase):
    def test_rules_on_synthetic_sample(self):
        sample = (
            "  warehouse 位置                file:/C:/Users/x/AppData/Local/Temp/b29-warehouse-abc123\n"
            "  生成 40 万行用时                  1.7 s\n"
            "  耗时（3 次取中——单次实测）             plain 157 ms / salted 197 ms\n"
            "成功: 已终止 PID 10312 (属于 PID 27412 子进程)的进程。\n"
        )
        masked = sc._norm(sample)
        self.assertNotIn("b29-warehouse-abc123", masked)
        self.assertNotIn("1.7 s", masked)
        self.assertNotIn("157 ms", masked)
        self.assertNotIn("PID 10312", masked)
        self.assertIn("<当场>", masked)
        self.assertIn("已按规则移除", masked)


class TestPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = sc.collect()

    def test_data_and_skew_numbers(self):
        facts = dict(self.payload["facts"])
        self.assertIn("399888", facts["合成日志"])
        self.assertIn("'bad_timestamp': 40", facts["合成日志"])
        self.assertIn("True", facts["清洗三方对账"])
        self.assertIn("2.51", facts["倾斜实验"])
        self.assertIn("1.00", facts["倾斜实验"])
        self.assertIn("207159", facts["倾斜实验"])

    def test_demo_clean_of_volatile_bits(self):
        demo = self.payload["demo"]
        # 注意：demo 正文里 'WARN' 是日志级别数据，合法；这里盯的是 JVM 日志行本身
        self.assertFalse(re.search(r"\d\d/\d\d/\d\d \d\d:\d\d:\d\d WARN", demo), "JVM 日志混进来了")
        self.assertNotIn("winutils", demo)
        self.assertNotIn("log4j", demo)
        self.assertNotIn("b29-warehouse", demo)   # warehouse 临时目录已规范化
        self.assertIn("<临时目录>", demo)
        self.assertNotIn("fil<临时目录>", demo)   # file: 前缀要被一起吃掉
        # 注意：worker 解释器的 Python 安装路径含 AppData 且是稳定内容（环境段），不规范化


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B29-bigdata-spark"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_pinned_values_in_page(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for token in ("399888", "2.51", "1.00", "&lt;当场&gt;"):  # 页内 <当场> 是转义形态
            self.assertIn(token, text)
        self.assertNotIn("<当场>", text.replace("&lt;当场&gt;", ""))

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
