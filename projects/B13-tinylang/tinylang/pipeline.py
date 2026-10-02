"""tinylang/pipeline.py —— 词法 → 语法 → 语义 → 字节码 → 执行，串成一条能追踪的链。

对外只暴露三个入口：
    build(source)            走到语义为止，返回全部错误（CLI 与测试都用它）
    compile_source(source)   一路生成字节码；有错误就抛出带行列的完整渲染
    run(source, ...)         编译 + 执行，返回 VmResult

设计原则：**语义错误永远不许被"能跑"绕过**。build 有错时 code 一定是 None，
run 也就无从执行；任何"先跑起来看看"的路径都不存在。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .bytecode import Code
from .codegen import generate
from .lexer import tokenize
from .nodes import Program
from .parser import parse
from .semantics import analyze
from .spans import TinyError
from .tree_walk import WalkResult, interpret
from .vm import VmResult, run_code

DEFAULT_MAX_STEPS = 200_000


@dataclass
class Build:
    source: str
    tokens: list = field(default_factory=list)
    program: Program | None = None
    errors: list = field(default_factory=list)
    code: Code | None = None

    @property
    def ok(self) -> bool:
        return not self.errors and self.code is not None

    def report(self) -> str:
        if not self.errors:
            return "没有错误：词法、语法、语义全部通过。"
        blocks = [error.render(self.source) for error in self.errors]
        return "\n".join(f"{index}. {text}" for index, text in enumerate(blocks, 1))


def build(source: str) -> Build:
    """编译到字节码；把过程中发现的**全部**错误留在 Build.errors 里，不抛异常。"""
    result = Build(source=source)
    try:
        result.tokens = tokenize(source)
    except TinyError as exc:
        result.errors.append(exc)
        return result
    try:
        result.program = parse(source)
    except TinyError as exc:
        result.errors.append(exc)
        return result
    errors = analyze(result.program)
    if errors:
        result.errors.extend(errors)
        return result
    result.code = generate(result.program, source)
    return result


def compile_source(source: str) -> Code:
    """一路生成字节码；任何阶段出错都抛第一条错误，消息里带完整错误清单。"""
    result = build(source)
    if result.errors:
        first = result.errors[0]
        prefix = (f"编译失败，共 {len(result.errors)} 条错误：\n{result.report()}"
                  if len(result.errors) > 1 else f"编译失败：{first.render(source)}")
        raise _WrappedError(prefix, first)
    return result.code


class _WrappedError(Exception):
    """把"多条错误的整体报告"作为异常消息抛出，同时保留第一条原始错误。"""

    def __init__(self, message: str, original: TinyError):
        super().__init__(message)
        self.original = original


def run(source: str, *, max_steps: int = DEFAULT_MAX_STEPS,
        trace_limit: int = 0) -> VmResult:
    code = compile_source(source)
    return run_code(code, max_steps=max_steps, trace_limit=trace_limit)


def run_reference(source: str, *, max_steps: int = DEFAULT_MAX_STEPS) -> tuple[WalkResult, str]:
    """参照实现：走同一条前端，但用树遍历执行；返回 (结果, 反汇编文本) 方便对拍照合。"""
    result = build(source)
    if result.errors:
        raise result.errors[0]
    return interpret(result.program, max_steps=max_steps), result.code.disassemble()


def run_both(source: str, *, max_steps: int = DEFAULT_MAX_STEPS):
    """两条路各跑一遍，返回 (VM 结果, 树遍历结果)；调用方负责比较。"""
    result = build(source)
    if result.errors:
        raise result.errors[0]
    return (run_code(result.code, max_steps=max_steps),
            interpret(result.program, max_steps=max_steps))
