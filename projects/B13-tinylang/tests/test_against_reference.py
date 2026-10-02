"""与参照实现对拍：同一份源码，字节码 VM 与树遍历解释器必须给出逐字节相同的结果。

两条路刻意做得很不一样——变量是槽位 vs 名字字典、控制流是跳转 vs Python 递归、
短路是 JZ/JNZ + 补丁 vs 语言自带 and/or——所以一致才说明一致不是抄来的。
运算规则本身（tinylang/values.py）是语言定义，两边共用；那部分共用是对的。

随机程序由本文件内的生成器产生：它自己维护类型与作用域，产出的一定是"应当通过语义检查"的程序。
**生成器产出的程序若被检查器拒绝，本文件当作失败**——那说明两边的类型规则走偏了，
正是这类测试最有价值的时刻，不能"跳过这个样本"糊过去。
"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tinylang.fuzz import ProgramGen                              # noqa: E402
from tinylang.nodes import VarDecl                                    # noqa: E402
from tinylang.pipeline import build                                   # noqa: E402
from tinylang.spans import RuntimeError_                   # noqa: E402
from tinylang.tree_walk import interpret                              # noqa: E402
from tinylang.vm import run_code                                      # noqa: E402

def global_slots(program):
    """顶层 let 的名字 → 槽位，用来比较两边的最终状态。"""
    return {node.name: node.slot for node in program.stmts if isinstance(node, VarDecl)}


class TestEnginesAgree(unittest.TestCase):
    COUNT = 300

    def run_pair(self, source: str):
        built = build(source)
        self.assertEqual(built.errors, [], f"生成器产出的程序被检查器拒绝：\n{source}"
                                           f"\n{built.report()}")
        vm = run_code(built.code, max_steps=200_000)
        walk = interpret(built.program, max_steps=200_000)
        self.assertEqual(vm.output, walk.output,
                         f"两条执行路径输出不同：\n{source}\nVM={vm.output}\n树={walk.output}")
        mapping = global_slots(built.program)
        for name, slot in mapping.items():
            self.assertEqual(vm.locals_view[slot], walk.environment.get(name),
                             f"变量 {name} 的最终状态不同：\n{source}")
        return vm, walk

    def test_random_programs_agree(self):
        seen_outputs = 0
        for seed in range(self.COUNT):
            rng = random.Random(seed)
            source = ProgramGen(rng).program(self.rng_statements(rng))
            with self.subTest(seed=seed):
                vm, _ = self.run_pair(source)
                seen_outputs += len(vm.output)
        self.assertGreater(seen_outputs, 1000, "随机程序怎么也得产生上千行输出才算覆盖到")

    @staticmethod
    def rng_statements(rng):
        return rng.randint(4, 14)

    def test_hand_written_corpus_agrees(self):
        corpus = [
            "let i : int := 0; let sum : int := 0; while i < 10 do { sum := sum + i; i := i + 1; } print sum;",
            'let s : string := "a"; { let s : string := s + "b"; print s; } print s;',
            "let x : int := 0; if x != 0 and 10 / x > 1 then print 1; else print 2;",
            "let r : real := 1; print r / 2; print r + 1; print (r + r) * 2;",
            "let a : int := 5; let b : int := 3; while a > b do { a := a - 1; } print a; print b;",
            "print -7 / 2; print -7 % 2; print 7 % -2;",
            "let t : bool := true; print t and not t; print t or false;",
            "print 1; print 2; print 3;",
            "{ let deep : int := 1; { let deep : int := deep + 1; { print deep; } } }",
            "let n : int := 0; while n < 3 do { n := n + 1; print n * n; }",
        ]
        for source in corpus:
            with self.subTest(source=source[:48]):
                self.run_pair(source)

    def test_runtime_errors_agree_too(self):
        """除零这类运行期错误：两边必须报同一句话、同一行。"""
        sources = [
            "let z : int := 0;\nprint 10 / z;",
            "let i : int := 3;\nwhile i > 0 do { i := i - 1; }\nprint 1 / (0 * i);",
            "let r : real := 0.0;\nprint 1.0 % r;",
        ]
        for source in sources:
            with self.subTest(source=source[:32]):
                built = build(source)
                self.assertEqual(built.errors, [], built.report())
                with self.assertRaises(RuntimeError_) as vm_exc:
                    run_code(built.code)
                with self.assertRaises(RuntimeError_) as walk_exc:
                    interpret(built.program)
                self.assertEqual(vm_exc.exception.message, walk_exc.exception.message)
                self.assertEqual(vm_exc.exception.span.line, walk_exc.exception.span.line)
                self.assertEqual(vm_exc.exception.span.line, source.count("\n", 0,
                                   source.index("print 1")) + 1
                                   if "print 1 /" in source else vm_exc.exception.span.line)

    def test_generated_programs_actually_execute_loops_and_branches(self):
        """随机语料必须真的走到循环与分支：只生成一串 print 的对拍等于没测。"""
        counters = {"while": 0, "if": 0, "block": 0}
        steps = 0
        for seed in range(60):
            source = ProgramGen(random.Random(seed)).program(10)
            for key in counters:
                counters[key] += source.count(key)
            built = build(source)
            self.assertEqual(built.errors, [], f"{source}\n{built.report()}")
            steps += run_code(built.code).steps
        self.assertGreater(counters["while"], 10, counters)
        self.assertGreater(counters["if"], 10, counters)
        self.assertGreater(steps, 5000, "总执行步数太少，说明程序都是空壳")


if __name__ == "__main__":
    unittest.main(verbosity=2)
