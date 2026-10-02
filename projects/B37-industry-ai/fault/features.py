"""fault/features.py —— 滑窗特征与标签：只在"过去"里看，只在"未来"里标

两条口径钉死在这里（两个最容易做错的地方）：
    1. **特征不泄漏**：以 t 结尾的窗口只用 t-window+1..t 的读数——故障时刻 f
       之后的数据永远不会出现在 f 之前的窗口里；
    2. **标签看未来**：y=1 当且仅当未来 horizon 步内（不含 t 当步）会发生故障。
       t≥f 的窗口（故障已发生/恢复暂态）**排除出数据集**——把"读数还在高位但
       故障已过去"的窗口当负样本教，模型学到的是噪声。

样本台账（meta）保留 device/end/kind，供误报解剖与提前量计算逐条追溯到
具体设备与窗口末端。
"""
from __future__ import annotations

from fault.config import Config

FEATURES = ["temp_mean", "temp_slope", "temp_range", "temp_std",
            "vib_mean", "vib_slope", "vib_max", "vib_std"]


def _slope(values: list[float]) -> float:
    """最小二乘斜率（对步下标回归），比首尾差更抗单点尖峰。"""
    n = len(values)
    mean_i = (n - 1) / 2
    mean_v = sum(values) / n
    num = sum((i - mean_i) * (v - mean_v) for i, v in enumerate(values))
    den = sum((i - mean_i) ** 2 for i in range(n))
    return num / den


def window_features(window_rows: list[dict]) -> list[float]:
    temps = [r["temp"] for r in window_rows]
    vibs = [r["vib"] for r in window_rows]
    n = len(temps)

    def std(xs: list[float]) -> float:
        mean = sum(xs) / len(xs)
        return (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5

    return [sum(temps) / n, _slope(temps), max(temps) - min(temps), std(temps),
            sum(vibs) / n, _slope(vibs), max(vibs), std(vibs)]


def window_label(end: int, events: list[tuple[int, str]], cfg: Config
                 ) -> tuple[int | None, str | None]:
    """单个窗口末端 end 的标签：(y, kind)。排除窗口返回 (None, None)。

    口径（测试逐边界钉住）：
      - 排除：t≥f 到恢复暂态结束（end ∈ [f, f+window+decay-1]）——故障已发生，
        读数还在高位，标 0 会教模型学噪声；
      - 正：未来 horizon 步内**不含当步**会发生故障（0 < f-end ≤ horizon）；
      - 负：其余。
    """
    if any(f <= end <= f + cfg.window + cfg.decay - 1 for f, _k in events):
        return None, None
    for f, k in events:
        if 0 < f - end <= cfg.horizon:
            return 1, k
    return 0, None


def build_dataset(cfg: Config, fleet: dict) -> dict:
    """把读数行切成 (X, y, meta)。同一设备相邻窗口高度相关——切分不能随机（见 split 层）。"""
    by_device: dict[int, list[dict]] = {}
    for row in fleet["rows"]:
        by_device.setdefault(row["device"], []).append(row)

    failures_by_device: dict[int, list[tuple[int, str]]] = {}
    for f in fleet["failures"]:
        failures_by_device.setdefault(f["device"], []).append((f["step"], f["kind"]))

    X: list[list[float]] = []
    y: list[int] = []
    meta: list[dict] = []
    excluded = 0

    for device, rows in sorted(by_device.items()):
        rows = sorted(rows, key=lambda r: r["step"])
        events = failures_by_device.get(device, [])
        for end in range(cfg.window, cfg.steps + 1, cfg.stride):
            label, kind = window_label(end, events, cfg)
            if label is None:
                excluded += 1
                continue
            span = rows[end - cfg.window:end]
            X.append(window_features(span))
            y.append(label)
            meta.append({"device": device, "end": end, "kind": kind})

    return {"X": X, "y": y, "meta": meta, "excluded": excluded,
            "features": list(FEATURES)}


def split_by_device(cfg: Config, dataset: dict) -> tuple[list[int], list[int]]:
    """按设备切分：测试设备整台不见于训练集。返回两组下标。"""
    train = [i for i, m in enumerate(dataset["meta"]) if m["device"] not in cfg.test_devices]
    test = [i for i, m in enumerate(dataset["meta"]) if m["device"] in cfg.test_devices]
    return train, test


def take(X: list, y: list, idx: list[int]) -> tuple[list, list]:
    return [X[i] for i in idx], [y[i] for i in idx]
