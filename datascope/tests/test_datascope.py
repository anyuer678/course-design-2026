"""DataScope 轮四（一）自测：解析/画像/清洗步骤账本/配方执行/CLI。

账本纪律（继承 B26）：构造数据时**缺陷数量已知**，清洗报告的每个计数
必须与已知数量精确对上——报告不是文案，是账本。
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import datascope
from datascope import RecipeError, apply_recipe, parse_csv, profile

DIRTY = """name,qty,amount,city
甲,2,19.9,北京
乙 ,1,5.0,上海
甲,2,19.9,北京
丙,3,,深圳
,1,2.0,广州
丁,abc,7.0,杭州
"""


def make_dirty(tmp: Path) -> Path:
    path = tmp / "dirty.csv"
    path.write_text(DIRTY, encoding="utf-8")
    return path


class TestParseAndProfile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.table = parse_csv(make_dirty(Path(self._tmp.name)))

    def test_parse_rows_and_columns(self):
        """6 数据行（BOM 兼容、空值保留、尾部空行跳过）、4 列。"""
        self.assertEqual(self.table.columns, ["name", "qty", "amount", "city"])
        self.assertEqual(len(self.table), 6)
        self.assertEqual(self.table.rows[2]["name"], "甲")     # 重复行保留（清洗才删）

    def test_profile_infers_types(self):
        p = profile(self.table)
        self.assertEqual(p["qty"]["type"], "text")     # "abc" 混进来 → 整列退化为 text
        self.assertEqual(p["amount"]["type"], "float")
        self.assertEqual(p["city"]["type"], "text")
        self.assertEqual(p["name"]["missing"], 1)
        self.assertEqual(p["amount"]["min"], 2.0)          # 19.9/5.0/2.0/7.0 里的最小值
        self.assertEqual(p["amount"]["missing"], 1)        # 丙行金额缺失

    def test_empty_file_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.csv"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                parse_csv(path)

    def test_unknown_column_keyerror(self):
        with self.assertRaises(KeyError):
            self.table.column("nope")


class TestCleaning(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.table = parse_csv(make_dirty(Path(self._tmp.name)))

    def test_drop_duplicates_ledger(self):
        cleaned, report = apply_recipe(
            self.table, [{"op": "drop_duplicates"}])
        self.assertEqual(report["steps"][0]["counts"]["duplicates_removed"], 1)
        self.assertEqual(len(cleaned), 5)

    def test_drop_empty_rows_specific_column(self):
        cleaned, report = apply_recipe(
            self.table, [{"op": "drop_empty_rows", "column": "name"}])
        self.assertEqual(report["steps"][0]["counts"]["empty_rows_removed"], 1)
        self.assertEqual(len(cleaned), 5)

    def test_fill_missing_mean_ledger(self):
        cleaned, report = apply_recipe(
            self.table, [{"op": "fill_missing", "column": "amount",
                          "strategy": "mean"}])
        counts = report["steps"][0]["counts"]
        self.assertEqual(counts["cells_filled"], 1)        # 只有丙行金额缺失
        self.assertGreater(float(counts["fill_value"]), 0)

    def test_fill_missing_fixed_value(self):
        cleaned, _ = apply_recipe(
            self.table, [{"op": "fill_missing", "column": "name",
                          "strategy": "value", "value": "匿名"}])
        self.assertEqual(cleaned.rows[4]["name"], "匿名")

    def test_trim(self):
        cleaned, report = apply_recipe(self.table, [{"op": "trim"}])
        self.assertEqual(report["steps"][0]["counts"]["rows_trimmed"], 1)
        self.assertEqual(cleaned.rows[1]["name"], "乙")

    def test_to_number_fail_on_bad_value(self):
        with self.assertRaises(RecipeError) as ctx:
            apply_recipe(self.table, [{"op": "to_number", "column": "qty"}])
        self.assertIn("abc", "；".join(ctx.exception.problems))

    def test_to_number_blank_then_drop(self):
        """on_error=blank 把换不动的挖空，再用 drop_empty_rows 收走——账对得上。"""
        cleaned, report = apply_recipe(self.table, [
            {"op": "to_number", "column": "qty", "on_error": "blank"},
            {"op": "drop_empty_rows", "column": "qty"},
        ])
        self.assertEqual(report["steps"][0]["counts"]["cells_converted"], 5)
        self.assertEqual(report["steps"][1]["counts"]["empty_rows_removed"], 1)
        self.assertEqual(len(cleaned), 5)
        self.assertEqual(cleaned.column("qty"), ["2", "1", "2", "3", "1"])

    def test_drop_column(self):
        cleaned, report = apply_recipe(
            self.table, [{"op": "drop_column", "column": "city"}])
        self.assertEqual(report["steps"][0]["counts"]["column_dropped"], "city")
        self.assertEqual(cleaned.columns, ["name", "qty", "amount"])

    def test_recipe_problems_all_at_once(self):
        with self.assertRaises(RecipeError) as ctx:
            apply_recipe(self.table, [
                {"op": "nope"}, {"op": "fill_missing"},
                {"op": "drop_column", "column": "ghost"},
            ])
        text = "；".join(ctx.exception.problems)
        for needle in ("nope", "fill_missing", "ghost"):
            self.assertIn(needle, text)

    def test_empty_recipe_rejected(self):
        with self.assertRaises(RecipeError):
            apply_recipe(self.table, [])

    def test_profile_after_reflects_cleaning(self):
        cleaned, report = apply_recipe(self.table, [
            {"op": "drop_duplicates"},
            {"op": "to_number", "column": "qty", "on_error": "blank"},
            {"op": "drop_empty_rows", "column": "qty"},
        ])
        self.assertEqual(report["profile_after"]["qty"]["type"], "int")
        self.assertEqual(report["rows_after"], len(cleaned))


class TestCli(unittest.TestCase):
    def test_clean_end_to_end_via_cli(self):
        with tempfile.TemporaryDirectory() as td:
            csv_path = make_dirty(Path(td))
            recipe = Path(td) / "recipe.json"
            recipe.write_text(json.dumps([
                {"op": "drop_duplicates"},
                {"op": "fill_missing", "column": "amount", "strategy": "mean"},
            ]), encoding="utf-8")
            out = Path(td) / "clean.csv"
            report = Path(td) / "report.json"
            run_py = Path(datascope.__file__).parents[1] / "datascope" / "run.py"
            proc = subprocess.run(
                [sys.executable, str(run_py), "clean", str(csv_path),
                 "--recipe", str(recipe), "--out", str(out),
                 "--report", str(report)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            loaded = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(loaded["rows_before"], 6)
            self.assertEqual(loaded["rows_after"], 5)
            self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 6)

    def test_cli_profile(self):
        with tempfile.TemporaryDirectory() as td:
            run_py = Path(datascope.__file__).parents[1] / "datascope" / "run.py"
            proc = subprocess.run(
                [sys.executable, str(run_py), "profile",
                 str(make_dirty(Path(td)))],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["amount"]["type"], "float")


if __name__ == "__main__":
    unittest.main(verbosity=2)
