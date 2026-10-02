"""tinylang/codegen.py —— AST → 栈机字节码。

**前置条件**：必须先跑过语义检查。每个节点的类型与槽位是检查器就地标注的，
代码生成读这些标注，不再自己推一遍类型——两处推断迟早会不一致，
那种不一致表现为"检查通过但运行期炸了"，比直接报错难查一个数量级。
所以这里对齐写检查器的字段，缺标注就立刻抛 CodegenError，而不是默默生成半条指令。

跳转与回填（本课设最容易写错的地方）：
* `if` / `while` / `and` / `or` 都需要**先知道目标位置才能生成跳转，但目标位置在生成之后才出现**。
  做法是：先占位（参数写 0），把占位下标压进"待 patch 列表"，代码生成到那个标签时统一回填。
* 忘记 patch 会怎样？跳转参数停在 0，VM 会跳到第一条指令——表现为"程序死循环"或"重复执行开头"，
  而且没有任何错误信息。所以测试里除了运行结果对拍，还直接断言反汇编里的跳转目标。
* `and/or` 用 JZ/JNZ（弹出测试）而不是"压两份值"，这样短路才真实存在：
  `x != 0 and 10 / x > 1` 在 x 为 0 时不会算除法。
"""
from __future__ import annotations

from .bytecode import (BIN, CALL, CMP, HALT, I2F, JNZ, JUMP, JZ, NORET, OP_INDEX,
                       PRINT, PUSH, RET, LOAD, STORE, UN, Code, FunctionInfo)
from .nodes import (Assign, Binary, Block, BoolLit, Call, FunDef, Ident, If, IntLit,
                    Node, Print, Program, RealLit, Return, StrLit, Unary, VarDecl, While)
from .spans import CodegenError


class Compiler:
    def __init__(self, program: Program, source: str = ""):
        self.program = program
        self.code = Code(locals_count=program.locals_count, source=source)
        self.line = 0
        self.current_return_type: str | None = None

    # ---------------------------------------------------- 入口
    def compile(self) -> Code:
        """布局：主线在前（含全局槽位），函数体按定义顺序排在主线 HALT 之后。
        CALL 的参数是函数表下标而不是地址，所以主线里发出的 CALL 不需要回填——
        entry 是函数表项在函数体生成完时填的。"""
        for statement in self.program.stmts:
            if isinstance(statement, FunDef):
                continue
            self.statement(statement)
        self.emit(HALT)
        for statement in self.program.stmts:
            if isinstance(statement, FunDef):
                self.function(statement)
        return self.code

    def function(self, node: FunDef) -> None:
        if node.func_index is None:
            raise CodegenError(f"函数 {node.name!r} 没有编号（语义检查没跑过？）", node.span)
        if node.func_index != len(self.code.functions):
            raise CodegenError(f"函数编号 {node.func_index} 与定义顺序不一致"
                               f"（表里已有 {len(self.code.functions)} 个）", node.span)
        self.code.functions.append(FunctionInfo(
            name=node.name, entry=len(self.code.instrs), locals_count=node.locals_count,
            arity=len(node.params),
            param_types=tuple(p.declared_type.upper() for p in node.params),
            return_type=node.return_type.upper()))
        saved_return_type = self.current_return_type
        self.current_return_type = node.return_type.upper()
        try:
            self._at(node)
            self.statement(node.body)
            end_line = node.body.span.end_line or self.line
            self.code.add(NORET, None, end_line)     # 走到这里 = 缺 return，运行期报
        finally:
            self.current_return_type = saved_return_type

    def emit(self, op: str, arg=None) -> int:
        return self.code.add(op, arg, self.line)

    def _at(self, node: Node) -> None:
        self.line = node.span.line or self.line

    # ---------------------------------------------------- 语句
    def statement(self, node: Node) -> None:
        self._at(node)
        if isinstance(node, VarDecl):
            self.expr(node.init, want=node.declared_type.upper())
            self.store(node)
        elif isinstance(node, Assign):
            self.expr(node.expr, want=node.target_type)
            self.emit(STORE, node.slot)
        elif isinstance(node, Print):
            self.expr(node.expr)
            self.emit(PRINT)
        elif isinstance(node, If):
            self.if_statement(node)
        elif isinstance(node, While):
            self.while_statement(node)
        elif isinstance(node, Block):
            for statement in node.stmts:
                self.statement(statement)
        elif isinstance(node, Return):
            if self.current_return_type is None:
                raise CodegenError("return 出现在函数体之外（语义检查没跑过？）", node.span)
            self.expr(node.expr, want=self.current_return_type)
            self.emit(RET)
        else:
            raise CodegenError(f"不支持的语句节点 {type(node).__name__}", node.span)

    def store(self, node: VarDecl) -> None:
        if node.slot is None:
            raise CodegenError(f"变量 {node.name!r} 没有分配槽位（语义检查没跑过？）", node.span)
        self.emit(STORE, node.slot)

    def if_statement(self, node: If) -> None:
        self.expr(node.cond)
        jump_to_else = self.emit(JZ, 0)                 # 参数先占位，稍后回填
        self.statement(node.then_branch)
        if node.else_branch is None:
            self.code.patch(jump_to_else, len(self.code.instrs))
            return
        jump_over_else = self.emit(JUMP, 0)
        self.code.patch(jump_to_else, len(self.code.instrs))
        self.statement(node.else_branch)
        self.code.patch(jump_over_else, len(self.code.instrs))

    def while_statement(self, node: While) -> None:
        start = len(self.code.instrs)
        self.expr(node.cond)
        jump_to_end = self.emit(JZ, 0)
        self.statement(node.body)
        self.emit(JUMP, start)
        self.code.patch(jump_to_end, len(self.code.instrs))

    # ---------------------------------------------------- 表达式
    def expr(self, node: Node, want: str | None = None) -> None:
        """求值并把结果压栈；want='REAL' 且本身是 int 时补一条 I2F。"""
        self._at(node)
        produced = self._emit_value(node)
        if want == "REAL" and produced == "INT":
            self.emit(I2F)

    def _emit_value(self, node: Node) -> str | None:
        self._at(node)
        if isinstance(node, IntLit):
            self.emit(PUSH, self.code.constant(node.value))
            return "INT"
        if isinstance(node, RealLit):
            self.emit(PUSH, self.code.constant(node.value))
            return "REAL"
        if isinstance(node, StrLit):
            self.emit(PUSH, self.code.constant(node.value))
            return "STRING"
        if isinstance(node, BoolLit):
            self.emit(PUSH, self.code.constant(node.value))
            return "BOOL"
        if isinstance(node, Ident):
            if node.type is None or node.slot is None:
                raise CodegenError(f"变量 {node.name!r} 缺少类型或槽位标注", node.span)
            self.emit(LOAD, node.slot)
            return node.type
        if isinstance(node, Unary):
            if node.type is None:
                raise CodegenError("一元表达式未标注类型", node.span)
            self._emit_value(node.operand)
            self.emit(UN, OP_INDEX[node.op])
            return node.type
        if isinstance(node, Binary):
            return self.binary(node)
        if isinstance(node, Call):
            if node.func_index is None or node.type is None or node.param_types is None:
                raise CodegenError(f"调用 {node.name!r} 缺少函数编号或类型标注"
                                   "（语义检查没跑过？）", node.span)
            for arg, want in zip(node.args, node.param_types):
                self.expr(arg, want=want)        # 实参加宽在调用点显式发生
            self.emit(CALL, node.func_index)
            return node.type
        raise CodegenError(f"不支持的表达式节点 {type(node).__name__}", node.span)

    def binary(self, node: Binary) -> str:
        if node.type is None:
            raise CodegenError(f"表达式 {node.op!r} 未标注类型（语义检查没跑过？）", node.span)
        if node.op in ("and", "or"):
            self.short_circuit(node)
            return "BOOL"
        if node.operand_type is None:
            raise CodegenError(f"运算符 {node.op!r} 缺少操作数类型标注", node.span)
        want = node.operand_type          # INT 操作数在这里被显式加宽成 REAL
        self.expr(node.left, want=want)
        self.expr(node.right, want=want)
        if node.op in ("=", "!=", "<", "<=", ">", ">="):
            self.emit(CMP, OP_INDEX[node.op])
        else:
            self.emit(BIN, OP_INDEX[node.op])
        return node.type

    def short_circuit(self, node: Binary) -> None:
        """and/or 的短路形式：JZ/JNZ 弹出测试，两条分支各压一个 bool 常量。"""
        left_truthy = JNZ if node.op == "or" else JZ
        self.expr(node.left)
        first_exit = self.emit(left_truthy, 0)
        self.expr(node.right)
        second_exit = self.emit(left_truthy, 0)
        self.emit(PUSH, self.code.constant(node.op == "and"))       # and 走到这里是 false
        merge = self.emit(JUMP, 0)
        self.code.patch(first_exit, len(self.code.instrs))
        self.code.patch(second_exit, len(self.code.instrs))
        self.emit(PUSH, self.code.constant(node.op == "or"))        # or 走到这里是 true
        self.code.patch(merge, len(self.code.instrs))


def generate(program: Program, source: str = "") -> Code:
    return Compiler(program, source).compile()
