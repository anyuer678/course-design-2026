"""algebra/sets.py —— 集合论小工具：运算、幂集、笛卡尔积、函数性质、容斥

课程要点（集合论）：
    - 有限集合的一切都能**穷举核对**：幂集大小 = 2n、笛卡尔积大小 = |A|·|B|、
      容斥公式算出的并集大小必须等于"真的把元素并起来数一遍"——公式不是背的，是对出来的；
    - 函数的三档性质（单射/满射/双射）判定的全定义域扫描：把"每个输入恰好一个输出、
      不同输入不同输出、值域覆盖陪域"写成可执行的三段；
    - 有限集合用 frozenset 表示（可哈希、无重复、天然去重），与 Python 的 set 语义同源，
      但比较一律用我们的函数（教学：不要借语言内置把定理省掉）。
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations


def union(a: frozenset, b: frozenset) -> frozenset:
    return frozenset(a | b)


def intersection(a: frozenset, b: frozenset) -> frozenset:
    return frozenset(a & b)


def difference(a: frozenset, b: frozenset) -> frozenset:
    return frozenset(a - b)


def symmetric_difference(a: frozenset, b: frozenset) -> frozenset:
    return frozenset(a ^ b)


def power_set(s: frozenset) -> list[frozenset]:
    """幂集：对元素列表做 0..2n-1 的位枚举（顺序确定：先短后长、字典序内层）。"""
    items = sorted(s)
    result = []
    for size in range(len(items) + 1):
        for combo in combinations(items, size):
            result.append(frozenset(combo))
    return result


def cartesian(a: frozenset, b: frozenset) -> frozenset:
    """笛卡尔积 A×B：|A×B| = |A|·|B| 由测试对账。"""
    return frozenset((x, y) for x in sorted(a) for y in sorted(b))


def inclusion_exclusion(sets: list[frozenset]) -> int:
    """容斥原理的**一般形式**：|∪Ai| = Σ(-1)^(k+1)·|∩ 选中的 k 个|。

    逐个非空子集下标集合算交集——这是"逐项公式"与"穷举并集"对拍的标的。
    """
    total = 0
    for k in range(1, len(sets) + 1):
        sign = 1 if k % 2 == 1 else -1
        for combo in combinations(range(len(sets)), k):
            inter = sets[combo[0]]
            for idx in combo[1:]:
                inter = inter & sets[idx]
            total += sign * len(inter)
    return total


@dataclass
class FunctionReport:
    """函数三档性质 + 反例（教学：拒绝也要带原因）。"""
    is_function: bool
    injective: bool | None = None
    surjective: bool | None = None
    reasons: list[str] = None            # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = []

    @property
    def bijective(self) -> bool:
        return bool(self.is_function and self.injective and self.surjective)


def check_function(pairs: set[tuple], domain: frozenset, codomain: frozenset) -> FunctionReport:
    """判定 pairs 是不是函数（要求每个对都取自 D×C，且每个输入恰一个输出），并继续判单射/满射。

    三类"不是函数"的情形分开报：输入无定义、输入多输出、取值超出陪域。
    """
    report = FunctionReport(is_function=True)
    images: dict = {}
    missing: list = []
    extra: list = []
    for x in sorted(domain):
        outs = [y for (a, y) in pairs if a == x]
        if not outs:
            missing.append(x)
        elif len(outs) > 1:
            report.is_function = False
            report.reasons.append(f"输入 {x} 对应多个输出 {outs}")
        else:
            images[x] = outs[0]
    if missing:
        report.is_function = False
        report.reasons.append(f"定义域上无定义：{missing}")
    for (x, y) in sorted(pairs):
        if x not in domain or y not in codomain:
            extra.append((x, y))
    if extra:
        report.is_function = False
        report.reasons.append(f"有不在 D×C 内的对：{extra}")
    if not report.is_function:
        return report

    # 单射：不同输入不同输出
    seen: dict = {}
    report.injective = True
    for x, y in images.items():
        if y in seen:
            report.injective = False
            report.reasons.append(f"不单射：{seen[y]} 与 {x} 都映到 {y}")
            break
        seen[y] = x

    # 满射：值域盖住陪域
    report.surjective = set(images.values()) == set(codomain)
    if not report.surjective:
        missed = sorted(set(codomain) - set(images.values()))
        report.reasons.append(f"不满射：陪域里 {missed} 没有原像")
    if report.injective and report.surjective:
        report.reasons.append("是双射")
    return report
