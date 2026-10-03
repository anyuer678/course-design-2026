"""tests/test_showcase.py —— B13 展示页生成器自测（口径：showcase/SPEC.md）。

三件事：页面新鲜度（重算比对）、真数据抽查（程序清单/双后端输出/报错定位，
全部钉在"引擎现跑"的事实上）、改坏必红（页面对不上现算就算是手改）。
"""
from __future__ import annotations

import io
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
        with tempfile.TemporaryDirectory(prefix="b13-showcase-") as tmp:
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
        cls.by_name = {p["name"]: p for p in cls.payload["programs"]}

    def test_program_inventory(self):
        names = sorted(self.by_name)
        self.assertEqual(len(names), 14, "programs/ 里的样例数变了要同步本页口径")
        ok = [p for p in self.payload["programs"] if p["status"] == "ok"]
        self.assertEqual(len(ok), 10)
        self.assertEqual({p["name"] for p in self.payload["programs"] if p["status"] != "ok"},
                         {"error_syntax", "error_types", "error_runtime", "error_depth"})

    def test_dual_backend_outputs_are_pinned(self):
        expected = {
            "fib": ["0", "1", "1", "2", "3", "5", "8", "13"],
            "gcd": ["21"],
            "collatz": ["111", "9232"],
            "ackermann": ["9", "61"],
            "binomial": ["252", "1"],
            "hanoi": ["A->C", "A->B", "C->B", "A->C", "B->A", "B->C", "A->C", "7"],
        }
        for name, head in expected.items():
            run = self.by_name[name]["stages"]["run"]
            self.assertTrue(run["same"], f"{name} 两条后端输出应当一致")
            self.assertEqual(run["output"][:len(head)], head, name)

    def test_three_stage_products_exist_per_program(self):
        fib = self.by_name["fib"]
        self.assertIn("行", fib["stages"]["tokens"])          # 记号带行列
        self.assertIn("fun fib", fib["stages"]["ast"])        # AST 真的格式化出来了
        self.assertIn("CALL", fib["stages"]["bytecode"])      # 字节码含函数调用指令
        self.assertGreater(len(fib["stages"]["run"]["trace"]), 0)

    def test_errors_are_rendered_with_positions(self):
        syntax = self.by_name["error_syntax"]
        self.assertEqual(syntax["status"], "compile_error")
        self.assertIn("行", syntax["errors"][0])
        self.assertIn("列", syntax["errors"][0])
        types = self.by_name["error_types"]
        import re
        blocks = re.findall(r"(?m)^\d+\. ", types["errors"][0])
        self.assertEqual(len(blocks), 4, "语义错误要一次报全四条，不 fail-fast")
        depth = self.by_name["error_depth"]
        self.assertEqual(depth["status"], "runtime_error")
        self.assertIn("100", depth["errors"][0])              # 深度上限是真的在报错里

    def test_facts_are_recomputed_from_this_repo(self):
        facts = dict(self.payload["facts"])
        self.assertIn("14 个", facts["样例程序"])
        self.assertEqual(facts["双后端对拍"].split("（")[0], "10/10 输出一致")


class TestRenderedPage(unittest.TestCase):
    def test_page_carries_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B13-tinylang"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_page_has_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        import re
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
