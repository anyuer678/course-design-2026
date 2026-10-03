"""tests/test_showcase.py —— B37 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、三模型/阈值表的逐格数值、耗时列规范化的真生效、三张 SVG 是
build/ 里的同一份产物、改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b37-showcase-") as tmp:
            fake = Path(tmp) / "showcase.html"
            fake.write_text("手改过的页面", encoding="utf-8")
            sc.OUT = fake
            try:
                self.assertEqual(quiet_main(["showcase", "--check"]), 1)
            finally:
                sc.OUT = original


class TestNormalization(unittest.TestCase):
    def test_ms_column_is_masked(self):
        raw = sc._run([sys.executable, "demo.py"])
        self.assertRegex(raw, r"\d+(\.\d+)? ms")
        masked = sc._norm(raw)
        self.assertIsNone(re.search(r"\d+(\.\d+)? ms", masked), "耗时列未规范化")
        self.assertIn("<当场> ms", masked)


class TestPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = sc.collect()

    def test_model_and_sweep_tables(self):
        models = {row[0]: row for row in self.payload["model_rows"]}
        self.assertEqual(len(models), 3)
        tree = models["B23 决策树"]
        self.assertEqual(tree[1:], ["0.14", "20", "0.950", "0.792", "0.864", "0.899"])
        lr = models["手写逻辑回归(L2)"]
        self.assertEqual(lr[5:], ["0.857", "0.926"])
        sweep = {row[0]: row for row in self.payload["sweep_rows"]}
        self.assertEqual(sweep["告警预算≤24"][1:], ["0.22", "24", "0.833", "0.833"])

    def test_facts_pin_the_dissection(self):
        facts = dict(self.payload["facts"])
        self.assertIn("20/20", facts["误报解剖"])
        self.assertIn("6/6", facts["提前量"])
        self.assertIn("0.926", facts["三模型（best-F1）"])

    def test_svgs_are_the_real_artifacts(self):
        svgs = self.payload["svgs"]
        self.assertEqual([s["name"] for s in svgs],
                         ["alert_budget.svg", "dev08_temp.svg", "dev08_vib.svg"])
        for s in svgs:
            self.assertEqual(s["bytes"], (sc.BUILD / s["name"]).stat().st_size)
            self.assertTrue(s["text"].startswith("<svg"))


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B37-industry-ai"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_inline_svgs_and_pinned_values(self):
        text = sc.OUT.read_text(encoding="utf-8")
        self.assertEqual(text.count("<svg xmlns="), 3)
        for token in ("0.864", "0.926", "20/20"):
            self.assertIn(token, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
