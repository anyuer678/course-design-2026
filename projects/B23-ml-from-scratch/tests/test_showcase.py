"""B23 展示页测试：新鲜度、必备锚点、自包含、负面对照。

页面是生成物（web/showcase.html），这些测试钉住三件事：
    1. 生成器 --check 通过（页面与现算一致，未手改未过期）；
    2. 页面结构符合 showcase/SPEC.md（锚点/标记/零外链/无危险 DOM）；
    3. 数据抽查：页面里的关键数字与现算一致。
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT))

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
            PAGE.write_text(original.replace("Iris 150", "Iris 999"),
                            encoding="utf-8")
            check = run_gen("--check")
            self.assertNotEqual(check.returncode, 0,
                                "改坏页面后 --check 必须红")
        finally:
            PAGE.write_text(original, encoding="utf-8")

    def test_required_structure(self):
        self.assertTrue(self.page.startswith("<!DOCTYPE html>"))
        self.assertIn('lang="zh-CN"', self.page)
        self.assertIn('data-showcase="B23-ml-from-scratch"', self.page)
        for anchor in ("facts", "demo", "repro"):
            self.assertIn(f'id="{anchor}"', self.page)
        self.assertIn("tools/showcase.py --write", self.page)

    def test_self_contained(self):
        for pattern in ("http://", "https://"):
            for hit in re.finditer(re.escape(pattern), self.page):
                ctx = self.page[hit.start():hit.start() + 40]
                self.assertIn("www.w3.org", ctx,
                              msg=f"出现外部引用: {ctx}")

    def test_no_dangerous_dom(self):
        for pattern in ("innerHTML", "outerHTML", "document.write",
                        "insertAdjacentHTML"):
            self.assertNotIn(pattern, self.page)

    def test_data_spot_check_against_fresh_compute(self):
        """页面上的 KNN 精度与现算一致（数据是真算的，不是装饰）。"""
        sys.path.insert(0, str(REPO / "projects" / "B23-ml-from-scratch"))
        from ml import data as mldata
        from ml.knn import KNN
        from ml.linear import accuracy
        X, y = mldata.load_iris()
        tr, te = mldata.train_test_split(len(X), 0.2, seed=42)
        Xtr, Xte = mldata.standardize([X[i] for i in tr], [X[i] for i in te])
        ytr, yte = [y[i] for i in tr], [y[i] for i in te]
        acc = accuracy(yte, KNN(k=3).fit(Xtr, ytr).predict(Xte))
        self.assertIn(f"{acc:.2f}", self.page)

    def test_manifest_entry(self):
        manifest = json.loads((REPO / "showcase" / "manifest.json")
                              .read_text(encoding="utf-8"))
        entry = next(e for e in manifest["projects"]
                     if e["id"] == "B23-ml-from-scratch")
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["page"], "projects/B23-ml-from-scratch/web/showcase.html")
        self.assertTrue(PAGE.is_file())

    def test_node_check_inline_scripts(self):
        node = None
        for cand in ("node",):
            try:
                probe = subprocess.run([cand, "--version"], capture_output=True)
                node = cand if probe.returncode == 0 else None
            except FileNotFoundError:
                pass
        if node is None:
            self.skipTest("本机没有 node")
        scripts = re.findall(r"<script>(.*?)</script>", self.page, re.S)
        self.assertGreaterEqual(len(scripts), 2)
        tmp = PAGE.parent / "_showcase_check.js"
        try:
            for i, script in enumerate(scripts):
                tmp.write_text(script, encoding="utf-8")
                proc = subprocess.run([node, "--check", str(tmp)],
                                      capture_output=True)
                self.assertEqual(proc.returncode, 0,
                                 msg=f"第 {i + 1} 段内联脚本语法不过")
        finally:
            tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
