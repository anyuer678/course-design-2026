"""tests/test_showcase.py —— dorm-repair 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、13 段 walkthrough 的现算事实（验收标准 40 / 判定表 1680 格 /
8 组件 22 边 / 门禁 11 层 / 走查 20 步分解 / 台账 27 键）、改坏必红、标记与零外链。

注意依赖方向：本测试只 import 标准库与 tools/showcase（docs/08 允许 tests→tools），
不 import spec/arch/prototype——生成器同样只跑 demo.py 子进程，不碰依赖图。
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
        with tempfile.TemporaryDirectory(prefix="dorm-showcase-") as tmp:
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

    def test_tests_fact(self):
        facts = dict(self.payload["facts"])
        self.assertIn("216 核心 + 9 展示页自测", facts["测试"])

    def test_requirement_and_verdict_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("验收标准 40 条全部可执行", facts["需求 → 测试"])
        self.assertIn("待决问题 12 条", facts["需求 → 测试"])
        self.assertIn("1680 格", facts["判定表（B18 跨语言）"])
        self.assertIn("8 个组件、真实 import 边 22 条", facts["架构（B17 实测依赖图）"])

    def test_gate_and_walkthrough_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("11 层（blocking 9、advisory 2）", facts["质量门禁（B21）"])
        self.assertIn("纯自动 11 + 仍需眼看 7 + 只能人工 2", facts["人工走查（B16/B21）"])
        self.assertIn("变异登记 17 条 + 1 条阴性对照", facts["验证工程（B20）"])
        self.assertIn("AQ-10 循环 6 步", facts["验证工程（B20）"])

    def test_ledger_facts(self):
        facts = dict(self.payload["facts"])
        self.assertIn("27 个键全部现算", facts["台账（B22）"])
        self.assertIn("rounds_done 21", facts["台账（B22）"])
        self.assertIn("pitfalls 53", facts["台账（B22）"])


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="dorm-repair"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_walkthrough_sections_present(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for token in ("追踪旅程", "状态机走一遍", "质量门禁", "项目管理"):
            self.assertIn(token, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
