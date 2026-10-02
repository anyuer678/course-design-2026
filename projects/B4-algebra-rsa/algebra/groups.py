"""algebra/groups.py —— 群运算表（Cayley 表）的判定器

课程要点（近世代数 / 群论初步）：
    - 一个二元运算 + 一张表，"是不是群"要**逐条对定义**：封闭、结合、单位元、逆元；
      判定器把四条全查、能查多少查多少，并给出**反例**（不满足的那一格/那一组三元）——
      和 B13 的"全量错误收集"同一条纪律：拒绝要带着原因拒绝；
    - 结合律是 O(n3) 的三重循环——n=8 也要 512 次检查，演示里把次数打出来；
      单位元与逆元都依赖表内的元素**编号**（元素 i 的逆是表中使 i·j = e 的 j）；
    - `mul_units_table(n)` 生成 Z_n 的乘法单位群（与 n 互素的剩余类）：这是"最便宜的群例子工厂"——
      判定器直接在它上面拿真群来验（包括 Z_8* 同构 Klein 四元群这种教材常客）；
    - 本模块只做**有限二元运算表**的判定；子群/生成元/同态属 PLAN 选做项，没做。

约定：表 `table[i][j]` 的值是**元素编号**（0..n-1），元素本身的名字由调用方维护
（例如 Z_n 的单位群把"编号 k <-> 数值 elements[k]"映射交给返回值）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from algebra.numbertheory import gcd


@dataclass
class GroupReport:
    """四条定义的逐条结果 + 反例。`ok` 只在四条全过时为真。"""
    n: int
    closure_missing: list[tuple[int, int, int]] = field(default_factory=list)
    assoc_ok: bool = False
    assoc_witness: tuple[int, int, int, int, int] | None = None   # (i,j,k, 左, 右)
    identity_candidates: list[int] = field(default_factory=list)
    inverses_missing: list[int] = field(default_factory=list)

    @property
    def closure_ok(self) -> bool:
        return not self.closure_missing

    @property
    def identity(self) -> int | None:
        return self.identity_candidates[0] if self.identity_candidates else None

    @property
    def inverses_ok(self) -> bool:
        return not self.inverses_missing

    @property
    def ok(self) -> bool:
        return (self.closure_ok and self.assoc_ok and self.identity is not None
                and self.inverses_ok)

    def explain(self) -> list[str]:
        """把判定变成人话（演示与测试共用同一套理由文本）。"""
        lines: list[str] = []
        if self.closure_missing:
            i, j, v = self.closure_missing[0]
            lines.append(f"不封闭：{len(self.closure_missing)} 处越界，例如 [{i}][{j}]={v}")
        if not self.assoc_ok:
            if self.assoc_witness:
                i, j, k, left, right = self.assoc_witness
                lines.append(f"不结合：（{i}·{j}）·{k}={left}，而 {i}·（{j}·{k}）={right}")
            else:
                lines.append("不结合（封闭性不满足，未能查完）")
        if self.identity is None:
            lines.append(f"没有单位元（检查过 {self.n} 个候选）")
        elif len(self.identity_candidates) > 1:
            lines.append(f"单位元不唯一：{self.identity_candidates}（这本身就是病态信号）")
        if self.inverses_missing:
            lines.append(f"缺逆元：元素 {self.inverses_missing}")
        if not lines:
            lines.append(f"是群（{self.n} 个元素；结合律检查 {self.n ** 3} 组三元）")
        return lines


def check_group(table: list[list[int]]) -> GroupReport:
    """逐条判定：封闭 → 结合 → 单位元 → 逆元（后者依赖前者，逐级做）。"""
    n = len(table)
    if n == 0 or any(len(row) != n for row in table):
        raise ValueError("运算表必须是非空方阵")
    report = GroupReport(n=n)

    # 1) 封闭：每个格子都是合法元素编号
    for i in range(n):
        for j in range(n):
            if not 0 <= table[i][j] < n:
                report.closure_missing.append((i, j, table[i][j]))

    # 2) 结合：全查 n3 组，第一组反例就记下（继续查完没有意义，但如果封闭失败没法查）
    if report.closure_ok:
        report.assoc_ok = True
        for i in range(n):
            for j in range(n):
                ij = table[i][j]
                for k in range(n):
                    left = table[ij][k]
                    right = table[i][table[j][k]]
                    if left != right:
                        report.assoc_ok = False
                        report.assoc_witness = (i, j, k, left, right)
                        break
                if not report.assoc_ok:
                    break
            if not report.assoc_ok:
                break

    # 3) 单位元：两侧都要吸收所有元素
    if report.closure_ok:
        for e in range(n):
            if all(table[e][i] == i and table[i][e] == i for i in range(n)):
                report.identity_candidates.append(e)

    # 4) 逆元：以（第一个）单位元为准
    e = report.identity
    if e is not None:
        for i in range(n):
            has_inverse = any(table[i][j] == e and table[j][i] == e for j in range(n))
            if not has_inverse:
                report.inverses_missing.append(i)

    return report


def is_group(table: list[list[int]]) -> bool:
    return check_group(table).ok


def is_abelian(table: list[list[int]]) -> bool:
    """交换律：n2 次检查（交换群 = 阿贝尔群；群不一定交换，Z_8* 恰好交换）。"""
    n = len(table)
    return all(table[i][j] == table[j][i] for i in range(n) for j in range(n))


def abelian_witness(table: list[list[int]]) -> tuple[int, int, int, int] | None:
    """交换律的第一处反例 (i, j, i·j, j·i)，供演示打印。"""
    n = len(table)
    for i in range(n):
        for j in range(n):
            if table[i][j] != table[j][i]:
                return (i, j, table[i][j], table[j][i])
    return None


# ---------------------------------------------------------------- 例子工厂

def add_table(n: int) -> tuple[list[int], list[list[int]]]:
    """Z_n 加法表：任意 n ≥ 1 都是（交换）群——"最便宜的群"。"""
    if n < 1:
        raise ValueError(f"n 必须 ≥ 1：{n}")
    labels = list(range(n))
    table = [[(i + j) % n for j in range(n)] for i in range(n)]
    return labels, table


def mul_units_table(n: int) -> tuple[list[int], list[list[int]]]:
    """Z_n 的乘法单位群：元素是与 n 互素的剩余类，运算是模 n 乘法。

    n=8 → 单位 {1,3,5,7}（Klein 四元群：非循环的阿贝尔群，教材常客）。
    n < 2 时单位集合为空，构不成群——直接抛错而不是给张空表。
    """
    if n < 2:
        raise ValueError(f"n 必须 ≥ 2：{n}")
    units = [k for k in range(1, n) if gcd(k, n) == 1]
    index = {v: i for i, v in enumerate(units)}
    table = [[index[(a * b) % n] for b in units] for a in units]
    return units, table
