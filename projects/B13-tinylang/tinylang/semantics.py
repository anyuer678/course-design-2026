"""tinylang/semantics.py —— 语义检查：作用域、类型、槽位分配，并且一次报全部错误。

**为什么必须"一次全报"**：本课设的验收标准是"语义错误不许被跑通掩盖"。
逐条报（fail-fast）会让一个 200 行的程序改一个错跑一次，也让人误以为"修完这条就能跑"。
所以这里把所有错误收集起来、按源码位置排序输出；错误太多时截断并说明还剩几条。

类型规则（这些是**语言决定**，不是自然规律，写在 README 里给读者看）：
* 四种类型：int / real / bool / string。
* **只有 int → real 自动加宽**（记在节点上，由代码生成发出显式 I2F 指令）。
  real → int 一律拒绝：截断方式（floor / round / truncate）必须让程序员选。
* bool 与数字之间不互转：`if 1 then` 是错误，不是"真"。`x = true` 与 `x = 1` 也不同义。
* `/` 与 `%`：两边都是 int 时结果是 int，按 **floor** 语义（-7/2 = -4，-7%2 = 1）；
  任一边是 real 时结果是 real 的除法与 fmod。这一点必须写清并有测试钉住。
* 字符串只支持 `+`（拼接）与 `= !=`；`< >` 明确拒绝——不是不能做，是做了就得规定编码顺序。
* `and / or / not` 只吃 bool；**不做短路类型放宽**。
* 条件必须是 bool；`print` 吃任何类型。

作用域：块 `{ … }` 新开一层，允许遮蔽外层同名变量（遮蔽时分配新槽位）；
同一层重复 `let` 是错误。初始化表达式在**外层**作用域求值，
所以块里的 `let x : int := x;` 用的是外面那个 x——这条也写了测试。

函数（B41 候选②，完整规则见 docs/frames-spec.md）：
* 单遍检查、**先定义后使用**；函数体检查时自身已登记，所以自递归可用，互递归不支持。
* 函数名与变量名禁止重名（两个命名空间，但撞名一律报错——规则简单好解释）。
* **函数体看不到全局变量**：形参 + 自身局部就是全部（没有闭包、没有全局）。
  每个函数的槽位从 0 独立分配：形参占 0..arity-1，局部从 arity 起。
* `return` 只能在函数体内；缺 return 不做静态流分析，交给运行期报（两个后端同一句话）。
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from .nodes import (Assign, Binary, Block, BoolLit, Call, FunDef, Ident, If, IntLit,
                    Node, Param, Print, Program, RealLit, Return, StrLit, Unary,
                    VarDecl, While)
from .spans import NO_SPAN, SemanticError, Span

ARITHMETIC = ("+", "-", "*", "/", "%")
COMPARISONS = ("=", "!=", "<", "<=", ">", ">=")
LOGIC = ("and", "or")
MAX_ERRORS = 40


@dataclass
class Symbol:
    name: str
    type: str
    slot: int
    declared_at: Span = NO_SPAN


class Checker:
    def __init__(self, program: Program):
        self.program = program
        self.scopes: list[dict] = [{}]          # 第 0 层是全局
        self.errors: list = []
        self.truncated = False
        self.next_slot = 0
        self.functions: dict = {}               # 函数名 → {index, param_types, return_type}
        self.next_func = 0
        self.function_depth = 0                 # >0 表示正在检查函数体（return 合法性）
        self.current_return_type: str | None = None
        self.visible_floor = 0                  # 函数体内把全局作用域遮住（没有全局变量）

    # ---------------------------------------------------- 入口
    def run(self) -> list:
        for statement in self.program.stmts:
            self.visit_statement(statement)
        self.program.locals_count = self.next_slot
        self.errors.sort(key=lambda e: (e.span.line, e.span.col))
        return self.errors

    def _error(self, message: str, span: Span, hint: str = "") -> None:
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(SemanticError(message, span, hint))
        elif not self.truncated:
            self.truncated = True
            self.errors.append(SemanticError(
                f"错误太多（超过 {MAX_ERRORS} 条），先修前面这些再重新检查",
                span, "后面的错误没有列出来，不是它们不存在"))

    # ---------------------------------------------------- 作用域
    def lookup(self, name: str):
        for scope in reversed(self.scopes[self.visible_floor:]):
            if name in scope:
                return scope[name]
        return None

    def _suggest(self, name: str) -> str:
        known = [symbol.name for scope in self.scopes[self.visible_floor:]
                 for symbol in scope.values()]
        close = difflib.get_close_matches(name, known, n=1, cutoff=0.6)
        return f"是不是想写 {close[0]!r}？" if close else f"当前可见的变量：{known or '（无）'}"

    # ---------------------------------------------------- 语句
    def visit_statement(self, node: Node, in_body: bool = False) -> None:
        if isinstance(node, VarDecl):
            if in_body:
                # if/while 的单条语句位置不接 let：那样会把符号声明到外层作用域，
                # 而槽位却只在分支执行时才有值——读得到名字、拿不到值，是最难查的一类 bug。
                self._error("let 不能直接作为 if/while 的语句体", node.span,
                            "把声明放进块里：if c then { let x : int := 1; }")
                return
            self.visit_let(node)
        elif isinstance(node, Assign):
            self.visit_assign(node)
        elif isinstance(node, Print):
            self.type_of(node.expr)
        elif isinstance(node, If):
            self._require_bool(node.cond, "if 的条件")
            self.visit_statement(node.then_branch, in_body=True)
            if node.else_branch is not None:
                self.visit_statement(node.else_branch, in_body=True)
        elif isinstance(node, While):
            self._require_bool(node.cond, "while 的条件")
            self.visit_statement(node.body, in_body=True)
        elif isinstance(node, Block):
            self.scopes.append({})
            try:
                for statement in node.stmts:
                    self.visit_statement(statement)
            finally:
                self.scopes.pop()
        elif isinstance(node, Return):
            self.visit_return(node)
        elif isinstance(node, FunDef):
            self.visit_fundef(node)
        else:
            self._error(f"不支持的语句节点 {type(node).__name__}", node.span)

    # ---------------------------------------------------- 函数
    def visit_fundef(self, node: FunDef) -> None:
        if len(self.scopes) != 1:
            self._error("函数只能在顶层定义", node.span, "嵌套函数不在本语言范围内")
            return
        if node.name in self.functions:
            self._error(f"函数 {node.name!r} 已经定义过", node.name_span)
        if node.name in self.scopes[0]:
            self._error(f"函数名 {node.name!r} 和已声明的变量重名", node.name_span,
                        "函数名与变量名是两个命名空间，但本语言禁止重名")
        # 先登记再检查函数体：自递归因此天然可用；元组顺序保证互递归不可用（后定义不可见）
        node.func_index = self.next_func
        self.next_func += 1
        self.functions[node.name] = {"index": node.func_index,
                                     "param_types": [p.declared_type.upper() for p in node.params],
                                     "return_type": node.return_type.upper()}
        # 形参与函数体在**独立的槽位空间**里检查：帧从 0 开始，装得下函数能看到的一切；
        # visible_floor 同时把全局作用域遮住（函数体看不到全局变量）
        self.scopes.append({})
        saved_next_slot = self.next_slot
        saved_return_type = self.current_return_type
        saved_floor = self.visible_floor
        self.next_slot = 0
        self.current_return_type = node.return_type.upper()
        self.visible_floor = len(self.scopes) - 1
        self.function_depth += 1
        try:
            for param in node.params:
                self.visit_param(param)
            self.visit_statement(node.body)
            node.locals_count = self.next_slot
        finally:
            self.function_depth -= 1
            self.current_return_type = saved_return_type
            self.next_slot = saved_next_slot
            self.visible_floor = saved_floor
            self.scopes.pop()

    def visit_param(self, param: Param) -> None:
        current = self.scopes[-1]
        if param.name in current:
            self._error(f"参数 {param.name!r} 重复", param.name_span)
            return
        if param.name in self.functions:
            self._error(f"参数 {param.name!r} 和函数重名", param.name_span,
                        "函数名与变量名不能重名")
            # 仍然照常登记：函数体里引用它按参数理解，不再级联报一条"函数名当值用"
        current[param.name] = Symbol(param.name, param.declared_type.upper(),
                                     self.next_slot, param.name_span)
        self.next_slot += 1

    def visit_return(self, node: Return) -> None:
        if self.function_depth == 0:
            self._error("return 只能出现在函数体内", node.span,
                        "顶层语句写到结尾自然结束，没有可返回的值")
            self.type_of(node.expr)              # 表达式仍然检查，错误不互相掩盖
            return
        found = self.type_of(node.expr)
        if found is not None and not self.assignable(found, self.current_return_type):
            self._error(f"return 的值是 {found.lower()}，函数声明的返回类型是 "
                        f"{self.current_return_type.lower()}", node.span,
                        self.widening_hint(found, self.current_return_type))

    def _suggest_function(self, name: str) -> str:
        close = difflib.get_close_matches(name, list(self.functions), n=1, cutoff=0.6)
        return f"是不是想写 {close[0]!r}？" if close else f"已定义的函数：{list(self.functions) or '（无）'}"

    def visit_let(self, node: VarDecl) -> None:
        # 语法里的类型名是小写（int），表达式类型内部用大写（INT）。
        # AST 保留写法不动，只在比较时统一：这样 --ast 打印出来仍是用户写的那个词。
        declared = node.declared_type.upper()
        init_type = self.type_of(node.init)
        if init_type is not None and not self.assignable(init_type, declared):
            self._error(f"{node.name} 声明为 {node.declared_type}，"
                        f"但初始值是 {init_type.lower()}", node.name_span,
                        self.widening_hint(init_type, declared))
        current = self.scopes[-1]
        if node.name in current:
            self._error(f"变量 {node.name!r} 在本作用域已经声明过", node.name_span,
                        "换个名字，或者把它放进 { } 块里遮蔽外层变量")
            return
        if node.name in self.functions:
            self._error(f"变量名 {node.name!r} 和函数重名", node.name_span,
                        "函数名与变量名不能重名：换一个变量名")
            return
        node.slot = self.next_slot
        self.next_slot += 1
        current[node.name] = Symbol(node.name, declared, node.slot, node.name_span)

    def visit_assign(self, node: Assign) -> None:
        symbol = self.lookup(node.name)
        if symbol is None:
            if node.name in self.functions:
                self._error(f"函数名 {node.name!r} 不能作为变量赋值", node.name_span,
                            f"函数不是一等值；要调用请写 {node.name}(…)")
            else:
                hint = "先用 let 声明；本语言不允许隐式创建变量。"
                if self.function_depth > 0:
                    hint += "函数体只能看到形参与自身局部变量（没有全局变量）。"
                self._error(f"给未声明的变量 {node.name!r} 赋值", node.name_span,
                            hint + self._suggest(node.name))
            self.type_of(node.expr)              # 仍然检查右端，错误不互相掩盖
            return
        value_type = self.type_of(node.expr)
        if value_type is not None and not self.assignable(value_type, symbol.type):
            self._error(f"不能把 {value_type.lower()} 赋给 {symbol.type.lower()} 类型的 {node.name!r}",
                        node.name_span, self.widening_hint(value_type, symbol.type))
        node.slot = symbol.slot
        node.target_type = symbol.type

    # ---------------------------------------------------- 表达式类型
    def type_of(self, node: Node) -> str | None:
        """返回节点类型；未知/出错返回 None，调用方必须容忍 None 而不再级联报错。"""
        if isinstance(node, (IntLit, RealLit, StrLit, BoolLit)):
            return node.type
        if isinstance(node, Ident):
            symbol = self.lookup(node.name)
            if symbol is None:
                if node.name in self.functions:
                    self._error(f"函数名 {node.name!r} 不能当值用", node.span,
                                f"要调用请写 {node.name}(…)；函数不是一等值（见 docs/frames-spec.md）")
                    return None
                hint = self._suggest(node.name)
                if self.function_depth > 0:
                    hint += "。函数体只能看到形参与自身局部变量——本语言没有全局变量"
                self._error(f"使用了未声明的变量 {node.name!r}", node.span, hint)
                return None
            node.type = symbol.type
            node.slot = symbol.slot
            return symbol.type
        if isinstance(node, Call):
            return self.type_of_call(node)
        if isinstance(node, Unary):
            operand = self.type_of(node.operand)
            if node.op == "not":
                if operand is not None and operand != "BOOL":
                    self._error(f"not 只能作用于 bool，收到 {operand.lower()}", node.span)
                    return None
                node.type = "BOOL"
            else:
                if operand is not None and operand not in ("INT", "REAL"):
                    self._error(f"一元 - 只能作用于数字，收到 {operand.lower()}", node.span)
                    return None
                node.type = operand
            return node.type
        if isinstance(node, Binary):
            return self.type_of_binary(node)
        self._error(f"不支持的表达式节点 {type(node).__name__}", node.span)
        return None

    def type_of_call(self, node: Call) -> str | None:
        info = self.functions.get(node.name)
        if info is None:
            if self.lookup(node.name) is not None:
                self._error(f"{node.name!r} 是变量，不是函数，不能调用", node.name_span,
                            "只有 fun 定义的名字可以调用")
            else:
                self._error(f"调用了未定义的函数 {node.name!r}", node.name_span,
                            "本语言要求函数先定义后使用（互递归不支持）。"
                            + self._suggest_function(node.name))
            for arg in node.args:
                self.type_of(arg)                # 实参里的错误也要报出来
            return None
        param_types = info["param_types"]
        node.func_index = info["index"]
        node.type = info["return_type"]
        node.param_types = tuple(param_types)
        if len(node.args) != len(param_types):
            self._error(f"函数 {node.name!r} 需要 {len(param_types)} 个参数，"
                        f"收到 {len(node.args)} 个", node.span,
                        "个数要对上；本语言没有默认参数与可变参数")
            for arg in node.args:
                self.type_of(arg)
            return node.type
        for index, (arg, want) in enumerate(zip(node.args, param_types), 1):
            found = self.type_of(arg)
            if found is not None and not self.assignable(found, want):
                self._error(f"函数 {node.name!r} 的第 {index} 个参数要求 {want.lower()}，"
                            f"收到 {found.lower()}", arg.span, self.widening_hint(found, want))
        return node.type

    def type_of_binary(self, node: Binary) -> str | None:
        left = self.type_of(node.left)
        right = self.type_of(node.right)
        if left is None or right is None:
            return None                    # 子表达式已经报过错，这里不再重复刷屏
        op = node.op
        if op in LOGIC:
            for side, name in ((left, "左"), (right, "右")):
                if side != "BOOL":
                    self._error(f"{op} 的{name}边必须是 bool，收到 {side.lower()}", node.span)
                    return None
            node.type = "BOOL"
            return node.type
        if op in COMPARISONS:
            return self._check_comparison(node, left, right)
        return self._check_arithmetic(node, left, right)

    def _check_comparison(self, node: Binary, left: str, right: str) -> str | None:
        if left == "BOOL" or right == "BOOL":
            if left != right:
                self._error(f"bool 不能和 {(right if left == 'BOOL' else left).lower()} 比较（{node.op}）",
                            node.span, "bool 只跟 bool 比；把 0/1 当真假是另一套语言")
                return None
            if node.op not in ("=", "!="):
                self._error(f"bool 不支持 {node.op}，只能用 = 或 !=", node.span)
                return None
            node.operand_type = "BOOL"
            node.type = "BOOL"
            return node.type
        if left == "STRING" or right == "STRING":
            if left != right:
                self._error(f"字符串不能和 {(right if left == 'STRING' else left).lower()} 比较（{node.op}）",
                            node.span)
                return None
            if node.op not in ("=", "!="):
                self._error("字符串只支持 = 与 !=；本语言没有定义字典序", node.span,
                            "要按字典序比较请作为扩展实现，并写清编码顺序")
                return None
            node.operand_type = "STRING"
            node.type = "BOOL"
            return node.type
        node.operand_type = "REAL" if "REAL" in (left, right) else "INT"
        node.type = "BOOL"
        return node.type

    def _check_arithmetic(self, node: Binary, left: str, right: str) -> str | None:
        if left == "BOOL" or right == "BOOL":
            self._error(f"bool 不参与算术（{node.op}）：{left.lower()} {node.op} {right.lower()}", node.span,
                        "本语言不把 true 当 1；请先写成条件表达式")
            return None
        if left == "STRING" or right == "STRING":
            if node.op == "+" and left == right == "STRING":
                node.operand_type = "STRING"
                node.type = "STRING"
                return node.type
            self._error(f"{left.lower()} {node.op} {right.lower()}："
                        f"字符串只能用 + 拼接，且两边都必须是字符串", node.span,
                        "本语言没有隐式转字符串；要拼数字请先想清楚用哪种表示")
            return None
        mixed = "REAL" in (left, right)
        if mixed and node.op in ("/", "%"):
            node.operand_type = "REAL"
            node.type = "REAL"             # real 的 / 是普通除法，% 是 fmod
            return node.type
        node.operand_type = left if left == right else "REAL"
        node.type = "INT" if node.operand_type == "INT" else "REAL"
        return node.type

    # ---------------------------------------------------- 规则小工具
    @staticmethod
    def assignable(value_type: str, target_type: str) -> bool:
        if value_type == target_type:
            return True
        return (value_type, target_type) == ("INT", "REAL")     # 唯一的自动加宽

    @staticmethod
    def widening_hint(value_type: str, target_type: str) -> str:
        if (value_type, target_type) == ("REAL", "INT"):
            return ("real → int 不自动：截断方式（floor / round / 向零）必须由你选。"
                    "内置转换函数留作扩展练习")
        if target_type == "BOOL":
            return "bool 与数字之间不互转：条件要写成比较表达式"
        if target_type == "STRING":
            return "字符串没有隐式转换：本语言不做数字拼进字符串"
        return ""

    def _require_bool(self, node: Node, role: str) -> None:
        found = self.type_of(node)
        if found is not None and found != "BOOL":
            self._error(f"{role}必须是 bool，收到 {found.lower()}", node.span,
                        "例如写成 x > 0；本语言不把非零当真")


def analyze(program: Program) -> list:
    """返回按源码位置排序的语义错误列表；空列表代表通过。"""
    return Checker(program).run()
