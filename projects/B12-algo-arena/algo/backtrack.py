"""algo/backtrack.py —— 回溯：N 皇后。

**搜索树**：按行往下放，第 r 行选一个列 c。剪枝条件是这一列、两条对角线都还没被占。

**递归不变式**：进入 `search(r)` 时，前 r 行已经放好且两两不互相攻击，
`cols / diag_a / diag_b` 恰好是这些棋子占用的列与对角线集合。
所以任何被这三个集合挡住的 c 都一定与某个已放的棋子冲突，而被剪掉的整棵子树
不会有合法解——这是"剪枝不丢解"的全部依据。

**对角线编号**：同一条主对角线上 ``r - c`` 相同，同一条副对角线上 ``r + c`` 相同。
写反成 ``r + c`` / ``r - c`` 会让同一行的两个格子看起来"冲突"，解数会莫名其妙变少。

**撤销必须与放置严格成对**，且顺序相反：先加后删。少删一个元素，
下一层就会看见上一层还在的占用，表现为"解变少"，最难查。
"""
from __future__ import annotations

from itertools import permutations

# 教材与 OEIS A000147：n 皇后在 n×n 棋盘上的摆法数
KNOWN_COUNTS = {1: 1, 2: 0, 3: 0, 4: 2, 5: 10, 6: 4, 7: 40, 8: 92, 9: 352}


def solve_n_queens(n: int):
    """返回所有解，每个解是长度为 n 的元组：第 r 行放在 solution[r] 列。"""
    if n < 0:
        raise ValueError(f"棋盘边长不能为负：{n}")
    solutions = []
    placement = []
    cols, diag_a, diag_b = set(), set(), set()

    def search(row: int) -> None:
        if row == n:
            solutions.append(tuple(placement))
            return
        for col in range(n):
            if col in cols or row - col in diag_a or row + col in diag_b:
                continue
            cols.add(col); diag_a.add(row - col); diag_b.add(row + col)
            placement.append(col)
            search(row + 1)
            placement.pop()
            cols.discard(col); diag_a.discard(row - col); diag_b.discard(row + col)

    search(0)
    return solutions


def count_n_queens(n: int) -> int:
    """位运算版计数：三个整数当三个集合用，规模上比集合版快一个量级。"""
    if n < 0:
        raise ValueError(f"棋盘边长不能为负：{n}")
    if n == 0:
        return 1
    full = (1 << n) - 1
    total = 0

    def search(rows: int, cols: int, left: int, right: int) -> None:
        nonlocal total
        if rows == full:
            total += 1
            return
        blocked = cols | left | right
        available = full & ~blocked
        while available:
            bit = available & -available            # 最低位的可放列
            available ^= bit
            search(rows | bit, cols | bit,
                   (left | bit) << 1 & full, (right | bit) >> 1)

    search(0, 0, 0, 0)
    return total


def count_by_permutations(n: int) -> int:
    """参照实现：n 个皇后不同行不同列 ⟺ 一个排列，只剩检查对角线。

    O(n!) 但没有集合操作，规模上限到 8 左右；用它交叉验证上面两个实现。
    """
    count = 0
    for perm in permutations(range(n)):
        diag_a = set()
        diag_b = set()
        for row, col in enumerate(perm):
            diag_a.add(row - col)
            diag_b.add(row + col)
        if len(diag_a) == n and len(diag_b) == n:
            count += 1
    return count


def is_solution(n: int, placement) -> bool:
    """独立校验一个解（不复用搜索逻辑）：不重复列、不共对角线、行数正确。"""
    if len(placement) != n or sorted(placement) != list(range(n)):
        return False
    diag_a = {row - col for row, col in enumerate(placement)}
    diag_b = {row + col for row, col in enumerate(placement)}
    return len(diag_a) == n and len(diag_b) == n
