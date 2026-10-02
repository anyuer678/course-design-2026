"""sparklab/reference.py —— 纯 Python 参照聚合（完全不用 Spark）

对拍纪律：Spark 算出来的每个结果，都要和这套"教科书 Python"逐行相等。
参照实现故意写成最笨的样子——sorted + Counter，让"对"这件事不依赖任何框架。
"""
from __future__ import annotations

from collections import Counter


def by_device_level(clean_rows: list[dict]) -> list[tuple]:
    """按 (device, level) 计数，按 (device, level) 排序。"""
    counter = Counter((r["device"], r["level"]) for r in clean_rows)
    return sorted((dev, lvl, cnt) for (dev, lvl), cnt in counter.items())


def errors_per_hour(clean_rows: list[dict]) -> list[tuple]:
    """ERROR 行按小时（ts 的 12-13 位）计数，按小时排序。"""
    counter = Counter(r["ts"][11:13] for r in clean_rows if r["level"] == "ERROR")
    return sorted(counter.items())


def top_error_codes(clean_rows: list[dict], k: int = 3) -> list[tuple]:
    """ERROR 行按 code 计数，取前 k；并列时 code 升序（与 Spark 侧同一口径）。"""
    counter = Counter(r["code"] for r in clean_rows if r["level"] == "ERROR")
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(code, cnt) for code, cnt in ranked[:k]]


def clean_row_set(clean_rows: list[dict]) -> list[tuple]:
    """把清洗后的行转成可排序的元组列表（逐行对拍的载体）。"""
    return sorted((r["ts"], r["device"], r["level"], r["code"], r["msg"])
                  for r in clean_rows)
