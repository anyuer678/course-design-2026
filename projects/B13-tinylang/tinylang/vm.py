"""tinylang/vm.py —— 栈机执行器：结果、步数上限、可回溯的 trace。

四条防线，一条都不能省：
* **步数上限**：死循环在教学语言里太容易写出来（`while true do x := x;`）。
  没有上限，测试进程就挂在那儿；有上限，报的是"第 N 行大概死循环"而不是"没响应"。
* **栈下溢检测**：正常情况下代码生成保证栈平衡，所以一旦下溢就是编译器 bug。
  把它做成显式错误，比让 Python 抛 IndexError 更容易定位（后者不带你自己的行号）。
* **运行期类型/除零检查**：语义检查已经挡掉大部分，这里再挡一次是防线不是装饰——
  直接构造非法字节码的测试就是用来证明这道防线存在的。
* **调用帧的防御**：RET 时调用栈为空、CALL 编号/入口越界、NORET 不在函数体内，
  都是"手工构造的非法指令"才会出现的状态，全部做成带行号的显式错误。

调用帧（B41 候选②，口径见 docs/frames-spec.md）：帧是**显式的列表栈**——
`self.locals` 是当前帧的槽位数组，调用时把（返回地址、调用者帧、函数编号）
压进 `self.call_stack` 并换上新帧；返回时弹回。深度上限在压入前检查，
超过就是语言护栏报错；宿主语言一个递归都不用，所以 VM 侧不存在栈溢出风险。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .bytecode import (BIN, CALL, CMP, HALT, I2F, JNZ, JUMP, JZ, NAME_BY_INDEX, NORET,
                       PRINT, RET, LOAD, PUSH, STORE, UN, Code)
from .runtime import DEFAULT_MAX_CALL_DEPTH, depth_exceeded, missing_return
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
    depth: int = 0                 # 调用深度（0 = 顶层程序帧）

    def render(self) -> str:
        return (f"{self.pc:>5}  行{self.line:<3} {self.instruction:<18} "
                f"栈顶={self.stack_top!r:<10} 变量={self.locals_view} 深度={self.depth}")


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
                 trace_limit: int = 0, max_call_depth: int = DEFAULT_MAX_CALL_DEPTH):
        self.code = code
        self.max_steps = max_steps
        self.trace_limit = trace_limit
        self.max_call_depth = max_call_depth
        self.stack: list = []
        self.locals: list = [None] * max(code.locals_count, 1)   # 当前帧（顶层 = 全局槽位）
        self.call_stack: list = []      # [(返回地址, 调用者帧, 函数编号)]
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
                self.trace.append(Step(self.pc, instr.line, instr.render(self.code.constants,
                                                                        self.code.functions),
                                       self.stack[-1] if self.stack else None,
                                       list(self.locals), depth=len(self.call_stack)))
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
        elif op == CALL:
            self.call(instr, span)
        elif op == RET:
            self.ret(span)
        elif op == NORET:
            info = self.current_function()
            if info is None:
                raise RuntimeError_("NORET 被执行时不在任何函数体内（手工构造的非法指令）",
                                    span)
            raise missing_return(info.name, info.return_type, instr.line)
        elif op == HALT:
            return True
        else:
            raise RuntimeError_(f"未知指令 {op}", span)
        return False

    # ---------------------------------------------------- 调用帧
    def call(self, instr, span: Span) -> None:
        if instr.arg is None or not 0 <= instr.arg < len(self.code.functions):
            raise RuntimeError_(f"调用了不存在的函数编号 {instr.arg}", span)
        info = self.code.functions[instr.arg]
        if len(self.call_stack) >= self.max_call_depth:
            raise depth_exceeded(info.name, self.max_call_depth, instr.line)
        if not 0 <= info.entry < len(self.code.instrs):
            raise RuntimeError_(f"函数 {info.name!r} 的入口地址越界（{info.entry}）", span)
        frame = [None] * max(info.locals_count, info.arity, 1)
        for index in range(info.arity - 1, -1, -1):    # 先弹的实参填在后面的槽位
            frame[index] = self.pop(span)
        self.call_stack.append((self.pc, self.locals, instr.arg))
        self.locals = frame
        self.pc = info.entry

    def ret(self, span: Span) -> None:
        if not self.call_stack:
            raise RuntimeError_("RET 被执行时调用栈是空的（代码生成有误，或手工构造的非法指令）",
                                span)
        value = self.pop(span)
        return_pc, caller_locals, _ = self.call_stack.pop()
        self.locals = caller_locals
        self.pc = return_pc
        self.stack.append(value)

    def current_function(self):
        return self.code.functions[self.call_stack[-1][2]] if self.call_stack else None

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
             trace_limit: int = 0,
             max_call_depth: int = DEFAULT_MAX_CALL_DEPTH) -> VmResult:
    return VM(code, max_steps=max_steps, trace_limit=trace_limit,
              max_call_depth=max_call_depth).run()
