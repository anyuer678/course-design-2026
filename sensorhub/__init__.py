"""sensorhub —— P6 物联网监测（PRODUCTS.md §五 轮六之一）。

零件库纪律：**MQTT 全链路直接 import B35 手写 mqttlite 的真实实现**——
broker（selectors 真套接字）、SensorSimulator（随机游走 + 三类异常账本）、
Recorder（订阅入库 SQLite + 四个对账口）、svgplot（手写 SVG 曲线）。
SensorHub 只做产品层：阈值告警台账、节拍编排、HTTP 观察面。零重写。
"""
from __future__ import annotations

import sys
from pathlib import Path

_B35 = Path(__file__).resolve().parents[1] / "projects" / "B35-iot-mqtt"
if str(_B35) not in sys.path:
    sys.path.insert(0, str(_B35))

from .engine import METRICS, SensorHub          # noqa: E402,F401

__all__ = ["METRICS", "SensorHub"]
