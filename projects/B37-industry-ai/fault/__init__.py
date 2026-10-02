"""B37-industry-ai —— 设备故障预测：复用 B35 遥测 + B23 手写模型，做误报/漏报分析。

两件复用（本仓库的规矩：能用已有的就不写第二份，复制会烂成两份）：
    B35-iot-mqtt    `mqttlite.sensors`  种子化传感器遥测（随机游走 + spike/freeze 账本）
    B35-iot-mqtt    `mqttlite.svgplot`  手写 SVG 折线图（阈值扫描曲线写进 build/）
    B23-ml-from-scratch  `ml.tree`      手写决策树（叶子类分布直接当概率分数用）
    B23-ml-from-scratch  `ml.data`      防泄漏的 train_test_split / standardize

这里做一件事：把两个项目的目录挂进 `sys.path`（同 B28 的做法）。
B37 自己只新写三样东西：退化/故障注入层、滑窗特征与标签、逻辑回归（B23 练习第 3 条
建议的补做——B23 只有硬判别的感知机，误报/漏报分析需要概率分数）。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECTS_DIR = Path(__file__).resolve().parents[2]        # fault/ → B37-industry-ai/ → projects/
B35_DIR = PROJECTS_DIR / "B35-iot-mqtt"
B23_DIR = PROJECTS_DIR / "B23-ml-from-scratch"

_REQUIRED = ((B35_DIR / "mqttlite" / "sensors.py", "B35-iot-mqtt/mqttlite"),
             (B35_DIR / "mqttlite" / "svgplot.py", "B35-iot-mqtt/mqttlite"),
             (B23_DIR / "ml" / "tree.py", "B23-ml-from-scratch/ml"),
             (B23_DIR / "ml" / "data.py", "B23-ml-from-scratch/ml"))

for path, label in _REQUIRED:
    if not path.is_file():
        raise RuntimeError(
            f"没找到 {label}（期望 {path}）。B37 是构建在 B35/B23 之上的："
            "要么两个目录不在同一个 projects/ 下，要么它们被移动过。")

for directory in (B35_DIR, B23_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
