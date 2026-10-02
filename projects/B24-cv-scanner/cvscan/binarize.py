"""cvscan/binarize.py —— 二值化：Otsu 全局阈值 vs 自适应局部阈值

课程要点：
    - Otsu 在**直方图**上找一个让"类间方差最大"的全局阈值——一张图只有一个门槛，
      对均匀光照的文档又快又好；
    - 自适应阈值给**每个像素**在它的邻域里单独算门槛（block 内的局部均值/高斯加权减 C）——
      阴影、光照不均时更稳，代价是平坦区域会"无中生有"地出噪点；
    - 两种做法都保留，是因为它们的失败方式不同：测试与演示里用**已知文字掩码**
      量出各自的一致率，让"什么时候用哪个"变成数据而不是口诀。
"""
from __future__ import annotations

import cv2
import numpy as np


def binarize_otsu(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """全局 Otsu。返回 (二值图 bool：前景=文字为 True, 阈值)。"""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thr, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return binary > 0, float(thr)


def binarize_adaptive(gray: np.ndarray, block_size: int = 35, c: float = 15.0) -> np.ndarray:
    """自适应局部阈值（均值法）。返回二值图 bool：前景=文字为 True。

    block_size 必须是奇数（邻域窗口大小）；C 是从局部均值里减掉的偏置。"""
    if block_size % 2 == 0:
        block_size += 1
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV, block_size, c)
    return binary > 0


def agreement(binary: np.ndarray, truth_mask: np.ndarray) -> dict:
    """与真值掩码的一致性：逐像素一致率 + 前景交并比（IoU）。"""
    correct = float((binary == truth_mask).mean())
    inter = float(np.count_nonzero(binary & truth_mask))
    union = float(np.count_nonzero(binary | truth_mask))
    iou = inter / union if union > 0 else 1.0
    return {"pixel_accuracy": correct, "iou": iou,
            "foreground_ratio": float(binary.mean()),
            "truth_ratio": float(truth_mask.mean())}
