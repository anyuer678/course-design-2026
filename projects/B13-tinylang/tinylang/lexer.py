"""tinylang/lexer.py —— 词法分析：手工扫描，行列由自己维护。

不用正则，是因为**位置必须精确**：正则匹配完之后要反推行列，
一处漏算（换行、\r\n、块注释里的换行）就会让插入符指错地方——
而"报错位置不准"比"没报错"更害人：你会去改根本没错的那一行。

语言定义（本阶段只看形状，不看意义）：
    关键字（全小写、区分大小写）：let int real bool string print if then else
                                  while do true false and or not
                                  fun return
    运算符：:= = != < <= > >= -> + - * / % ( ) { } : ; ,
    数字：  123        整数
            1.5        实数（小数点后必须有数字；不支持 1e5、.5、1.）
    字符串："双引号"，转义 \\ \" \n \t \0；不允许裸换行
    注释：  # 到行尾；/* 到 */ （不嵌套，未闭合报错）
"""
from __future__ import annotations

from dataclasses import dataclass

from .spans import LexError, Span

KEYWORDS = {"let", "int", "real", "bool", "string", "print", "if", "then", "else",
            "while", "do", "true", "false", "and", "or", "not", "fun", "return"}

OPERATORS = [":=", "!=", "<=", ">=", "->", "=", "<", ">", "+", "-", "*", "/", "%",
             "(", ")", "{", "}", ":", ";", ","]

ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "0": "\0", "r": "\r"}

MAX_SOURCE_BYTES = 256 * 1024        # 与 B11 的 HTTP 同一套规矩：先有上限再谈功能

WHITESPACE = " \t\f\v"


@dataclass(frozen=True)
class Token:
    kind: str            # int | real | string | ident | keyword | op | eof
    text: str
    value: object        # 数字是 int/float，字符串是解码后的内容，其余是原文
    span: Span

    def is_keyword(self, name: str) -> bool:
        return self.kind == "keyword" and self.text == name

    def is_op(self, symbol: str) -> bool:
        return self.kind == "op" and self.text == symbol

    def __str__(self) -> str:
        return f"{self.kind}({self.text}){self.span}"


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() and ch.isascii() or ch == "_"


def _is_ident_char(ch: str) -> bool:
    return (ch.isalnum() and ch.isascii()) or ch == "_"


class Lexer:
    def __init__(self, source: str):
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise LexError(f"源码超过 {MAX_SOURCE_BYTES} 字节上限，本教学实现不处理这么大的程序")
        self.source = source
        self.i = 0
        self.line = 1
        self.col = 1

    # ---------------------------------------------------- 位置推进
    def _advance(self, count: int = 1) -> None:
        for _ in range(count):
            if self.i >= len(self.source):
                return
            ch = self.source[self.i]
            self.i += 1
            if ch == "\n":
                self.line += 1
                self.col = 1
            elif ch == "\r":
                # CRLF 里的 \r 不动行号，让紧跟的 \n 来推进；
                # 裸 \r（老 Mac 换行）自己算一次换行，否则行号会全体错位。
                if self._peek() != "\n":
                    self.line += 1
                    self.col = 1
            else:
                self.col += 1

    def _peek(self, offset: int = 0) -> str:
        index = self.i + offset
        return self.source[index] if index < len(self.source) else ""

    # ---------------------------------------------------- 主循环
    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while True:
            self._skip_blanks_and_comments()
            if self.i >= len(self.source):
                tokens.append(Token("eof", "", None, Span(self.line, self.col, self.line, self.col)))
                return tokens
            start_line, start_col = self.line, self.col
            token = self._one_token(start_line, start_col)
            tokens.append(token)

    def _skip_blanks_and_comments(self) -> None:
        while self.i < len(self.source):
            ch = self._peek()
            if ch in WHITESPACE or ch in "\n":
                self._advance()
            elif ch == "\r":                       # 同时兼容 CRLF 与裸 CR
                if self._peek(1) == "\n":
                    self._advance(2)
                else:
                    self._advance()
            elif ch == "#":
                while self.i < len(self.source) and self._peek() != "\n":
                    self._advance()
            elif ch == "/" and self._peek(1) == "*":
                self._block_comment(start_line=self.line, start_col=self.col)
            else:
                return

    def _block_comment(self, start_line: int, start_col: int) -> None:
        self._advance(2)
        while self.i < len(self.source):
            if self._peek() == "*" and self._peek(1) == "/":
                self._advance(2)
                return
            self._advance()
        raise LexError("块注释没有闭合", Span(start_line, start_col, start_line, start_col + 1),
                       "补一个 */，或者把开头的 /* 去掉")

    # ---------------------------------------------------- 单个记号
    def _one_token(self, line: int, col: int) -> Token:
        ch = self._peek()

        if _is_digit(ch):
            return self._number(line, col)
        if ch == '"':
            return self._string(line, col)
        if _is_ident_start(ch):
            text = ""
            while _is_ident_char(self._peek()):
                text += self._peek()
                self._advance()
            kind = "keyword" if text in KEYWORDS else "ident"
            return Token(kind, text, text, Span(line, col, line, col + len(text) - 1))
        for symbol in OPERATORS:
            if self.source.startswith(symbol, self.i):
                self._advance(len(symbol))
                return Token("op", symbol, symbol, Span(line, col, line, col + len(symbol) - 1))
        raise LexError(f"无法识别的字符 {ch!r}", Span(line, col, line, col),
                       "检查是否用了中文标点，或者漏了运算符")

    def _number(self, line: int, col: int) -> Token:
        text = ""
        while _is_digit(self._peek()):
            text += self._peek()
            self._advance()
        is_real = False
        if self._peek() == ".":
            if not _is_digit(self._peek(1)):
                raise LexError("小数点后缺少数字", Span(line, col, line, col + len(text)),
                               "写成 1.0；点号不是语句结束符")
            is_real = True
            text += "."
            self._advance()
            while _is_digit(self._peek()):
                text += self._peek()
                self._advance()
        if _is_ident_start(self._peek()):
            raise LexError(f"数字后面紧跟标识符 {self._peek()!r}",
                           Span(line, col, line, col + len(text) + 1),
                           "本语言不支持 1e5 这类科学计数法")
        value = float(text) if is_real else int(text)
        return Token("real" if is_real else "int", text, value,
                     Span(line, col, line, col + len(text) - 1))

    def _string(self, line: int, col: int) -> Token:
        start = self.i
        self._advance()                          # 消耗起始引号
        out: list[str] = []
        while True:
            if self.i >= len(self.source):
                raise LexError("字符串没有结束引号", Span(line, col, self.line, self.col),
                               "从这一行的开头引号开始往下找闭合引号")
            ch = self._peek()
            if ch == "\n":
                raise LexError("字符串里出现了裸换行", Span(line, col, self.line, self.col),
                               "换行要写成转义 \\n；也可能是上一行的引号忘了闭合")
            if ch == '"':
                self._advance()
                # raw 直接取源码切片：跨行字符串的列号不能当字符下标用
                return Token("string", self.source[start:self.i], "".join(out),
                             Span(line, col, self.line, self.col - 1))
            if ch == "\\":
                escape = self._peek(1)
                if escape not in ESCAPES:
                    raise LexError(f"未知转义 \\{escape}",
                                   Span(self.line, self.col, self.line, self.col + 1),
                                   "可用转义：" + " ".join(f"\\{k}" for k in ESCAPES))
                out.append(ESCAPES[escape])
                self._advance(2)
                continue
            out.append(ch)
            self._advance()


def tokenize(source: str) -> list[Token]:
    return Lexer(source).tokenize()
