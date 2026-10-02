"""tinylang/reporting.py —— 把内部结构打成人类能核对的文本。

优先级这类事情，光看代码注释是检查不出来的；把 AST 打成 s-表达式，
"1 + 2 * 3" 到底长成 +(1, *(2,3)) 还是 *(+(1,2),3) 一眼就看得见，测试也能直接断言形状。
"""
from __future__ import annotations

from .nodes import (Assign, Binary, Block, BoolLit, Call, FunDef, Ident, If, IntLit,
                    Node, Print, Program, RealLit, Return, StrLit, Unary, VarDecl, While)


def format_ast(node: Node, indent: int = 0) -> str:
    """s-表达式形式的 AST，带行号；不打印列号是因为那会把形状挤成一团。"""
    pad = "  " * indent
    at = f"  (行{node.span.line})" if node.span.line else ""
    if isinstance(node, Program):
        return _block_lines("program", node.stmts, indent)
    if isinstance(node, Block):
        return _block_lines("block", node.stmts, indent)
    if isinstance(node, FunDef):
        params = ", ".join(f"{p.name} : {p.declared_type}" for p in node.params)
        head = f"{pad}fun {node.name}({params}) -> {node.return_type}"
        return head + "\n" + format_ast(node.body, indent + 1)
    if isinstance(node, Return):
        return f"{pad}return" + "\n" + format_ast(node.expr, indent + 1)
    if isinstance(node, Call):
        lines = [f"{pad}call {node.name}{at}"]
        lines += [format_ast(arg, indent + 1) for arg in node.args]
        return "\n".join(lines)
    if isinstance(node, VarDecl):
        head = f"{pad}let {node.name} : {node.declared_type} :="
        return head + "\n" + format_ast(node.init, indent + 1)
    if isinstance(node, Assign):
        return f"{pad}assign {node.name}" + "\n" + format_ast(node.expr, indent + 1)
    if isinstance(node, Print):
        return f"{pad}print" + "\n" + format_ast(node.expr, indent + 1)
    if isinstance(node, If):
        lines = [f"{pad}if{at}", format_ast(node.cond, indent + 1),
                 f"{pad}then", format_ast(node.then_branch, indent + 1)]
        if node.else_branch is not None:
            lines += [f"{pad}else", format_ast(node.else_branch, indent + 1)]
        return "\n".join(lines)
    if isinstance(node, While):
        return (f"{pad}while{at}\n" + format_ast(node.cond, indent + 1)
                + f"\n{pad}do\n" + format_ast(node.body, indent + 1))
    if isinstance(node, Binary):
        return (f"{pad}({node.op}){at}\n" + format_ast(node.left, indent + 1)
                + "\n" + format_ast(node.right, indent + 1))
    if isinstance(node, Unary):
        return f"{pad}({node.op}){at}\n" + format_ast(node.operand, indent + 1)
    if isinstance(node, Ident):
        return f"{pad}{node.name}{at}"
    if isinstance(node, BoolLit):
        return f"{pad}{'true' if node.value else 'false'}{at}"
    if isinstance(node, IntLit):
        return f"{pad}{node.value}{at}"
    if isinstance(node, RealLit):
        return f"{pad}{node.value!r}{at}"
    if isinstance(node, StrLit):
        return f"{pad}{node.value!r}{at}"
    return f"{pad}{type(node).__name__}{at}"


def _block_lines(name: str, stmts: list, indent: int) -> str:
    pad = "  " * indent
    if not stmts:
        return f"{pad}{name} (空)"
    body = "\n".join(format_ast(item, indent + 1) for item in stmts)
    return f"{pad}{name}\n{body}"


def shape(node: Node) -> str:
    """单行形状：`(op 左 右)`，专门用来断言优先级与结合性。"""
    if isinstance(node, Binary):
        return f"({node.op} {shape(node.left)} {shape(node.right)})"
    if isinstance(node, Unary):
        return f"({node.op} {shape(node.operand)})"
    if isinstance(node, Call):
        inner = " ".join(shape(arg) for arg in node.args)
        return f"(call {node.name}{' ' + inner if inner else ''})"
    if isinstance(node, Return):
        return f"(return {shape(node.expr)})"
    if isinstance(node, FunDef):
        params = " ".join(f"({p.name} {p.declared_type})" for p in node.params)
        return (f"(fun {node.name} [{params}] {node.return_type} {shape(node.body)})")
    if isinstance(node, Print):
        return f"(print {shape(node.expr)})"
    if isinstance(node, Assign):
        return f"(assign {node.name} {shape(node.expr)})"
    if isinstance(node, VarDecl):
        return f"(let {node.name} {node.declared_type} {shape(node.init)})"
    if isinstance(node, If):
        if node.else_branch is None:
            return f"(if {shape(node.cond)} {shape(node.then_branch)})"
        return (f"(if {shape(node.cond)} {shape(node.then_branch)} "
                f"{shape(node.else_branch)})")
    if isinstance(node, While):
        return f"(while {shape(node.cond)} {shape(node.body)})"
    if isinstance(node, Block):
        return "(block " + " ".join(shape(item) for item in node.stmts) + ")"
    if isinstance(node, Program):
        return "(program " + " ".join(shape(item) for item in node.stmts) + ")"
    if isinstance(node, Ident):
        return node.name
    if isinstance(node, BoolLit):
        return "true" if node.value else "false"
    return repr(node.value)
