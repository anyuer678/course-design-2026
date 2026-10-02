"""tinylang/tree_walk.py —— 参照实现：不生成任何指令，直接递归解释 AST。

它存在的唯一理由是**给 VM 当一个独立的答案来源**。两条路的差别刻意做得很大：
* 变量：这里用"作用域字典的名字 → 值"，VM 用整数槽位；
* 控制流：这里靠 Python 自身的 if/while 与递归，VM 靠跳转下标；
* 短路：这里用 Python 的 and/or，VM 用 JZ/JNZ + 两个补丁；
* 调用（B41 候选②）：这里把整个作用域栈换成"形参一层"、用 Python 递归执行函数体、
  用宿主异常传递 return 值；VM 用显式帧栈与 CALL/RET 指令。

实现方式差这么多，输出还逐字节一致，才说明一致不是"两边抄了同一段代码"。
运算规则本身（values.py）是语言定义的一部分，两边必须共用——那部分抄了才是对的。

宿主栈护栏：递归的每一层要消耗若干 Python 栈帧（每层最坏 ≈ 2 × 表达式嵌套深度 + 常数，
表达式嵌套已被解析器钉死在 MAX_EXPRESSION_DEPTH）。所以 interpret() 入口把
sys.setrecursionlimit 临时提升到"深度上限 × 每层最坏帧数 + 余量"再跑——
不提升的话 RecursionError 会抢在语言自己的深度上限之前触发，两条后端报的
就不是同一件事、同一条深度了（口径见 docs/frames-spec.md §五）。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

from .nodes import (Assign, Binary, Block, BoolLit, Call, FunDef, Ident, If, IntLit,
                    Node, Print, Program, RealLit, Return, StrLit, Unary, VarDecl, While)
from .parser import MAX_EXPRESSION_DEPTH
from .runtime import DEFAULT_MAX_CALL_DEPTH, depth_exceeded, missing_return
from .spans import RuntimeError_, Span
from .values import binary_arith, compare, format_value, to_real, unary_arith

DEFAULT_MAX_STEPS = 200_000


class _ReturnSignal(Exception):
    """return 的载体：函数体执行中抛出，由调用边界接住取值。"""

    def __init__(self, value):
        super().__init__("return")
        self.value = value


@dataclass
class WalkResult:
    output: list = field(default_factory=list)
    steps: int = 0
    environment: dict = field(default_factory=dict)

    def text(self) -> str:
        return "\n".join(self.output)


class TreeWalker:
    def __init__(self, program: Program, *, max_steps: int = DEFAULT_MAX_STEPS,
                 max_call_depth: int = DEFAULT_MAX_CALL_DEPTH):
        self.program = program
        self.max_steps = max_steps
        self.max_call_depth = max_call_depth
        self.scopes: list[dict] = [{}]
        self.output: list[str] = []
        self.steps = 0
        self.call_depth = 0
        self.functions: dict = {}       # 名字 → (param_types, return_type, FunDef)
        for statement in program.stmts:
            if isinstance(statement, FunDef):
                self.functions[statement.name] = (
                    [p.declared_type.upper() for p in statement.params],
                    statement.return_type.upper(), statement)

    # ---------------------------------------------------- 入口
    def run(self) -> WalkResult:
        for statement in self.program.stmts:
            if isinstance(statement, FunDef):     # 函数体只通过调用进入
                continue
            self.statement(statement)
        merged: dict = {}
        for scope in self.scopes:
            merged.update(scope)
        return WalkResult(output=self.output, steps=self.steps, environment=merged)

    def _tick(self, node: Node) -> None:
        self.steps += 1
        if self.steps > self.max_steps:
            raise RuntimeError_(f"树遍历步数超过上限 {self.max_steps}", node.span,
                                "大概是死循环")

    # ---------------------------------------------------- 语句
    def statement(self, node: Node) -> None:
        self._tick(node)
        if isinstance(node, VarDecl):
            self.current()[node.name] = self.value(node.init, node.declared_type.upper())
        elif isinstance(node, Assign):
            if node.name not in self.current() and self.lookup(node.name) is None:
                raise RuntimeError_(f"给未声明的变量 {node.name!r} 赋值", node.name_span)
            self.assign(node.name, self.value(node.expr, node.target_type))
        elif isinstance(node, Print):
            self.output.append(format_value(self.value(node.expr)))
        elif isinstance(node, If):
            if self.bool_value(node.cond):
                self.statement(node.then_branch)
            elif node.else_branch is not None:
                self.statement(node.else_branch)
        elif isinstance(node, While):
            while self.bool_value(node.cond):
                self._tick(node)
                self.statement(node.body)
        elif isinstance(node, Block):
            self.scopes.append({})
            try:
                for statement in node.stmts:
                    self.statement(statement)
            finally:
                self.scopes.pop()
        elif isinstance(node, Return):
            if self.call_depth == 0:
                raise RuntimeError_("return 出现在函数体之外（语义检查没拦住？）", node.span)
            raise _ReturnSignal(self.value(node.expr))
        else:
            raise RuntimeError_(f"树遍历器不认识 {type(node).__name__}", node.span)

    # ---------------------------------------------------- 作用域
    def current(self) -> dict:
        return self.scopes[-1]

    def lookup(self, name: str):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope
        return None

    def assign(self, name: str, value) -> None:
        scope = self.lookup(name)
        if scope is None:
            raise RuntimeError_(f"给未声明的变量 {name!r} 赋值", Span(self._line(), 1, self._line(), 1))
        scope[name] = value

    def _line(self) -> int:
        return getattr(self, "_current_line", 0)

    # ---------------------------------------------------- 表达式
    def value(self, node: Node, want: str | None = None):
        self._current_line = node.span.line
        result = self._value(node)
        if want == "REAL" and isinstance(result, int) and not isinstance(result, bool):
            result = to_real(result)               # 与 VM 的 I2F 同一规则
        return result

    def _value(self, node: Node):
        self._tick(node)
        if isinstance(node, (IntLit, RealLit, StrLit, BoolLit)):
            return node.value
        if isinstance(node, Ident):
            scope = self.lookup(node.name)
            if scope is None:
                raise RuntimeError_(f"读取未声明的变量 {node.name!r}", node.span)
            return scope[node.name]
        if isinstance(node, Unary):
            return unary_arith(node.op, self.value(node.operand), node.span)
        if isinstance(node, Binary):
            if node.op == "and":
                return self.bool_value(node.left) and self.bool_value(node.right)
            if node.op == "or":
                return self.bool_value(node.left) or self.bool_value(node.right)
            left = self.value(node.left, node.operand_type)
            right = self.value(node.right, node.operand_type)
            if node.op in ("=", "!=", "<", "<=", ">", ">="):
                return compare(node.op, left, right, node.span)
            return binary_arith(node.op, left, right, node.span)
        if isinstance(node, Call):
            return self.call_function(node)
        raise RuntimeError_(f"树遍历器不认识 {type(node).__name__}", node.span)

    def call_function(self, node: Call):
        info = self.functions.get(node.name)
        if info is None:
            raise RuntimeError_(f"调用了未定义的函数 {node.name!r}（语义检查没拦住？）",
                                node.span)
        param_types, return_type, definition = info
        if len(node.args) != len(param_types):
            raise RuntimeError_(f"函数 {node.name!r} 的参数个数不符（语义检查没拦住？）",
                                node.span)
        args = [self.value(arg, want) for arg, want in zip(node.args, param_types)]
        if self.call_depth >= self.max_call_depth:
            raise depth_exceeded(node.name, self.max_call_depth, node.span.line)
        scope = {param.name: value for param, value in zip(definition.params, args)}
        saved_scopes = self.scopes
        self.scopes = [scope]
        self.call_depth += 1
        try:
            self.statement(definition.body)
        except _ReturnSignal as signal:
            value = signal.value
            if return_type == "REAL" and isinstance(value, int) and not isinstance(value, bool):
                value = to_real(value)           # 与 VM 的 I2F 同一规则
            return value
        finally:
            self.scopes = saved_scopes
            self.call_depth -= 1
        raise missing_return(node.name, return_type,
                             definition.body.span.end_line or node.span.line)

    def bool_value(self, node: Node) -> bool:
        result = self.value(node)
        if not isinstance(result, bool):
            raise RuntimeError_("条件位置出现非 bool 值", node.span)
        return result


def interpret(program: Program, *, max_steps: int = DEFAULT_MAX_STEPS,
              max_call_depth: int = DEFAULT_MAX_CALL_DEPTH) -> WalkResult:
    # 宿主栈护栏：把 Python 的递归上限临时提到"语言深度上限 × 每层最坏帧数 + 余量"。
    # 每层最坏 ≈ 2 × 表达式嵌套（value → _value 各一帧）+ 语句/调用边界常数；
    # 表达式嵌套已被解析器钉死，所以这个上界是**可计算**的，不是拍脑袋。
    needed = (max_call_depth + 8) * (2 * MAX_EXPRESSION_DEPTH + 12) + 1000
    old_limit = sys.getrecursionlimit()
    if old_limit < needed:
        sys.setrecursionlimit(needed)
    try:
        return TreeWalker(program, max_steps=max_steps,
                          max_call_depth=max_call_depth).run()
    finally:
        sys.setrecursionlimit(old_limit)
