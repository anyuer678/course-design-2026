"""ml/knn.py —— K 近邻（惰性学习：没有训练过程，"记住"就是全部训练）

课程要点：
    - 距离度量决定"相似"的含义（这里用欧氏距离）
    - k 的取舍：k=1 过拟合噪声，k 太大欠拟合（被多数类淹没）
    - 投票平局必须有确定性规则——这里按"平局类中最近样本的总距离"破平局
    - 惰性学习的代价：预测 O(n·d)，每次都要扫全库（本实现的教学版）；
      加速结构（KD-tree/球树/LSH）是进阶方向

注意两件容易做错的事：
    - 预测前先标准化（否则大尺度特征支配距离）——标准化在 data.py 统一做
    - k=1 时训练集自身是最近邻（距离 0），"训练准确率恒 100%"是定义使然，
      不是模型好
"""
from __future__ import annotations

import math
from collections import Counter


def euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


class KNN:
    def __init__(self, k: int = 3):
        if k < 1:
            raise ValueError("k >= 1")
        self.k = k
        self._X: list[list[float]] = []
        self._y: list = []

    def fit(self, X: list[list[float]], y: list) -> "KNN":
        self._X = [row[:] for row in X]
        self._y = list(y)
        return self

    def kneighbors(self, x: list[float]) -> list[tuple[float, object]]:
        """全部训练点按距离升序（平距按插入序），返回 (距离, 标签) 列表。
        与"先算距离表再 sort"的朴素参照实现结果必须一致（见测试）。"""
        pairs = [(euclidean(x, row), i) for i, row in enumerate(self._X)]
        pairs.sort(key=lambda p: (p[0], p[1]))     # 平距稳定：下标小者在前
        return [(d, self._y[i]) for d, i in pairs[:self.k]]

    def predict_one(self, x: list[float]):
        neighbors = self.kneighbors(x)
        votes = Counter(label for _, label in neighbors)
        if len(votes) == 1:
            return votes.most_common(1)[0][0]
        top = max(votes.values())
        tied = [c for c, n in votes.items() if n == top]
        if len(tied) == 1:
            return tied[0]
        # 平局破法：比较各类在 k 邻居中的累计距离，总距离小者胜（确定性）
        dist_sum = {c: 0.0 for c in tied}
        for d, label in neighbors:
            if label in dist_sum:
                dist_sum[label] += d
        return min(tied, key=lambda c: dist_sum[c])

    def predict(self, X: list[list[float]]) -> list:
        return [self.predict_one(x) for x in X]
