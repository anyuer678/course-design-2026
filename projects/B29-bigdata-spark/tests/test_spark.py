"""tests/test_spark.py —— B29 自测：Spark 每一路结果都要与纯 Python 参照逐行相等。

纪律（和本仓库其它项目一致）：
  1. 参照是"最笨但最可信"的纯 Python（Counter + sorted）——不是第二种 Spark 写法；
  2. 账本纪律：缺陷按已知数量注入，清洗计数逐类对账（同 B26）；
  3. Spark 会话只起一次（setUpClass 复用）——启动 ~20s，每个用例各起一次是浪费；
     数据目录在系统临时目录并断言不在仓库内（事故后纪律）。
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sparklab import clean, genlog, jobs, reference, session, skew   # noqa: E402


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b29-{name}-"))
    if str(base.resolve()).lower().startswith(str(session.REPO.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


class TestCleanPure(unittest.TestCase):
    """不需要 Spark 的部分：账本对账、优先级、边界。"""

    def test_quarantine_matches_ledger(self):
        bundle = genlog.make_log(n_lines=2000, seed=7)
        result = clean.clean_lines(bundle.lines)
        self.assertEqual(result.quarantined, bundle.ledger)
        self.assertEqual(len(result.clean), bundle.clean_true)

    def test_classify_priority_first_rule_wins(self):
        # 多缺陷行只归第一类：3 个字段（同时时间戳也坏）→ missing_field
        self.assertEqual(clean.classify_line("not-a-date|dev|FATAL"), "missing_field")
        # 字段数够、时间戳坏 → bad_timestamp（哪怕等级也怪）
        self.assertEqual(clean.classify_line(
            "2026-09-30 25:02:03.004|dev-01|FATAL|code=200|msg=x"), "bad_timestamp")
        # 时间戳好、等级坏 → bad_level（哪怕 code 也坏）
        self.assertEqual(clean.classify_line(
            "2026-09-30 01:02:03.004|dev-01|FATAL|code=abc|msg=x"), "bad_level")
        self.assertEqual(clean.classify_line(
            "2026-09-30 01:02:03.004|dev-01|INFO|code=abc|msg=x"), "bad_code")
        self.assertEqual(clean.classify_line(
            "2026-09-30 01:02:03.004|dev-01|INFO|code=200|msg=x"), "ok")

    def test_hand_checked_parse(self):
        row = clean.parse_ok_line("2026-09-30 01:02:03.004|dev-07|ERROR|code=503|msg=timeout")
        self.assertEqual(row, {"ts": "2026-09-30 01:02:03.004", "device": "dev-07",
                               "level": "ERROR", "code": "503", "msg": "timeout"})

    def test_generator_ledger_is_exact(self):
        bundle = genlog.make_log(n_lines=500, seed=3, defects={
            "bad_timestamp": 4, "bad_level": 3, "missing_field": 2, "bad_code": 1})
        result = clean.clean_lines(bundle.lines)
        self.assertEqual(result.quarantined, {"bad_timestamp": 4, "bad_level": 3,
                                              "missing_field": 2, "bad_code": 1})
        self.assertEqual(len(result.clean), 500 - 10)


class TestSparkParity(unittest.TestCase):
    """一个会话跑完所有对拍（启动成本只付一次）。"""

    @classmethod
    def setUpClass(cls):
        cls.work = make_tmp("data")
        cls.bundle = genlog.make_log(n_lines=2000, seed=7)
        cls.path = cls.work / "log.txt"
        genlog.write_log(cls.bundle, cls.path)
        cls.cr = clean.clean_file(cls.path)

        cls._cm = session.spark_session("b29-tests")
        cls.spark = cls._cm.__enter__()
        cls.df = jobs.parsed(jobs.load_lines(cls.spark, cls.path))
        jobs.register_view(cls.df)
        cls.clean_df = jobs.cleaned(cls.df)

    @classmethod
    def tearDownClass(cls):
        cls._cm.__exit__(None, None, None)
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_warehouse_outside_repo(self):
        wh = self.spark.conf.get("spark.sql.warehouse.dir")
        self.assertFalse(str(wh).lower().startswith(str(session.REPO).lower()))

    def test_kind_counts_match_ledger(self):
        counts = jobs.clean_counts(self.df)
        self.assertEqual(counts.get("ok"), self.bundle.clean_true)
        for kind, n in self.bundle.ledger.items():
            self.assertEqual(counts.get(kind, 0), n, msg=kind)

    def test_clean_rows_parity_line_by_line(self):
        rows = sorted((r["ts"], r["device"], r["level"], r["code"], r["msg"])
                      for r in self.clean_df.select("ts", "device", "level", "code", "msg").collect())
        self.assertEqual(rows, reference.clean_row_set(self.cr.clean))

    def test_device_level_parity(self):
        self.assertEqual(jobs.agg_device_level(self.clean_df),
                         reference.by_device_level(self.cr.clean))

    def test_errors_per_hour_parity(self):
        self.assertEqual(jobs.agg_errors_per_hour(self.clean_df),
                         reference.errors_per_hour(self.cr.clean))

    def test_top_error_codes_parity(self):
        for k in (1, 3, 5):
            self.assertEqual(jobs.agg_top_error_codes(self.clean_df, k),
                             reference.top_error_codes(self.cr.clean, k), msg=f"k={k}")

    def test_sql_matches_dataframe_api(self):
        # 同一台引擎的两种说法：SQL 与 DataFrame 的结果必须逐行相等，
        # 且都等于纯 Python 参照（两条链一次钉住）
        self.assertEqual(jobs.sql_device_level(self.spark),
                         jobs.agg_device_level(self.clean_df))
        self.assertEqual(jobs.sql_errors_per_hour(self.spark),
                         jobs.agg_errors_per_hour(self.clean_df))
        self.assertEqual(jobs.sql_top_error_codes(self.spark),
                         jobs.agg_top_error_codes(self.clean_df))

    def test_handmade_six_line_frame(self):
        # 六行手工样例：五类各一 + 一条优先级行（3 字段同时时间戳也坏）
        lines = [
            "2026-09-30 01:02:03.004|dev-01|INFO|code=200|msg=ok",
            "2026-09-30 25:02:03.004|dev-01|INFO|code=200|msg=ok",
            "2026-09-30 01:02:03.004|dev-01|FATAL|code=200|msg=ok",
            "2026-09-30 01:02:03.004|dev-01|INFO|code=abc|msg=ok",
            "2026-09-30 01:02:03.004|dev-01|INFO",
            "not-a-date|dev|FATAL",
        ]
        df = jobs.parsed(self.spark.createDataFrame([(l,) for l in lines], ["value"]))
        counts = jobs.clean_counts(df)
        self.assertEqual(counts, {"ok": 1, "bad_timestamp": 1, "bad_level": 1,
                                  "bad_code": 1, "missing_field": 2})

    def test_empty_input(self):
        df = jobs.parsed(self.spark.createDataFrame([], "value STRING"))
        self.assertEqual(jobs.clean_counts(df), {})
        self.assertEqual(jobs.agg_device_level(jobs.cleaned(df)), [])
        self.assertEqual(jobs.agg_errors_per_hour(jobs.cleaned(df)), [])

    def test_aggregations_deterministic(self):
        a = jobs.agg_device_level(self.clean_df)
        b = jobs.agg_device_level(self.clean_df)
        self.assertEqual(a, b)
        self.assertEqual(a, reference.by_device_level(self.cr.clean))


class TestSkew(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cm = session.spark_session("b29-skew")
        cls.spark = cls._cm.__enter__()
        rows = [("dev-01" if i < 3000 else f"dev-{i % 8 + 2:02d}",) for i in range(4000)]
        cls.df = cls.spark.createDataFrame(rows, ["device"])

    @classmethod
    def tearDownClass(cls):
        cls._cm.__exit__(None, None, None)

    def test_keyed_partitioning_concentrates_hot_key(self):
        skewed = skew.partition_row_counts(self.df.repartition(4, "device"))
        uniform = skew.partition_row_counts(self.df.repartition(4))
        self.assertGreater(skew.skew_ratio(skewed), 1.5)   # 热键把某分区撑大
        self.assertLess(skew.skew_ratio(uniform), 1.3)     # 随机重分区是摊平的
        self.assertEqual(sum(skewed), 4000)
        self.assertEqual(sum(uniform), 4000)

    def test_salted_result_equals_plain(self):
        plain = skew.plain_group_count(self.df, "device")
        salted = skew.salted_group_count(self.df, "device", salt_n=8)
        self.assertEqual(salted, plain)
        self.assertEqual(dict(salted)["dev-01"], 3000)

    def test_salted_on_clean_real_log(self):
        # 真实日志管线上的 salting 正确性（数据是生成器的干净子集）
        bundle = genlog.make_log(n_lines=1000, seed=5, skew_device_ratio=0.5)
        path = make_tmp("skewlog") / "l.txt"
        genlog.write_log(bundle, path)
        df = jobs.cleaned(jobs.parsed(jobs.load_lines(self.spark, path))).select("device")
        self.assertEqual(skew.salted_group_count(df, "device", salt_n=4),
                         skew.plain_group_count(df, "device"))


if __name__ == "__main__":
    unittest.main()
