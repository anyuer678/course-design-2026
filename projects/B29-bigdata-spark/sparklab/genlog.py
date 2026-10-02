"""sparklab/genlog.py —— 合成工业日志：可制造缺陷、可对账、可制造键倾斜

课程要点（工业大数据的第一课）：**数据是脏的，而且脏得"有账可查"**。
本生成器把每一类缺陷**按已知数量注入**并返回账本（ledger）：
    bad_timestamp  时间戳格式不对（少了毫秒/日期乱写）
    bad_level      等级字段不在 {INFO, WARN, ERROR} 里
    missing_field  管道分隔的字段数不足
    bad_code       code= 后面不是三位数字
清洗侧每删一类，都要和账本对上（同 B26 的"缺陷注入 → 逐步清洗 → 计数逐数对账"）。

行格式（管道分隔，正则好抓）：
    2026-09-30 14:23:01.123|dev-03|ERROR|code=503|msg=timeout
键倾斜开关：`skew_device_ratio` 把大比例的事件集中到 dev-01 上——这是第 6 段
（salting 两阶段聚合）实验的输入。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

DEVICES = [f"dev-{i:02d}" for i in range(1, 9)]
LEVELS = ["INFO", "INFO", "INFO", "WARN", "WARN", "ERROR"]
CODES = {"INFO": ["200", "200", "201"], "WARN": ["301", "302"], "ERROR": ["500", "503", "404"]}
MESSAGES = ["ok", "slow-query", "timeout", "retry-ok", "disk-warn", "conn-reset"]


@dataclass
class LogBundle:
    lines: list[str]
    ledger: dict = field(default_factory=dict)   # 注入账本：每类缺陷的确切条数
    clean_true: int = 0                          # 应通过清洗的行数（真值）


def _ts(rng: random.Random) -> str:
    day = rng.choice([29, 30])
    hour = rng.randrange(0, 24)
    minute = rng.randrange(0, 60)
    second = rng.randrange(0, 60)
    milli = rng.randrange(0, 1000)
    return f"2026-09-{day:02d} {hour:02d}:{minute:02d}:{second:02d}.{milli:03d}"


def _good_line(rng: random.Random, device: str | None = None) -> str:
    dev = device or rng.choice(DEVICES)
    level = rng.choice(LEVELS)
    code = rng.choice(CODES[level])
    msg = rng.choice(MESSAGES)
    return f"{_ts(rng)}|{dev}|{level}|code={code}|msg={msg}"


def make_log(n_lines: int = 2000, seed: int = 7, skew_device_ratio: float = 0.0,
             defects: dict | None = None) -> LogBundle:
    """生成日志 + 账本。defects 覆盖默认缺陷数（默认按行数的比例给少量）。"""
    rng = random.Random(seed)
    defects = defects or {
        "bad_timestamp": max(1, n_lines // 400),
        "bad_level": max(1, n_lines // 500),
        "missing_field": max(1, n_lines // 600),
        "bad_code": max(1, n_lines // 700),
    }
    total_defects = sum(defects.values())
    if total_defects >= n_lines:
        raise ValueError("缺陷数不能超过总行数")

    lines: list[str] = []
    for _ in range(n_lines):
        # 键倾斜：大比例行固定给 dev-01
        if skew_device_ratio > 0 and rng.random() < skew_device_ratio:
            lines.append(_good_line(rng, device="dev-01"))
        else:
            lines.append(_good_line(rng))

    # 缺陷注入：在互不重叠的下标上改造
    defect_idx = rng.sample(range(n_lines), total_defects)
    pos = 0
    for kind, count in defects.items():
        for i in defect_idx[pos:pos + count]:
            line = lines[i]
            fields = line.split("|")
            if kind == "bad_timestamp":
                fields[0] = "2026-09-30 25:99:99"          # 越界时间
            elif kind == "bad_level":
                fields[2] = "FATAL"                          # 不在合法等级里
            elif kind == "missing_field":
                fields = fields[:3]                          # 字段数不足
            elif kind == "bad_code":
                fields[3] = "code=abc"                       # 非三位数字
            lines[i] = "|".join(fields)
        pos += count

    return LogBundle(lines=lines, ledger=dict(defects), clean_true=n_lines - total_defects)


def write_log(bundle: LogBundle, path) -> int:
    path = str(path)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for line in bundle.lines:
            f.write(line + "\n")
    return len(bundle.lines)
