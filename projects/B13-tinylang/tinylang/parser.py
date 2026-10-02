"""tinylang/parser.py —— 递归下降 + 显式优先级链。

文法（基础范围 + B41 候选②的增量）：
    program  := (fun_def | stmt)*
    fun_def  := "fun" ident "(" [param ("," param)*] ")" "->" type block
    param    := ident ":" type
    stmt     := "let" ident ":" type ":=" expr ";"
              | ident ":=" expr ";"
              | "print" expr ";"
              | "if" expr "then" stmt ["else" stmt]
              | "while" expr "do" stmt
              | "return" expr ";"
              | "{" stmt* "}"
    type     := int | real | bool | string
    expr     := or_expr
    primary  := … | ident "(" [expr ("," expr)*] ")"      # 函数调用

函数定义只能出现在顶层（块里出现 `fun` 是明确的语法错误，不是"当普通语句解析"）。
调用实参从左到右求值；调用是表达式，没有"丢弃返回值"的裸调用语句——
这些选择都写在 docs/frames-spec.md，与两条执行后端共用同一份口径。

优先级（低 → 高），每一级一个函数，链式往下调用：
    or  →  and  →  not(前缀)  →  比较  →  +-  →  */%  →  一元减号  →  primary
所以：
    or a = b            →  or(a) = b        （比较比 or 紧）
    not a = b           →  not (a = b)      （not 的操作数是"比较及以下"）
    -2 * 3              →  (-2) * 3
    1 + 2 * 3           →  1 + (2 * 3)
括号不产生 AST 节点：优先级已经编码在树形里，留一个壳只会多一处要穿透的分支。

三个刻意的取舍：
* **不猜测、不回填**（错误恢复留给扩展）：一遇到非法结构就停，报"期望什么、实际是什么、在哪"。
  半个 AST 比没有 AST 更危险，因为下游会把它当成正确程序继续跑。
* **嵌套深度有上限**：递归下降的深度由表达式嵌套决定，不设上限时一万个左括号会把
  Python 的 RecursionError 抖出来——那不是错误信息，是崩溃。
* **比较不可连续**：`1 < 2 < 3` 直接报语法错（Python 允许，C 允许但语义怪异，
  这里必须选一个并写清楚）。dangling else 归最近的 if。
"""
from __future__ import annotations

from .lexer import Token, tokenize
from .nodes import (Assign, Binary, Block, BoolLit, Call, FunDef, Ident, If, IntLit,
                    Node, Param, Print, Program, RealLit, Return, StrLit, Unary,
                    VarDecl, While)
from .spans import ParseError, Span

TYPES = ("int", "real", "bool", "string")

COMPARISON_OPS = ("=", "!=", "<", "<=", ">", ">=")
ADDITIVE_OPS = ("+", "-")
MULTIPLICATIVE_OPS = ("*", "/", "%")
MAX_EXPRESSION_DEPTH = 64
MAX_STATEMENTS = 100_000


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0
        self.depth = 0

    # ---------------------------------------------------- 记号窗口
    def peek(self) -> Token:
        return self.tokens[self.i] if self.i < len(self.tokens) else self.tokens[-1]

    def advance(self) -> Token:
        token = self.peek()
        if token.kind != "eof":
            self.i += 1
        return token

    def _fail(self, expected: str, at: Token | None = None) -> None:
        token = at or self.peek()
        raise ParseError(f"期望 {expected}，实际是 {token.text!r}（{token.kind}）",
                         token.span, f"第 {token.span.line} 行这一处是不是漏了或者多了符号")

    def eat(self, kind: str, text: str | None = None, expected: str = "") -> Token:
        token = self.peek()
        if token.kind != kind or (text is not None and token.text != text):
            self._fail(expected or (text or kind))
        return self.advance()

    def _enter(self) -> None:
        """递归深度守卫：parse 函数每层调用都进出一次。"""
        self.depth += 1
        if self.depth > MAX_EXPRESSION_DEPTH:
            self.depth -= 1
            token = self.peek()
            raise ParseError(f"表达式嵌套过深（上限 {MAX_EXPRESSION_DEPTH} 层）", token.span,
                             "拆成几条语句或引入中间变量；这不是程序的限制，是栈的保护")

    def _leave(self) -> None:
        self.depth -= 1

    # ---------------------------------------------------- 程序与语句
    def parse_program(self) -> Program:
        stmts = []
        while self.peek().kind != "eof":
            if self.peek().is_keyword("fun"):
                stmts.append(self.parse_fun())
            else:
                stmts.append(self.parse_statement())
            if len(stmts) > MAX_STATEMENTS:
                self._fail(f"语句数不超过 {MAX_STATEMENTS}")
        end = self.peek().span
        return Program(stmts=stmts, span=Span(1, 1, end.line, end.col))

    def parse_statement(self) -> Node:
        token = self.peek()
        if token.is_keyword("let"):
            return self.parse_let()
        if token.is_keyword("print"):
            return self.parse_print()
        if token.is_keyword("if"):
            return self.parse_if()
        if token.is_keyword("while"):
            return self.parse_while()
        if token.is_keyword("return"):
            return self.parse_return()
        if token.is_keyword("fun"):
            # 顶层由 parse_program 处理；能走到这里说明 fun 出现在块里
            raise ParseError("fun 只能定义在顶层，不能放进块里", token.span,
                             "把函数定义移到文件最外层；嵌套函数不在本语言范围内")
        if token.is_op("{"):
            return self.parse_block()
        if token.kind == "ident":
            return self.parse_assign()
        self._fail("语句（let / print / if / while / return / { … } / 赋值）")

    def parse_fun(self) -> Node:
        start = self.eat("keyword", "fun", "fun")
        name = self.eat("ident", None, "函数名")
        self.eat("op", "(", "参数列表的左括号 '('")
        params = []
        if not self.peek().is_op(")"):
            params.append(self.parse_param())
            while self.peek().is_op(","):
                self.advance()
                params.append(self.parse_param())
        self.eat("op", ")", "参数列表的右括号 ')'")
        self.eat("op", "->", "返回类型箭头 '->'")
        type_token = self.peek()
        if type_token.kind != "keyword" or type_token.text not in TYPES:
            self._fail("返回类型（int / real / bool / string）")
        self.advance()
        if not self.peek().is_op("{"):
            self._fail("函数体的左花括号 '{'")
        body = self.parse_block()
        return FunDef(name=name.text, params=params, return_type=type_token.text,
                      body=body, name_span=name.span, span=start.span.joined_with(body.span))

    def parse_param(self) -> Node:
        name = self.eat("ident", None, "参数名")
        self.eat("op", ":", "参数类型标注的冒号 ':'")
        type_token = self.peek()
        if type_token.kind != "keyword" or type_token.text not in TYPES:
            self._fail("参数类型（int / real / bool / string）")
        self.advance()
        return Param(name=name.text, declared_type=type_token.text, name_span=name.span,
                     span=name.span.joined_with(type_token.span))

    def parse_return(self) -> Node:
        start = self.eat("keyword", "return", "return")
        expr = self.parse_expression()
        semicolon = self.eat("op", ";", "语句结束的分号")
        return Return(expr=expr, span=start.span.joined_with(semicolon.span))

    def parse_let(self) -> Node:
        start = self.eat("keyword", "let", "let")
        name = self.eat("ident", None, "变量名")
        self.eat("op", ":", "类型标注的冒号 ':'")
        type_token = self.peek()
        if type_token.kind != "keyword" or type_token.text not in TYPES:
            self._fail("类型（int / real / bool / string）")
        self.advance()
        self.eat("op", ":=", "初始化符号 ':='")
        init = self.parse_expression()
        semicolon = self.eat("op", ";", "语句结束的分号")
        return VarDecl(name=name.text, declared_type=type_token.text, init=init,
                       name_span=name.span, span=start.span.joined_with(semicolon.span))

    def parse_assign(self) -> Node:
        name = self.eat("ident", None, "变量名")
        self.eat("op", ":=", "赋值符号 ':='")
        expr = self.parse_expression()
        semicolon = self.eat("op", ";", "语句结束的分号")
        return Assign(name=name.text, expr=expr, name_span=name.span,
                      span=name.span.joined_with(semicolon.span))

    def parse_print(self) -> Node:
        start = self.eat("keyword", "print", "print")
        expr = self.parse_expression()
        semicolon = self.eat("op", ";", "语句结束的分号")
        return Print(expr=expr, span=start.span.joined_with(semicolon.span))

    def parse_if(self) -> Node:
        start = self.eat("keyword", "if", "if")
        cond = self.parse_expression()
        self.eat("keyword", "then", "then")
        then_branch = self.parse_statement()      # 分号属于内层语句，不在这里吃
        end = then_branch.span
        else_branch = None
        if self.peek().is_keyword("else"):
            self.advance()
            else_branch = self.parse_statement()
            end = else_branch.span
        return If(cond=cond, then_branch=then_branch, else_branch=else_branch,
                  span=start.span.joined_with(end))

    def parse_while(self) -> Node:
        start = self.eat("keyword", "while", "while")
        cond = self.parse_expression()
        self.eat("keyword", "do", "do")
        body = self.parse_statement()
        return While(cond=cond, body=body, span=start.span.joined_with(body.span))

    def parse_block(self) -> Node:
        open_brace = self.eat("op", "{", "左花括号")
        stmts = []
        while not self.peek().is_op("}"):
            if self.peek().kind == "eof":
                self._fail("块结束的 '}'")
            stmts.append(self.parse_statement())
        close_brace = self.eat("op", "}", "块结束的 '}'")
        return Block(stmts=stmts, span=open_brace.span.joined_with(close_brace.span))

    # ---------------------------------------------------- 表达式：一级一个函数
    def parse_expression(self) -> Node:
        self._enter()
        try:
            return self.parse_or()
        finally:
            self._leave()

    def parse_or(self) -> Node:
        left = self.parse_and()
        while self.peek().is_keyword("or"):
            self.advance()
            right = self.parse_and()
            left = Binary(op="or", left=left, right=right,
                          span=left.span.joined_with(right.span))
        return left

    def parse_and(self) -> Node:
        left = self.parse_not()
        while self.peek().is_keyword("and"):
            self.advance()
            right = self.parse_not()
            left = Binary(op="and", left=left, right=right,
                          span=left.span.joined_with(right.span))
        return left

    def parse_not(self) -> Node:
        if self.peek().is_keyword("not"):
            token = self.advance()
            self._enter()
            try:
                operand = self.parse_not()
            finally:
                self._leave()
            return Unary(op="not", operand=operand, span=token.span.joined_with(operand.span))
        return self.parse_comparison()

    def parse_comparison(self) -> Node:
        left = self.parse_additive()
        token = self.peek()
        if token.kind == "op" and token.text in COMPARISON_OPS:
            op = self.advance()
            right = self.parse_additive()
            after = self.peek()
            if after.kind == "op" and after.text in COMPARISON_OPS:
                raise ParseError(f"不支持连续比较（{op.text} 之后又出现 {after.text!r}）",
                                 after.span, "请用 and 连接，例如 1 < x and x < 3")
            left = Binary(op=op.text, left=left, right=right,
                          span=left.span.joined_with(right.span))
        return left

    def parse_additive(self) -> Node:
        left = self.parse_multiplicative()
        while self.peek().kind == "op" and self.peek().text in ADDITIVE_OPS:
            op = self.advance()
            right = self.parse_multiplicative()
            left = Binary(op=op.text, left=left, right=right,
                          span=left.span.joined_with(right.span))
        return left

    def parse_multiplicative(self) -> Node:
        left = self.parse_unary_minus()
        while self.peek().kind == "op" and self.peek().text in MULTIPLICATIVE_OPS:
            op = self.advance()
            right = self.parse_unary_minus()
            left = Binary(op=op.text, left=left, right=right,
                          span=left.span.joined_with(right.span))
        return left

    def parse_unary_minus(self) -> Node:
        token = self.peek()
        if token.kind == "op" and token.text == "-":
            self.advance()
            self._enter()
            try:
                operand = self.parse_unary_minus()
            finally:
                self._leave()
            # 负字面量折叠成常量：`-2` 是 2 的一元负，语义上不该再产生一次运算
            if isinstance(operand, IntLit):
                return IntLit(span=token.span.joined_with(operand.span), value=-operand.value)
            if isinstance(operand, RealLit):
                return RealLit(span=token.span.joined_with(operand.span), value=-operand.value)
            return Unary(op="-", operand=operand, span=token.span.joined_with(operand.span))
        return self.parse_primary()

    def parse_primary(self) -> Node:
        token = self.peek()
        if token.kind == "int":
            self.advance()
            return IntLit(span=token.span, value=token.value)
        if token.kind == "real":
            self.advance()
            return RealLit(span=token.span, value=token.value)
        if token.kind == "string":
            self.advance()
            return StrLit(span=token.span, value=token.value)
        if token.is_keyword("true") or token.is_keyword("false"):
            self.advance()
            return BoolLit(span=token.span, value=token.text == "true")
        if token.kind == "ident":
            following = self.tokens[self.i + 1] if self.i + 1 < len(self.tokens) else token
            if following.is_op("("):
                return self.parse_call()
            self.advance()
            return Ident(span=token.span, name=token.text, name_span=token.span)
        if token.is_op("("):
            self.advance()
            self._enter()
            try:
                inner = self.parse_expression()
            finally:
                self._leave()
            self.eat("op", ")", "右括号 ')'")
            return inner
        if token.kind == "eof":
            raise ParseError("表达式在文件末尾就结束了", token.span, "少了一个操作数或分号")
        self._fail("表达式（数字、字符串、true/false、变量、函数调用或 '(' …）")

    def parse_call(self) -> Node:
        name = self.eat("ident", None, "函数名")
        self.eat("op", "(", "调用实参的左括号 '('")
        args = []
        if not self.peek().is_op(")"):
            args.append(self.parse_expression())
            while self.peek().is_op(","):
                self.advance()
                args.append(self.parse_expression())
        close = self.eat("op", ")", "调用实参的右括号 ')'")
        return Call(name=name.text, args=args, name_span=name.span,
                    span=name.span.joined_with(close.span))


def parse(source: str) -> Program:
    return Parser(tokenize(source)).parse_program()
