"""fault/telemetry.py —— 车队遥测：均值回复基线 + B35 异常分类学 + 退化/故障注入

**复用边界是实测出来的**（这是本节最该读的一段）：
    1. 异常分类学（spike/freeze/dropout）、概率容器 `ReadingPlan`、账本口径
       （逐类计数、sent 对账）与读数 schema 全部沿用 B35；
    2. **不整包复用 `SensorSimulator` 的信号生成**，原因不是喜好，是实测：
       B35 的随机游走**没有均值回复**，而且它的 spike 是**持久偏移**
       （+40°C 留在游走状态里）——480 步 × 3% 尖峰下，温度整条时间线被顶到
       150°C 上限：实测 10 台设备均值 **141.3°C、18.3% 读数夹在 150**
       （同参数去掉尖峰：66.9°C、0 夹取）。短时演示没问题，长时线故障预测里
       这个温度通道就失效了。
    3. 替代基线用 **OU 均值回复**（行业里传感器正常形态）+ 尖峰改**单点离群**
       （"阈值报警被尖峰欺骗"的经典形态）。这个测量本身由测试钉住
       （test_b35_simulator_saturates_on_long_runs），B35 若变，这里会被提醒。

故障时间表：每台设备 failures_per_device 次，起点由 种子=seed_base*1000+d 决定，
两次间隔 ≥ min_gap（排除窗口重叠导致的"一次故障被数成两次"）。
"""
from __future__ import annotations

import random

from fault.config import Config
from mqttlite.sensors import ReadingPlan           # 复用 B35 的概率容器


def failure_schedule(cfg: Config, device: int) -> list[tuple[int, str]]:
    """返回 [(故障步, 类型), ...]；类型 overheat/wear。种子化、确定性。"""
    rng = random.Random(cfg.seed_base * 1000 + device)
    out: list[tuple[int, str]] = []
    step = cfg.first_failure_min + rng.randrange(0, 40)
    while len(out) < cfg.failures_per_device and step <= cfg.steps - 10:
        kind = "overheat" if rng.random() < 0.5 else "wear"
        out.append((step, kind))
        step += cfg.min_gap + rng.randrange(0, 80)
    return out


def _effect(t: int, events: list[tuple[int, str]], cfg: Config, kind: str) -> float:
    """t 时刻的退化附加量：故障前 ramp 步线性爬升，故障后 decay 步线性恢复。"""
    total = 0.0
    for f, k in events:
        if k != kind:
            continue
        if f - cfg.ramp <= t <= f:
            i = t - (f - cfg.ramp)                    # 0..ramp
            total += i * (cfg.overheat_rate if kind == "overheat" else cfg.wear_rate)
        elif f < t <= f + cfg.decay:
            k2 = t - f
            peak = cfg.ramp * (cfg.overheat_rate if kind == "overheat" else cfg.wear_rate)
            total += peak * max(0.0, (cfg.decay - k2) / cfg.decay)
    return total


def _step_ou(value: float, base: float, reversion: float, noise: float,
             lo: float, hi: float, rng: random.Random) -> float:
    """一步 OU：向基线回复 reversion 比例 + 均匀噪声，然后夹到物理量程。"""
    value += -reversion * (value - base) + rng.uniform(-noise, noise)
    return min(hi, max(lo, value))


def generate_fleet(cfg: Config) -> dict:
    """生成整支车队的遥测与三份账本：读数行、故障表、异常账本。

    返回 {"rows": [...], "failures": [...], "sensor_ledger": {...}, "config": cfg}
    rows: {device, step, temp, vib, spike, freeze}（已含退化量与数据质量事件）
    """
    if cfg.dropout_p != 0.0:
        raise ValueError(
            "B37 固定 dropout_p=0：断数会让时间线缺行、窗口与账本对不齐；"
            "B35 已把断数的完整性账本讲透，这里聚焦'读数存在但设备在退化'。")

    rows: list[dict] = []
    failures: list[dict] = []
    sensor_ledger = {"spike": 0, "freeze": 0, "dropout": 0, "sent": 0}

    for d in range(cfg.n_devices):
        rng = random.Random(cfg.seed_base + d)
        jitter_rng = random.Random(cfg.seed_base * 777 + d)
        base_t = round(cfg.base_temp + jitter_rng.uniform(-cfg.base_temp_jitter,
                                                          cfg.base_temp_jitter), 2)
        temp = base_t
        vib = 0.5
        last_pub_temp = base_t
        events = failure_schedule(cfg, d)
        for f, kind in events:
            failures.append({"device": d, "step": f, "kind": kind})

        for t in range(1, cfg.steps + 1):
            temp = _step_ou(temp, base_t, cfg.temp_reversion, cfg.temp_noise,
                            0.0, 160.0, rng)
            vib = _step_ou(vib, 0.5, cfg.vib_reversion, cfg.vib_noise,
                           0.02, 5.0, rng)
            spike = freeze = False
            outlier = 0.0
            roll = rng.random()
            if roll < cfg.spike_p:
                spike = True
                outlier = cfg.spike_delta              # 单点离群：只进输出，不进游走状态
                sensor_ledger["spike"] += 1
            elif roll < cfg.spike_p + cfg.freeze_p:
                freeze = True                          # 死锁：本条重复上一条发出值
                sensor_ledger["freeze"] += 1
            out_temp = temp + outlier + _effect(t, events, cfg, "overheat")
            out_vib = vib + _effect(t, events, cfg, "wear")
            if freeze:
                out_temp = last_pub_temp               # 输出级卡值（与退化叠加不重复计）
            last_pub_temp = out_temp
            rows.append({"device": d, "step": t,
                         "temp": round(out_temp, 2), "vib": round(out_vib, 3),
                         "spike": spike, "freeze": freeze})

        sensor_ledger["sent"] += cfg.steps

    return {"rows": rows, "failures": failures, "sensor_ledger": sensor_ledger}
