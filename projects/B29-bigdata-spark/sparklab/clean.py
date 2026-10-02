"""sparklab/clean.py —— 纯 Python 清洗：坏行分类 + 与注入账本逐数对账

规则与 Spark 侧**一字不差**（同一套正则、同一个优先级顺序）——这是"对拍"能成立的前提：
    missing_field  管道字段数 ≠ 5（最先判，避免空字段进后面的正则）
    bad_timestamp  时间戳不匹配 `YYYY-MM-DD HH:MM:SS.mmm`（含 24 小时制范围）
    bad_level      等级不在 INFO/WARN/ERROR
    bad_code       code 字段不是 code=\\d{3}
行内每个缺陷只归**一类**（注入时就不重叠；优先级保证与 Spark 的 CASE WHEN 一致）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LEVELS = ("INFO", "WARN", "ERROR")

# 与 Spark 端 rlike 使用的正则**逐字相同**（改一处必须两处一起改，测试盯着）：
# 小时必须真落在 00-23 —— `[0-2]\d` 会放行 25 点（探针抓过的错），用 ([01]\d|2[0-3])。
TS_PATTERN = r"^\d{4}-\d{2}-\d{2} ([01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{3}$"
CODE_PATTERN = r"^code=\d{3}$"
TS_RE = re.compile(TS_PATTERN)      # 单一出处：Python 侧的正则从上面派生，防两处漂移
CODE_RE = re.compile(CODE_PATTERN)


@dataclass
class CleanResult:
    clean: list[dict] = field(default_factory=list)       # 清洗后的结构化行
    quarantined: dict = field(default_factory=dict)       # 类别 -> 条数


def classify_line(line: str) -> str:
    """返回 'ok' / 'missing_field' / 'bad_timestamp' / 'bad_level' / 'bad_code'。
    优先级与 Spark 的 CASE WHEN 一致：字段数 → 时间戳 → 等级 → code。"""
    fields = line.split("|")
    if len(fields) != 5:
        return "missing_field"
    ts, _device, level, code_field, _msg = fields
    if not TS_RE.match(ts):
        return "bad_timestamp"
    if level not in LEVELS:
        return "bad_level"
    if not CODE_RE.match(code_field):
        return "bad_code"
    return "ok"


def parse_ok_line(line: str) -> dict:
    ts, device, level, code_field, msg_field = line.split("|")
    # 契约：code 字段剥 "code=" 前缀并只留三位数；msg 字段剥 "msg=" 前缀（Spark 端同一规则）
    msg = msg_field[4:] if msg_field.startswith("msg=") else msg_field
    return {"ts": ts, "device": device, "level": level,
            "code": code_field[5:], "msg": msg}


def clean_lines(lines: list[str]) -> CleanResult:
    result = CleanResult()
    for line in lines:
        kind = classify_line(line)
        if kind == "ok":
            result.clean.append(parse_ok_line(line))
        else:
            result.quarantined[kind] = result.quarantined.get(kind, 0) + 1
    return result


def clean_file(path) -> CleanResult:
    with open(path, encoding="utf-8") as f:
        return clean_lines([l.rstrip("\n") for l in f if l.strip() != ""])
