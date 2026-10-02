"""b31/codec.py —— 自增 id ↔ 短码（base62）。

为什么是 base62 而不是 base64：base64 的字母表里有 `+` 和 `/`，
`+` 在查询串里会被解成空格，`/` 会撞路径分隔符——短码是要放进 URL 里跑的，
`[0-9A-Za-z]` 全都不需要转义，两边不必再约定一套编码规则。

代价是区分大小写：`Ab` 和 `ab` 是两个不同的码。人眼抄写时 0/O、1/l 也易混，
这是教学实现里可以接受、但必须写清楚的一条取舍（真实产品常用去掉易混字符的 base58）。

`decode_code()` 只接受**规范形式**：不允许多余的前导零。因为编码本身是"一个整数一种写法"，
一旦允许 `00`、`000` 也解出同一个 id，主键就不再唯一，短码和别名两条路径会互相打架。
"""
from __future__ import annotations

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)                       # 62
_INDEX = {ch: i for i, ch in enumerate(ALPHABET)}

MAX_ID = 2 ** 62 - 1                       # 单表自增 id 的上限：约 4.6 × 10^18 条
MIN_CODE_LEN = 1
MAX_CODE_LEN = 11                          # base62(2**62 - 1) 正好 11 位


class CodecError(ValueError):
    """短码非法：字符不在字母表里、长度越界、或者不是规范形式。"""


def encode_id(n: int) -> str:
    """非负整数 → 短码。0 编成 "0"，没有前导零。"""
    if isinstance(n, bool) or not isinstance(n, int):
        raise CodecError(f"id 必须是 int，收到 {type(n).__name__}")
    if not 0 <= n <= MAX_ID:
        raise CodecError(f"id {n} 超出可用范围 0..{MAX_ID}")
    if n == 0:
        return ALPHABET[0]
    digits = []
    while n:
        n, rest = divmod(n, BASE)
        digits.append(ALPHABET[rest])
    return "".join(reversed(digits))


def decode_code(code: str) -> int:
    """短码 → 整数。只收规范形式，否则抛 CodecError。"""
    if not isinstance(code, str):
        raise CodecError("短码必须是字符串")
    if not MIN_CODE_LEN <= len(code) <= MAX_CODE_LEN:
        raise CodecError(f"短码长度应在 {MIN_CODE_LEN}..{MAX_CODE_LEN}，收到 {len(code)}")
    if any(ch not in _INDEX for ch in code):
        bad = next(ch for ch in code if ch not in _INDEX)
        raise CodecError(f"短码含字母表外的字符 {bad!r}")
    if len(code) > 1 and code[0] == ALPHABET[0]:
        raise CodecError(f"短码 {code!r} 有多余的前导零：不是规范形式")
    value = 0
    for ch in code:                          # Horner：从左到右，每一位乘回基数
        value = value * BASE + _INDEX[ch]
    if value > MAX_ID:
        raise CodecError(f"短码 {code!r} 表示的 id 超出上限")
    return value


def is_code_shape(code: str) -> bool:
    """形状检查：字符与长度合规。别名允许前导零（它就是用户挑的字面串，不是整数写法）。"""
    return (isinstance(code, str) and MIN_CODE_LEN <= len(code) <= MAX_CODE_LEN
            and all(ch in _INDEX for ch in code))
