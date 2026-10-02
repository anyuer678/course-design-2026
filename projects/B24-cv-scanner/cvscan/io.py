"""cvscan/io.py —— 图像读写（绕开 OpenCV 的中文路径坑）

为什么不用 cv2.imwrite 了：**它遇到含非 ASCII 的"绝对路径"会静默失败**
（本机实测：`cv2.imwrite(r"C:\\...\\课设\\...\\x.png", img)` 返回 False、文件不出现；
换成相对路径就没事）。demo 里当初写的是绝对路径，画了半天的图根本没落盘——
现在统一走 `imencode + Python 文件写入`：编码出 PNG 字节后由 Python 的文件 API 落盘，
路径是不是中文、是绝对还是相对，都无所谓。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def save_png(path: str | Path, image: np.ndarray) -> int:
    """把图像存成 PNG（灰度/彩色都行）。返回写入字节数；失败抛错，绝不静默。"""
    path = Path(path)
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"PNG 编码失败：{path}")
    data = buf.tobytes()
    path.write_bytes(data)
    if path.stat().st_size != len(data):
        raise RuntimeError(f"写入不完整：{path}")
    return len(data)


def load_png(path: str | Path, grayscale: bool = True) -> np.ndarray:
    """读 PNG：字节由 Python 读入，再交给 imdecode。"""
    path = Path(path)
    data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    flag = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
    image = cv2.imdecode(data, flag)
    if image is None:
        raise RuntimeError(f"PNG 解码失败：{path}")
    return image
