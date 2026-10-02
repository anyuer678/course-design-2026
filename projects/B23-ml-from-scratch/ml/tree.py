"""ml/tree.py —— 决策树（CART 风格的二叉树，支持熵/基尼两种不纯度）

课程要点：
    - 不纯度：熵 H = -Σp·log2(p)；基尼 G = 1 - Σp²
    - 信息增益 = 父不纯度 - 加权子不纯度；树"贪心"地选增益最大的分裂
    - 连续特征：候选阈值取相邻值的中点——这是与教材离散版最大的不同
    - 贪心 ≠ 最优：每步局部最优，不保证全局最优树（NP-hard，所以贪心）
    - 停止条件：max_depth / min_samples / 纯节点——三者都在防过拟合

可复现性约定：增益平局时选 (特征下标, 阈值) 字典序最小的一组——
没有这条规则，同一份数据两次训练可能长出两棵树，实验不可对拍。
"""
from __future__ import annotations

import math


def entropy(labels: list) -> float:
    n = len(labels)
    if n == 0:
        return 0.0
    counts: dict = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def gini(labels: list) -> float:
    n = len(labels)
    if n == 0:
        return 0.0
    counts: dict = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    return 1.0 - sum((c / n) ** 2 for c in counts.values())


class _Node:
    __slots__ = ("feature", "threshold", "left", "right", "majority", "proba")

    def __init__(self, majority, proba):
        self.feature: int | None = None       # None = 叶子
        self.threshold: float = 0.0
        self.left = None
        self.right = None
        self.majority = majority
        self.proba = proba                    # 叶子内的类分布


class DecisionTree:
    def __init__(self, criterion: str = "entropy", max_depth: int = 4,
                 min_samples: int = 2):
        if criterion not in ("entropy", "gini"):
            raise ValueError("criterion 是 entropy 或 gini")
        self.criterion = criterion
        self.max_depth = max_depth
        self.min_samples = min_samples
        self.root_: _Node | None = None
        self.n_features_ = 0

    def _impurity(self, labels: list) -> float:
        return entropy(labels) if self.criterion == "entropy" else gini(labels)

    def _best_split(self, X, y):
        """穷举所有 (特征, 中点阈值)，返回 (增益, 特征, 阈值)。
        平局取字典序最小——可复现性的关键约定。"""
        n = len(y)
        parent = self._impurity(y)
        best_gain, best_f, best_t = -1.0, None, None
        for f in range(self.n_features_):
            values = sorted({row[f] for row in X})
            for a, b in zip(values, values[1:]):
                t = (a + b) / 2
                left = [lab for row, lab in zip(X, y) if row[f] <= t]
                right = [lab for row, lab in zip(X, y) if row[f] > t]
                gain = parent - (len(left) * self._impurity(left)
                                 + len(right) * self._impurity(right)) / n
                if gain > best_gain + 1e-12:          # 严格更优才替换（平局保先到者）
                    best_gain, best_f, best_t = gain, f, t
        return best_gain, best_f, best_t

    def _build(self, X, y, depth: int) -> _Node:
        counts: dict = {}
        for lab in y:
            counts[lab] = counts.get(lab, 0) + 1
        majority = max(counts, key=lambda c: (counts[c], -ord(str(c)[0])))
        proba = {c: n / len(y) for c, n in counts.items()}
        node = _Node(majority, proba)

        if (depth >= self.max_depth or len(y) < self.min_samples
                or len(counts) == 1):
            return node                               # 叶子：停止条件之一触发
        _, feature, threshold = self._best_split(X, y)
        if feature is None:
            return node
        # 注意：增益为 0 也照样分裂！XOR 在根节点上任何单次分裂的增益
        # 都是 0，"零增益即停"会让贪心树永远学不会 XOR——只要节点不纯，
        # 就继续尝试（max_depth / min_samples 兜底防过拟合）。
        left_idx = [i for i, row in enumerate(X) if row[feature] <= threshold]
        right_idx = [i for i, row in enumerate(X) if row[feature] > threshold]
        node.feature, node.threshold = feature, threshold
        node.left = self._build([X[i] for i in left_idx], [y[i] for i in left_idx],
                                depth + 1)
        node.right = self._build([X[i] for i in right_idx], [y[i] for i in right_idx],
                                 depth + 1)
        return node

    def fit(self, X: list[list[float]], y: list) -> "DecisionTree":
        self.n_features_ = len(X[0])
        self.root_ = self._build(X, y, 0)
        return self

    def _walk(self, x: list[float]) -> _Node:
        node = self.root_
        while node.feature is not None:               # 内部节点：沿分裂下走
            node = node.left if x[node.feature] <= node.threshold else node.right
        return node

    def predict_one(self, x: list[float]):
        return self._walk(x).majority

    def predict(self, X: list[list[float]]) -> list:
        return [self.predict_one(x) for x in X]

    def predict_proba_one(self, x: list[float]) -> dict:
        return self._walk(x).proba
