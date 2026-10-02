"""B13-tinylang 演示：一条能完整追踪的编译流水线。

    python demo.py

    七个部分：全链逐阶段展示 → 语言定义 → 错误定位 → 函数与调用帧 →
    两条执行路径对拍 → 样例程序 → 自己动手。
    全部只跑本机、不联网、不写文件。
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tinylang.fuzz import ProgramGen                                   # noqa: E402
from tinylang.pipeline import build                                     # noqa: E402
from tinylang.reporting import format_ast, shape                        # noqa: E402
from tinylang.spans import TinyError                                    # noqa: E402
from tinylang.tree_walk import interpret                                # noqa: E402
from tinylang.vm import run_code                                        # noqa: E402

BAR = "=" * 78
HERE = os.path.dirname(os.path.abspath(__file__))


def title(index: int, text: str) -> None:
    print(f"\n{BAR}\n[{index}/7] {text}\n{BAR}")


def section(text: str) -> None:
    print(f"\n-- {text} " + "-" * max(0, 72 - len(text)))


def run_file(name: str) -> tuple[int, str]:
    """按 CLI 的方式跑一个样例：返回 (退出码, 文本)。"""
    path = os.path.join(HERE, "programs", name)
    with open(path, encoding="utf-8", newline="") as handle:
        source = handle.read()
    built = build(source)
    if built.errors:
        return 2, built.report()
    try:
        result = run_code(built.code, max_steps=200_000)
    except TinyError as exc:
        return 1, exc.render(source)
    return 0, "\n".join(result.output) + f"\n（{result.steps} 步）"


def demo_pipeline() -> None:
    source = """let n : int := 6;
let sum : int := 0;
let i : int := 1;
while i <= n do {
    sum := sum + i * i;
    i := i + 1;
}
print sum;
"""
    built = build(source)
    print(source)
    section("1) 词法：每个记号自带行列")
    kinds = [f"{t.kind}:{t.text}" for t in built.tokens[:12]]
    print("  " + "  ".join(kinds) + f"  …（共 {len(built.tokens)} 个记号）")
    print(f"  例如 'while' 在第 {next(t.span.line for t in built.tokens if t.text == 'while')} 行")

    section("2) 语法：AST 的形状，单行版用来断言优先级")
    print("  " + shape(built.program))
    print("  缩进版：")
    print("\n".join("  " + line for line in format_ast(built.program).splitlines()))

    section("3) 语义：类型标注 + 槽位分配（没有错误才能往下走）")
    for statement in built.program.stmts:
        if type(statement).__name__ == "VarDecl":
            print(f"  let {statement.name} : {statement.declared_type} → 槽位 {statement.slot}")
    print(f"  共 {built.program.locals_count} 个槽位，语义错误 {len(built.errors)} 条")

    section("4) 代码生成：栈机指令，每条都带源码行号")
    print("\n".join("  " + line for line in built.code.disassemble().splitlines()))
    print(f"  常量池: {built.code.constants}")

    section("5) 虚拟机：执行 + 前 8 步轨迹")
    traced = run_code(built.code, trace_limit=8)
    for step in traced.trace:
        print("  " + step.render())
    print(f"  输出 {traced.output}，总步数 {traced.steps}")


def demo_language_choices() -> None:
    cases = [
        ("整数除法是 floor，不是向零截断",
         "print -7 / 2; print -7 % 2; print 7 % -2;",
         "C/Java 会给 -3 和 1；这里与 Python 一致：-4、1、-1"),
        ("bool 不当数字用",
         "print true = 1;",
         "语义直接拒绝（见下一条），不做 true→1 的隐式转换"),
        ("bool 与数字混合是错误",
         "let t : bool := true; print t + 1;",
         "错误，而不是“悄悄算出 2”"),
        ("real 不能塞进 int",
         "let x : int := 1; x := 2.5;",
         "截断方式必须由程序员选；内置转换函数是扩展练习"),
        ("字符串没有字典序",
         'print "a" < "b";',
         "要做就得先规定编码顺序，别默认自己会选对"),
        ("短路是真的短路",
         "let z : int := 0; print (z != 0) and (10 / z > 2);",
         "z 为 0，右边那次的除法根本没执行"),
        ("块作用域与自引用初始值",
         "let b : int := 7; { let b : int := b + 1; print b; } print b;",
         "内层初始值读的是外层 b；出块后外层值不变"),
        ("函数看不到全局变量",
         "let g : int := 1;\nfun f() -> int { return g; }",
         "语义直接拒绝：函数的作用域只有形参与局部——帧模型因此干净"),
        ("自递归可以、互递归不行",
         "fun f(n : int) -> int { return f2(n); }\nfun f2(n : int) -> int { return f(n); }",
         "先定义后使用：f 的定义点还看不到 f2；互递归需要前向声明（不做）"),
    ]
    for name, source, note in cases:
        built = build(source)
        if built.errors:
            outcome = f"被拒：{built.errors[0].stage} {built.errors[0].message}"
        else:
            outcome = f"输出 {run_code(built.code).output}"
        print(f"  {name}")
        print(f"    {source}")
        print(f"    → {outcome}")
        print(f"    注：{note}")


def demo_errors() -> None:
    for name, expected_code in (("error_syntax.tiny", 2), ("error_types.tiny", 2),
                                ("error_runtime.tiny", 1), ("error_depth.tiny", 1)):
        code, text = run_file(name)
        head = text.splitlines()
        print(f"\n  {name}  （退出码 {code}，预期 {expected_code}）")
        for line in head[:9]:
            print("    " + line)
        if len(head) > 9:
            print(f"    …（共 {len(head)} 行）")


def demo_call_frames() -> None:
    source = """fun fib(n : int) -> int {
    if n < 2 then return n;
    return fib(n - 1) + fib(n - 2);
}
print fib(10);
"""
    built = build(source)
    section("1) 函数体的字节码：CALL / RET 与体尾的 NORET（落点保护）")
    for line in built.code.disassemble().splitlines():
        if any(op in line for op in ("CALL", "RET", "NORET", ";;")):
            print("  " + line)
    print(f"  函数表：{[(f.name, f.entry, f.arity, f.return_type) for f in built.code.functions]}")

    section("2) 执行轨迹：每一步带调用深度（顶层=0，进函数=1…）")
    traced = run_code(built.code, trace_limit=600)
    deep = [step for step in traced.trace if step.depth > 0][:5]
    for step in deep:
        print("  " + step.render())
    print(f"  …（共 {traced.steps} 步；完整轨迹用 python tiny.py programs/fib.tiny --trace）")

    section("3) 栈护栏：无限递归在第 100 层、同一条消息上停住（两边后端）")
    bad = build("fun dive(n : int) -> int {\n    return dive(n + 1);\n}\nprint dive(0);")
    for name, engine in (("VM    ", lambda: run_code(bad.code)),
                         ("树遍历", lambda: interpret(bad.program))):
        try:
            engine()
        except TinyError as exc:
            print(f"  {name}：{exc.message}（第 {exc.span.line} 行）")

    section("4) 缺 return：诚实做法是运行期错误，不做假的静态流分析")
    missing = build("fun f(x : int) -> int {\n    let y : int := x + 1;\n}\nprint f(1);")
    try:
        run_code(missing.code)
    except TinyError as exc:
        print(f"  {exc.message}（第 {exc.span.line} 行，指到函数体结尾的右花括号）")

    section("5) 递归互证：fib / 汉诺塔 / Ackermann / 二项式，见 tests/test_recursion.py")
    code, text = run_file("hanoi.tiny")
    print(f"  hanoi.tiny 退出码 {code}，输出 {len(text.splitlines())} 行（7 步移动 + 总步数 7）")
    code, text = run_file("fib.tiny")
    print(f"  fib.tiny 退出码 {code}，前 8 项：{' '.join(text.splitlines()[:8])}")


def demo_two_engines() -> None:
    total_programs = 40
    total_lines = 0
    mismatch = 0
    for seed in range(total_programs):
        rng = random.Random(1000 + seed)
        source = ProgramGen(rng).program(rng.randint(6, 16))
        built = build(source)
        if built.errors:
            mismatch += 1
            print(f"  × seed={seed} 生成器产出被检查器拒绝：{built.errors[0].message}")
            continue
        vm = run_code(built.code, max_steps=200_000)
        walk = interpret(built.program, max_steps=200_000)
        total_lines += len(vm.output)
        if vm.output != walk.output:
            mismatch += 1
            print(f"  × seed={seed} 两条路输出不同")
    print(f"  {total_programs} 个随机程序（1–3 个函数 + 主程序，函数间调用图无环），"
          f"两条执行路径输出一致；共 {total_lines} 行输出，不一致 {mismatch} 例")
    print("  （完整 300 个程序的语料在 tests/test_against_reference.py 里跑）")
    trap = "(g != 0) and (10 / g > 0)"
    print(f"  随机语料里埋了短路陷阱，例如 {trap}：g 为 0 时右边一算就除零")


def demo_samples() -> None:
    for name in ("gcd.tiny", "collatz.tiny", "sum_of_squares.tiny", "types_and_print.tiny",
                 "short_circuit.tiny", "scope_shadow.tiny", "fib.tiny", "hanoi.tiny",
                 "ackermann.tiny", "binomial.tiny"):
        code, text = run_file(name)
        preview = " / ".join(text.splitlines()[:4])
        print(f"  {name:22s} 退出码 {code}  {preview}")


def main() -> int:
    print("tinylang 演示：词法 → 语法 → 语义 → 字节码 → 虚拟机 → 参照实现对拍")
    title(1, "同一段程序，逐个阶段看清楚")
    demo_pipeline()
    title(2, "语言定义里的每个选择都是要写下来的")
    demo_language_choices()
    title(3, "错误定位：语法 / 多条语义 / 运行期")
    demo_errors()
    title(4, "函数与调用帧：调用约定、栈护栏、缺 return（B41 候选②）")
    demo_call_frames()
    title(5, "两条独立执行路径互相对拍")
    demo_two_engines()
    title(6, "样例程序")
    demo_samples()
    title(7, "自己动手")
    print("  python tiny.py programs/gcd.tiny --tokens     # 看词法")
    print("  python tiny.py programs/fib.tiny --ast         # 看 AST（含函数定义）")
    print("  python tiny.py programs/fib.tiny --asm         # 看字节码（CALL/RET/NORET）")
    print("  python tiny.py programs/fib.tiny --trace       # 看轨迹（带调用深度）")
    print("  python tiny.py programs/error_depth.tiny       # 看栈护栏怎么报错")
    print("  python -m pytest tests -q                      # 85 项测试 + 300+ 个 subTest")
    print("\n  练习：给语言加数组与越界检查（有了它才能写快排）、内置转换函数（int()/round()）、")
    print("        做常量折叠优化——见 README 的练习建议。")
    return 0


if __name__ == "__main__":
    # 直接跑时中文控制台默认 GBK，示例里的中文和 ∞ 会编码失败
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
