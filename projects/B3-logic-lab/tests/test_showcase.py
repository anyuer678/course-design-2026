"""tests/test_showcase.py —— B3 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、真数据抽查（真值表行数=2^变量数、分类、闭包两法一致、
等价类划分）、改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b3-showcase-") as tmp:
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
        cls.formulas = {f["text"]: f for f in cls.payload["formulas"]}

    def test_inventory(self):
        self.assertEqual(len(self.payload["formulas"]), 12)
        self.assertEqual(len(self.payload["pairs"]), 4)
        self.assertEqual(len(self.payload["relations"]), 4)
        self.assertTrue(all(p["ok"] for p in self.payload["pairs"]),
                        "四对等价公式必须逐格相等")

    def test_truth_table_row_counts(self):
        for f in self.payload["formulas"]:
            self.assertEqual(f["rows"], 2 ** f["vars"], f["text"])

    def test_classification_pinned(self):
        self.assertEqual(self.formulas["p | ~p"]["class"], "重言式")
        self.assertEqual(self.formulas["p & ~p"]["class"], "矛盾式")
        self.assertEqual(self.formulas["p -> q"]["class"], "可满足（非重言）")

    def test_minterms_match_classification(self):
        taut = self.formulas["p | ~p"]
        self.assertEqual(len(taut["minterms"]), 2 ** taut["vars"], "重言式全行成真")
        contra = self.formulas["p & ~p"]
        self.assertEqual(contra["minterms"], [], "矛盾式没有成真行")

    def test_relations_closures_agree_and_classes_valid(self):
        for rel in self.payload["relations"]:
            self.assertTrue(rel["closures_same"], rel["name"])
        chain = next(r for r in self.payload["relations"] if r["name"] == "链条 0→1→2")
        self.assertIn("(0,2)", chain["warshall"], "传递闭包必须补出 (0,2)")
        mod3 = next(r for r in self.payload["relations"] if "模 3" in r["name"])
        self.assertEqual(mod3["verdict"], "等价关系")
        self.assertEqual(mod3["classes"], "{0,3}、{1,4}、{2,5}")
        self.assertTrue(mod3["partition_ok"])


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B3-logic-lab"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
