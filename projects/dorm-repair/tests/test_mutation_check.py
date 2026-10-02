"""tests/test_mutation_check.py —— 自检台自己也得有牙齿（B20）。

`tools/mutation_check.py` 的产物是"核对器会红"这个结论。写它的时候我踩了两个坑，
两个都是**自检台自己骗我**，而不是被测代码骗我：

1. 所有变异共用一份副本 → 核对器在副本里写下 `.pyc`。CPython 只用 pyc 头部的两个字段
   判缓存是否有效：源码 mtime 的**整数秒**与源码**字节数**，不比源码内容。
   `copytree` 保留 mtime、还原后字节数复原、两次写又落在同一整秒 → 解释器复用旧字节码，
   变异**在盘上但不在行为里**，于是 `stale-contract` 连跑变绿。
2. `--only <打错的 id>` → 待跑列表为空 → "0 条失败" → 退出码 0。

这两条下面各有一个测试钉住，外加"锚点必须还活在现树上"——重构让变异静默失效时，
宁可测试红，也不要一片绿。这里**不跑**完整自检台（那要 13 份副本 + 十几条子进程），
那是流水线里的一步；本文件只测它不该坏的性质。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import mutation_check as M                       # noqa: E402


class Registry(unittest.TestCase):
    def test_every_anchor_still_hits_the_current_tree_exactly_once(self):
        """变异锚点是纯文本约定，重构随时能让它命中 0 次——那时整片绿是假的。"""
        for m in M.MUTATIONS:
            if m.get("kind") == "inline":
                continue
            path = M.ROOT / m["file"]
            with self.subTest(mutation=m["id"]):
                self.assertTrue(path.is_file(), f"{m['id']} 指向的文件不存在：{m['file']}")
                text = path.read_text(encoding="utf-8")
                self.assertEqual(text.count(m["find"]), m["count"],
                                 f"锚点已失效，请同步 {m['id']} 的 find/replace：{m['find'][:60]}")
                self.assertNotEqual(m["find"], m["replace"])
                self.assertTrue(m["expect"].strip())

    def test_registered_checkers_are_real_scripts(self):
        """登记一个跑不起来的核对器 = 子进程非 0 = '红得对'，那是自证。"""
        for m in M.MUTATIONS:
            if m.get("kind") == "inline":
                continue
            target = m["check"][0]
            if target.startswith("-"):
                continue                                # -m pytest / -c 探针
            with self.subTest(mutation=m["id"]):
                self.assertTrue((M.ROOT / target).is_file(), f"核对器不存在：{target}")


class Apply(unittest.TestCase):
    def test_stale_anchor_raises_instead_of_silently_skipping(self):
        with tempfile.TemporaryDirectory(prefix="b20-t-") as tmp:
            copy = Path(tmp) / "tree"
            M._copy_tree(copy)
            bogus = dict(M.MUTATIONS[0], find="这行文本在 2026-10 之后不存在了-B20")
            with self.assertRaises(RuntimeError) as ctx:
                M._apply(copy, bogus)
            self.assertIn("变异锚点命中 0 次", str(ctx.exception))

    def test_ambiguous_anchor_also_raises(self):
        with tempfile.TemporaryDirectory(prefix="b20-t-") as tmp:
            copy = Path(tmp) / "tree"
            M._copy_tree(copy)
            many = dict(M.MUTATIONS[0], find="Priority", count=1)
            with self.assertRaises(RuntimeError) as ctx:
                M._apply(copy, many)
            self.assertRegex(str(ctx.exception), r"变异锚点命中 \d+ 次")

    def test_evidence_proves_the_mutation_landed_on_disk(self):
        """红/绿之前先确认"变异确实在盘上"，否则分不清是我的拷贝坏了。"""
        with tempfile.TemporaryDirectory(prefix="b20-t-") as tmp:
            copy = Path(tmp) / "tree"
            M._copy_tree(copy)
            evidence = M._apply(copy, M.MUTATIONS[0])
            self.assertNotEqual(evidence["before"], evidence["after"], "前后指纹一样＝没改")
            self.assertEqual(evidence["before"], M._sha(
                (M.ROOT / evidence["file"]).read_text(encoding="utf-8")),
                "副本的起点必须就是工作树的现在这版")
            on_disk = (copy / evidence["file"]).read_text(encoding="utf-8")
            self.assertIn("Priority.URGENT: 3}", on_disk)
            self.assertNotIn("Priority.URGENT: 2}", on_disk)
            self.assertIn(M.MUTATIONS[0]["replace"], "\n".join(evidence["lines"]))
            self.assertIn("+SLA_HOURS", evidence["diff"], "diff 要能看出改了哪一行")


class Isolation(unittest.TestCase):
    def test_each_mutation_runs_in_its_own_copy(self):
        """顺序污染的唯一防线：两个变异不许共用一份副本。"""
        seen = []

        def fake_run_check(copy_root, argv):
            seen.append((Path(copy_root), tuple(argv)))
            return 0, "fake：不提供预期原因"

        real, M.run_check = M.run_check, fake_run_check
        try:
            rows = M.run()
        finally:
            M.run_check = real
        self.assertTrue(rows[0]["passed"], rows[0]["detail"])
        mutation_dirs = [p for p, _ in seen if p.name != "control"]
        expected = [m for m in M.MUTATIONS if m.get("kind") != "inline"]
        self.assertEqual(len(mutation_dirs), len(expected),
                         "每条非内联变异应各跑一次自己的副本")
        self.assertEqual(len({str(p) for p in mutation_dirs}), len(expected),
                         "副本目录有重复＝变异之间会互相污染")
        self.assertEqual(sum(1 for p, _ in seen if p.name == "control"),
                         len(M.CONTROL_CHECKS), "阴性对照应逐个核对器各跑一次")

    def test_child_checkers_leave_no_bytecode_in_the_copy(self):
        """这条钉的是实测坑本身：子进程在副本里写 __pycache__，下一个变异就会被旧字节码吃掉。"""
        with tempfile.TemporaryDirectory(prefix="b20-t-") as tmp:
            copy = Path(tmp) / "tree"
            M._copy_tree(copy)
            code, out = M.run_check(copy, ["-c", "import spec.workorder as w; print(w.SLA_HOURS)"])
            self.assertEqual(code, 0, out)
            self.assertIn("URGENT", out)
            left = [str(p.relative_to(copy)) for p in copy.rglob("__pycache__")]
            self.assertEqual(left, [], f"副本里出现了字节码缓存，变异之间会互相污染：{left}")


class Invocation(unittest.TestCase):
    def test_unknown_id_is_a_failure_not_an_empty_green(self):
        rows = M.run(only="这条没登记过")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["passed"])
        self.assertIn("未知的变异 id", rows[0]["detail"])


if __name__ == "__main__":
    unittest.main()
