"""tinylang/tree_walk.py —— 参照实现：不生成任何指令，直接递归解释 AST。

它存在的唯一理由是**给 VM 当一个独立的答案来源**。两条路的差别刻意做得很大：
* 变量：这里用"作用域字典的名字 → 值"，VM 用整数槽位；
* 控制流：这里靠 Python 自身的 if/while 与递归，VM 靠跳转下标；
* 短路：这里用 Python 的 and/or，VM 用 JZ/JNZ + 两个补丁。

实现方式差这么多，输出还逐字节一致，才说明一致不是"两边抄了同一段代码"。
运算规则本身（values.py）是语言定义的一部分，两边必须共用——那部分抄了才是对的。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .nodes import (Assign, Binary, Block, BoolLit, Ident, If, IntLit, Node, Print,
                    Program, RealLit, StrLit, Unary, VarDecl, While)
from .spans import RuntimeError_, Span
from .values import binary_arith, compare, format_value, to_real, unary_arith

DEFAULT_MAX_STEPS = 200_000


@dataclass
class WalkResult:
    output: list = field(default_factory=list)
    steps: int = 0
    environment: dict = field(default_factory=dict)

    def text(self) -> str:
        return "\n".join(self.output)


class TreeWalker:
    def __init__(self, program: Program, *, max_steps: int = DEFAULT_MAX_STEPS):
        self.program = program
        self.max_steps = max_steps
        self.scopes: list[dict] = [{}]
        self.output: list[str] = []
        self.steps = 0

    # ---------------------------------------------------- 入口
    def run(self) -> WalkResult:
        for statement in self.program.stmts:
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
        raise RuntimeError_(f"树遍历器不认识 {type(node).__name__}", node.span)

    def bool_value(self, node: Node) -> bool:
        result = self.value(node)
        if not isinstance(result, bool):
            raise RuntimeError_("条件位置出现非 bool 值", node.span)
        return result


def interpret(program: Program, *, max_steps: int = DEFAULT_MAX_STEPS) -> WalkResult:
    return TreeWalker(program, max_steps=max_steps).run()
