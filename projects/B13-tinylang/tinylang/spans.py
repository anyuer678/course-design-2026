"""tinylang/spans.py —— 源码位置与错误渲染。

编译原理最容易骗人的地方是"报错了"：报错不等于报得准。
所以每个记号、每个 AST 节点都必须带 Span，每条错误都必须能被渲染成
"第几行第几列 + 源码那一行 + 一条插入符"，而且插入符不能指错位置。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    line: int          # 1 起
    col: int           # 1 起
    end_line: int
    end_col: int

    @property
    def length(self) -> int:
        return self.end_col - self.col if self.line == self.end_line else 0

    def joined_with(self, other: "Span") -> "Span":
        """两个跨度合成一个覆盖范围（二元表达式用它把自己的子表达式括进来）。"""
        if (self.line, self.col) <= (other.line, other.col):
            start = self
        else:
            start = other
        if (self.end_line, self.end_col) >= (other.end_line, other.end_col):
            end = self
        else:
            end = other
        return Span(start.line, start.col, end.end_line, end.end_col)

    def __str__(self) -> str:
        if self.line == self.end_line:
            return f"[{self.line}:{self.col}-{self.end_col}]"
        return f"[{self.line}:{self.col}-{self.end_line}:{self.end_col}]"


NO_SPAN = Span(0, 0, 0, 0)


class TinyError(Exception):
    """所有阶段的错误基类。stage 让"哪一层出的错"在输出里一眼可见。"""

    stage = "general"

    def __init__(self, message: str, span: Span | None = None, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.span = span or NO_SPAN
        self.hint = hint

    def __str__(self) -> str:
        place = f"{self.span.line}:{self.span.col}" if self.span.line else "位置未知"
        return f"{self.stage}: {self.message} ({place})"

    def render(self, source: str) -> str:
        """带插入符的多行输出。跨行跨度只指出起点行，这是取舍不是遗漏。"""
        lines = source.splitlines()
        head = f"{self.stage}: {self.message}"
        if not self.span.line:
            return head + (f"\n  提示：{self.hint}" if self.hint else "")
        text = lines[self.span.line - 1] if self.span.line <= len(lines) else ""
        col = max(1, self.span.col)
        width = max(1, self.span.length) if self.span.line == self.span.end_line else 1
        caret = " " * (col - 1) + "^" * width
        out = [f"{head}  （第 {self.span.line} 行第 {col} 列）",
               f"  {self.span.line:>4} | {text}",
               f"       | {caret}"]
        if self.hint:
            out.append(f"  提示：{self.hint}")
        return "\n".join(out)


class LexError(TinyError):
    stage = "词法"


class ParseError(TinyError):
    stage = "语法"


class SemanticError(TinyError):
    stage = "语义"


class CodegenError(TinyError):
    stage = "代码生成"


class RuntimeError_(TinyError):
    stage = "运行"
