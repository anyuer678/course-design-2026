"""ml/linear.py —— 线性回归：闭式解与梯度下降是同一个答案的两条路

课程要点：
    - 模型 y = w·x + b；损失 MSE = (1/n)Σ(yi - y_hati)^2
    - 闭式解（正规方程）：对 w 求导置零得 (X^TX)w = X^Ty —— 解线性方程组
    - 梯度下降：沿负梯度迭代。两种解法答案必须一致（对拍的天然素材）
    - R^2 = 1 - SS_res/SS_tot：衡量"比拿均值瞎猜好多少"

实现全部手写：高斯消元（带部分主元）解正规方程，不用 numpy。
"""
from __future__ import annotations



def add_bias(X: list[list[float]]) -> list[list[float]]:
    """给每行末尾补一列 1——把截距并入权重，闭式解统一处理。"""
    return [row + [1.0] for row in X]


def solve_linear_system(A: list[list[float]], b: list[float]) -> list[float]:
    """高斯消元（部分主元选取）解 Ax=b；矩阵奇异时抛异常。"""
    n = len(A)
    # 增广矩阵拷贝，避免污染调用方
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        # 部分主元：选当前列绝对值最大的行换上来，数值更稳
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            raise ValueError("矩阵奇异（特征共线？）：正规方程无唯一解")
        M[col], M[pivot] = M[pivot], M[col]
        for r in range(col + 1, n):
            factor = M[r][col] / M[col][col]
            for c in range(col, n + 1):
                M[r][c] -= factor * M[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))
        x[i] = s / M[i][i]
    return x


def mse_loss(X: list[list[float]], y: list[float], params: list[float]) -> float:
    """均方误差（params = [w..., b]）。梯度检查用它做参照。"""
    n = len(X)
    total = 0.0
    for row, yi in zip(X, y):
        pred = sum(p * x for p, x in zip(params, row + [1.0]))
        total += (yi - pred) ** 2
    return total / n


def mse_gradient(X: list[list[float]], y: list[float],
                 params: list[float]) -> list[float]:
    """MSE 对每个参数的解析梯度：d/dθ = -(2/n)Σ(yi - y_hati)·xi。
    与数值梯度（中心差分）对拍是测试的一部分。"""
    n = len(X)
    d = len(params)
    grads = [0.0] * d
    for row, yi in zip(X, y):
        err = yi - sum(p * x for p, x in zip(params, row + [1.0]))
        for j in range(d):
            xj = row[j] if j < d - 1 else 1.0
            grads[j] -= err * xj
    return [2.0 * g / n for g in grads]


class LinearRegression:
    """fit_closed_form 与 fit_gd 得到的解必须几乎一致（见测试）。"""

    def __init__(self) -> None:
        self.coef_: list[float] = []
        self.intercept_: float = 0.0
        self.history_: list[float] = []      # GD 的损失曲线

    def _split_params(self, params: list[float]) -> None:
        self.coef_ = params[:-1]
        self.intercept_ = params[-1]

    def fit_closed_form(self, X: list[list[float]], y: list[float]) -> "LinearRegression":
        """正规方程 (X^TX)θ = X^Ty。加 1e-10 的对角扰动防奇异（数值保险）。"""
        Xb = add_bias(X)
        d = len(Xb[0])
        AtA = [[sum(Xb[k][i] * Xb[k][j] for k in range(len(Xb))) for j in range(d)]
               for i in range(d)]
        Aty = [sum(Xb[k][i] * y[k] for k in range(len(Xb))) for i in range(d)]
        for i in range(d):
            AtA[i][i] += 1e-10               # 正则化最小量：只防奇异，不改变解
        self._split_params(solve_linear_system(AtA, Aty))
        return self

    def fit_gd(self, X: list[list[float]], y: list[float], lr: float = 0.05,
               epochs: int = 5000) -> "LinearRegression":
        """全批量梯度下降。学习率过大 -> 发散，过大/small -> 慢（demo 演示）。"""
        params = [0.0] * (len(X[0]) + 1)
        self.history_ = []
        for _ in range(epochs):
            grads = mse_gradient(X, y, params)
            params = [p - lr * g for p, g in zip(params, grads)]
            self.history_.append(mse_loss(X, y, params))
        self._split_params(params)
        return self

    def predict(self, X: list[list[float]]) -> list[float]:
        return [sum(w * x for w, x in zip(self.coef_, row)) + self.intercept_
                for row in X]


def r2_score(y_true: list[float], y_pred: list[float]) -> float:
    """R^2 = 1 - SS_res/SS_tot。1 是完美，0 等于拿均值猜，负数不如均值。"""
    mean = sum(y_true) / len(y_true)
    ss_res = sum((t - p) ** 2 for t, p in zip(y_true, y_pred))
    ss_tot = sum((t - mean) ** 2 for t in y_true)
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


def accuracy(y_true, y_pred) -> float:
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    return correct / len(y_true)
