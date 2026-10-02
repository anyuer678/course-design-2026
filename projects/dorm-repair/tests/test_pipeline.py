"""tests/test_pipeline.py —— 流水线自己的回归网（B20）。

流水线最容易犯的错不是"命令跑挂"，那看得见；是**命令退 0、我却没读到数**，
于是报告里那一层写着绿。B18 的 `BUILD SUCCESS 但 0 个测试`、B19 的"加固其实没生效"
都是同一类事故，所以这里测的重点是：

* 读数读不到 → 这层必须判红（不是判跳过，也不是留个空；实测见本轮探针）；
* 层登记表的完整性：id 唯一、每层都写得出"什么改动会让它红"；
* `--only <不存在的层>` 不能变成"选到 0 层 → 全绿 → 退出码 0"。

期望值的出处：`docs/02-srs.md` 里 FR 那条计数行是 2026-10-01 实测 `python checks/check_docs.py`
的输出，我把它抄进来当样本；抄的东西会过期，所以第 5 条测试**真的跑一次** docs 层。
"""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import pipeline as P                          # noqa: E402


class Registry(unittest.TestCase):
    def test_layer_ids_are_unique_and_each_says_how_it_goes_red(self):
        ids = [layer.id for layer in P.LAYERS]
        self.assertEqual(len(ids), len(set(ids)), "层 id 重复：--only 会跑两层或跑不到")
        for layer in P.LAYERS:
            with self.subTest(layer=layer.id):
                self.assertTrue(layer.turns_red.strip(), "没写清什么改动能让这层红 = 这层不需要存在")
                self.assertTrue(layer.why.strip())
                self.assertTrue(callable(layer.read))
                self.assertTrue(layer.argv, "空命令")
                first = layer.argv[0]
                if not first.startswith("-"):
                    self.assertTrue((ROOT / first).is_file(), f"{layer.id} 指向不存在的脚本")

    def test_read_functions_exist_for_every_layer(self):
        # 每层的读数函数不许是占位：给它一份明显不对的输出，必须抛 CannotRead 而不是返回空 dict
        for layer in P.LAYERS:
            with self.subTest(layer=layer.id):
                with self.assertRaises(P.CannotRead):
                    layer.read("这行里什么数都没有-B20")


class ReadDocs(unittest.TestCase):
    SAMPLE = ("文档一致性通过：FR 15 / BR 11 / NFR 7 / IF 4 / UC 6 / US 13 / AC 40 / "
              "转换 15 / 待决 12\n  追踪矩阵与文档一致\n")

    def test_parses_the_measured_line(self):
        """出处：2026-10-01 实跑 `python checks/check_docs.py` 的那一行。"""
        self.assertEqual(P.read_docs(self.SAMPLE),
                         {"FR": 15, "BR": 11, "NFR": 7, "IF": 4, "UC": 6, "US": 13,
                          "AC": 40, "转换": 15, "待决": 12})

    def test_missing_counts_are_a_failure_not_a_zero(self):
        """0 和"读不到"必须分开：把读不到当成 0，报告就撒了谎。"""
        with self.assertRaises(P.CannotRead):
            P.read_docs(self.SAMPLE.replace("FR 15", "fr-15"))


class RedWhenUnreadable(unittest.TestCase):
    def test_exit_zero_but_unreadable_output_turns_the_layer_red(self):
        layer = P.Layer("probe", "探针层", ["-c", "print('什么都读不到')"],
                        P.read_docs, "输出里没有可解析的计数", "测的就是这条规则本身")
        row = layer.run()
        self.assertEqual(row["code"], 0, "命令本身要成功，否则测的就不是读数")
        self.assertEqual(row["status"], "红")
        self.assertIn("退出码 0 但读不到数", row["note"])
        self.assertEqual(row["metrics"], {})

    def test_layer_that_reports_a_real_number_is_green(self):
        layer = P.Layer("probe", "探针层", ["-c", "print('Ran 7 tests in 0.1s\\nOK')"],
                        P.read_python_tests, "测试数变少", "测的是绿路径")
        row = layer.run()
        self.assertEqual((row["status"], row["metrics"]["测试"]), ("绿", 7), row)


class Invocation(unittest.TestCase):
    def test_unknown_layer_is_not_an_empty_green(self):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = P.main(["x", "--only", "no-such-layer"])
        self.assertEqual(code, 1, "选不到层却退 0，就等于流水线被拼错的名字骗过")

    def test_docs_layer_actually_runs_end_to_end(self):
        """不是 mock：真的起子进程跑 checks/check_docs.py，确认 ROOT/编码/读数三样都接得上。"""
        rows = P.run(["docs"], quiet=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "绿",
                         rows[0]["note"] + "\n" + "\n".join(rows[0]["output_tail"]))
        self.assertGreater(rows[0]["duration_s"], 0.0, "耗时必须真测出来，不许是占位 0")


if __name__ == "__main__":
    unittest.main()
