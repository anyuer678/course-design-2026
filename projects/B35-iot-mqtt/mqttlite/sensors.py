"""mqttlite/sensors.py —— 模拟工业传感器：随机游走 + 注入三类异常（有账本）

课程要点：
    - 传感器读数是"带漂移的随机游走"：温度围绕基线小幅波动、振动独立取值——
      这不是装饰，是后面"异常检测/预测"（B37）的**基线**；
    - 三类异常各有教学含义：
        spike   尖峰：读数突然偏大（传感器故障或真实故障事件）
        freeze  卡值：读数不变（传感器死锁——数值本身"正常"最容易骗过阈值检测）
        dropout 断数：这一轮**不发**（网络抖动/设备复位；QoS0 下就是永久丢失）
      三类都进账本，接收端按账本对账（完整性不是"看起来齐全"，是逐数对得上）；
    - 每个设备自带固定种子的 RNG：整条时间线的异常位置可复现（演示与测试共用）。
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass


@dataclass
class ReadingPlan:
    """一个设备的读数规划：注入概率写死在这里，账本随实际注入累加。"""
    spike_p: float = 0.03
    freeze_p: float = 0.03
    dropout_p: float = 0.02
    spike_delta: float = 40.0


class SensorSimulator:
    def __init__(self, device_id: str, seed: int, base_temp: float = 70.0,
                 drift: float = 1.5, plan: ReadingPlan | None = None):
        self.device_id = device_id
        self.rng = random.Random(seed)
        self.base_temp = base_temp
        self.drift = drift
        self.plan = plan or ReadingPlan()
        self.temp = base_temp
        self.vib = 0.5
        self.seq = 0
        self.last_temp = base_temp
        self.ledger = {"spike": 0, "freeze": 0, "dropout": 0}
        self.sent = 0

    def next_reading(self) -> dict | None:
        """产生一轮读数；dropout 时返回 None（本轮不发）。"""
        self.seq += 1
        self.temp = min(150.0, max(0.0, self.temp + self.rng.uniform(-self.drift, self.drift)))
        self.vib = min(5.0, max(0.0, self.vib + self.rng.uniform(-0.05, 0.05)))

        anomaly = None
        roll = self.rng.random()
        if roll < self.plan.spike_p:
            anomaly = "spike"
            self.temp += self.plan.spike_delta
            self.ledger["spike"] += 1
        elif roll < self.plan.spike_p + self.plan.freeze_p:
            anomaly = "freeze"
            self.temp = self.last_temp          # 卡在上一轮的值
            self.ledger["freeze"] += 1
        elif roll < self.plan.spike_p + self.plan.freeze_p + self.plan.dropout_p:
            self.ledger["dropout"] += 1
            return None                          # 断数：这轮不发
        self.last_temp = self.temp
        self.sent += 1
        return {
            "device": self.device_id,
            "seq": self.seq,
            "ts": round(time.time(), 3),
            "temp": round(self.temp, 2),
            "vib": round(self.vib, 3),
            "anomaly": anomaly,
        }

    def publish(self, client, topic_prefix: str = "sensors") -> bool:
        """取一轮读数并发出去（dropout 直接返回 False）。"""
        reading = self.next_reading()
        if reading is None:
            return False
        topic = f"{topic_prefix}/{self.device_id}/data"
        payload = json.dumps(reading, ensure_ascii=False)
        client.publish(topic, payload)
        return True
