"""tinylang/bytecode.py —— 栈机指令集、常量池与反汇编。

指令都是三元组 `(操作码, 参数, 源码行号)`。**行号是流水线可追踪的关键**：
运行时错误、trace 输出、"这条指令来自哪一行"全靠它；丢了行号，
VM 报的错就只能说"程序某处"，等于把编译器的优势又还回去。

跳转参数一律是**绝对指令下标**（不是相对偏移）。好处是 patch 时不用换算，
坏处是代码搬动时必须整体重算——本实现不搬动代码，所以选绝对地址。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 栈与变量
PUSH = "PUSH"                       # 参数：常量池下标
LOAD = "LOAD"                       # 参数：局部槽位
STORE = "STORE"
I2F = "I2F"                         # 显式加宽：int → real
# 运算
BIN = "BIN"                         # 参数：运算码下标
CMP = "CMP"                         # 参数：比较码下标
UN = "UN"                           # 参数：一元运算码下标
# 控制流
JZ = "JZ"                           # 弹出栈顶：假(False)则跳
JNZ = "JNZ"                         # 真则跳（and/or 短路用）
JUMP = "JUMP"
# 其它
PRINT = "PRINT"
HALT = "HALT"

BINARY_OPS = ("+", "-", "*", "/", "%")
COMPARE_OPS = ("=", "!=", "<", "<=", ">", ">=")
UNARY_OPS = ("-", "not")
OP_INDEX = {**{op: i for i, op in enumerate(BINARY_OPS)},
            **{op: i + len(BINARY_OPS) for i, op in enumerate(COMPARE_OPS)},
            **{op: i + len(BINARY_OPS) + len(COMPARE_OPS) for i, op in enumerate(UNARY_OPS)}}
NAME_BY_INDEX = {index: name for name, index in OP_INDEX.items()}


@dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None = None
    line: int = 0

    def render(self, constants=()) -> str:
        if self.op in ("BIN", "CMP", "UN"):
            return f"{self.op:<6} {NAME_BY_INDEX[self.arg]:<6}".rstrip()
        if self.op == PUSH:
            return f"{'PUSH':<6} {self.arg:<6} ; {constants[self.arg]!r}".rstrip()
        if self.arg is None:
            return self.op
        return f"{self.op:<6} {self.arg}"


@dataclass
class Code:
    instrs: list = field(default_factory=list)
    constants: list = field(default_factory=list)
    locals_count: int = 0
    source: str = ""

    def add(self, op: str, arg: int | None = None, line: int = 0) -> int:
        self.instrs.append(Instr(op, arg, line))
        return len(self.instrs) - 1

    def constant(self, value) -> int:
        """常量池去重。键里带上类型名，否则 True 和 1 会共用一个槽位。"""
        from .values import type_name
        key = (type_name(value), value)
        for index, existing in enumerate(self.constants):
            if (type_name(existing), existing) == key:
                return index
        self.constants.append(value)
        return len(self.constants) - 1

    def patch(self, index: int, target: int) -> None:
        self.instrs[index] = Instr(self.instrs[index].op, target, self.instrs[index].line)

    def disassemble(self) -> str:
        lines = []
        previous_line = None
        for index, instr in enumerate(self.instrs):
            if instr.line != previous_line:
                text = self.source.splitlines()[instr.line - 1] if self.source and instr.line \
                    and instr.line <= len(self.source.splitlines()) else ""
                lines.append(f"  ;; 第 {instr.line} 行: {text.strip()}" if text
                             else f"  ;; 第 {instr.line} 行")
                previous_line = instr.line
            lines.append(f"{index:>5}  {instr.render(self.constants)}")
        return "\n".join(lines)
