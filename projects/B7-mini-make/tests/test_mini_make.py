"""tests/test_mini_make.py —— mini-make 的 15 项测试。

纪律（和本仓库其它项目一致）：
  1. 期望值来自**手算或独立参照**：执行顺序对着拓扑序人工推、`-j` 的结果与串行对拍；
  2. 每条断言都能回答"被什么改动弄红"；
  3. 临时目录一律 `tempfile.mkdtemp`，**删除前断言它不在仓库里**（这条是 2026-10-02 事故换来的）。
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mm                      # noqa: E402
import logstat                 # noqa: E402

REPO = ROOT.parent.parent


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b7-{name}-"))
    if str(base.resolve()).lower().startswith(str(REPO.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


class MakeTempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp(self._testMethodName[:20])
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, name: str, text: str) -> pathlib.Path:
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def load(self, text: str) -> mm.Makefile:
        return mm.Makefile.load(self.write("Makefile", text))


class TestParsing(MakeTempCase):
    def test_targets_deps_and_recipe_are_parsed(self):
        mf = self.load("all: a b\n\techo all\na:\n\techo a\nb: a\n\techo b\n")
        self.assertEqual(sorted(mf.targets), ["a", "all", "b"])
        self.assertEqual(mf.targets["all"].deps, ["a", "b"])
        self.assertEqual(mf.targets["b"].recipe, ["echo b"])
        self.assertEqual(mf.targets["b"].deps, ["a"])

    def test_phony_is_parsed_and_duplicate_target_is_refused(self):
        mf = self.load(".PHONY: all clean\nall:\n\ttype nul > out\nclean:\n\tdel /q out 2>nul\n")
        self.assertEqual(mf.phony, {"all", "clean"})
        with self.assertRaises(mm.MakeError):
            self.load("all:\n\techo >nul\nall:\n\techo >nul\n")

    def test_recipe_before_any_target_is_refused(self):
        with self.assertRaises(mm.MakeError):
            self.load("\techo oops\n")


class TestOrdering(MakeTempCase):
    def test_topological_order_respects_dependencies(self):
        mf = self.load("all: b c\n\techo >nul\nb: a\n\techo >nul\nc: a\n\techo >nul\na:\n\techo >nul\n")
        order = mf.order("all")
        self.assertLess(order.index("a"), order.index("b"))
        self.assertLess(order.index("b"), order.index("c"))
        self.assertEqual(order[-1], "all")

    def test_cycle_is_reported_with_the_cycle_on_it(self):
        mf = self.load("a: b\n\techo >nul\nb: a\n\techo >nul\n")
        with self.assertRaises(mm.MakeError) as caught:
            mf.order("a")
        self.assertIn("成环", str(caught.exception))
        self.assertIn("a -> b -> a", str(caught.exception))

    def test_missing_prerequisite_is_refused_but_existing_file_is_ok(self):
        self.write("real.txt", "x")
        mf = self.load("all: real.txt\n\techo >nul\n")
        self.assertIn("all", mf.order("all"))
        bad = self.load("all: nope.xyz\n\techo >nul\n")
        with self.assertRaises(mm.MakeError):
            bad.order("all")


class TestIncremental(MakeTempCase):
    def test_missing_target_and_phony_always_need_build(self):
        mf = self.load(".PHONY: all\nall: out\n\techo >nul\nout:\n\ttype nul > out\n")
        self.assertTrue(mf.needs_build("out"))       # 文件不存在
        self.assertTrue(mf.needs_build("all"))       # 伪目标永远执行

    def test_up_to_date_when_newer_than_dependencies(self):
        dep = self.write("dep.txt", "d")
        out = self.write("out.txt", "o")
        now = time.time()
        import os
        os.utime(dep, (now - 10, now - 10))
        os.utime(out, (now, now))
        mf = self.load("out.txt: dep.txt\n\tcopy /y dep.txt out.txt >nul\n")
        self.assertFalse(mf.needs_build("out.txt"))

    def test_touching_a_dependency_triggers_rebuild(self):
        dep = self.write("dep.txt", "d")
        out = self.write("out.txt", "o")
        import os
        os.utime(out, (time.time(), time.time()))
        os.utime(dep, (time.time() + 5, time.time() + 5))   # 前置更新
        mf = self.load("out.txt: dep.txt\n\tcopy /y dep.txt out.txt >nul\n")
        self.assertTrue(mf.needs_build("out.txt"))


class TestBuilding(MakeTempCase):
    def test_build_runs_recipe_and_creates_the_file(self):
        mf = self.load("all: out.txt\n\techo >nul\nout.txt:\n\techo hello > out.txt\n")
        code = mm.Builder(mf, verbose=False).build("all")
        self.assertEqual(code, 0)
        self.assertEqual((self.tmp / "out.txt").read_text(encoding="utf-8").strip(), "hello")

    def test_second_build_is_up_to_date_and_does_not_rerun(self):
        mf = self.load("all: out.txt\n\techo >nul\nout.txt:\n\techo x >> out.txt\n")
        builder = mm.Builder(mf, verbose=False)
        builder.build("all")
        first = (self.tmp / "out.txt").read_text(encoding="utf-8")
        second = mm.Builder(mf, verbose=False)
        second.build("all")
        self.assertIn("out.txt", second.skipped)
        self.assertNotIn("out.txt", second.built)
        self.assertEqual((self.tmp / "out.txt").read_text(encoding="utf-8"), first)

    def test_failure_returns_nonzero_and_does_not_build_dependents(self):
        mf = self.load("all: bad\n\techo should-not-run > ran.txt\nbad:\n\texit 7\n")
        code = mm.Builder(mf, verbose=False).build("all")
        self.assertEqual(code, 1)
        self.assertFalse((self.tmp / "ran.txt").exists(), "上游失败，下游不该执行")
        self.assertEqual(mm.Builder(mf, verbose=False).failed, None)   # 新实例从干净状态开始

    def test_parallel_matches_serial_on_independent_targets(self):
        text = ("all: x y z\n\techo >nul\nx:\n\techo x > x\n"
                "y:\n\techo y > y\nz:\n\techo z > z\n")
        serial = mm.Builder(self.load(text), jobs=1, verbose=False)
        serial.build("all")
        for f in ("x", "y", "z"):
            (self.tmp / f).unlink()
        parallel = mm.Builder(self.load(text), jobs=4, verbose=False)
        code = parallel.build("all")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(parallel.built), sorted(serial.built))
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.is_file()),
                         ["Makefile", "x", "y", "z"])


class TestLogstat(MakeTempCase):
    def test_diagnostics_are_counted_and_templated(self):
        log = self.write("build.log", "\n".join([
            "src/a.cpp:12:3: warning: symbol 'x1' defined but not used",
            "src/a.cpp:40:1: warning: symbol 'x2' defined but not used",
            "src/b.cpp:7:9: error: 'foo' was not declared in this scope",
            "3 warnings generated.",
        ]))
        report = logstat.parse(log.read_text(encoding="utf-8"))
        self.assertEqual(report["by_severity"], {"warning": 2, "error": 1})
        self.assertEqual(report["top"][0][0], "warning: symbol 'xN' defined but not used")
        self.assertEqual(report["summaries"], [(3, "warning")])

    def test_empty_log_is_zero_not_failure(self):
        log = self.write("empty.log", "")
        report = logstat.parse(log.read_text(encoding="utf-8"))
        self.assertEqual(report["by_severity"], {})
        self.assertEqual(report["top"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
