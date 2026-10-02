"""ml/data.py —— 数据加载、切分与预处理

三个数据来源（零下载，见 README 的数据来源说明）：
    1. data/iris.csv      Fisher 鸢尾花数据集（1936，公有领域），本仓库转写
    2. make_moons()       两条交错半圆（非线性可分，演示"感知机失败、BP 成功"）
    3. make_blobs()       高斯团块（线性可分，演示感知机收敛）

切分与标准化在这里统一做，是为了把两件容易做错的事钉死在同一个地方：
    - 切分必须可复现（固定种子的洗牌），否则实验不可对拍；
    - 标准化的均值/方差只能来自训练集——用全量数据算统计量叫"数据泄漏"。
"""
from __future__ import annotations

import csv
import math
import random
from pathlib import Path

IRIS_PATH = Path(__file__).resolve().parent.parent / "data" / "iris.csv"
IRIS_CLASSES = ["setosa", "versicolor", "virginica"]
IRIS_FEATURES = ["sepal_length", "sepal_width", "petal_length", "petal_width"]


def load_iris() -> tuple[list[list[float]], list[str]]:
    """读鸢尾花 CSV -> (特征矩阵 150x4, 标签列表)。"""
    X: list[list[float]] = []
    y: list[str] = []
    with open(IRIS_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            X.append([float(row[c]) for c in IRIS_FEATURES])
            y.append(row["species"])
    if len(X) != 150:
        raise ValueError(f"iris.csv 应有 150 行，实际 {len(X)}")
    return X, y


def class_distribution(y: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for label in y:
        out[label] = out.get(label, 0) + 1
    return out


def train_test_split(n: int, test_ratio: float = 0.2,
                     seed: int = 42) -> tuple[list[int], list[int]]:
    """固定种子的下标切分。返回 (train_idx, test_idx)，互斥且并集完备。"""
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    cut = int(n * (1 - test_ratio))
    return sorted(idx[:cut]), sorted(idx[cut:])


def standardize(train: list[list[float]],
                test: list[list[float]]) -> tuple[list[list[float]], list[list[float]]]:
    """z-score 标准化。均值/方差只从 train 计算（防数据泄漏）。"""
    d = len(train[0])
    means = [sum(row[j] for row in train) / len(train) for j in range(d)]
    stds = []
    for j in range(d):
        var = sum((row[j] - means[j]) ** 2 for row in train) / len(train)
        stds.append(math.sqrt(var) or 1.0)      # 方差为 0 的列按 1 处理，避免除零
    tr = [[(row[j] - means[j]) / stds[j] for j in range(d)] for row in train]
    te = [[(row[j] - means[j]) / stds[j] for j in range(d)] for row in test]
    return tr, te


def one_hot(labels: list[str], classes: list[str]) -> list[list[int]]:
    # 陌生标签 ⇒ 全 0 行（保持原行为；改成 idx[lab] 会在未知标签上抛 KeyError，那是行为变更）
    return [[1 if c == lab else 0 for c in classes] for lab in labels]


def make_moons(n: int = 200, noise: float = 0.15,
               seed: int = 7) -> tuple[list[list[float]], list[int]]:
    """两条交错半圆。线性不可分——感知机的坟场，多层网络的试金石。"""
    rng = random.Random(seed)
    X: list[list[float]] = []
    y: list[int] = []
    for i in range(n):
        cls = i % 2
        theta = math.pi * (i % (n // 2)) / (n // 2)
        if cls == 0:
            x, yy = math.cos(theta), math.sin(theta)
        else:
            x, yy = 1 - math.cos(theta), 0.5 - math.sin(theta)
        X.append([x + rng.uniform(-noise, noise),
                  yy + rng.uniform(-noise, noise)])
        y.append(cls)
    return X, y


def make_blobs(n: int = 100, seed: int = 3) -> tuple[list[list[float]], list[int]]:
    """两个线性可分的高斯团块（间隔明显）：感知机应当 100% 收敛。"""
    rng = random.Random(seed)
    X: list[list[float]] = []
    y: list[int] = []
    for i in range(n):
        cls = i % 2
        cx, cy = (0.0, 0.0) if cls == 0 else (4.0, 4.0)
        X.append([rng.gauss(cx, 0.6), rng.gauss(cy, 0.6)])
        y.append(cls)
    return X, y
