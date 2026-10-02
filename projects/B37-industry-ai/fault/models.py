"""fault/models.py —— 两个概率分数的来源：手写逻辑回归 + B23 决策树

为什么需要逻辑回归（而不是直接用 B23 的感知机/树）：
    - 误报/漏报分析和阈值扫描要的是**连续概率分数**——感知机只有硬判别，
      树叶子概率的取值个数受叶子数限制；sigmoid 输出才是"告警预算"可调的前提。
    - B23 的练习第 3 条正是"实现逻辑回归并与感知机对比"——本项目把它补上，
      并沿用 B23 的纪律：**解析梯度必须与数值梯度对拍**；
      双实现（GD 与 Newton/IRLS）互拍权重，防止"唯一的实现等于没有参照"。

决策树 import 自 B23（不复制），分数取叶子内正类占比 predict_proba_one(x)[1]。
"""
from __future__ import annotations

import math

from ml.data import standardize                                 # 复用 B23（防泄漏标准化）
from ml.tree import DecisionTree                                # 复用 B23


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _forward(X: list[list[float]], w: list[float], b: float) -> list[float]:
    return [sigmoid(sum(wi * xi for wi, xi in zip(w, row)) + b) for row in X]


def cross_entropy(X: list[list[float]], y: list[int], w: list[float], b: float) -> float:
    """平均负对数似然（加 1e-12 防 log(0)）。"""
    p = _forward(X, w, b)
    n = len(y)
    return -sum(yi * math.log(pi + 1e-12) + (1 - yi) * math.log(1 - pi + 1e-12)
                for yi, pi in zip(y, p)) / n


def gradient(X: list[list[float]], y: list[int], w: list[float], b: float
             ) -> tuple[list[float], float]:
    """解析梯度（对平均 NLL）：dw = X^T(p-y)/n，db = mean(p-y)。"""
    p = _forward(X, w, b)
    n = len(y)
    d = len(w)
    gw = [0.0] * d
    for row, pi, yi in zip(X, p, y):
        diff = pi - yi
        for j in range(d):
            gw[j] += row[j] * diff
    gw = [v / n for v in gw]
    gb = sum(pi - yi for pi, yi in zip(p, y)) / n
    return gw, gb


def numeric_gradient(X: list[list[float]], y: list[int], w: list[float], b: float,
                     eps: float = 1e-6) -> tuple[list[float], float]:
    """中心差分数值梯度——解析梯度的**独立参照**（B23 同款纪律）。"""
    gw = []
    for j in range(len(w)):
        up = list(w); up[j] += eps
        dn = list(w); dn[j] -= eps
        gw.append((cross_entropy(X, y, up, b) - cross_entropy(X, y, dn, b)) / (2 * eps))
    gb = (cross_entropy(X, y, w, b + eps) - cross_entropy(X, y, w, b - eps)) / (2 * eps)
    return gw, gb


class LogisticRegression:
    """逻辑回归：同样的梯度下降与 Newton/IRLS 两套实现（互拍用）。"""

    def __init__(self, n_features: int):
        self.w = [0.0] * n_features
        self.b = 0.0

    # ---------------------------------------------------------------- 两套优化器
    def fit_gd(self, X: list[list[float]], y: list[int], lr: float, epochs: int,
               l2: float = 0.0):
        """带 L2 的梯度下降：目标 = NLL + λ/2 · ||w||^2（b 不惩罚）。"""
        for _ in range(epochs):
            gw, gb = gradient(X, y, self.w, self.b)
            gw = [gi + l2 * wi for gi, wi in zip(gw, self.w)]
            self.w = [wi - lr * gi for wi, gi in zip(self.w, gw)]
            self.b -= lr * gb
        return self

    def fit_newton(self, X: list[list[float]], y: list[int], iters: int, tol: float,
                   l2: float = 0.0):
        """IRLS：在增广矩阵 [X|1] 上做联合 Newton（H·δ = g，w,b ← w,b - δ）。"""
        d = len(self.w)
        Xa = [row + [1.0] for row in X]
        n = len(y)
        for _ in range(iters):
            p = _forward(X, self.w, self.b)
            H = [[0.0] * (d + 1) for _ in range(d + 1)]
            g = [0.0] * (d + 1)
            for rowa, pi, yi in zip(Xa, p, y):
                wi = pi * (1 - pi)
                diff = pi - yi
                for j in range(d + 1):
                    g[j] += rowa[j] * diff
                    for k in range(j, d + 1):
                        H[j][k] += rowa[j] * rowa[k] * wi
            for j in range(d + 1):
                for k in range(j):
                    H[j][k] = H[k][j]           # 对称化
                H[j][j] += 1e-9 * n             # 数值守卫（归一化后只剩 1e-9 量级）
                g[j] /= n
                for k in range(j, d + 1):
                    H[j][k] /= n
            for j in range(d):
                H[j][j] += l2                   # L2：Hessian 加 λI，梯度加 λw
                g[j] += l2 * self.w[j]
            delta = _solve(H, g)
            self.w = [wi - di for wi, di in zip(self.w, delta[:d])]
            self.b -= delta[d]
            if max(abs(v) for v in delta) < tol:
                break
        return self

    # ---------------------------------------------------------------- 预测
    def predict_proba(self, X: list[list[float]]) -> list[float]:
        return _forward(X, self.w, self.b)


def _solve(A: list[list[float]], bvec: list[float]) -> list[float]:
    """高斯消元（部分主元），解 A·x = b。特征维度 ≤ 十几，直接 O(d^3)。"""
    n = len(A)
    M = [row[:] + [bvec[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-14:
            raise ValueError("奇异矩阵，无法求解")
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            factor = M[r][col] / M[col][col]
            for c in range(col, n + 1):
                M[r][c] -= factor * M[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))
        x[i] = s / M[i][i]
    return x


def fit_two(Xtr: list[list[float]], Xte: list[list[float]], ytr: list[int],
            cfg) -> dict:
    """标准化（只信训练集统计量）后训练两套 LR；返回权重/测试分数/权重差。"""
    tr_std, te_std = standardize(Xtr, Xte)
    lr_gd = LogisticRegression(len(tr_std[0])).fit_gd(tr_std, ytr, cfg.gd_lr,
                                                      cfg.gd_epochs, cfg.l2)
    lr_newton = LogisticRegression(len(tr_std[0])).fit_newton(tr_std, ytr,
                                                              cfg.newt_iters, cfg.newt_tol,
                                                              cfg.l2)
    max_gap = max([abs(a - b) for a, b in zip(lr_gd.w, lr_newton.w)] + [abs(lr_gd.b - lr_newton.b)])
    return {"gd": lr_gd, "newton": lr_newton,
            "scores_gd": lr_gd.predict_proba(te_std),
            "scores_newton": lr_newton.predict_proba(te_std),
            "max_weight_gap": max_gap}


def fit_tree(Xtr: list[list[float]], ytr: list[int], cfg) -> DecisionTree:
    tree = DecisionTree(criterion="entropy", max_depth=cfg.tree_max_depth,
                        min_samples=cfg.tree_min_samples)
    tree.fit(Xtr, ytr)
    return tree


def tree_scores(tree: DecisionTree, X: list[list[float]]) -> list[float]:
    return [tree.predict_proba_one(row).get(1, 0.0) for row in X]
