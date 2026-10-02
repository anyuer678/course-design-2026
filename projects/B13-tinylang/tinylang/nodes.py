"""tinylang/nodes.py —— AST 节点。

两点设计决定：
* **每个节点都带 Span**。语义检查、字节码行号表、运行时错误定位全靠它；
  一处漏了 span，错误就只能说"某处有问题"。
* **节点是可变的，语义检查阶段就地标注**。真实编译器基本都这么干（属性文法）：
  检查器把 `type`、`slot` 写回节点，代码生成读标注而不是重新推一遍类型——
  两处推断迟早会不一致，而"类型检查通过但代码生成按另一套规则走"是经典事故。

遍历写成通用的 `children()`（按 dataclass 字段顺序），新增节点类型不必同时改一圈 visitor。
"""
from __future__ import annotations

from dataclasses import dataclass, fields

from .spans import NO_SPAN, Span

BOOL, INT, REAL, STRING = "BOOL", "INT", "REAL", "STRING"
TYPES = (BOOL, INT, REAL, STRING)
NUMERIC = (INT, REAL)


@dataclass
class Node:
    span: Span = NO_SPAN

    def children(self):
        """按字段顺序给出子节点（Node 或 Node 列表）。"""
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, Node):
                yield value
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, Node):
                        yield item

    def walk(self):
        """前序遍历自己与所有后代节点。"""
        yield self
        for child in self.children():
            yield from child.walk()


# ---------------------------------------------------------------- 表达式


@dataclass
class IntLit(Node):
    value: int = 0
    type: str = INT


@dataclass
class RealLit(Node):
    value: float = 0.0
    type: str = REAL


@dataclass
class StrLit(Node):
    value: str = ""
    type: str = STRING


@dataclass
class BoolLit(Node):
    value: bool = False
    type: str = BOOL


@dataclass
class Ident(Node):
    name: str = ""
    type: str | None = None
    slot: int | None = None
    name_span: Span = NO_SPAN


@dataclass
class Unary(Node):
    op: str = ""
    operand: Node = None
    type: str | None = None


@dataclass
class Binary(Node):
    op: str = ""
    left: Node = None
    right: Node = None
    type: str | None = None        # 结果类型；比较与逻辑运算结果是 BOOL
    operand_type: str | None = None  # 算术/比较的操作数类型（BOOL 结果时才有意义）


# ---------------------------------------------------------------- 语句


@dataclass
class VarDecl(Node):
    name: str = ""
    declared_type: str = ""
    init: Node = None
    name_span: Span = NO_SPAN
    slot: int | None = None


@dataclass
class Assign(Node):
    name: str = ""
    expr: Node = None
    name_span: Span = NO_SPAN
    slot: int | None = None
    target_type: str | None = None


@dataclass
class Print(Node):
    expr: Node = None


@dataclass
class If(Node):
    cond: Node = None
    then_branch: Node = None
    else_branch: Node | None = None


@dataclass
class While(Node):
    cond: Node = None
    body: Node = None


@dataclass
class Block(Node):
    stmts: list = None


@dataclass
class Program(Node):
    stmts: list = None
    locals_count: int = 0          # 检查器分配完槽位后的总数，代码生成与 VM 用它开栈帧
