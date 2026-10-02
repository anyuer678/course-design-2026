"""与参照实现对拍：同一份源码，字节码 VM 与树遍历解释器必须给出逐字节相同的结果。

两条路刻意做得很不一样——变量是槽位 vs 名字字典、控制流是跳转 vs Python 递归、
短路是 JZ/JNZ + 补丁 vs 语言自带 and/or、调用是显式帧栈 + CALL/RET vs 整体换作用域 +
宿主异常——所以一致才说明一致不是抄来的。
运算规则本身（tinylang/values.py）是语言定义，两边共用；那部分共用是对的。

随机程序由本文件内的生成器产生：它自己维护类型与作用域（B41 候选②起还生成函数），
产出的一定是"应当通过语义检查"的程序。
**生成器产出的程序若被检查器拒绝，本文件当作失败**——那说明两边的类型规则走偏了，
正是这类测试最有价值的时刻，不能"跳过这个样本"糊过去。
"""
from __future__ import annotations

import os
import random
import re
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
            # ---- 函数与调用帧（B41 候选②）----
            "fun add(a : int, b : int) -> int { return a + b; }\nprint add(2, 3); print add(add(1, 2), 4);",
            "fun fib(n : int) -> int { if n < 2 then return n; return fib(n - 1) + fib(n - 2); }\nprint fib(12);",
            "fun f(x : int) -> int { return x + 1; }\nfun g(x : int) -> int { return f(f(x)); }\nprint g(1);",
            "fun one(x : int) -> int { return x; }\nlet keep : int := 7;\nprint one(keep) + keep;",
            "fun half(x : real) -> real { return x / 2.0; }\nprint half(5);",
            "fun h(n : int, a : string, b : string, c : string) -> int {\n"
            "    if n = 0 then return 0;\n"
            "    let m : int := h(n - 1, a, c, b);\n"
            "    print a + \"->\" + c;\n"
            "    return m + 1 + h(n - 1, b, a, c);\n"
            "}\nprint h(2, \"A\", \"B\", \"C\");",
            "fun msg() -> string { return \"hi\" + \"!\"; }\nprint msg() + msg();",
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

    def test_function_errors_agree_too(self):
        """缺 return / 深度上限 / 被调函数里的除零：两边必须报同一句话、同一行。"""
        cases = [
            # 缺 return：位置 = 函数体结尾的 } 所在行
            ("fun f(x : int) -> int {\n    let y : int := x + 1;\n}\nprint f(1);", 3),
            # 深度上限：位置 = 发起调用的那一行
            ("fun dive(n : int) -> int {\n    return dive(n + 1);\n}\nprint dive(0);", 2),
            # 除零发生在被调函数体内：位置 = 被调函数里的那一行
            ("fun bad(x : int) -> int {\n    return 10 / x;\n}\nprint bad(0);", 2),
            # 除零发生在实参求值（调用者一侧）
            ("fun f(x : int) -> int { return x; }\nlet z : int := 0;\nprint f(10 / z);", 3),
        ]
        for source, line in cases:
            with self.subTest(source=source[:40]):
                built = build(source)
                self.assertEqual(built.errors, [], built.report())
                with self.assertRaises(RuntimeError_) as vm_exc:
                    run_code(built.code)
                with self.assertRaises(RuntimeError_) as walk_exc:
                    interpret(built.program)
                self.assertEqual(vm_exc.exception.message, walk_exc.exception.message)
                self.assertEqual(vm_exc.exception.span.line, line)
                self.assertEqual(walk_exc.exception.span.line, line)

    def test_depth_cap_boundary_agrees(self):
        """第 100 层恰好可用、第 101 层被拒——两条后端在同一条线上翻转。"""
        program = ("fun down(n : int) -> int {\n"
                   "    if n = 0 then return 0;\n"
                   "    return down(n - 1);\n"
                   "}\n")
        built = build(program + "print down(99);")
        self.assertEqual(built.errors, [])
        self.assertEqual(run_code(built.code).output, interpret(built.program).output)
        built = build(program + "print down(100);")
        self.assertEqual(built.errors, [])
        lines = []
        for engine in (lambda: run_code(built.code), lambda: interpret(built.program)):
            with self.assertRaises(RuntimeError_) as ctx:
                engine()
            lines.append((ctx.exception.message, ctx.exception.span.line))
        self.assertEqual(lines[0], lines[1])
        self.assertIn("第 101 层调用被拒绝", lines[0][0])
        self.assertEqual(lines[0][1], 3)         # 递归下调的那一行

    def test_generated_programs_actually_call_functions(self):
        """随机语料必须真的在调函数：全是无函数程序的"对拍"等于没测新面。"""
        total_calls = 0
        seeds_with_calls = 0
        for seed in range(60):
            source = ProgramGen(random.Random(seed)).program(10)
            calls = len(re.findall(r"\bf\d+\(", source))
            total_calls += calls
            seeds_with_calls += 1 if calls else 0
            built = build(source)
            self.assertEqual(built.errors, [], f"{source}\n{built.report()}")
        self.assertGreater(total_calls, 150, f"调用总数太少：{total_calls}")
        self.assertGreater(seeds_with_calls, 30, f"有调用的程序太少：{seeds_with_calls}")

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
