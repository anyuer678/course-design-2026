"""tiny.py —— tinylang 命令行入口。

    python tiny.py programs/gcd.tiny              跑
    python tiny.py -c "print 1 + 2;"              跑一段代码
    python tiny.py programs/gcd.tiny --tokens     看词法
    python tiny.py programs/gcd.tiny --ast        看 AST（带行号）
    python tiny.py programs/gcd.tiny --asm        看字节码与常量池
    python tiny.py programs/gcd.tiny --trace      看执行轨迹（前 N 步）
    python tiny.py programs/gcd.tiny --dry-run    只编译，不执行
    python tiny.py programs/gcd.tiny --max-steps 5000

退出码：0 正常 / 1 运行期错误 / 2 编译期错误 / 3 用法或读文件问题。
编译失败一定返回非 0，而且把**所有**错误带行列打出来——"程序跑起来了"不能是编译错误的掩体。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tinylang.pipeline import build                                   # noqa: E402
from tinylang.reporting import format_ast                             # noqa: E402
from tinylang.spans import TinyError                                  # noqa: E402
from tinylang.vm import run_code                                      # noqa: E402

EXIT_OK, EXIT_RUNTIME, EXIT_COMPILE, EXIT_USAGE = 0, 1, 2, 3


def read_source(args) -> str:
    if args.code:
        return args.code
    with open(args.file, encoding="utf-8", newline="") as handle:
        return handle.read()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tiny.py", description="tinylang 教学语言")
    parser.add_argument("file", nargs="?", help="源文件（.tiny）")
    parser.add_argument("-c", "--code", help="直接给一段代码")
    parser.add_argument("--tokens", action="store_true", help="打印记号表")
    parser.add_argument("--ast", action="store_true", help="打印 AST")
    parser.add_argument("--asm", action="store_true", help="打印字节码")
    parser.add_argument("--trace", action="store_true", help="打印执行轨迹")
    parser.add_argument("--dry-run", action="store_true", help="只编译不执行")
    parser.add_argument("--max-steps", type=int, default=200_000)
    parser.add_argument("--trace-limit", type=int, default=40)
    args = parser.parse_args(argv)

    if not args.file and not args.code:
        parser.print_usage()
        print("需要一个 .tiny 文件或者 -c \"代码\"")
        return EXIT_USAGE
    try:
        source = read_source(args)
    except OSError as exc:
        print(f"读文件失败：{exc}")
        return EXIT_USAGE

    label = args.file or "<-c>"
    built = build(source)
    if args.tokens:
        for token in built.tokens:
            print(f"  {token.span.line:>3}:{token.span.col:<3} {token.kind:<8} {token.text!r}")
    if built.errors:
        print(f"{label}: 编译失败，共 {len(built.errors)} 条错误")
        print(built.report())
        return EXIT_COMPILE
    if args.ast:
        print(f"{label}: AST")
        print(format_ast(built.program))
    if built.tokens and args.tokens:
        print(f"记号 {len(built.tokens)} 个，语句 {len(built.program.stmts)} 条，"
              f"变量 {built.program.locals_count} 个")
    if args.asm:
        print(f"{label}: 字节码（常量池 {len(built.code.constants)} 项）")
        print(built.code.disassemble())
        print(f"常量池: {built.code.constants}")
    if args.dry_run:
        print(f"{label}: 编译通过（{len(built.code.instrs)} 条指令），未执行。")
        return EXIT_OK

    try:
        result = run_code(built.code, max_steps=args.max_steps,
                          trace_limit=args.trace_limit if args.trace else 0)
    except TinyError as exc:
        print(f"{label}: 运行失败")
        print(exc.render(source))
        return EXIT_RUNTIME

    for line in result.output:
        print(line)
    if args.trace:
        print(f"--- 执行轨迹（前 {len(result.trace)} 步）---")
        for step in result.trace:
            print(step.render())
    print(f"--- 共 {result.steps} 步，输出 {len(result.output)} 行，"
          f"变量槽位 {built.code.locals_count} 个 ---", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
