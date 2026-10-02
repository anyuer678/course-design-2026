"""logic3/relation.py —— 二元关系：性质判定、闭包、Warshall、等价类 / 偏序

课程要点（离散结构：关系）：
    - 关系就是**关系矩阵**：性质判定全是矩阵上的一行定义（自反看对角线、对称看转置、
      传递看 R∘R ⊆ R）。判定与定义一一对应，才能解释"为什么是 n² / n³"；
    - **Warshall 是动态规划**：k 作中间点逐轮放宽，O(n³)；它算的是可达性（传递闭包）。
      独立参照是"对每个点做一次 BFS"，两者必须逐格一致——测试里就这么对拍；
    - 闭包有套路：自反闭包 = 加对角线，对称闭包 = R ∪ Rᵀ，传递闭包交给 Warshall；
    - 等价关系 = 自反 + 对称 + 传递 ⇒ 可以按类划分（划分要覆盖全集且两两不交）；
      偏序 = 自反 + 反对称 + 传递 ⇒ 可拓扑（本项目只做判定与类划分，拓扑留给 B27）。
"""
from __future__ import annotations

from collections import deque


class RelationError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Relation:
    """{0..n-1} 上的关系，用 0/1 布尔矩阵表示（`matrix[i][j]` 为真表示 i R j）。"""

    def __init__(self, matrix: list[list[bool]]):
        n = len(matrix)
        if n == 0:
            raise RelationError("空关系")
        for row in matrix:
            if len(row) != n:
                raise RelationError("关系矩阵必须是方阵")
        self.n = n
        self.m = [[bool(x) for x in row] for row in matrix]

    # ---------------------------------------------------------------- 构造
    @classmethod
    def from_pairs(cls, n: int, pairs: list[tuple[int, int]]) -> "Relation":
        m = [[False] * n for _ in range(n)]
        for (i, j) in pairs:
            if not (0 <= i < n and 0 <= j < n):
                raise RelationError(f"点对越界：{(i, j)}（n={n}）")
            m[i][j] = True
        return cls(m)

    def pairs(self) -> list[tuple[int, int]]:
        return [(i, j) for i in range(self.n) for j in range(self.n) if self.m[i][j]]

    # ---------------------------------------------------------------- 性质
    def is_reflexive(self) -> bool:
        return all(self.m[i][i] for i in range(self.n))

    def is_irreflexive(self) -> bool:
        return not any(self.m[i][i] for i in range(self.n))

    def is_symmetric(self) -> bool:
        return all(self.m[i][j] == self.m[j][i]
                   for i in range(self.n) for j in range(self.n))

    def is_antisymmetric(self) -> bool:
        """反对称：i R j 且 j R i ⇒ i == j。**不是"不对称"**，对角线不受限（教材常见混淆点）。"""
        return all(i == j or not (self.m[i][j] and self.m[j][i])
                   for i in range(self.n) for j in range(self.n))

    def is_transitive(self) -> bool:
        """传递：i R j 且 j R k ⇒ i R k。三重循环 O(n³)，与定义字面一致。"""
        for i in range(self.n):
            for j in range(self.n):
                if not self.m[i][j]:
                    continue
                for k in range(self.n):
                    if self.m[j][k] and not self.m[i][k]:
                        return False
        return True

    # ---------------------------------------------------------------- 闭包
    def reflexive_closure(self) -> "Relation":
        return Relation([[self.m[i][j] or i == j for j in range(self.n)]
                         for i in range(self.n)])

    def symmetric_closure(self) -> "Relation":
        return Relation([[self.m[i][j] or self.m[j][i] for j in range(self.n)]
                         for i in range(self.n)])

    def transitive_closure_warshall(self) -> "Relation":
        """Warshall：k 作中间点逐轮放宽。注意初始化时**先补对角线**——
        教材的 Warshall 给出的是"可达性"，含自身；要不要含自身取决于语境，这里写死为"含"。"""
        reach = [[self.m[i][j] or i == j for j in range(self.n)]
                 for i in range(self.n)]
        for k in range(self.n):
            for i in range(self.n):
                if not reach[i][k]:
                    continue
                for j in range(self.n):
                    if reach[k][j]:
                        reach[i][j] = True
        return Relation(reach)

    def transitive_closure_bfs(self) -> "Relation":
        """独立参照：对每个起点做一次 BFS，能走到谁就标谁（含自身）。"""
        reach = [[False] * self.n for _ in range(self.n)]
        for start in range(self.n):
            reach[start][start] = True
            queue = deque([start])
            while queue:
                node = queue.popleft()
                for nxt in range(self.n):
                    if self.m[node][nxt] and not reach[start][nxt]:
                        reach[start][nxt] = True
                        queue.append(nxt)
        return Relation(reach)

    # ---------------------------------------------------------------- 结构
    def is_equivalence(self) -> bool:
        return self.is_reflexive() and self.is_symmetric() and self.is_transitive()

    def is_partial_order(self) -> bool:
        return self.is_reflexive() and self.is_antisymmetric() and self.is_transitive()

    def equivalence_classes(self) -> list[list[int]]:
        """等价关系的商集。判定不是等价关系时**拒绝**而不是硬算（不然出来的是错答案）。"""
        if not self.is_equivalence():
            raise RelationError("不是等价关系，不能划分等价类")
        seen = [False] * self.n
        classes = []
        for i in range(self.n):
            if seen[i]:
                continue
            cls = [j for j in range(self.n)
                   if self.m[i][j] and self.m[j][i]]
            for j in cls:
                seen[j] = True
            classes.append(sorted(cls))
        return sorted(classes)

    def check_partition(self) -> list[str]:
        """校验等价类是不是一个合法划分：覆盖 1..n-1 且两两不交。返回问题列表（空=合法）。"""
        classes = self.equivalence_classes()
        flat = [x for cls in classes for x in cls]
        problems = []
        if sorted(flat) != list(range(self.n)):
            problems.append(f"并集不是全集：{sorted(flat)}")
        if len(flat) != len(set(flat)):
            problems.append("有元素同时落在两个类里")
        return problems
