"""tests/test_showcase.py —— B41 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、demo 现算事实（核验 PASS / 候选清零 / 负面对照 3 条）、选定清单 5 条
（标题+日期）、毫秒规范化三条规则、改坏必红、标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b41-showcase-") as tmp:
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

    def test_checker_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("PASS（0 个问题）", facts["事实核验"])
        self.assertIn("收官态——双空才红", facts["事实核验"])
        self.assertIn("已清零：5 个候选全部选定实施", facts["候选表"])
        self.assertIn("3 条改坏全部报红", facts["负面对照（核验器有没有牙齿）"])

    def test_chosen_pins(self):
        chosen = self.payload["chosen"]
        self.assertEqual(len(chosen), 5)
        self.assertEqual(chosen[0]["title"], "B38 主从复制（RESP 内复制协议子集）")
        self.assertEqual(chosen[0]["date"], "2026-10-02")
        self.assertEqual(chosen[-1]["evidence"]["path"], "projects/B23-ml-from-scratch/README.md")

    def test_norm_rules(self):
        # 规范化把数字与前后对齐空格一起压成单空格：demo 数字列按宽度对齐，
        # 中位数宽度跨机不同，保留原空格会漂（2026-10-11 CI 实测）。
        sample = "  写 8KB 记录（60 次中位数）             plain    0.398 ms"
        self.assertEqual(sc._norm(sample), "  写 8KB 记录（60 次中位数） plain <当场> ms")
        sample = "  写 8KB + fsync（60 次中位数）   fsync  12.34 ms"
        self.assertEqual(sc._norm(sample), "  写 8KB + fsync（60 次中位数） fsync <当场> ms")
        sample = "  解读                            「提交即持久」的边际成本 ≈ 0.304 ms/条（本机介质相关，仅供参考）"
        self.assertIn("<当场> ms/条", sc._norm(sample))

    def test_demo_has_no_raw_ms(self):
        self.assertIsNone(re.search(r"\d+\.\d+ ms", self.payload["demo"]),
                          "规范化后不应残留裸毫秒读数")


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B41-thesis-seeds"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_chosen_table_rendered(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertIn("已选定并实施（5 个）", text)
        self.assertIn("B30 Raft 完整化（快照 + 成员变更）", text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
