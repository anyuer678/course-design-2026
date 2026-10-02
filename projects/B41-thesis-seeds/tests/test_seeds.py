"""tests/test_seeds.py —— B41 自测：事实核验器（正/负例）+ 比较表 + 基准

纪律：核验器的每条规则配一条"改坏必须红"；候选 id 集合与"每条都有文件+探针"
是刻意钉住的（改动数据必须来这里改——防悄悄变化）。

**候选清零态（2026-10-02 收官）**：5 个候选全部选定实施后 seeds=[]；核验器允许
"候选空、chosen 非空"（双空才红）。负面对照的夹具因此改为**注入式**：先往空表里
注入一条必然通过的最小候选，再对它改坏——规则不因数据清空而失去牙齿。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]        # B41-thesis-seeds/
sys.path.insert(0, str(ROOT / "tools"))

import bench_io                                           # noqa: E402
import check_seeds                                        # noqa: E402
import report_seeds                                       # noqa: E402

REPO_ROOT = ROOT.parents[1]
SEEDS_PATH = ROOT / "data" / "seeds.json"


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b41-{name}-"))
    if str(base.resolve()).lower().startswith(str(REPO_ROOT.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


def synthetic_seed() -> dict:
    """注入夹具（工厂在 tools/check_seeds.py——测试与演示共用，防两处漂移）。"""
    return check_seeds.synthetic_seed()


class TestSeedsChecker(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp("chk")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.seeds = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))

    def problems(self, mutate) -> list[str]:
        data = json.loads(json.dumps(self.seeds))         # 深拷贝
        if not data["seeds"]:
            data["seeds"].append(synthetic_seed())        # 候选清零态：先注入再改坏
        mutate(data["seeds"])
        path = self.tmp / "seeds.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return check_seeds.check_seeds_data(path, REPO_ROOT)

    def test_real_data_passes(self):
        self.assertEqual(check_seeds.check_seeds_data(SEEDS_PATH, REPO_ROOT), [])

    def test_empty_candidates_allowed_but_double_empty_turns_red(self):
        data = json.loads(json.dumps(self.seeds))
        self.assertEqual(data["seeds"], [])              # 真实数据就是收官态
        self.assertTrue(data["chosen"])
        data["chosen"] = []                              # 双空则红
        path = self.tmp / "seeds.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        problems = check_seeds.check_seeds_data(path, REPO_ROOT)
        self.assertTrue(any("同时为空" in p for p in problems), problems)

    def test_wrong_line_count_turns_red(self):
        problems = self.problems(lambda s: s[0]["files"].__setitem__(
            0, {"path": s[0]["files"][0]["path"], "lines": s[0]["files"][0]["lines"] + 1}))
        self.assertTrue(any("行数对不上" in p for p in problems), problems)

    def test_probe_expected_mismatch_turns_red(self):
        """代码计数探针的"计数不符"规则：候选表里已没有现役 code-count 探针，
        现场注入一条指向真文件的探针来钉规则（glob 能匹配、计数故意写错）。"""
        def mutate(seeds):
            seeds[0]["probes"].append({
                "name": "注入的计数探针", "kind": "code-count",
                "glob": "projects/B23-ml-from-scratch/ml/*.py",
                "pattern": "def ", "expected": 0})
        problems = self.problems(mutate)
        self.assertTrue(any("计数不符" in p for p in problems), problems)

    def test_glob_without_match_turns_red(self):
        def mutate(seeds):
            seeds[0]["probes"].append({
                "name": "注入的假 glob 探针", "kind": "code-count",
                "glob": "projects/B10-minidb/nope/*.py",
                "pattern": "def ", "expected": 0})
        problems = self.problems(mutate)
        self.assertTrue(any("没匹配到任何文件" in p for p in problems), problems)

    def test_missing_anchor_turns_red(self):
        problems = self.problems(lambda s: s[0]["evidence"].__setitem__(
            "anchor", "这段字符串绝不可能出现xq9"))
        self.assertTrue(any("锚点" in p for p in problems), problems)

    def test_empty_files_turns_red(self):
        problems = self.problems(lambda s: s[0].__setitem__("files", []))
        self.assertTrue(any("files 为空" in p for p in problems), problems)

    def test_empty_probes_turns_red(self):
        problems = self.problems(lambda s: s[0].__setitem__("probes", []))
        self.assertTrue(any("probes 为空" in p for p in problems), problems)

    def test_duplicate_id_turns_red(self):
        def mutate(seeds):
            seeds.append(json.loads(json.dumps(seeds[0])))   # 复制一条 → id 重复
        problems = self.problems(mutate)
        self.assertTrue(any("id 重复" in p for p in problems), problems)

    def test_chosen_bad_anchor_turns_red(self):
        def mutate(data):
            data["chosen"][0]["evidence"]["anchor"] = "这段字符串绝不可能出现xq9"
        data = json.loads(json.dumps(self.seeds))
        mutate(data)
        path = self.tmp / "seeds.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        problems = check_seeds.check_seeds_data(path, REPO_ROOT)
        self.assertTrue(any("chosen" in p and "锚点" in p for p in problems), problems)

    def test_import_expectation_mismatch_turns_red(self):
        def mutate(seeds):
            for seed in seeds:
                for probe in seed["probes"]:
                    if probe.get("kind") == "import-check" and probe["module"] == "numpy":
                        probe["expected"] = False
        problems = self.problems(mutate)
        self.assertTrue(any("numpy" in p and "import" in p for p in problems), problems)

    def test_empty_question_turns_red(self):
        problems = self.problems(lambda s: s[0].__setitem__("question", ""))
        self.assertTrue(any("question 为空" in p for p in problems), problems)


class TestReport(unittest.TestCase):
    def test_report_deterministic(self):
        seeds = report_seeds._load()
        self.assertEqual(report_seeds.render_report(seeds), report_seeds.render_report(seeds))

    def test_report_lists_remaining_candidates_and_chosen(self):
        rendered = report_seeds.render_report(report_seeds._load())
        self.assertNotIn("| 1 |", rendered)               # 候选表已清零，没有数据行
        self.assertIn("候选表已清零", rendered)
        self.assertIn("B13 加函数调用帧", rendered)        # 来自"已选定"段
        self.assertIn("B23 + NumPy", rendered)
        self.assertIn("已选定并实施（5 个）", rendered)
        self.assertIn("B38 主从复制", rendered)
        self.assertIn("B10 加 fsync", rendered)
        self.assertIn("B30 Raft 完整化", rendered)

    def test_report_footer_keeps_choice_with_user(self):
        text = report_seeds.render_report(report_seeds._load())
        self.assertIn("选定由你", text)
        self.assertIn("不等于开题", text)


class TestDesignPins(unittest.TestCase):
    def test_seed_id_set_pinned(self):
        data = report_seeds._load()
        self.assertEqual({s["id"] for s in data["seeds"]}, set())    # 收官：候选清零
        self.assertEqual([c["id"] for c in data["chosen"]],
                         ["b38-replication", "b10-fsync-pages", "b13-call-frames",
                          "b30-raft-snapshot", "b23-numpy-sklearn"])

    def test_chosen_records_pinned(self):
        data = report_seeds._load()
        for chosen in data["chosen"]:
            self.assertEqual(chosen["date"], "2026-10-02")
            self.assertTrue(chosen["note"])
            path = REPO_ROOT / chosen["evidence"]["path"]
            self.assertTrue(path.is_file(), msg=chosen["id"])
            self.assertIn(chosen["evidence"]["anchor"], path.read_text(encoding="utf-8"),
                          msg=chosen["id"])

    def test_every_seed_has_facts(self):
        seeds = report_seeds._load()["seeds"]
        for seed in seeds:
            self.assertGreaterEqual(len(seed["files"]), 1, msg=seed["id"])
            self.assertGreaterEqual(len(seed["probes"]), 1, msg=seed["id"])

    def test_bench_positive(self):
        tmp = make_tmp("bench")
        self.addCleanup(shutil.rmtree, tmp, True)
        result = bench_io.write_bench(tmp, reps=10)
        self.assertGreater(result["plain_ms"], 0.0)
        self.assertGreater(result["fsync_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
