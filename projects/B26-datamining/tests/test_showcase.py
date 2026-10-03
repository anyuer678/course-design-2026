"""B26 展示页测试：新鲜度、必备锚点、自包含、数据抽查。"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT))

from mining.apriori import apriori                                   # noqa: E402
from mining.clean import clean, make_dirty_ledger                    # noqa: E402

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
            PAGE.write_text(original.replace("行数守恒", "行数不守恒"),
                            encoding="utf-8")
            check = run_gen("--check")
            self.assertNotEqual(check.returncode, 0, "改坏页面后 --check 必须红")
        finally:
            PAGE.write_text(original, encoding="utf-8")

    def test_required_structure(self):
        self.assertTrue(self.page.startswith("<!DOCTYPE html>"))
        self.assertIn('lang="zh-CN"', self.page)
        self.assertIn('data-showcase="B26-datamining"', self.page)
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
        rows, _ = make_dirty_ledger(40, seed=7)
        clean_rows, report = clean(rows)
        # 页面上的清洗结果与现算一致（两个确定性数字）
        self.assertIn(str(report["clean"]), self.page)
        self.assertIn(str(report["duplicates_removed"]), self.page)

    def test_manifest_entry(self):
        manifest = json.loads((REPO / "showcase" / "manifest.json")
                              .read_text(encoding="utf-8"))
        entry = next(e for e in manifest["projects"]
                     if e["id"] == "B26-datamining")
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["page"], "projects/B26-datamining/web/showcase.html")
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
