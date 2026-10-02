"""tinylang/values.py —— 运行期值的表示、运算与打印。

VM 与"树遍历参照解释器"共用这一个模块，是刻意的：
对拍要比的是**输出文本逐字节相同**，如果两边各自格式化浮点数、各自决定负数怎么除，
差异会被当成"算法不一致"追半天，而真正的原因只是两处实现各写了一遍规则。

运算约定（语言决定，见 README）：
* `/` 与 `%` 对整数是 **floor 语义**（和 Python 一致）：-7/2 == -4，-7%2 == 1。
  C/Java 的向零截断会得到 -3 和 -1，这是移植事故的经典来源，所以这里把选择写死并有测试。
* 实数的 `/` 是普通除法，`%` 同样按 floor（与整数保持一套故事）。
* 除数为 0（整数 0 或实数 0.0）是运行期错误，必须带行号。
"""
from __future__ import annotations

from .spans import NO_SPAN, RuntimeError_, Span

INT, REAL, BOOL, STRING = "INT", "REAL", "BOOL", "STRING"


def type_name(value) -> str:
    # bool 是 int 的子类：这个顺序判断不能反，否则 true 会被认成 INT
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, int):
        return INT
    if isinstance(value, float):
        return REAL
    if isinstance(value, str):
        return STRING
    return type(value).__name__


def format_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)            # 最短往返表示：2.5 → '2.5'，2.0 → '2.0'
    if isinstance(value, str):
        return value
    raise RuntimeError_(f"无法打印 {type_name(value).lower()} 类型的值")


def to_real(value) -> float:
    if isinstance(value, bool):
        raise RuntimeError_("bool 不能加宽成 real")
    return float(value)


def _zero_division(left, span: Span):
    raise RuntimeError_(f"除数为 0（{left} 除以 0 没有定义）", span,
                        "把除数换成常量前先确认它不会为 0；本语言不做 IEEE 的 inf 语义")


def binary_arith(op: str, left, right, span: Span = NO_SPAN):
    """执行一次算术/拼接运算。类型错误按理说语义检查已经挡掉，这里再挡一次是防线不是装饰。"""
    lt, rt = type_name(left), type_name(right)
    if op == "+":
        if lt == STRING and rt == STRING:
            return left + right
        if STRING in (lt, rt):
            raise RuntimeError_(f"{lt.lower()} + {rt.lower()}：字符串只能用 + 拼接，且两边都必须是字符串", span)
    if BOOL in (lt, rt):
        raise RuntimeError_(f"{lt.lower()} {op} {rt.lower()}：bool 不参与算术", span)
    if lt not in (INT, REAL) or rt not in (INT, REAL):
        raise RuntimeError_(f"{op} 不支持 {lt.lower()} 与 {rt.lower()}", span)
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            _zero_division(left, span)
        return left // right if lt == rt == INT else left / right
    if op == "%":
        if right == 0:
            _zero_division(left, span)
        return left % right
    raise RuntimeError_(f"未知运算符 {op}", span)


def unary_arith(op: str, value, span: Span = NO_SPAN):
    if op == "not":
        if type_name(value) != BOOL:
            raise RuntimeError_(f"not 只能作用于 bool，收到 {type_name(value).lower()}", span)
        return not value
    if op == "-":
        if isinstance(value, bool) or type_name(value) not in (INT, REAL):
            raise RuntimeError_(f"一元 - 只能作用于数字，收到 {type_name(value).lower()}", span)
        return -value
    raise RuntimeError_(f"未知一元运算符 {op}", span)


def compare(op: str, left, right, span: Span = NO_SPAN) -> bool:
    lt, rt = type_name(left), type_name(right)
    if BOOL in (lt, rt) and lt != rt:
        raise RuntimeError_(f"{lt.lower()} {op} {rt.lower()}：bool 不与数字比较", span)
    if STRING in (lt, rt):
        if lt != rt:
            raise RuntimeError_(f"字符串不能与 {(rt if lt == 'STRING' else lt).lower()} 比较", span)
        if op not in ("=", "!="):
            raise RuntimeError_("字符串只支持 = 与 !=（本语言没有定义字典序）", span)
    if lt == rt == BOOL and op not in ("=", "!="):
        raise RuntimeError_(f"bool 不支持 {op}", span)
    if op == "=":
        return left == right
    if op == "!=":
        return left != right
    if lt == STRING or rt == STRING or lt == BOOL or rt == BOOL:
        raise RuntimeError_(f"{op} 不支持 {lt.lower()} 与 {rt.lower()}", span)
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    raise RuntimeError_(f"未知比较运算符 {op}", span)
