"""g2/tests/test_g2.py —— G2 练习册的自测：一条正例 + 一组"改坏必须红"。

负面对照都在临时沙箱里做（复制 cards.json 与它引用到的 README 副本），
不碰仓库真文件。
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "g2"))

import render as R  # noqa: E402


class TestG2(unittest.TestCase):
    def scaffold(self, cards=None) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="g2-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "g2").mkdir(parents=True)
        cards = copy.deepcopy(cards) if cards is not None else R.load_cards(ROOT)
        (tmp / "g2" / "cards.json").write_text(
            json.dumps(cards, ensure_ascii=False), encoding="utf-8")
        files = {s["file"] for c in cards for s in c["sources"]}
        for rel in files:
            src = ROOT / rel
            if not src.is_file():
                continue          # 缺失来源文件那类负面对照：故意不拷，交给核对器报红
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        return tmp

    # ------------------------------------------------------------ 正例

    def test_real_tree_passes(self):
        self.assertEqual(R.check(ROOT), [])

    def test_ids_and_shapes(self):
        cards = R.load_cards(ROOT)
        self.assertEqual([c["id"] for c in cards], R.EXPECTED_IDS)
        for c in cards:
            self.assertGreaterEqual(len(c["oral"]), 3, c["id"])
            self.assertGreaterEqual(len(c["sources"]), 3, c["id"])

    # ------------------------------------------------------------ 负面对照

    def test_anchor_drift_turns_red(self):
        cards = R.load_cards(ROOT)
        cards[0]["sources"][0]["anchor"] = "绝不可能出现的锚点字符串zzq9"
        tmp = self.scaffold(cards)
        problems = R.validate_cards(tmp, cards)
        self.assertTrue(any("锚点不在" in p for p in problems), problems)

    def test_short_anchor_turns_red(self):
        cards = R.load_cards(ROOT)
        cards[0]["sources"][0]["anchor"] = "太短"
        tmp = self.scaffold(cards)
        problems = R.validate_cards(tmp, cards)
        self.assertTrue(any("锚点过短" in p for p in problems), problems)

    def test_missing_source_file_turns_red(self):
        cards = R.load_cards(ROOT)
        cards[0]["sources"][0]["file"] = "projects/NOPE/README.md"
        tmp = self.scaffold(cards)
        problems = R.validate_cards(tmp, cards)
        self.assertTrue(any("来源文件不存在" in p for p in problems), problems)

    def test_duplicate_or_missing_id_turns_red(self):
        cards = R.load_cards(ROOT)
        cards[-1]["id"] = "B1"
        tmp = self.scaffold(cards)
        problems = R.validate_cards(tmp, cards)
        self.assertTrue(any("编号必须恰好" in p for p in problems), problems)
        self.assertTrue(any("编号重复" in p for p in problems), problems)

    def test_stale_or_extra_render_turns_red(self):
        tmp = self.scaffold()
        R.write(tmp)
        self.assertEqual(R.freshness_problems(tmp, R.load_cards(tmp)), [])
        p = tmp / "g2" / "B1.md"
        p.write_text(p.read_text(encoding="utf-8") + "x", encoding="utf-8")
        problems = R.freshness_problems(tmp, R.load_cards(tmp))
        self.assertTrue(any("不一致" in x for x in problems), problems)
        (tmp / "g2" / "B2.md").unlink()
        (tmp / "g2" / "B99.md").write_text("多余", encoding="utf-8")
        problems = R.freshness_problems(tmp, R.load_cards(tmp))
        self.assertTrue(any("不存在" in x for x in problems), problems)
        self.assertTrue(any("多余" in x for x in problems), problems)

    def test_empty_oral_turns_red(self):
        cards = R.load_cards(ROOT)
        cards[0]["oral"] = cards[0]["oral"][:2]
        tmp = self.scaffold(cards)
        problems = R.validate_cards(tmp, cards)
        self.assertTrue(any("口述提纲至少 3 条" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
