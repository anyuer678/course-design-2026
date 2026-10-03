"""tests/test_showcase.py —— B7 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、增量构建回放的确定性（up to date 判定出现次数、跑完自清理）、
Makefile 解析（.PHONY 不算目标）、日志聚合计数与模板、改坏必红、页面标记与零外链。
回放每次 collect 都真跑一遍 mm.py（六步），所以本文件会多花几秒——那是故意的：
页面里的每个数字都来自这次真跑。
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
        with tempfile.TemporaryDirectory(prefix="b7-showcase-") as tmp:
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

    def test_selftest_method_count(self):
        # 15 是 test_mini_make.py 的方法数；本文件 9 个方法也会被静态数进来（B12 同款口径）
        self.assertEqual(self.payload["method_count"], 15 + 9)

    def test_replay_transcript_deterministic_markers(self):
        text = self.payload["transcript"]
        self.assertIn("=== 1) clean", text)
        self.assertIn("=== 4) 触碰", text)
        self.assertIn("hello from mini-make #3", text)
        self.assertEqual(text.count("已是最新（up to date）"), 2)
        self.assertEqual(text.count("完成："), 6)

    def test_replay_cleans_up_after_itself(self):
        self.assertFalse((ROOT / "demo" / "build").exists(),
                         "回放收尾的 clean 必须把 demo/build 清掉")

    def test_makefile_targets_parsed(self):
        targets = self.payload["targets"]
        self.assertEqual([t["target"] for t in targets],
                         ["all", "build/greet.exe", "run", "clean"])
        build = targets[1]
        self.assertEqual(build["deps"], ["src/greet.cpp"])
        self.assertTrue(any("g++" in c for c in build["commands"]))

    def test_logstat_counts_and_templates(self):
        self.assertEqual(self.payload["counts"], {"error": 1, "warning": 8, "note": 1})
        top = self.payload["top"]
        self.assertEqual(len(top), 5)
        self.assertIn("3 × warning: comparison", top[0])


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B7-mini-make"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
