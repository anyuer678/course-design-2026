"""logic3/truth.py —— 真值表、主析取/合取范式、可满足性（全部由**穷举**给出，不靠化简）

课程要点：
    - 真值表是命题逻辑的**语义定义**：2^n 行枚举 + 按 AST 求值，一步捷径都不走；
    - 主析取范式（极小项之和）与主合取范式（极大项之积）**就是真值表的两半**：
      取值为 1 的行 = 极小项、取值为 0 的行 = 极大项。所谓"化主范式"不需要任何公式变形；
    - 小的序与编号全靠**变量的字典序**：第 i 位对应 vars[i]，`1` 取变量本身、`0` 取否定。
      顺序一变，编号就全变——所以 `variables()` 的排序是规范的一部分；
    - 可满足 / 重言 / 矛盾三者的判定 = 数极小项/极大项的个数（3 行代码，但含义要写清）。
"""
from __future__ import annotations

import itertools

from logic3 import formula as F


def truth_table(node: F.Node) -> dict:
    """返回 {"vars": [...], "rows": [((True, False, …), value), …]}，行序按变量的二进制计数。"""
    names = F.variables(node)
    rows = []
    for bits in itertools.product((False, True), repeat=len(names)):
        assignment = dict(zip(names, bits))
        rows.append((bits, F.evaluate(node, assignment)))
    return {"vars": names, "rows": rows}


def minterms(node: F.Node) -> list[int]:
    """取值为真的行号（= 极小项编号）。行号按**变量字典序**的二进制权重。"""
    table = truth_table(node)
    return [i for i, (_, value) in enumerate(table["rows"]) if value]


def maxterms(node: F.Node) -> list[int]:
    """取值为假的行号（= 极大项编号）。"""
    table = truth_table(node)
    return [i for i, (_, value) in enumerate(table["rows"]) if not value]


def to_dnf(node: F.Node) -> str:
    """主析取范式：每个极小项写成"变量或其否定的合取"，再全部用 | 连接。"""
    names = F.variables(node)
    if not names:                       # 常量公式没有极小项可言，直接给 0/1
        return "1" if F.evaluate(node, {}) else "0"
    parts = []
    for index in minterms(node):
        bits = [(index >> (len(names) - 1 - k)) & 1 for k in range(len(names))]
        literals = [f"{name}" if bit else f"~{name}" for name, bit in zip(names, bits)]
        parts.append("(" + " & ".join(literals) + ")")
    return " | ".join(parts) if parts else "0"          # 矛盾式


def to_cnf(node: F.Node) -> str:
    """主合取范式：每个极大项写成"变量或其否定的析取"，再全部用 & 连接。

    注意极大项的取反方向：**成真的行取变量本身、成假的行取变量的否定**——
    写反了会得到一个与原公式不等价的式子（测试里有专门一条盯着它）。
    """
    names = F.variables(node)
    if not names:
        return "1" if F.evaluate(node, {}) else "0"
    parts = []
    for index in maxterms(node):
        bits = [(index >> (len(names) - 1 - k)) & 1 for k in range(len(names))]
        literals = [f"~{name}" if bit else f"{name}" for name, bit in zip(names, bits)]
        parts.append("(" + " | ".join(literals) + ")")
    return " & ".join(parts) if parts else "1"          # 重言式


def is_tautology(node: F.Node) -> bool:
    return not maxterms(node)


def is_contradiction(node: F.Node) -> bool:
    return not minterms(node)


def is_satisfiable(node: F.Node) -> bool:
    return bool(minterms(node))


def equivalent(left: F.Node, right: F.Node) -> bool:
    """等价 = 对所有公共变量的赋值取值相同。变量集合不同时按**并集**补全再比。"""
    names = sorted(set(F.variables(left)) | set(F.variables(right)))
    for bits in itertools.product((False, True), repeat=len(names)):
        assignment = dict(zip(names, bits))
        if F.evaluate(left, assignment) != F.evaluate(right, assignment):
            return False
    return True


def assignment_of(index: int, names: list[str]) -> dict[str, bool]:
    """把行号还原成赋值（演示里打印"哪一行让它成真"时用）。"""
    bits = [(index >> (len(names) - 1 - k)) & 1 for k in range(len(names))]
    return dict(zip(names, (bool(b) for b in bits)))


def format_table(node: F.Node) -> list[str]:
    """真值表的可打印形态：变量列 + 结果列 + 行号（极小项编号）。"""
    table = truth_table(node)
    names = table["vars"]
    head = "  ".join(names + ["结果", "行号"])
    lines = [head]
    for i, (bits, value) in enumerate(table["rows"]):
        cells = ["1" if b else "0" for b in bits] + ["1" if value else "0", str(i)]
        lines.append("  ".join(cells))
    return lines
