"""tinylang/runtime.py —— 两条执行后端共用的运行期上限与错误构造器。

为什么要有这个模块：调用深度上限与「缺 return」两类错误必须**逐字相同**地
从两个后端报出来（对拍测试直接比较 message 字符串）。两个后端各自拼一遍
字符串迟早漂走——改了这边忘那边，测试红的时候还要先分辨是语义差异还是
文案差异。把上限常数与构造器放在一处，两边只做翻译。

位置只承诺行号对齐：VM 的指令只带行号，两边都按 Span(line, 1, line, 1) 构造；
列号不承诺一致（见 docs/frames-spec.md §六）。
"""
from __future__ import annotations

from .spans import RuntimeError_, Span

DEFAULT_MAX_CALL_DEPTH = 100


def depth_exceeded(function: str, cap: int, line: int) -> RuntimeError_:
    """第 cap+1 层调用被拒绝（两个后端在压入前检查，口径相同）。"""
    return RuntimeError_(
        f"调用深度超过上限 {cap}：函数 {function!r} 的第 {cap + 1} 层调用被拒绝"
        "（很可能是无限递归）",
        Span(line, 1, line, 1),
        "检查递归的终止条件；调用深度上限是保护宿主栈的护栏，不是语言特性")


def missing_return(function: str, return_type: str, line: int) -> RuntimeError_:
    """函数体自然执行到结尾（没有遇到 return）时的运行期错误。"""
    return RuntimeError_(
        f"函数 {function!r} 执行到了函数体结尾也没有遇到 return"
        f"（返回类型 {return_type.lower()}）",
        Span(line, 1, line, 1),
        "本语言不做「所有路径都 return」的静态分析：这个错误在执行到结尾时才报出来")
