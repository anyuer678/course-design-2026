"""ml/neuralnet.py —— 多层感知机 + 反向传播（BP）手写实现

课程要点：
    - 前向：z = Wx + b，隐藏层 tanh/ReLU，输出层 softmax
    - 损失：交叉熵 CE = -(1/n)ΣΣ y·log(ŷ)。softmax + 交叉熵的梯度
      恰好是 (ŷ - y)——两者"天生一对"，这是推导笔记里的重点
    - 反向传播 = 链式法则的动态规划：误差信号从输出层逐层回传，
      每层的梯度只依赖下一层的 delta 和本层的输入
    - 梯度检查：解析梯度 vs 数值梯度（中心差分）——手写 BP 的第一道
      验收，误差应在 1e-6 量级（见测试）

课程红线（考试高频）：为什么需要非线性激活？——没有它，多层等价于
一层线性变换（W2(W1x) = (W2W1)x），网络表达力退化成线性模型。
"""
from __future__ import annotations

import math
import random


def _tanh(z: float) -> float:
    return math.tanh(z)


def _softmax(z: list[float]) -> list[float]:
    """数值稳定的 softmax：先减最大值，防 exp 上溢。"""
    m = max(z)
    exps = [math.exp(v - m) for v in z]
    s = sum(exps)
    return [e / s for e in exps]


class MLP:
    """layer_sizes 形如 [4, 8, 3]：输入 4 维，隐藏 8，输出 3 类。

    参数按层存放：W[l][j][i] 是第 l 层单元 i 到第 l+1 层单元 j 的权重；
    b[l][j] 是第 l+1 层单元 j 的偏置。梯度结构与参数完全同形。
    """

    def __init__(self, layer_sizes: list[int], hidden_act: str = "tanh",
                 seed: int = 42, lr: float = 0.1, epochs: int = 300,
                 batch_size: int | None = None):
        if len(layer_sizes) < 3:
            raise ValueError("至少三层：输入 / 隐藏 / 输出")
        if hidden_act not in ("tanh", "relu"):
            raise ValueError("hidden_act 是 tanh 或 relu")
        self.sizes = layer_sizes
        self.hidden_act = hidden_act
        self.lr = lr
        self.epochs = epochs
        self.batch_size = batch_size
        self.seed = seed
        self.seed = seed
        self.seed = seed
        rng = random.Random(seed)
        # Xavier 风格初始化：尺度 1/sqrt(输入数)。全零初始化会让同层单元对称、
        # 永远学成同一个东西；太大则 tanh 饱和、梯度消失。
        self.W: list[list[list[float]]] = []
        self.b: list[list[float]] = []
        for l in range(len(layer_sizes) - 1):
            scale = 1.0 / math.sqrt(layer_sizes[l])
            self.W.append([[rng.uniform(-scale, scale)
                            for _ in range(layer_sizes[l])]
                           for _ in range(layer_sizes[l + 1])])
            self.b.append([0.0] * layer_sizes[l + 1])
        self.loss_history_: list[float] = []
        self.classes_: list = []

    # ------------------------------------------------ 激活
    def _act(self, z: float) -> float:
        return _tanh(z) if self.hidden_act == "tanh" else (z if z > 0 else 0.0)

    def _act_grad(self, z: float, a: float) -> float:
        # tanh' = 1 - a²（用激活值算，省一次 tanh）；relu' = z > 0
        if self.hidden_act == "tanh":
            return 1.0 - a * a
        return 1.0 if z > 0 else 0.0

    # ------------------------------------------------ 前向 / 损失 / 反向
    def _forward_one(self, x: list[float]) -> tuple[list[list[float]], list[list[float]]]:
        """返回 (激活列表 a, 加权和列表 z)。a[0] = x，末层激活 = softmax。"""
        acts = [x]
        zs: list[list[float]] = []
        a = x
        L = len(self.W)
        for l in range(L):
            z = [self.b[l][j] + sum(self.W[l][j][i] * a[i]
                                    for i in range(len(a)))
                 for j in range(len(self.b[l]))]
            zs.append(z)
            a = (_softmax(z) if l == L - 1
                 else [self._act(v) for v in z])
            acts.append(a)
        return acts, zs

    def loss(self, X: list[list[float]], Y1h: list[list[float]]) -> float:
        """平均交叉熵。加 1e-12 防 log(0)。"""
        total = 0.0
        for x, y in zip(X, Y1h):
            probs = self._forward_one(x)[0][-1]
            total -= sum(t * math.log(p + 1e-12) for t, p in zip(y, probs))
        return total / len(X)

    def backprop(self, X: list[list[float]], Y1h: list[list[float]]):
        """整批的梯度（对 batch 平均）。返回 (gradW, gradB)，形状同参数。
        手写 BP 的正确性由测试的数值梯度检查担保。"""
        L = len(self.W)
        gradW = [[[0.0] * len(self.W[l][j]) for j in range(len(self.W[l]))]
                 for l in range(L)]
        gradB = [[0.0] * len(self.b[l]) for l in range(L)]
        n = len(X)
        for x, y in zip(X, Y1h):
            acts, zs = self._forward_one(x)
            # 输出层：softmax + 交叉熵 -> delta = p - y（推导见 docs/derivations.md）
            delta = [p - t for p, t in zip(acts[-1], y)]
            for l in range(L - 1, -1, -1):
                for j in range(len(delta)):
                    for i in range(len(acts[l])):
                        gradW[l][j][i] += delta[j] * acts[l][i]
                    gradB[l][j] += delta[j]
                if l > 0:
                    # 误差回传上一层：W^T·delta 再乘激活函数导数
                    prev = [0.0] * len(acts[l])
                    for i in range(len(acts[l])):
                        s = sum(self.W[l][j][i] * delta[j]
                                for j in range(len(delta)))
                        prev[i] = s * self._act_grad(zs[l - 1][i], acts[l][i])
                    delta = prev
        for l in range(L):
            for j in range(len(gradW[l])):
                for i in range(len(gradW[l][j])):
                    gradW[l][j][i] /= n
                gradB[l][j] /= n
        return gradW, gradB

    # ------------------------------------------------ 训练与预测
    def fit(self, X: list[list[float]], y: list, classes: list | None = None):
        self.classes_ = classes or sorted(set(y))
        idx = {c: i for i, c in enumerate(self.classes_)}
        Y1h = [[1.0 if idx[lab] == j else 0.0 for j in range(len(self.classes_))]
               for lab in y]
        rng = random.Random(self.seed)
        self.loss_history_ = []
        n = len(X)
        bs = self.batch_size or n
        for _ in range(self.epochs):
            order = list(range(n))
            rng.shuffle(order)                       # 每个 epoch 重新洗牌
            for start in range(0, n, bs):
                batch = order[start:start + bs]
                BX = [X[i] for i in batch]
                BY = [Y1h[i] for i in batch]
                gradW, gradB = self.backprop(BX, BY)
                for l in range(len(self.W)):
                    for j in range(len(self.W[l])):
                        for i in range(len(self.W[l][j])):
                            self.W[l][j][i] -= self.lr * gradW[l][j][i]
                        self.b[l][j] -= self.lr * gradB[l][j]
            self.loss_history_.append(self.loss(X, Y1h))
        return self

    def predict_proba(self, X: list[list[float]]) -> list[list[float]]:
        return [self._forward_one(x)[0][-1] for x in X]

    def predict(self, X: list[list[float]]) -> list:
        return [self.classes_[max(range(len(p)), key=p.__getitem__)]
                for p in self.predict_proba(X)]
