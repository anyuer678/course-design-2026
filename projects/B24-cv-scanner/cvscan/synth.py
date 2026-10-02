"""cvscan/synth.py —— 合成"文档照片"：给检测/还原/二值化提供**有出处的真值**

课程要点（也是本仓库的验证纪律）：计算机视觉的期望值最容易"凭感觉"——
所以本模块不找现成图片：**程序渲染一份文档（顶视图），记录它的四角真值、
文字掩码与暗像素占比，再按已知的透视变换"拍成照片"**。此后：
    - 角点检测的误差 = 检测结果与**已知四角**的距离（像素级，有出处）；
    - 透视还原的质量 = 还原图与**原始文档**的逐像素差（MAD，有出处）；
    - 二值化的质量 = 二值图与**已知文字掩码**的逐像素一致率（有出处）。
"拍照"这一步故意用 getPerspectiveTransform + warpPerspective 实现——它是
检测侧透视变换的**逆过程**，两边共享同一套数学，但真值（角点/掩码）是我
先摆好的，不是从函数里反推的。

可制造的难度开关（失败样例对照用）：
    low_contrast  纸与字的灰度差被压到 ~10（Canny 找不到边）
    shadow        叠加一侧渐暗的阴影（本流水线未做去阴影——演示里如实展示）
    tiny          文档太小（面积占比低于检测阈值）
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Document:
    """顶视图文档：图像 + 文字掩码 + 统计（全部是检测/二值化要对的真值）。"""
    image: np.ndarray          # uint8, (H, W) 灰度
    text_mask: np.ndarray      # bool, 同尺寸：文字像素为 True
    dark_ratio: float          # 文字像素占比（掩码的均值）


@dataclass
class Photo:
    """"拍下来"的照片：图像 + 文档四角的真值（TL, TR, BR, BL 顺序）。"""
    image: np.ndarray                      # uint8, (Hc, Wc) 灰度
    true_corners: np.ndarray               # float32 (4, 2)，左上/右上/右下/左下
    document: Document                     # 生成它的那份文档（还原对比用）


def render_document(width: int = 600, height: int = 800, n_lines: int = 18,
                    rng: np.random.Generator | None = None) -> Document:
    """顶视图渲染：浅灰纸底 + 深色"文字条带"（行高/长度带随机，但位置已知）。"""
    rng = rng or np.random.default_rng(0)
    image = np.full((height, width), 235, dtype=np.uint8)
    mask = np.zeros((height, width), dtype=bool)

    y = 60
    line_h = 12
    stride = 26
    for _ in range(n_lines):
        if y + line_h >= height - 40:
            break
        x0 = 40
        x1 = width - 40 - int(rng.integers(0, width // 3))
        if rng.random() < 0.25:                     # 25% 的行短一些（段落收尾）
            x1 = min(x1, x0 + int((x1 - x0) * 0.6))
        image[y:y + line_h, x0:x1] = 30
        mask[y:y + line_h, x0:x1] = True
        y += stride

    noise = rng.normal(0, 2.5, size=image.shape)
    image = np.clip(image.astype(np.float64) + noise, 0, 255).astype(np.uint8)
    return Document(image=image, text_mask=mask, dark_ratio=float(mask.mean()))


def photograph(document: Document, canvas: tuple[int, int] = (1200, 900),
               doc_scale: float = 0.75, jitter_px: float = 18.0,
               bg_level: int = 175, noise_sigma: float = 5.0,
               low_contrast: bool = False, shadow: bool = False,
               rng: np.random.Generator | None = None) -> Photo:
    """把文档"拍"进画布：已知四角 + 透视畸变 + 背景与噪声。

    返回的 true_corners 是目标四角（TL, TR, BR, BL）——检测的期望值。
    """
    rng = rng or np.random.default_rng(0)
    hc, wc = canvas
    dh, dw = document.image.shape

    doc = document.image.astype(np.float64)
    if low_contrast:
        # 整个场景"洗白"：纸压到 ~210、桌面也提到 ~205——
        # 纸与桌面差 ~5 灰阶、字与纸差 ~16 灰阶，都在 Canny 阈值(50)之下。
        # （只压低纸与字是没用的：纸对桌面的外轮廓仍然会被 Canny 抓住——探针实测过）
        doc = 210.0 + (doc - 235.0) * 0.08
        bg_level = 205

    background = np.full((hc, wc), float(bg_level))
    background += rng.normal(0, noise_sigma, size=background.shape)

    bw = dw * doc_scale
    bh = dh * doc_scale
    cx, cy = wc / 2.0, hc / 2.0
    corners = np.array([
        [cx - bw / 2.0, cy - bh / 2.0],          # 左上
        [cx + bw / 2.0, cy - bh / 2.0],          # 右上
        [cx + bw / 2.0, cy + bh / 2.0],          # 右下
        [cx - bw / 2.0, cy + bh / 2.0],          # 左下
    ], dtype=np.float64)
    corners += rng.normal(0, jitter_px, size=corners.shape)
    margin = 12.0
    corners[:, 0] = np.clip(corners[:, 0], margin, wc - 1 - margin)
    corners[:, 1] = np.clip(corners[:, 1], margin, hc - 1 - margin)

    src = np.array([[0, 0], [dw - 1, 0], [dw - 1, dh - 1], [0, dh - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, corners.astype(np.float32))
    warped = cv2.warpPerspective(doc, m, (wc, hc))
    alpha = cv2.warpPerspective(np.ones_like(doc), m, (wc, hc))

    composed = background * (1.0 - alpha) + warped * alpha

    if shadow:
        # 从左上到右下渐暗（最深处 ×0.75）：本流水线没有去阴影步骤——演示里如实展示后果
        gradient = np.linspace(1.0, 0.75, wc)[None, :] * np.ones((hc, 1))
        composed *= gradient

    composed += rng.normal(0, noise_sigma, size=composed.shape)
    image = np.clip(composed, 0, 255).astype(np.uint8)
    return Photo(image=image, true_corners=corners.astype(np.float32), document=document)


def blank_scene(canvas: tuple[int, int] = (1200, 900), bg_level: int = 175,
                noise_sigma: float = 5.0, rng: np.random.Generator | None = None) -> np.ndarray:
    """纯背景（没有文档）——失败样例之一。"""
    rng = rng or np.random.default_rng(0)
    hc, wc = canvas
    image = np.full((hc, wc), float(bg_level)) + rng.normal(0, noise_sigma, size=(hc, wc))
    return np.clip(image, 0, 255).astype(np.uint8)


def noise_scene(canvas: tuple[int, int] = (1200, 900), rng: np.random.Generator | None = None) -> np.ndarray:
    """纯噪声（没有结构）——失败样例之二。"""
    rng = rng or np.random.default_rng(0)
    hc, wc = canvas
    return (rng.random((hc, wc)) * 255.0).astype(np.uint8)
