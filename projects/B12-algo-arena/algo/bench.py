"""algo/bench.py —— 规模计时。

先把话说清楚：**计时不是复杂度证明**。证明靠不变式与归纳（见各算法模块的 docstring），
实验只回答两个问题：

1. 实测增长趋势与理论同阶吗？（log-log 斜率 ≈ 1 / 2 / 3 …）
2. 同阶的算法差多少常数？（比如"能算"和"算得完"之间的那道沟）

重复次数的中位数而不是单次：一次的性能数字基本是噪声。min 一并留着，
因为"最接近算法本体耗时"的观测通常是最小值，中位数则用来抗系统抖动。
"""
from __future__ import annotations

import math
import os
import platform
import sys
import time
from dataclasses import dataclass


@dataclass
class Timing:
    median: float
    fastest: float
    slowest: float
    repeats: int

    def __str__(self) -> str:
        return f"{self.median * 1000:9.2f} ms（{self.repeats} 次，" \
               f"最快 {self.fastest * 1000:.2f}，最慢 {self.slowest * 1000:.2f}）"


def measure(fn, arg=None, *, repeats: int = 5, warmup: int = 1) -> Timing:
    """跑 repeats 次取中位数。fn 接受一个参数（arg 为位置参数）。"""
    if repeats < 1:
        raise ValueError("repeats 至少 1 次")
    for _ in range(warmup):               # 让 import、缓存这些一次性开销先发生掉
        fn(arg)
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn(arg)
        samples.append(time.perf_counter() - start)
    samples.sort()
    middle = samples[len(samples) // 2] if len(samples) % 2 else \
        (samples[len(samples) // 2 - 1] + samples[len(samples) // 2]) / 2
    return Timing(middle, samples[0], samples[-1], repeats)


def growth(fn, sizes, *, repeats: int = 3):
    """对一串规模各测一次，返回 [(n, Timing, 与上一个规模的耗时比)]。

    注意 fn 自己负责造输入：如果输入生成也计进时间，测的是"生成 + 算法"。
    想只测算法本身，用 `sweep` 把输入预先备好。
    """
    rows, previous = [], None
    for size in sizes:
        timing = measure(fn, size, repeats=repeats)
        ratio = None if previous in (None, 0) else timing.median / previous
        rows.append((size, timing, ratio))
        previous = timing.median
    return rows


def sweep(fn, cases, *, repeats: int = 3):
    """cases 是 [(标签, 参数)]：输入在计时之外准备好，只测算法本体。"""
    rows, previous = [], None
    for label, arg in cases:
        timing = measure(fn, arg, repeats=repeats)
        ratio = None if previous in (None, 0) else timing.median / previous
        rows.append((label, timing, ratio))
        previous = timing.median
    return rows


def log_log_slope(sizes, times) -> float:
    """最小二乘拟合 ln(t) = a + b·ln(n) 的 b。

    b≈1 线性、2 平方、3 立方、0.5 开方；n 或 t 里有非正数时无法取对数，直接报错，
    免得拟合出一个看起来很像样的假斜率。
    """
    if len(sizes) != len(times) or len(sizes) < 2:
        raise ValueError("至少需要两组 (n, t) 才能拟合")
    if any(n <= 0 or t <= 0 for n, t in zip(sizes, times)):
        raise ValueError("对数拟合要求规模与耗时都为正")
    xs = [math.log(n) for n in sizes]
    ys = [math.log(t) for t in times]
    count = len(xs)
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        raise ValueError("规模没有变化，斜率无意义")
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / variance


def machine_info() -> dict:
    """实验环境。README 里每一张计时表都必须带上这些信息，否则数字没有可比性。"""
    return {
        "系统": platform.platform(),
        "处理器": platform.processor() or "未报告",
        "CPU 逻辑核": os.cpu_count(),
        "Python": sys.version.split()[0],
        "计时源": "time.perf_counter（单调钟，含进程外等待）",
    }


def format_rows(rows, header=("规模", "耗时", "与上一档的倍率")) -> str:
    lines = ["  ".join(f"{column:<{width}}" for column, width in
                       zip(header, (18, 42, 16)))]
    for label, timing, ratio in rows:
        note = f"×{ratio:.2f}" if ratio else ""
        lines.append(f"{str(label):<20}  {str(timing):<42}  {note}")
    return "\n".join(lines)
