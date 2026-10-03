"""tests/test_showcase.py —— B9 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、真数据抽查（183 断言、五套调度的教材数值与甘特图段数、
置换表与 Belady 异常、银行家三幕、FAT 复满盘、生产消费者计数）、改坏必红、
页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b9-showcase-") as tmp:
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

    def test_selftest_counts(self):
        self.assertEqual(self.payload["assertions"], 183)
        self.assertEqual(self.payload["failures"], 0)

    def test_sched_textbook_numbers(self):
        sched = {a["name"]: a for a in self.payload["sched"]}
        self.assertEqual(len(sched), 5)
        self.assertEqual(sched["FCFS"]["wait"], 4.75)
        self.assertEqual(sched["SJF"]["wait"], 4.00)
        self.assertAlmostEqual(sched["RR q=2"]["wait"], 5.00)
        self.assertEqual(sched["RR q=100"]["wait"], sched["FCFS"]["wait"],
                         "q 极大必须退化为 FCFS")
        rr2 = [seg for _, a, b in sched["RR q=2"]["gantt"] for seg in [b - a]]
        self.assertEqual(sum(rr2), 16, "甘特图必须铺满 0..16")
        self.assertGreaterEqual(len(sched["RR q=2"]["gantt"]), 9, "RR 切片多，段数应明显更多")

    def test_paging_table_and_belady(self):
        pg = self.payload["paging"]
        self.assertEqual(len(pg["rows"]), 2)
        three, four = pg["rows"]
        self.assertEqual((three["frames"], four["frames"]), (3, 4))
        self.assertEqual(three["faults"]["FIFO"], 9)
        self.assertEqual(four["faults"]["FIFO"], 10)
        self.assertEqual(three["faults"]["OPT"], 7)
        self.assertIn("9", pg["belady"])
        self.assertIn("10", pg["belady"])

    def test_banker_fat_producer_blocks(self):
        self.assertEqual(len(self.payload["banker"]), 4)
        self.assertIn("安全", self.payload["banker"][0])
        self.assertTrue(any("回滚" in line for line in self.payload["banker"]))
        self.assertEqual(len(self.payload["fat"]), 3)
        self.assertTrue(any("复用" in line for line in self.payload["fat"]))
        self.assertTrue(self.payload["pc"], "生产者-消费者段必须解析出来")
        self.assertIn("40000", self.payload["pc"][-1])


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B9-os-sim"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_gantt_bars_rendered(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertEqual(text.count('class="grow"'), 5, "五套算法各一条时间轴")
        self.assertIn('class="p1"', text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
