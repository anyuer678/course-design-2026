"""cvscan/rectify.py —— 透视变换：把倾斜的文档"拉正"

课程要点：
    - 透视变换要解一个 8 参数矩阵（3×3 齐次矩阵最后一项归一化），
      `getPerspectiveTransform` 用**四对点**（原图的四个角 → 目标的四个角）求它；
    - `warpPerspective` 做的就是反向映射 + 插值：对输出图的每个像素问"你对应原图哪里"，
      因此输出尺寸由**调用方决定**（我们拉成 600×800 的"纸面尺寸"）；
    - 检测那一步的角点排序（TL,TR,BR,BL）在这里兑现价值：顺序错了，
      矩阵会把文档拧成镜像——测试里用"文字条带的行方向"专门盯着这一点。
"""
from __future__ import annotations

import cv2
import numpy as np


def four_point_warp(image: np.ndarray, corners: np.ndarray,
                    out_size: tuple[int, int] = (600, 800)) -> np.ndarray:
    """把 corners（TL,TR,BR,BL）框住的四边形拉正到 out_size=(宽,高)。"""
    dst = np.array([
        [0, 0],
        [out_size[0] - 1, 0],
        [out_size[0] - 1, out_size[1] - 1],
        [0, out_size[1] - 1],
    ], dtype=np.float32)
    m = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    return cv2.warpPerspective(image, m, out_size, flags=cv2.INTER_LINEAR)
