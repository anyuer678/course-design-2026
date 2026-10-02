"""B13-tinylang 演示：一条能完整追踪的编译流水线。

    python demo.py

六个部分：全链逐阶段展示 → 语言定义 → 五个语义选择的现场 → 错误定位 →
两条执行路径对拍 → 样例程序。全部只跑本机、不联网、不写文件。
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
    print(f"\n{BAR}\n[{index}/6] {text}\n{BAR}")


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
                                ("error_runtime.tiny", 1)):
        code, text = run_file(name)
        head = text.splitlines()
        print(f"\n  {name}  （退出码 {code}，预期 {expected_code}）")
        for line in head[:9]:
            print("    " + line)
        if len(head) > 9:
            print(f"    …（共 {len(head)} 行）")


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
            print(f"  ✗ seed={seed} 生成器产出被检查器拒绝：{built.errors[0].message}")
            continue
        vm = run_code(built.code, max_steps=200_000)
        walk = interpret(built.program, max_steps=200_000)
        total_lines += len(vm.output)
        if vm.output != walk.output:
            mismatch += 1
            print(f"  ✗ seed={seed} 两条路输出不同")
    print(f"  {total_programs} 个随机程序，两条执行路径输出一致；"
          f"共 {total_lines} 行输出，不一致 {mismatch} 例")
    print("  （完整 300 个程序的语料在 tests/test_against_reference.py 里跑）")
    trap = "(g != 0) and (10 / g > 0)"
    print(f"  随机语料里埋了短路陷阱，例如 {trap}：g 为 0 时右边一算就除零")


def demo_samples() -> None:
    for name in ("gcd.tiny", "collatz.tiny", "sum_of_squares.tiny", "types_and_print.tiny",
                 "short_circuit.tiny", "scope_shadow.tiny"):
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
    title(4, "两条独立执行路径互相对拍")
    demo_two_engines()
    title(5, "样例程序")
    demo_samples()
    title(6, "自己动手")
    print("  python tiny.py programs/gcd.tiny --tokens     # 看词法")
    print("  python tiny.py programs/collatz.tiny --ast     # 看 AST")
    print("  python tiny.py programs/gcd.tiny --asm         # 看字节码")
    print("  python tiny.py programs/gcd.tiny --trace       # 看执行轨迹")
    print("  python tiny.py -c 'let x : int := 1.5;'        # 看语义怎么拒")
    print("  python -m pytest tests -q                      # 55 项测试 + 393 个 subTest")
    print("\n  练习：实现内置转换函数（int()/round()）、给 if/elif 加错误恢复、")
    print("        加函数与调用帧、做常量折叠优化——见 README 的练习建议。")
    return 0


if __name__ == "__main__":
    # 直接跑时中文控制台默认 GBK，示例里的中文和 ∞ 会编码失败
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
