"""cvscan/pipeline.py —— 全流程：检测 → 透视还原 → 二值化（一步到位，带指标）

把三段拼成 `scan()`：输入一张"照片"，输出 ScanResult——检测失败时**带着原因**
返回（ok=False），而不是抛异常或硬猜；成功时顺带把"内部质量指标"算好
（角点误差要靠外部真值，这里只算能自证的：边长度差、二值前景比）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from cvscan.binarize import agreement, binarize_adaptive, binarize_otsu
from cvscan.detect import detect_document
from cvscan.rectify import four_point_warp


@dataclass
class ScanResult:
    ok: bool
    reason: str = ""
    corners: np.ndarray | None = None
    warped: np.ndarray | None = None
    binary_otsu: np.ndarray | None = None
    binary_adaptive: np.ndarray | None = None
    otsu_threshold: float = 0.0
    metrics: dict = field(default_factory=dict)


def scan(image: np.ndarray, out_size: tuple[int, int] = (600, 800),
         min_area_ratio: float = 0.2, eps_ratio: float = 0.02) -> ScanResult:
    """文档扫描全流程。失败时 ok=False + reason（原因由 detect 给出）。"""
    detected = detect_document(image, min_area_ratio=min_area_ratio, eps_ratio=eps_ratio)
    if not detected.ok:
        return ScanResult(ok=False, reason=detected.reason, metrics=detected.diag)

    warped = four_point_warp(image, detected.corners, out_size)
    binary_o, thr = binarize_otsu(warped)
    binary_a = binarize_adaptive(warped)

    metrics = dict(detected.diag)
    metrics["otsu_threshold"] = thr
    metrics["otsu_foreground_ratio"] = float(binary_o.mean())
    metrics["adaptive_foreground_ratio"] = float(binary_a.mean())
    metrics["otsu_adaptive_agreement"] = float((binary_o == binary_a).mean())

    return ScanResult(ok=True, corners=detected.corners, warped=warped,
                      binary_otsu=binary_o, binary_adaptive=binary_a,
                      otsu_threshold=thr, metrics=metrics)


def corner_errors(detected_corners: np.ndarray, true_corners: np.ndarray) -> np.ndarray:
    """逐角点的欧氏距离（检测 vs 真值，均按 TL,TR,BR,BL 排序）。"""
    d = np.asarray(detected_corners, dtype=np.float64) - np.asarray(true_corners, dtype=np.float64)
    return np.sqrt((d ** 2).sum(axis=1))


def compare_rectified(warped: np.ndarray, document) -> dict:
    """还原图 vs 原始顶视图文档：平均绝对差（MAD）+ 二值掩码一致率。"""
    a = warped.astype(np.float64)
    b = document.image.astype(np.float64)
    if a.shape != b.shape:
        raise ValueError(f"尺寸不一致：还原 {a.shape} vs 文档 {b.shape}")
    mad = float(np.abs(a - b).mean())
    binary = binarize_otsu(warped)[0]
    quality = agreement(binary, document.text_mask)
    return {"mad": mad, **quality}
