"""fault/report.py —— 行业交付形态的静态图表（复用 B35 的手写 SVG）

两张图回答两个问题：
    1. "告警预算曲线"：允许的告警条数从 0 往上加，能抓到多少故障、
       精确率怎么掉——运营定阈值看的就是它（不是告诉你"AUC 很高"）；
    2. "设备时间线"：一台测试设备的温度/振动原始读数 + 故障实际发生点
       （红圈），把"模型报的警"和"真发生的故障"放在同一条线上对照。
"""
from __future__ import annotations

from pathlib import Path

from mqttlite.svgplot import line_chart                 # 复用 B35


def alert_budget_chart(rows: list[dict], out_path) -> int:
    """rows 来自 metrics.sweep：x=报警条数，y=召回/精确率。"""
    recall = [(r["alerts"], r["recall"]) for r in rows]
    precision = [(r["alerts"], r["precision"]) for r in rows]
    return line_chart(out_path, {"召回率": recall, "精确率": precision},
                      title="告警预算曲线（模拟数据，不外推生产）",
                      y_label="比率", width=900, height=420)


def device_charts(fleet: dict, device: int, out_dir) -> dict:
    """一台设备的温度/振动时间线（红圈=实际故障时刻），返回 {名字: 字节数}。"""
    rows = sorted((r for r in fleet["rows"] if r["device"] == device),
                  key=lambda r: r["step"])
    failures = [(f["step"], None) for f in fleet["failures"]
                if f["device"] == device]
    out_dir = Path(out_dir)
    out: dict[str, int] = {}
    for field, label, scale in (("temp", "温度（°C）", 1.0), ("vib", "振动（mm/s）", 1.0)):
        series = [(r["step"], r[field] * scale) for r in rows]
        marks = []
        value_of = {r["step"]: r[field] for r in rows}
        for step, _k in failures:
            if step in value_of:
                marks.append((step, value_of[step], f"故障 t={step}"))
        out[field] = line_chart(out_dir / f"dev{device:02d}_{field}.svg",
                                {f"dev{device:02d}": series},
                                anomalies=marks,
                                title=f"dev{device:02d} {label} 时间线（红圈=故障）",
                                y_label=label)
    return out
