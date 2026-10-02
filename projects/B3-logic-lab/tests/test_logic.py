"""tests/test_logic.py —— B3-logic-lab 的单元测试。

纪律（和本仓库其它项目一致）：
  1. 期望值来自**手算或独立参照**：真值表逐行手写、范式逐字符对照、
     Warshall 与 BFS 对拍、随机关系用固定种子（无种子 = 失败无法复现）；
  2. 每条断言都能回答"被什么改动弄红"；
  3. 本套件**纯内存**，不建临时目录、不碰文件系统（事故后纪律：测试不接触仓库外路径）。
"""
from __future__ import annotations

import random
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from logic3 import formula as F          # noqa: E402
from logic3 import truth as T            # noqa: E402
from logic3 import relation as R         # noqa: E402


def parse(text: str):
    return F.parse(text)


class TestLexer(unittest.TestCase):
    def test_two_char_operators_win(self):
        # 先吃两字符运算符，`->` 不会被拆成 `-` 与 `>`
        self.assertEqual(F.tokenize("p->q"), ["p", "->", "q"])
        self.assertEqual(F.tokenize("p<=>q"), ["p", "<=>", "q"])

    def test_whitespace_and_mixed(self):
        self.assertEqual(F.tokenize("(p & q) | ~r"), ["(", "p", "&", "q", ")", "|", "~", "r"])
        self.assertEqual(F.tokenize("  p1 <=> q2  "), ["p1", "<=>", "q2"])

    def test_constants_are_tokens(self):
        self.assertEqual(F.tokenize("p & 1"), ["p", "&", "1"])
        self.assertEqual(F.tokenize("0 | p"), ["0", "|", "p"])

    def test_bad_char_reports_position(self):
        with self.assertRaises(F.FormulaError) as ctx:
            F.tokenize("p @ q")
        self.assertEqual(ctx.exception.pos, 2)

    def test_lone_angle_and_dash_rejected(self):
        with self.assertRaises(F.FormulaError) as ctx1:
            F.tokenize("p<q")
        self.assertEqual(ctx1.exception.pos, 1)
        with self.assertRaises(F.FormulaError) as ctx2:
            F.tokenize("p - > q")
        self.assertEqual(ctx2.exception.pos, 2)


class TestParser(unittest.TestCase):
    def test_precedence_render(self):
        # render 的括号位置就是解析出的树形；逐条手推
        self.assertEqual(F.render(parse("~p & q")), "(~p & q)")
        self.assertEqual(F.render(parse("p | q & r")), "(p | (q & r))")
        self.assertEqual(F.render(parse("p & q -> r")), "((p & q) -> r)")
        self.assertEqual(F.render(parse("p -> q <=> r")), "((p -> q) <=> r)")
        self.assertEqual(F.render(parse("p <=> q -> r")), "(p <=> (q -> r))")
        self.assertEqual(F.render(parse("~~p")), "~(~p)")

    def test_imp_right_associative(self):
        self.assertEqual(F.render(parse("p -> q -> r")), "(p -> (q -> r))")
        # 见证赋值：全假时右结合为真；左结合 ((p->q)->r) 会算成假
        node = parse("p -> q -> r")
        self.assertTrue(F.evaluate(node, {"p": False, "q": False, "r": False}))

    def test_iff_lower_than_imp_witness(self):
        # p=F, q=T, r=T：若把 <=> 当得更紧（(p<=>q)->r）会得真，这里必须是假
        node = parse("p <=> q -> r")
        self.assertFalse(F.evaluate(node, {"p": False, "q": True, "r": True}))

    def test_and_binds_tighter_than_imp_witness(self):
        # p & q -> r 读作 (p & q) -> r；p=F 时应为真（前件假）
        node = parse("p & q -> r")
        self.assertTrue(F.evaluate(node, {"p": False, "q": True, "r": False}))
        # 若误读成 p & (q -> r)，p=F 时也为真——换 p=T,q=F,r=F 再卡一次：
        # (T & F) -> F = 真；T & (F -> F) = 真。两读法在此同值，故用 render 已足够，
        # 这里只保留一个不假阴性的一致点。
        self.assertTrue(F.evaluate(node, {"p": True, "q": False, "r": False}))

    def test_constants_parse_and_render(self):
        self.assertEqual(F.render(parse("1")), "1")
        self.assertEqual(F.render(parse("0")), "0")
        self.assertEqual(F.variables(parse("1")), [])
        self.assertTrue(F.evaluate(parse("1"), {}))
        self.assertFalse(F.evaluate(parse("0"), {}))

    def test_variables_sorted_lexicographically(self):
        node = parse("z & a & m & b & p1 & p10 & p2")
        self.assertEqual(F.variables(node), ["a", "b", "m", "p1", "p10", "p2", "z"])

    def test_error_positions_are_char_offsets(self):
        cases = [("p &", 3, "意外结束"),          # 末尾缺操作数
                 ("(p & q", 6, "期望"),            # 缺右括号，报在末尾
                 (")", 0, "不该出现"),
                 ("()", 1, "不该出现"),
                 ("p q", 2, "多余"),
                 ("~", 1, "意外结束"),
                 ("p -> ", 5, "意外结束"),
                 ("", 0, "空公式"),
                 ("   ", 0, "空公式")]
        for text, pos, frag in cases:
            with self.assertRaises(F.FormulaError, msg=text) as ctx:
                parse(text)
            self.assertEqual(ctx.exception.pos, pos, msg=text)
            self.assertIn(frag, str(ctx.exception), msg=text)


class TestTruthTable(unittest.TestCase):
    def test_hand_written_table_for_and(self):
        table = T.truth_table(parse("p & q"))
        self.assertEqual(table["vars"], ["p", "q"])
        self.assertEqual(table["rows"], [((False, False), False),
                                         ((False, True), False),
                                         ((True, False), False),
                                         ((True, True), True)])

    def test_implication_hand_counted(self):
        node = parse("p -> q")
        self.assertEqual(T.minterms(node), [0, 1, 3])   # 唯一假行是 10
        self.assertEqual(T.maxterms(node), [2])

    def test_minterms_and_maxterms_partition(self):
        for text in ("p", "~p", "p & q", "p -> q", "p <=> q", "~(p & (q | ~r))"):
            node = parse(text)
            n = len(F.variables(node))
            self.assertEqual(sorted(T.minterms(node) + T.maxterms(node)),
                             list(range(2 ** n)), msg=text)
            self.assertEqual(len(T.minterms(node)) + len(T.maxterms(node)), 2 ** n,
                             msg=text)

    def test_tautology_and_contradiction(self):
        self.assertTrue(T.is_tautology(parse("p | ~p")))
        self.assertFalse(T.is_satisfiable(parse("p & ~p")))
        self.assertTrue(T.is_contradiction(parse("p & ~p")))
        self.assertEqual(T.to_dnf(parse("p & ~p")), "0")
        self.assertEqual(T.to_cnf(parse("p | ~p")), "1")
        self.assertEqual(T.to_dnf(parse("1")), "1")
        self.assertEqual(T.to_cnf(parse("0")), "0")

    def test_de_morgan_table_equality(self):
        left, right = parse("~(p & q)"), parse("~p | ~q")
        self.assertEqual(T.truth_table(left)["rows"], T.truth_table(right)["rows"])
        self.assertEqual(T.minterms(left), [0, 1, 2])    # 手算：只有 11 行是假
        self.assertTrue(T.equivalent(left, right))
        self.assertFalse(T.equivalent(parse("~(p & q)"), parse("~p & ~q")))

    def test_contrapositive(self):
        self.assertTrue(T.equivalent(parse("p -> q"), parse("~q -> ~p")))

    def test_dnf_cnf_exact_strings(self):
        self.assertEqual(T.to_dnf(parse("p & q")), "(p & q)")
        self.assertEqual(T.to_cnf(parse("p & q")),
                         "(p | q) & (p | ~q) & (~p | q)")
        node = parse("p -> (q & r)")
        self.assertEqual(T.minterms(node), [0, 1, 2, 3, 7])   # 手算：假行仅 100/101/110
        self.assertEqual(T.maxterms(node), [4, 5, 6])

    def test_dnf_cnf_round_trip(self):
        # 主范式的文本必须能被解析器吃下，且与原公式等价（含退化式 0/1）
        for text in ("p | q -> r", "p <=> q", "~(p & (q | ~r))",
                     "p & ~p", "p | ~p"):
            node = parse(text)
            self.assertTrue(T.equivalent(parse(T.to_dnf(node)), node), msg=text)
            self.assertTrue(T.equivalent(parse(T.to_cnf(node)), node), msg=text)

    def test_equivalent_uses_variable_union(self):
        self.assertFalse(T.equivalent(parse("p"), parse("p & q")))
        self.assertTrue(T.equivalent(parse("p | ~p"), parse("q -> q")))

    def test_assignment_of(self):
        self.assertEqual(T.assignment_of(3, ["p", "q"]), {"p": True, "q": True})
        self.assertEqual(T.assignment_of(0, ["p", "q"]), {"p": False, "q": False})
        self.assertEqual(T.assignment_of(5, ["p", "q", "r"]),
                         {"p": True, "q": False, "r": True})

    def test_format_table(self):
        lines = T.format_table(parse("p & q"))
        self.assertEqual(lines[0], "p  q  结果  行号")
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[4], "1  1  1  3")
        self.assertEqual(lines[1], "0  0  0  0")


def pairs_of(n, predicate):
    return [(i, j) for i in range(n) for j in range(n) if predicate(i, j)]


class TestRelationProperties(unittest.TestCase):
    def test_equality_is_equivalence_and_partial_order(self):
        eq3 = R.Relation.from_pairs(3, [(i, i) for i in range(3)])
        self.assertTrue(eq3.is_reflexive())
        self.assertTrue(eq3.is_symmetric())
        self.assertTrue(eq3.is_transitive())
        self.assertTrue(eq3.is_antisymmetric())      # 对角线自由，故恒等关系也是偏序
        self.assertTrue(eq3.is_equivalence())
        self.assertTrue(eq3.is_partial_order())
        self.assertEqual(eq3.equivalence_classes(), [[0], [1], [2]])
        self.assertEqual(eq3.check_partition(), [])

    def test_empty_relation_is_symmetric_vacuously(self):
        empty2 = R.Relation.from_pairs(2, [])
        self.assertFalse(empty2.is_reflexive())
        self.assertTrue(empty2.is_irreflexive())
        self.assertTrue(empty2.is_symmetric())       # 空集上全称命题为真
        self.assertTrue(empty2.is_transitive())
        self.assertFalse(empty2.is_equivalence())    # 缺自反

    def test_antipair_is_symmetric_not_transitive(self):
        pair01 = R.Relation.from_pairs(2, [(0, 1), (1, 0)])
        self.assertTrue(pair01.is_symmetric())
        self.assertFalse(pair01.is_antisymmetric())  # i≠j 却互相可达
        self.assertFalse(pair01.is_transitive())     # 0R1 ∧ 1R0 要求 0R0，缺失

    def test_strict_order_and_reflexive_closure(self):
        lt3 = R.Relation.from_pairs(3, pairs_of(3, lambda i, j: i < j))
        self.assertTrue(lt3.is_irreflexive())
        self.assertTrue(lt3.is_antisymmetric())
        self.assertTrue(lt3.is_transitive())
        self.assertFalse(lt3.is_partial_order())     # 严格序不自反
        le3 = lt3.reflexive_closure()
        self.assertTrue(le3.is_reflexive())
        self.assertTrue(le3.is_partial_order())
        self.assertEqual(le3.pairs(), [(0, 0), (0, 1), (0, 2),
                                       (1, 1), (1, 2), (2, 2)])

    def test_divisibility_is_partial_order(self):
        n = 4
        div = R.Relation.from_pairs(n, pairs_of(n, lambda i, j: (j + 1) % (i + 1) == 0))
        self.assertTrue(div.is_partial_order())
        self.assertFalse(div.is_equivalence())

    def test_symmetric_closure(self):
        rel = R.Relation.from_pairs(3, [(0, 1)])
        sym = rel.symmetric_closure()
        self.assertTrue(sym.is_symmetric())
        self.assertEqual(sym.pairs(), [(0, 1), (1, 0)])
        self.assertEqual(sym.symmetric_closure().pairs(), sym.pairs())  # 幂等


class TestClosures(unittest.TestCase):
    def test_warshall_matches_bfs_on_seeded_random(self):
        rng = random.Random(20261002)                # 固定种子：失败可复现
        compared = 0
        for n in (1, 2, 3, 5, 8):
            for density in (0.0, 0.25, 0.6, 1.0):
                matrix = [[rng.random() < density for _ in range(n)]
                          for _ in range(n)]
                rel = R.Relation(matrix)
                w = rel.transitive_closure_warshall()
                b = rel.transitive_closure_bfs()
                self.assertEqual(w.m, b.m, msg=f"n={n} d={density}")
                self.assertTrue(w.is_transitive())
                for i in range(n):                   # 原关系 ⊆ 闭包
                    for j in range(n):
                        if rel.m[i][j]:
                            self.assertTrue(w.m[i][j])
                        compared += 1
        self.assertGreater(compared, 400)            # 真的比过这么多格

    def test_cycle_closure_is_universal(self):
        cyc = R.Relation.from_pairs(3, [(0, 1), (1, 2), (2, 0)])
        w = cyc.transitive_closure_warshall()
        self.assertTrue(all(all(row) for row in w.m))
        self.assertTrue(w.is_equivalence())
        self.assertEqual(w.equivalence_classes(), [[0, 1, 2]])

    def test_warshall_diagonal_baked_in(self):
        # 教材 Warshall 含自身可达；无环无自环的关系闭包也全对角线为真
        rel = R.Relation.from_pairs(2, [(0, 1)])
        w = rel.transitive_closure_warshall()
        self.assertEqual(w.pairs(), [(0, 0), (0, 1), (1, 1)])


class TestEquivalenceClasses(unittest.TestCase):
    def test_mod3_partition(self):
        n = 9
        mod3 = R.Relation.from_pairs(n, pairs_of(n, lambda i, j: i % 3 == j % 3))
        self.assertTrue(mod3.is_equivalence())
        self.assertEqual(mod3.equivalence_classes(), [[0, 3, 6], [1, 4, 7], [2, 5, 8]])
        self.assertEqual(mod3.check_partition(), [])

    def test_refuses_non_equivalence(self):
        lt3 = R.Relation.from_pairs(3, pairs_of(3, lambda i, j: i < j))
        with self.assertRaises(R.RelationError) as ctx:
            lt3.reflexive_closure().equivalence_classes()   # ≤ 对称性不成立
        self.assertIn("不是等价关系", ctx.exception.reason)


class TestRelationErrors(unittest.TestCase):
    def test_from_pairs_bounds(self):
        with self.assertRaises(R.RelationError):
            R.Relation.from_pairs(3, [(0, 3)])
        with self.assertRaises(R.RelationError):
            R.Relation.from_pairs(3, [(-1, 0)])

    def test_matrix_shape(self):
        with self.assertRaises(R.RelationError):
            R.Relation([[True, False], [True]])
        with self.assertRaises(R.RelationError):
            R.Relation([])


if __name__ == "__main__":
    unittest.main()
