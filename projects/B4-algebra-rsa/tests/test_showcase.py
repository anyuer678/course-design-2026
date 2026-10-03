"""tests/test_showcase.py —— B4 展示页生成器自测（口径：showcase/SPEC.md）。

钉住：页面新鲜度、真数据抽查（RSA 逐字节回读与确定性缺陷、egcd 两版互拍、
平方-乘成本、CRT 逐项验证、群判定器好表/坏表结论、容斥两法一致、函数三档性质）、
改坏必红、页面标记与零外链。
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
        with tempfile.TemporaryDirectory(prefix="b4-showcase-") as tmp:
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

    def test_rsa_roundtrip_and_determinism_flaw(self):
        rsa = self.payload["rsa"]
        self.assertEqual(rsa["back"], rsa["message"])
        self.assertTrue(rsa["roundtrip"])
        self.assertEqual(rsa["restored"], rsa["text"], "文本必须逐字节回读")
        self.assertTrue(rsa["deterministic"], "教科书 RSA 的确定性缺陷必须被页面如实展示")

    def test_number_theory_facts(self):
        nt = self.payload["nt"]
        self.assertEqual(nt["egcd"]["g"], 21)
        self.assertTrue(nt["egcd"]["same"], "egcd 递推版与迭代版必须互拍")
        self.assertTrue(nt["egcd"]["bezout"])
        self.assertLess(nt["modpow"]["fast"], nt["modpow"]["naive"])
        self.assertEqual(nt["modpow"]["naive"], 65536)
        self.assertEqual(nt["crt"]["value"], 23)
        self.assertTrue(all(v % m == r for (v, m), r in zip(
            [(nt["crt"]["value"], m) for m in nt["crt"]["moduli"]], nt["crt"]["residues"])))
        self.assertEqual(nt["inverse"], 2753)

    def test_groups_verdicts_and_counterexamples(self):
        groups = {g["name"]: g for g in self.payload["groups"]}
        self.assertEqual(len(groups), 6)
        self.assertTrue(groups["Z6 加法表"]["ok"])
        self.assertTrue(groups["Z6 加法表"]["abelian"])
        self.assertTrue(groups["U(8) 乘法单位表"]["ok"])
        bad1 = groups["坏表①：不封闭"]
        self.assertFalse(bad1["closure_ok"])
        self.assertIn("不封闭", " ".join(bad1["explain"]))
        bad2 = groups["坏表②：没有单位元"]
        self.assertTrue(bad2["assoc_ok"])
        self.assertIsNone(bad2["identity"])
        bad3 = groups["坏表③：缺逆元"]
        self.assertFalse(bad3["inverses_ok"])
        bad4 = groups["坏表④：不结合"]
        self.assertFalse(bad4["assoc_ok"])
        self.assertIn("不结合", " ".join(bad4["explain"]))

    def test_sets_and_functions(self):
        sets = self.payload["sets"]
        self.assertEqual(sets["ie"], sets["brute"], "容斥公式必须等于暴力并集")
        self.assertEqual(sets["ie"], 7)
        self.assertEqual(sets["power"], 16)
        funcs = {f["name"]: f for f in sets["functions"]}
        self.assertTrue(funcs["双射 {1->a, 2->b, 3->c}"]["bijective"])
        self.assertFalse(funcs["非单射 {1->a, 2->a, 3->b}"]["injective"])
        self.assertFalse(funcs["非满射 {1->a, 2->b, 3->b}"]["surjective"])
        self.assertFalse(funcs["不是函数：1 有两像"]["is_function"])
        self.assertTrue(funcs["不是函数：1 有两像"]["reasons"])
        self.assertFalse(funcs["不是函数：取值出陪域"]["is_function"])


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B4-algebra-rsa"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
