"""B41 候选②的第三项验收：与 B12 同族的递归算法互相验证。

这部分回答"调用帧真的算对了吗"：拿递归算法当被测对象，答案不来自我们自己——
斐波那契对**迭代参照**、汉诺塔对 **Python 递归参照 + 2^n-1 性质**、
Ackermann 对 Python 参照、二项式系数对 `math.comb`。每个程序同时过一遍
双后端对拍（输出逐字节一致），所以它既是"算法对不对"的验证，也是"两条路
在递归上是否仍一致"的验证。

**不覆盖快排**：本语言没有数组，序列类算法无法表达——快排要等"数组与越界检查"
这个扩展（见 README 练习）。把这句话写在这里也是验收的一部分：不假装测过。
"""
from __future__ import annotations

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tinylang.pipeline import build                                   # noqa: E402
from tinylang.tree_walk import interpret                              # noqa: E402
from tinylang.vm import run_code                                      # noqa: E402


def run_program(name: str) -> list:
    """跑 programs/ 下的样例：两条后端都必须成功且输出一致，返回输出行列表。"""
    with open(os.path.join(ROOT, "programs", name), encoding="utf-8", newline="") as handle:
        source = handle.read()
    built = build(source)
    if built.errors:
        raise AssertionError(f"{name} 编译失败：\n{built.report()}")
    vm = run_code(built.code)
    walk = interpret(built.program)
    if vm.output != walk.output:
        raise AssertionError(f"{name} 两条后端输出不同：\nVM={vm.output}\n树={walk.output}")
    return vm.output


def fib_iterative(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def ack_python(m: int, n: int) -> int:
    return n + 1 if m == 0 else (ack_python(m - 1, 1) if n == 0
                                 else ack_python(m - 1, ack_python(m, n - 1)))


def hanoi_moves(n: int, a: str = "A", b: str = "B", c: str = "C") -> list:
    """Python 递归参照：与 tinylang 版同序（先递归 A→C 中转 B，再走本步，再递归 B→A）。"""
    if n == 0:
        return []
    return (hanoi_moves(n - 1, a, c, b) + [f"{a}->{c}"]
            + hanoi_moves(n - 1, b, a, c))


class TestRecursionVersusReferences(unittest.TestCase):
    def test_fib_sequence_equals_iterative_reference(self):
        output = run_program("fib.tiny")
        self.assertEqual(output, [str(fib_iterative(i)) for i in range(16)])
        self.assertEqual(output[:8], ["0", "1", "1", "2", "3", "5", "8", "13"])

    def test_hanoi_moves_and_count_match_python_reference(self):
        output = run_program("hanoi.tiny")
        moves = hanoi_moves(3)
        self.assertEqual(output[:-1], moves)
        self.assertEqual(output[-1], str(len(moves)))
        self.assertEqual(len(moves), 2 ** 3 - 1)

    def test_hanoi_move_count_property_two_to_the_n_minus_one(self):
        with open(os.path.join(ROOT, "programs", "hanoi.tiny"),
                  encoding="utf-8", newline="") as handle:
            base = handle.read()
        core = base.split("print hanoi(3", 1)[0]
        for n in (1, 2, 4, 5):
            source = core + f'print hanoi({n}, "A", "B", "C");\n'
            built = build(source)
            self.assertEqual(built.errors, [], built.report())
            output = run_code(built.code).output
            self.assertEqual(output, hanoi_moves(n) + [str(2 ** n - 1)], f"n={n}")

    def test_ackermann_matches_python_reference(self):
        output = run_program("ackermann.tiny")
        self.assertEqual(output, [str(ack_python(2, 3)), str(ack_python(3, 3))])
        self.assertEqual(output, ["9", "61"])

    def test_binomial_matches_math_comb(self):
        output = run_program("binomial.tiny")
        self.assertEqual(output, [str(math.comb(10, 5)), str(math.comb(1, 1))])
        self.assertEqual(output, ["252", "1"])

    def test_recursive_programs_have_bounded_steps(self):
        """递归样例必须真的在跑（步数有量级），而不是碰巧被优化成常量。"""
        with open(os.path.join(ROOT, "programs", "fib.tiny"),
                  encoding="utf-8", newline="") as handle:
            source = handle.read()
        built = build(source)
        result = run_code(built.code)
        self.assertGreater(result.steps, 10_000, "fib(0..15) 的调用步数不该这么少")


if __name__ == "__main__":
    unittest.main(verbosity=2)
