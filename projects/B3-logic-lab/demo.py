"""demo.py —— B3 离散结构实验台五段演示。数字全部运行时现算，不抄文档。

  1) 词法与解析：优先级、右结合、出错位置的字符定位
  2) 真值表与主范式：2^n 行穷举；主析取/合取范式就是真值表的两半
  3) 语义等价：德摩根、逆否、变量并集比较
  4) 关系性质与闭包：整除偏序、自反闭包、环的传递闭包
  5) Warshall 与 BFS 对拍（固定种子）+ 等价类划分校验

本演示不依赖任何第三方库；关系对拍用固定种子，两遍运行输出应逐字一致，
可用 `python demo.py > a.txt` 跑两遍 diff 自证。
"""
from __future__ import annotations

import itertools
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from logic3 import formula as F          # noqa: E402
from logic3 import truth as T            # noqa: E402
from logic3 import relation as R         # noqa: E402

LINE = "=" * 78


def section(no: int, title: str) -> None:
    print(f"\n{LINE}\n  {no}) {title}\n{LINE}")


def show(label: str, value: object) -> None:
    print(f"  {label:<30}{value}")


def main() -> int:
    print("B3 离散结构实验台 —— 命题逻辑（解析/真值表/主范式）+ 二元关系（闭包/划分）")

    # ------------------------------------------------------------------ 1
    section(1, "词法与解析：两字符运算符、右结合、出错定位")
    text = "~(p & q) | r -> p <=> q"
    show("输入", text)
    show("词法结果", F.tokenize(text))
    show("结构还原（括号即树形）", F.render(F.parse(text)))
    show("p -> q -> r 读作", F.render(F.parse("p -> q -> r")))
    witness = {"p": False, "q": False, "r": False}
    show("全假赋值下 p->q->r", F.evaluate(F.parse("p -> q -> r"), witness))
    print("   （左结合 ((p->q)->r) 在此赋值下会算成假，故上行是右结合的见证）")
    for bad in ("p @ q", "(p & q", "p q"):
        try:
            F.parse(bad)
        except F.FormulaError as err:
            show(f"坏输入 {bad!r}", str(err))

    # ------------------------------------------------------------------ 2
    section(2, "真值表与主范式：穷举 2^n 行，范式 = 表的两半")
    node = F.parse("p -> (q & r)")
    for line in T.format_table(node):
        print("   " + line)
    n = len(F.variables(node))
    mi, ma = T.minterms(node), T.maxterms(node)
    show(f"{len(F.variables(node))} 个变量共 {2 ** n} 行", f"真行 {len(mi)} 条，假行 {len(ma)} 条")
    show("极小项（=真行号）", mi)
    show("极大项（=假行号）", ma)
    show("主析取范式", T.to_dnf(node))
    show("主合取范式", T.to_cnf(node))
    rt_d = T.equivalent(F.parse(T.to_dnf(node)), node)
    rt_c = T.equivalent(F.parse(T.to_cnf(node)), node)
    show("回代验证（解析器吃自己的输出）", f"析取 {rt_d}，合取 {rt_c}")

    # ------------------------------------------------------------------ 3
    section(3, "语义等价：德摩根、逆否、变量并集")
    pairs = [("~(p & q)", "~p | ~q"), ("p -> q", "~q -> ~p"),
             ("p | q", "~(~p & ~q)"), ("~(p & q)", "~p & ~q")]
    for left, right in pairs:
        a, b = F.parse(left), F.parse(right)
        names = sorted(set(F.variables(a)) | set(F.variables(b)))
        rows = 2 ** len(names)
        same = sum(1 for bits in itertools.product((False, True), repeat=len(names))
                   if F.evaluate(a, dict(zip(names, bits))) == F.evaluate(b, dict(zip(names, bits))))
        verdict = "等价" if T.equivalent(a, b) else "不等价"
        show(f"{left}  vs  {right}", f"{verdict}（{rows} 行中 {same} 行一致）")
    a, b = F.parse("~(p & q)"), F.parse("~p & ~q")
    diff = next(bits for bits in [(x, y) for x in (False, True) for y in (False, True)]
                if F.evaluate(a, dict(zip("pq", bits))) != F.evaluate(b, dict(zip("pq", bits))))
    show("一个分歧赋值（p,q）", f"{diff} 处两式取值不同")

    # ------------------------------------------------------------------ 4
    section(4, "关系性质与闭包：整除偏序、自反闭包、环的闭包")
    k = 6
    div = R.Relation.from_pairs(k, [(i, j) for i in range(k) for j in range(k)
                                    if (j + 1) % (i + 1) == 0])
    show(f"{{1..{k}}} 上的整除关系边数", len(div.pairs()))
    show("自反 / 反对称 / 传递", f"{div.is_reflexive()} / "
                                 f"{div.is_antisymmetric()} / {div.is_transitive()}")
    show("是偏序（不是等价）", f"{div.is_partial_order()} / {div.is_equivalence()}")
    lt = R.Relation.from_pairs(4, [(i, j) for i in range(4) for j in range(4) if i < j])
    le = lt.reflexive_closure()
    show("严格序 < 的自反闭包 ≤", f"自反 {le.is_reflexive()}，偏序 {le.is_partial_order()}")
    show("≤ 的点对（n=4）", le.pairs())
    cyc = R.Relation.from_pairs(3, [(0, 1), (1, 2), (2, 0)])
    w = cyc.transitive_closure_warshall()
    show("环 0->1->2->0 的传递闭包边数", len(w.pairs()))
    show("闭包是等价关系", f"{w.is_equivalence()}，类 {w.equivalence_classes()}")

    # ------------------------------------------------------------------ 5
    section(5, "Warshall 与 BFS 对拍（固定种子）+ 等价类划分")
    rng = random.Random(20261002)
    n5 = 6
    density = 0.35
    matrix = [[rng.random() < density for _ in range(n5)] for _ in range(n5)]
    rel = R.Relation(matrix)
    wm = rel.transitive_closure_warshall()
    bm = rel.transitive_closure_bfs()
    cells = n5 * n5
    same_cells = sum(1 for i in range(n5) for j in range(n5) if wm.m[i][j] == bm.m[i][j])
    show(f"随机关系 n={n5} 密度≈{density}（种子固定）", f"原边 {len(rel.pairs())} 条")
    show("Warshall vs BFS 逐格比较", f"{same_cells}/{cells} 格一致，闭包边 {len(wm.pairs())} 条")
    show("闭包自身满足传递性", wm.is_transitive())
    mod3 = R.Relation.from_pairs(9, [(i, j) for i in range(9) for j in range(9)
                                     if i % 3 == j % 3])
    show("同余 mod 3（0..8）的等价类", mod3.equivalence_classes())
    show("划分校验（覆盖 + 两两不交）", mod3.check_partition() or "通过")
    try:
        le.equivalence_classes()
    except R.RelationError as err:
        show("对非等价关系求等价类", f"拒绝：{err.reason}")

    print("\n" + LINE)
    print("完成：5 段演示全部跑通。本演示无随机数（对拍种子固定），两遍输出应逐字一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
