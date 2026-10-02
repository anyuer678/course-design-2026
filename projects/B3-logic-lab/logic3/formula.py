"""logic3/formula.py —— 命题公式：词法 → 递归下降 → AST 求值

课程要点（离散结构：数理逻辑）：
    - 命题公式的语法是**分层的**：¬ > ∧ > ∨ > → > ↔。递归下降按优先级一层一个函数，
      解析出的树形结构就是"运算次序"，不必在求值时再猜；
    - ↔ 写成 `<=>`，→ 写成 `->`：**词法必须多吃一个字符**（先试两字符运算符再试单字符），
      否则 `->` 会被拆成 `-` 与 `>`（本模块的经典坑，见 README）；
    - 变量集合从 AST 现收集，顺序固定为**字典序**——真值表行序、极小项编号都依赖它，
      顺序一变编号就全变，所以"哪来的顺序"必须显式写在代码里。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 变量名：单个字母，或 p/q/r 加数字（p1, p12 …）。允许 a..z 更符合教材习惯。
VAR_RE = re.compile(r"[A-Za-z][0-9]*")

BINARY_BY_PRECEDENCE = (("<=>", "iff"), ("->", "imp"), ("|", "or"),
                        ("&", "and"))
TOKENS = ("<=>", "->", "(", ")", "~", "&", "|")


class FormulaError(ValueError):
    """解析失败。message 里带出错位置，方便在真值表/主范式之前就拦住坏输入。"""

    def __init__(self, message: str, pos: int):
        super().__init__(f"{message}（第 {pos + 1} 个字符处）")
        self.pos = pos


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Const:
    """常量 0 / 1：主范式在退化情形（矛盾式/重言式）会输出它们，
    解析器必须能吃下自己的输出，否则"主范式可回代验证"就不成立。"""
    value: bool


@dataclass(frozen=True)
class Not:
    operand: "Node"


@dataclass(frozen=True)
class Bin:
    op: str                      # "and" / "or" / "imp" / "iff"
    left: "Node"
    right: "Node"


Node = Var | Const | Not | Bin


def tokenize(text: str) -> list[str]:
    """词法：两字符运算符优先，其次单字符，最后变量名与常量。空白忽略。"""
    return [tok for tok, _ in tokenize_spans(text)]


def tokenize_spans(text: str) -> list[tuple[str, int]]:
    """带字符下标的词法结果——用**字符位置**而非记号序号报错，
    否则"第 N 个记号处"会被当成"第 N 个字符处"，误导定位。"""
    tokens: list[tuple[str, int]] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if text.startswith("<=>", i) or text.startswith("->", i):
            width = 3 if text[i] == "<" else 2
            tokens.append((text[i:i + width], i))
            i += width
            continue
        if ch in TOKENS:
            tokens.append((ch, i))
            i += 1
            continue
        if ch in "01":
            tokens.append((ch, i))
            i += 1
            continue
        m = VAR_RE.match(text, i)
        if m:
            tokens.append((m.group(0), i))
            i = m.end()
            continue
        raise FormulaError(f"无法识别的字符 {ch!r}", i)
    return tokens


class _Parser:
    def __init__(self, spans: list[tuple[str, int]], text: str):
        self.spans = spans
        self.text = text
        self.pos = 0

    # ---- 工具
    def peek(self) -> str | None:
        return self.spans[self.pos][0] if self.pos < len(self.spans) else None

    def here(self) -> int:
        """当前记号的**字符下标**；已在末尾时给出公式长度（"意外结束"报在末尾）。"""
        return self.spans[self.pos][1] if self.pos < len(self.spans) else len(self.text)

    def eat(self, what: str) -> str:
        tok = self.peek()
        if tok != what:
            raise FormulaError(f"期望 {what!r}，实际是 {tok!r}", self.here())
        self.pos += 1
        return tok

    # ---- 优先级链：每层只处理自己这一级，把下一级当"原子"来要
    def parse(self) -> Node:
        node = self.parse_iff()
        if self.peek() is not None:
            raise FormulaError(f"公式结束后还有多余记号 {self.peek()!r}", self.here())
        return node

    def parse_iff(self) -> Node:
        node = self.parse_imp()
        while self.peek() == "<=>":
            self.pos += 1
            node = Bin("iff", node, self.parse_imp())
        return node

    def parse_imp(self) -> Node:
        node = self.parse_or()
        while self.peek() == "->":
            self.pos += 1
            # **右结合**：p -> q -> r 读作 p -> (q -> r)，这是逻辑教材的约定
            node = Bin("imp", node, self.parse_imp())
        return node

    def parse_or(self) -> Node:
        node = self.parse_and()
        while self.peek() == "|":
            self.pos += 1
            node = Bin("or", node, self.parse_and())
        return node

    def parse_and(self) -> Node:
        node = self.parse_not()
        while self.peek() == "&":
            self.pos += 1
            node = Bin("and", node, self.parse_not())
        return node

    def parse_not(self) -> Node:
        if self.peek() == "~":
            self.pos += 1
            return Not(self.parse_not())          # ~~p 合法
        return self.parse_atom()

    def parse_atom(self) -> Node:
        tok = self.peek()
        if tok is None:
            raise FormulaError("公式意外结束", self.here())
        if tok == "(":
            self.pos += 1
            node = self.parse_iff()
            self.eat(")")
            return node
        if tok in ("0", "1"):
            self.pos += 1
            return Const(tok == "1")
        if tok in TOKENS:
            raise FormulaError(f"这里不该出现 {tok!r}", self.here())
        self.pos += 1
        return Var(tok)


def parse(text: str) -> Node:
    """把文本解析成 AST。空公式、坏括号、缺操作数都会带字符位置报错。"""
    if not text.strip():
        raise FormulaError("空公式", 0)
    return _Parser(tokenize_spans(text), text).parse()


def variables(node: Node) -> list[str]:
    """收集变量名，**按字典序**返回——真值表行序与极小项编号都以它为准。"""
    found: set[str] = set()

    def walk(n: Node) -> None:
        if isinstance(n, Const):
            return
        if isinstance(n, Var):
            found.add(n.name)
            return
        if isinstance(n, Not):
            walk(n.operand)
        else:
            walk(n.left)
            walk(n.right)

    walk(node)
    return sorted(found)


def evaluate(node: Node, assignment: dict[str, bool]) -> bool:
    if isinstance(node, Const):
        return node.value
    if isinstance(node, Var):
        return bool(assignment[node.name])
    if isinstance(node, Not):
        return not evaluate(node.operand, assignment)
    left = evaluate(node.left, assignment)
    right = evaluate(node.right, assignment)
    if node.op == "and":
        return left and right
    if node.op == "or":
        return left or right
    if node.op == "imp":
        return (not left) or right
    if node.op == "iff":
        return left == right
    raise AssertionError(f"未知运算符 {node.op!r}")


def render(node: Node) -> str:
    """把 AST 还原成带括号的文本：二元运算一律加括号（括号位置即树形），
    不做去括号化简——它的用途是肉眼核对解析结构，不是输出最简式。"""
    if isinstance(node, Const):
        return "1" if node.value else "0"
    if isinstance(node, Var):
        return node.name
    if isinstance(node, Not):
        inner = render(node.operand)
        return f"~{inner}" if isinstance(node.operand, Var) else f"~({inner})"
    symbol = {"and": "&", "or": "|", "imp": "->", "iff": "<=>"}[node.op]
    return f"({render(node.left)} {symbol} {render(node.right)})"
