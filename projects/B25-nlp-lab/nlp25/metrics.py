"""nlp25/metrics.py —— 分类指标（手写，测试与手算对拍）

约定（写死避免歧义）：
    - precision 的分母是"预测为正的个数"，recall 的分母是"真值为正的个数"；
      分母为 0 时该指标记 0.0（sklearn 的 zero_division=0 同款约定）。
    - F1 = 2PR/(P+R)，P+R=0 时记 0.0。
    - 混淆矩阵行是真值、列是预测。
"""
from __future__ import annotations


def accuracy(y_true: list, y_pred: list) -> float:
    if len(y_true) != len(y_pred):
        raise ValueError("y_true 与 y_pred 长度不一致")
    if not y_true:
        raise ValueError("空列表")
    return sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)


def confusion_matrix(y_true: list, y_pred: list,
                     labels: list) -> dict[tuple, int]:
    """{(真值, 预测): 次数}；labels 决定哪些组合即使为 0 也出现。"""
    counts: dict[tuple, int] = {(t, p): 0 for t in labels for p in labels}
    for t, p in zip(y_true, y_pred):
        if (t, p) not in counts:
            raise ValueError(f"出现 labels 之外的组合: ({t}, {p})")
        counts[(t, p)] += 1
    return counts


def precision_recall_f1(y_true: list, y_pred: list, positive) -> tuple:
    """二分类视角下指定 positive 类的 P/R/F1。"""
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == positive and p == positive)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t != positive and p == positive)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == positive and p != positive)
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall > 0 else 0.0)
    return precision, recall, f1
