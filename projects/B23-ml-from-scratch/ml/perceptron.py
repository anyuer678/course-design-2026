"""ml/perceptron.py —— 感知机（Rosenblatt 1958）

课程要点：
    - 模型：f(x) = sign(w·x + b)，约定 sign(0) = -1（写代码必须把 0 的归属说清）
    - 学习规则：错就调——w += lr·y·x，b += lr·y。只在"分错"时更新
    - 收敛定理（Novikoff）：数据线性可分 -> 有限步收敛；不可分则永不停止，
      所以必须有 max_epochs
    - 感知机是神经网络的最小单元：它失败的地方（XOR）正是多层网络的出发点

loss 的另一种视角：0-1 损失不可导，感知机用的是它的代理——
    L = -y·(w·x+b)（仅在错分类时为正），对它求导就得到上面的更新规则。
"""
from __future__ import annotations


class Perceptron:
    def __init__(self, lr: float = 1.0, max_epochs: int = 1000):
        self.lr = lr
        self.max_epochs = max_epochs
        self.w: list[float] = []
        self.b = 0.0
        self.updates_ = 0                 # 总更新次数（收敛速度的度量）
        self.epochs_ = 0                  # 实际跑的轮数
        self.converged_ = False           # 是否提前收敛（0 错误轮）

    def _score(self, x: list[float]) -> float:
        return sum(wi * xi for wi, xi in zip(self.w, x)) + self.b

    def _predict_one(self, x: list[float]) -> int:
        return 1 if self._score(x) > 0 else -1     # sign(0) = -1，约定写死

    def fit(self, X: list[list[float]], y: list[int]) -> "Perceptron":
        """y 必须是 ±1。可分数据有限步收敛；不可分跑满 max_epochs。"""
        if set(y) != {-1, 1}:
            raise ValueError("感知机的标签必须是 ±1（二分类）")
        self.w = [0.0] * len(X[0])
        self.b = 0.0
        self.updates_ = 0
        for epoch in range(1, self.max_epochs + 1):
            errors = 0
            for x, yi in zip(X, y):
                # y·(w·x+b) <= 0 等价于"分错或恰在边界上"
                if yi * self._score(x) <= 0:
                    for j in range(len(self.w)):
                        self.w[j] += self.lr * yi * x[j]
                    self.b += self.lr * yi
                    errors += 1
                    self.updates_ += 1
            self.epochs_ = epoch
            if errors == 0:
                self.converged_ = True
                break
        return self

    def predict(self, X: list[list[float]]) -> list[int]:
        return [self._predict_one(x) for x in X]
