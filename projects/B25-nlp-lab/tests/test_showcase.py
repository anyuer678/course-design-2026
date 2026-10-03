"""B25 展示页测试：新鲜度、必备锚点、自包含、数据抽查。"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT))

from nlp25.bayes import MultinomialNB                                # noqa: E402
from nlp25.corpus import make_corpus                                 # noqa: E402
from nlp25.metrics import accuracy                                   # noqa: E402
from nlp25.segment import fmm                                        # noqa: E402

PAGE = ROOT / "web" / "showcase.html"
GENERATOR = ROOT / "tools" / "showcase.py"


def run_gen(*args):
    return subprocess.run([sys.executable, str(GENERATOR), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(ROOT))


class TestShowcasePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_gen("--write")
        cls.page = PAGE.read_text(encoding="utf-8") if PAGE.is_file() else ""

    def test_generator_write_ok(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout)

    def test_freshness_check_passes(self):
        check = run_gen("--check")
        self.assertEqual(check.returncode, 0, check.stdout)

    def test_tamper_is_detected(self):
        original = PAGE.read_text(encoding="utf-8")
        try:
            PAGE.write_text(original.replace("研究生命起源", "研究生起源"),
                            encoding="utf-8")
            check = run_gen("--check")
            self.assertNotEqual(check.returncode, 0, "改坏页面后 --check 必须红")
        finally:
            PAGE.write_text(original, encoding="utf-8")

    def test_required_structure(self):
        self.assertTrue(self.page.startswith("<!DOCTYPE html>"))
        self.assertIn('lang="zh-CN"', self.page)
        self.assertIn('data-showcase="B25-nlp-lab"', self.page)
        for anchor in ("facts", "demo", "repro"):
            self.assertIn(f'id="{anchor}"', self.page)
        self.assertIn("tools/showcase.py --write", self.page)

    def test_self_contained(self):
        for pattern in ("http://", "https://"):
            for hit in re.finditer(re.escape(pattern), self.page):
                ctx = self.page[hit.start():hit.start() + 40]
                self.assertIn("www.w3.org", ctx, msg=f"出现外部引用: {ctx}")

    def test_no_dangerous_dom(self):
        for pattern in ("innerHTML", "outerHTML", "document.write",
                        "insertAdjacentHTML"):
            self.assertNotIn(pattern, self.page)

    def test_data_spot_check_against_fresh_compute(self):
        texts, labels = make_corpus(100, seed=42)
        tr_x, tr_y = texts[:70] + texts[100:170], labels[:70] + labels[100:170]
        te_x, te_y = texts[70:100] + texts[170:], labels[70:100] + labels[170:]
        acc = accuracy(te_y, MultinomialNB(alpha=1.0, tokenizer=fmm)
                       .fit(tr_x, tr_y).predict(te_x))
        self.assertIn(f"{acc:.2f}", self.page)

    def test_manifest_entry(self):
        manifest = json.loads((REPO / "showcase" / "manifest.json")
                              .read_text(encoding="utf-8"))
        entry = next(e for e in manifest["projects"] if e["id"] == "B25-nlp-lab")
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["page"], "projects/B25-nlp-lab/web/showcase.html")
        self.assertTrue(PAGE.is_file())

    def test_node_check_inline_scripts(self):
        scripts = re.findall(r"<script>(.*?)</script>", self.page, re.S)
        self.assertGreaterEqual(len(scripts), 2)
        tmp = PAGE.parent / "_showcase_check.js"
        try:
            for i, script in enumerate(scripts):
                tmp.write_text(script, encoding="utf-8")
                proc = subprocess.run(["node", "--check", str(tmp)],
                                      capture_output=True)
                self.assertEqual(proc.returncode, 0,
                                 msg=f"第 {i + 1} 段内联脚本语法不过")
        finally:
            tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
