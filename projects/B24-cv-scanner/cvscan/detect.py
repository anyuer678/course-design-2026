"""cvscan/detect.py —— 文档四角检测：Canny → 形态学 → 轮廓 → 多边形逼近 → 排角点

课程要点：
    - 检测流水线的每一步都为下一步"清场"：高斯模糊压噪点、Canny 把灰度差异变成
      二值边、膨胀/闭运算把断掉的边界接上，最后 findContours 才能拿到**闭合**轮廓；
    - 四边形判定 = 用 approxPolyDP 把轮廓压成最少顶点：**恰好 4 个顶点**且面积
      占比达标才算"文档"——不是文档的形状就拒识，而不是硬猜四角；
    - 四个角点要先**排序**（左上/右上/右下/左下）才能喂给透视变换：用"和最小是左上、
      差(y−x)最小是右上"这套经典启发式——排序错了，透视还原就会镜像/翻转；
    - 拒识路径是交付物的一部分：本模块为"没找到四边""面积太小""图像太小"给出
      **不同的原因**，测试与演示都盯着这些原因（失败样例对照）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class DetectResult:
    ok: bool
    corners: np.ndarray | None = None          # float32 (4,2)，TL, TR, BR, BL
    reason: str = ""
    diag: dict = field(default_factory=dict)   # 诊断：候选数、最大面积占比等


def order_points(pts: np.ndarray) -> np.ndarray:
    """把四个点排成 左上/右上/右下/左下：
    和(x+y)最小的是左上、最大的是右下；差(y−x)最小的是右上、最大的是左下。"""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = pts[:, 1] - pts[:, 0]
    tl = pts[int(np.argmin(s))]
    br = pts[int(np.argmax(s))]
    tr = pts[int(np.argmin(d))]
    bl = pts[int(np.argmax(d))]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def find_quad_candidates(image: np.ndarray, canny_lo: int = 50, canny_hi: int = 150,
                         min_area_ratio: float = 0.2, eps_ratio: float = 0.02):
    """返回 (candidates, diag)。candidates = [(面积, 四角 float32 4x2)]，面积降序。"""
    diag: dict = {}
    h, w = image.shape[:2]
    diag["image_size"] = (w, h)
    canvas_area = float(h * w)

    blurred = cv2.GaussianBlur(image, (5, 5), 0)
    edges = cv2.Canny(blurred, canny_lo, canny_hi)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    diag["edge_pixels"] = int(np.count_nonzero(closed))
    # 边缘密度：真实照片约 1%（实测 0.011），纯噪声约 37%——差两个数量级，
    # 阈值 0.25 留给"纹理很重的桌面"很大余量；不给这条，噪声的闭运算会糊成
    # 一整块并骗过"四边形"判定（假阳性，探针实测过）
    diag["edge_density"] = float(np.count_nonzero(edges) / edges.size)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    diag["contour_count"] = len(contours)

    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area_ratio * canvas_area:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, eps_ratio * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            candidates.append((area, approx.reshape(4, 2).astype(np.float32)))
    candidates.sort(key=lambda item: item[0], reverse=True)
    diag["candidate_count"] = len(candidates)
    if candidates:
        diag["best_area_ratio"] = candidates[0][0] / canvas_area
    return candidates, diag


def detect_document(image: np.ndarray, min_area_ratio: float = 0.2,
                    eps_ratio: float = 0.02, min_side: int = 200,
                    max_edge_density: float = 0.25) -> DetectResult:
    """检测文档四角。失败时给出**具体原因**（拒识是设计的一部分）。"""
    if image is None or image.size == 0:
        return DetectResult(ok=False, reason="空图像")
    h, w = image.shape[:2]
    if min(h, w) < min_side:
        return DetectResult(ok=False, reason=f"图像太小（{w}x{h}，短边需 ≥ {min_side}）",
                            diag={"image_size": (w, h)})

    candidates, diag = find_quad_candidates(image, min_area_ratio=min_area_ratio,
                                            eps_ratio=eps_ratio)
    if diag.get("edge_density", 0.0) > max_edge_density:
        return DetectResult(ok=False,
                            reason=f"边缘密度过高（{diag['edge_density']:.0%}），疑似噪声图像",
                            diag=diag)
    if not candidates:
        if diag.get("edge_pixels", 0) < 50:
            return DetectResult(ok=False, reason="没有可用的边缘（对比度过低？）", diag=diag)
        if diag.get("candidate_count", 0) == 0 and diag.get("contour_count", 0) > 0:
            return DetectResult(ok=False, reason="找到了轮廓，但没有面积达标的四边形", diag=diag)
        return DetectResult(ok=False, reason="没有找到四边形轮廓", diag=diag)

    _area, corners = candidates[0]
    return DetectResult(ok=True, corners=order_points(corners), diag=diag)
