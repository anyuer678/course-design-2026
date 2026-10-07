"""mqttlite/recorder.py —— 订阅端入库：消息 → SQLite（并给出可对账的汇总）

课程要点：
    - 物联网的"入库端"是消息链路的落点：订阅 `sensors/+/data`，把 JSON 解析后落到
      SQLite（一条读数一行），主键 (device, seq) 让重放天然幂等（INSERT OR REPLACE）；
    - **完整性是可数的**：实收行数、按设备分布、异常计数、以及"缺口"（seq 空档 =
      dropout 留下的洞）——三项都能与传感器账本逐数对上（测试与演示都这么做）；
    - 库文件落在指定的 build/ 目录（构建产物），schema 简单到可以直接用 sqlite3 命令看。
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    device  TEXT NOT NULL,
    seq     INTEGER NOT NULL,
    ts      REAL NOT NULL,
    temp    REAL NOT NULL,
    vib     REAL NOT NULL,
    anomaly TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (device, seq)
);
"""


class Recorder:
    def __init__(self, db_path: str | Path, client, topic_filter: str = "sensors/+/data"):
        self.path = Path(db_path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute(SCHEMA)
        self.conn.commit()
        self.topic_filter = topic_filter
        self.received = 0
        self.by_device: Counter = Counter()
        self.anomalies: Counter = Counter()
        self.parse_errors = 0
        self.client = client
        client.on_message = self._on_message
        client.subscribe([topic_filter])     # 订阅是 Recorder 的职责：连着才算入库端

    def _on_message(self, topic: str, payload: bytes) -> None:
        if not _match(self.topic_filter, topic):     # 复用协议层的匹配语义
            return
        try:
            row = json.loads(payload.decode("utf-8"))
            device = str(row["device"])
            seq = int(row["seq"])
            ts = float(row["ts"])
            temp = float(row["temp"])
            vib = float(row["vib"])
            anomaly = str(row.get("anomaly") or "")
        except (ValueError, KeyError, UnicodeDecodeError):
            self.parse_errors += 1
            return
        self.conn.execute(
            "INSERT OR REPLACE INTO readings (device, seq, ts, temp, vib, anomaly) "
            "VALUES (?, ?, ?, ?, ?, ?)", (device, seq, ts, temp, vib, anomaly))
        self.conn.commit()
        self.received += 1
        self.by_device[device] += 1
        if anomaly:
            self.anomalies[anomaly] += 1

    # ---------------------------------------------------------------- 对账口

    def summary(self) -> dict:
        rows = self.conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        return {"rows": rows, "received": self.received,
                "by_device": dict(self.by_device), "anomalies": dict(self.anomalies),
                "parse_errors": self.parse_errors}

    def gaps(self) -> dict[str, int]:
        """每个设备的 seq 缺口数（= dropout 留下的洞的个数）。"""
        out: dict[str, int] = {}
        for device, in self.conn.execute("SELECT DISTINCT device FROM readings"):
            count, lo, hi = self.conn.execute(
                "SELECT COUNT(*), MIN(seq), MAX(seq) FROM readings WHERE device = ?",
                (device,)).fetchone()
            out[device] = (hi - lo + 1) - count
        return out

    def series(self, device: str, metric: str = "temp",
               limit: int | None = None) -> list[tuple[int, float]]:
        """取一个设备的 (seq, 指标) 序列——SVG 曲线的数据源。
        limit 给定时只取最新 limit 点（SENSORHUB 长跑库的性能收口，2026-10-07；
        缺省 None 保持全量语义，B35 原有调用零影响）。走 (device, seq) 主键索引
        反向区间扫描，不靠全表取回再切尾。"""
        if limit is None:
            rows = self.conn.execute(
                f"SELECT seq, {metric} FROM readings WHERE device = ? ORDER BY seq",
                (device,)).fetchall()
        else:
            rows = self.conn.execute(
                f"SELECT seq, {metric} FROM readings WHERE device = ? "
                f"ORDER BY seq DESC LIMIT {int(limit)}", (device,)).fetchall()
            rows.reverse()
        return [(int(s), float(v)) for s, v in rows]

    def anomaly_points(self, device: str) -> list[tuple[int, float, str]]:
        rows = self.conn.execute(
            "SELECT seq, temp, anomaly FROM readings WHERE device = ? AND anomaly != '' "
            "ORDER BY seq", (device,)).fetchall()
        return [(int(s), float(v), a) for s, v, a in rows]

    def close(self) -> None:
        self.conn.close()


def _match(topic_filter: str, topic: str) -> bool:
    from mqttlite.packets import topic_matches
    return topic_matches(topic_filter, topic)
