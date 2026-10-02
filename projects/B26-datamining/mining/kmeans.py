"""mining/kmeans.py —— K-means 聚类 + 轮廓系数（纯标准库）

课程要点：
    - 目标函数是**惯性**（各点到所属中心的平方距离之和）；Lloyd 迭代
      （分配 -> 重算中心）保证每步惯性不增，但只收敛到局部最优——
      初始化决定落进哪个坑，所以必须固定种子。
    - **空簇处理是实现决策**：某中心一个点都没分到时，本实现把
      "离自己中心最远的那个点"移过去（确定性规则）；也有随机重 seeding
      或直接删簇的流派，取舍要写清楚。
    - 轮廓系数 s = (b−a)/max(a,b)：a = 到同簇其他点的平均距离，
      b = 到最近他簇各点的平均距离。s 接近 1 说明"簇内紧、簇间远"。
      单点簇的 s 约定为 0。
"""
from __future__ import annotations

import math
import random


def euclidean(a, b) -> float:
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def _dist2(a, b) -> float:
    return sum((ai - bi) ** 2 for ai, bi in zip(a, b))


class KMeans:
    def __init__(self, k: int, seed: int = 0, max_iters: int = 100):
        if k < 1:
            raise ValueError("k >= 1")
        self.k = k
        self.seed = seed
        self.max_iters = max_iters
        self.centroids_: list = []
        self.labels_: list[int] = []
        self.inertia_: float = 0.0
        self.iterations_: int = 0
        self.empty_cluster_events_ = 0            # 空簇发生过几次（可观测）

    def fit(self, X: list[list[float]]) -> "KMeans":
        if len(X) < self.k:
            raise ValueError(f"样本数 {len(X)} 少于簇数 {self.k}")
        distinct = {tuple(row) for row in X}
        if len(distinct) < self.k:
            raise ValueError(f"不同数据点只有 {len(distinct)} 个，无法取 {self.k} 个不同中心")

        rng = random.Random(self.seed)
        # 初始中心 = k 个互不相同的数据点（种子化）；k-means++ 列为扩展
        picked: list[tuple] = []
        while len(picked) < self.k:
            cand = tuple(X[rng.randrange(len(X))])
            if cand not in picked:
                picked.append(cand)
        centroids = [list(c) for c in picked]

        labels = [-1] * len(X)
        for it in range(1, self.max_iters + 1):
            self.iterations_ = it
            # ---- 分配：最近中心；平局取下标最小者（确定性）----
            new_labels = []
            for x in X:
                best, best_d2 = 0, _dist2(x, centroids[0])
                for j in range(1, self.k):
                    d2 = _dist2(x, centroids[j])
                    if d2 < best_d2:
                        best, best_d2 = j, d2
                new_labels.append(best)

            # ---- 空簇：把"离所属中心最远的点"移给空簇 ----
            for j in range(self.k):
                if j not in new_labels:
                    self.empty_cluster_events_ += 1
                    far_i = max(range(len(X)),
                                key=lambda i: _dist2(X[i], centroids[new_labels[i]]))
                    new_labels[far_i] = j

            # ---- 重算中心 ----
            new_centroids = []
            for j in range(self.k):
                members = [X[i] for i in range(len(X)) if new_labels[i] == j]
                dim = len(members[0])
                new_centroids.append([sum(m[d] for m in members) / len(members)
                                      for d in range(dim)])

            if new_labels == labels and new_centroids == centroids:
                break                              # 分配与中心都不再变化
            labels = new_labels
            centroids = new_centroids

        self.labels_ = labels
        self.centroids_ = centroids
        self.inertia_ = sum(_dist2(x, centroids[labels[i]])
                            for i, x in enumerate(X))
        return self

    def predict_one(self, x: list[float]) -> int:
        best, best_d2 = 0, _dist2(x, self.centroids_[0])
        for j in range(1, self.k):
            d2 = _dist2(x, self.centroids_[j])
            if d2 < best_d2:
                best, best_d2 = j, d2
        return best


def inertia_of(X: list[list[float]]) -> float:
    """对给定数据求"到均值的平方距离之和"（k=1 时的惯性，测试对拍用）。"""
    dim = len(X[0])
    mean = [sum(row[d] for row in X) / len(X) for d in range(dim)]
    return sum(_dist2(row, mean) for row in X)


def silhouette(X: list[list[float]], labels: list[int]) -> float:
    """平均轮廓系数。单点簇 s=0；只有一个簇时返回 0（无聚类结构可言）。"""
    n = len(X)
    clusters = sorted(set(labels))
    if len(clusters) < 2:
        return 0.0
    total = 0.0
    for i in range(n):
        same = [j for j in range(n) if labels[j] == labels[i] and j != i]
        if not same:
            total += 0.0                        # 单点簇约定
            continue
        a = sum(euclidean(X[i], X[j]) for j in same) / len(same)
        b = math.inf
        for c in clusters:
            if c == labels[i]:
                continue
            others = [j for j in range(n) if labels[j] == c]
            b = min(b, sum(euclidean(X[i], X[j]) for j in others) / len(others))
        total += (b - a) / max(a, b)
    return total / n
