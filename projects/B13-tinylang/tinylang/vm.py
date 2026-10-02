"""tinylang/vm.py —— 栈机执行器：结果、步数上限、可回溯的 trace。

三条防线，一条都不能省：
* **步数上限**：死循环在教学语言里太容易写出来（`while true do x := x;`）。
  没有上限，测试进程就挂在那儿；有上限，报的是"第 N 行大概死循环"而不是"没响应"。
* **栈下溢检测**：正常情况下代码生成保证栈平衡，所以一旦下溢就是编译器 bug。
  把它做成显式错误，比让 Python 抛 IndexError 更容易定位（后者不带你自己的行号）。
* **运行期类型/除零检查**：语义检查已经挡掉大部分，这里再挡一次是防线不是装饰——
  直接构造非法字节码的测试就是用来证明这道防线存在的。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .bytecode import (BIN, CMP, HALT, I2F, JNZ, JUMP, JZ, NAME_BY_INDEX, PRINT,
                       LOAD, PUSH, STORE, UN, Code)
from .spans import RuntimeError_, Span
from .values import binary_arith, compare, format_value, to_real, unary_arith

DEFAULT_MAX_STEPS = 200_000


@dataclass
class Step:
    pc: int
    line: int
    instruction: str
    stack_top: object
    locals_view: list

    def render(self) -> str:
        return (f"{self.pc:>5}  行{self.line:<3} {self.instruction:<18} "
                f"栈顶={self.stack_top!r:<10} 变量={self.locals_view}")


@dataclass
class VmResult:
    output: list = field(default_factory=list)
    steps: int = 0
    locals_view: list = field(default_factory=list)
    trace: list = field(default_factory=list)
    timed_out: bool = False

    def text(self) -> str:
        return "\n".join(self.output)


class VM:
    def __init__(self, code: Code, *, max_steps: int = DEFAULT_MAX_STEPS,
                 trace_limit: int = 0):
        self.code = code
        self.max_steps = max_steps
        self.trace_limit = trace_limit
        self.stack: list = []
        self.locals: list = [None] * max(code.locals_count, 1)
        self.pc = 0
        self.steps = 0
        self.output: list[str] = []
        self.trace: list[Step] = []

    # ---------------------------------------------------- 主循环
    def run(self) -> VmResult:
        while True:
            if self.steps >= self.max_steps:
                raise RuntimeError_(
                    f"执行步数超过上限 {self.max_steps}，第 {self.current_line()} 行附近"
                    "很可能是死循环", Span(self.current_line(), 1, self.current_line(), 1),
                    "确认循环里有没有让条件变假的语句；调大上限请用 --max-steps")
            if self.pc >= len(self.code.instrs):
                raise RuntimeError_("执行流掉到了最后一条指令之外（缺少 HALT？）",
                                    Span(self.current_line(), 1, self.current_line(), 1))
            instr = self.code.instrs[self.pc]
            self.steps += 1
            if self.trace_limit and len(self.trace) < self.trace_limit:
                self.trace.append(Step(self.pc, instr.line, instr.render(self.code.constants),
                                       self.stack[-1] if self.stack else None,
                                       list(self.locals)))
            self.pc += 1
            if self.execute(instr):
                break
        return VmResult(output=self.output, steps=self.steps,
                        locals_view=list(self.locals), trace=self.trace)

    def current_line(self) -> int:
        index = min(self.pc, len(self.code.instrs) - 1)
        return self.code.instrs[index].line if self.code.instrs else 0

    def execute(self, instr) -> bool:
        """执行一条指令；返回 True 表示 HALT（结束）。"""
        span = Span(instr.line, 1, instr.line, 1)
        op = instr.op
        if op == PUSH:
            self.stack.append(self.constant(instr.arg, span))
        elif op == LOAD:
            self.stack.append(self.read_slot(instr.arg, span))
        elif op == STORE:
            self.write_slot(instr.arg, self.pop(span), span)
        elif op == I2F:
            self.stack.append(to_real(self.pop(span)))
        elif op == BIN:
            right, left = self.pop(span), self.pop(span)
            self.stack.append(binary_arith(self.op_name(instr, span), left, right, span))
        elif op == CMP:
            right, left = self.pop(span), self.pop(span)
            self.stack.append(compare(self.op_name(instr, span), left, right, span))
        elif op == UN:
            self.stack.append(unary_arith(self.op_name(instr, span), self.pop(span), span))
        elif op == JZ:
            if not self._truthy(self.pop(span), span):
                self.jump(instr.arg, span)
        elif op == JNZ:
            if self._truthy(self.pop(span), span):
                self.jump(instr.arg, span)
        elif op == JUMP:
            self.jump(instr.arg, span)
        elif op == PRINT:
            self.output.append(format_value(self.pop(span)))
        elif op == HALT:
            return True
        else:
            raise RuntimeError_(f"未知指令 {op}", span)
        return False

    # ---------------------------------------------------- 小工具
    def pop(self, span: Span):
        if not self.stack:
            raise RuntimeError_(f"栈下溢：{span.line} 行的指令要弹一个不存在的值（编译器 bug）",
                                span)
        return self.stack.pop()

    def constant(self, index: int, span: Span):
        if not 0 <= index < len(self.code.constants):
            raise RuntimeError_(f"读取不存在的常量池下标 {index}", span,
                                "代码生成或手工构造的指令有误")
        return self.code.constants[index]

    @staticmethod
    def op_name(instr, span: Span) -> str:
        try:
            return NAME_BY_INDEX[instr.arg]
        except KeyError:
            raise RuntimeError_(f"{instr.op} 带了一个不认识的运算码 {instr.arg}", span)

    def write_slot(self, slot: int, value, span: Span) -> None:
        if not 0 <= slot < len(self.locals):
            raise RuntimeError_(f"写入不存在的变量槽位 {slot}", span)
        self.locals[slot] = value

    def read_slot(self, slot: int, span: Span):
        if not 0 <= slot < len(self.locals):
            raise RuntimeError_(f"访问不存在的变量槽位 {slot}", span)
        value = self.locals[slot]
        if value is None:
            raise RuntimeError_(f"读取未赋值的变量槽位 {slot}", span,
                                "语义检查没拦住？这是编译器 bug，请把这条程序贴进 issue")
        return value

    def jump(self, target: int, span: Span) -> None:
        if not 0 <= target < len(self.code.instrs):
            raise RuntimeError_(f"跳转到不存在的地址 {target}（跳转没回填？）", span)
        self.pc = target

    @staticmethod
    def _truthy(value, span: Span) -> bool:
        from .values import BOOL, type_name
        if type_name(value) != BOOL:
            raise RuntimeError_(f"条件位置出现 {type_name(value).lower()}：条件必须是 bool", span)
        return bool(value)


def run_code(code: Code, *, max_steps: int = DEFAULT_MAX_STEPS,
             trace_limit: int = 0) -> VmResult:
    return VM(code, max_steps=max_steps, trace_limit=trace_limit).run()
