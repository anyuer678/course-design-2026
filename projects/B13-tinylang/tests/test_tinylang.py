"""B13-tinylang 自测：词法 → 语法 → 语义 → 字节码 → VM，逐层单独验，再串起来验。

跑法：
    python tests\\test_tinylang.py
    pytest tests -q

验收态度来自上一轮的教训：**"跑通了"不等于"报得准"**。
所以这个文件里一半的断言是在检查错误信息：位置对不对、指没指到真正的字符、
一条程序里的多个错误是不是都报出来了。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tinylang import values                                            # noqa: E402
from tinylang.bytecode import (BIN, CALL, HALT, I2F, JNZ, JUMP, JZ, LOAD, NORET, PRINT,
                               PUSH, RET, Code, Instr, FunctionInfo)  # noqa: E402
from tinylang.codegen import generate                                  # noqa: E402
from tinylang.lexer import MAX_SOURCE_BYTES, LexError, tokenize        # noqa: E402
from tinylang.nodes import Binary, Ident, IntLit, Program              # noqa: E402
from tinylang.parser import MAX_EXPRESSION_DEPTH, ParseError, parse    # noqa: E402
from tinylang.pipeline import build, compile_source, run     # noqa: E402
from tinylang.reporting import shape                                   # noqa: E402
from tinylang.runtime import DEFAULT_MAX_CALL_DEPTH                    # noqa: E402
from tinylang.semantics import analyze, MAX_ERRORS                     # noqa: E402
from tinylang.spans import (CodegenError, RuntimeError_, SemanticError,
                           Span)  # noqa: E402
from tinylang.vm import VM, run_code                                   # noqa: E402


class TestLexer(unittest.TestCase):
    def test_kinds_and_values(self):
        tokens = tokenize('let x : int := 3;\nprint x * 2.5;')
        self.assertEqual([t.kind for t in tokens],
                         ["keyword", "ident", "op", "keyword", "op", "int", "op",
                          "keyword", "ident", "op", "real", "op", "eof"])
        self.assertEqual(tokens[5].value, 3)         # 3
        self.assertEqual(tokens[10].value, 2.5)      # 2.5
        self.assertEqual(tokens[-1].kind, "eof")

    def test_spans_are_exact_across_lines(self):
        source = "let a : int := 1;\nprint a;\n"
        tokens = {t.text: t for t in tokenize(source)}
        self.assertEqual((tokens["let"].span.line, tokens["let"].span.col), (1, 1))
        self.assertEqual((tokens["print"].span.line, tokens["print"].span.col), (2, 1))
        self.assertEqual(tokens[":="].span, Span(1, 13, 1, 14))

    def test_multiline_comment_shifts_columns(self):
        tokens = tokenize("/* 块\n注释 */ let x : int := 1;")
        let = next(t for t in tokens if t.text == "let")
        self.assertEqual((let.span.line, let.span.col), (2, 7))

    def test_string_escapes(self):
        token = next(t for t in tokenize(r'print "a\tb\\c\"d";') if t.kind == "string")
        self.assertEqual(token.value, 'a\tb\\c"d')
        self.assertEqual(token.text, r'"a\tb\\c\"d"')      # 原文保留，便于回显

    def test_lex_errors_carry_position(self):
        cases = {
            "print 1.;": "小数点后缺少数字",
            'print "未闭合;': "字符串没有结束引号",
            "print 1 @ 2;": "无法识别的字符",
            "/* 没闭合": "块注释没有闭合",
            "print 1e5;": "数字后面紧跟标识符",
            "print \"a\nb\";": "裸换行",
            "print \\;": "无法识别的字符",
            'print "x\\q";': "未知转义",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                with self.assertRaises(LexError) as ctx:
                    tokenize(source)
                self.assertIn(expected, ctx.exception.message)
                self.assertTrue(ctx.exception.span.line >= 1)
                self.assertTrue(ctx.exception.span.col >= 1)

    def test_crlf_and_bare_cr(self):
        for source in ("let a : int := 1;\r\nprint a;", "let a : int := 1;\rprint a;"):
            tokens = tokenize(source)
            print_token = next(t for t in tokens if t.text == "print")
            self.assertEqual((print_token.span.line, print_token.span.col), (2, 1))

    def test_source_size_guard(self):
        with self.assertRaises(LexError):
            tokenize("print 1;" * (MAX_SOURCE_BYTES // 8 + 10))

    def test_eof_token_is_last_and_stable(self):
        tokens = tokenize("")
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].kind, "eof")

    def test_fun_return_keywords_and_arrow(self):
        tokens = tokenize("fun f(a : int) -> int { return a; }")
        self.assertEqual(tokens[0].kind, "keyword")
        self.assertEqual(tokens[0].text, "fun")
        arrow = next(t for t in tokens if t.text == "->")
        self.assertEqual(arrow.kind, "op")            # -> 是一个记号，不是 - 和 > 两个
        self.assertTrue(all(t.kind == "keyword" for t in tokens if t.text == "return"))
        self.assertTrue(any(t.is_op(",") for t in tokenize("f(1, 2);")))
        self.assertTrue(any(t.is_op("->") for t in tokenize("a -> b")))


class TestParserShapes(unittest.TestCase):
    def shape_of(self, source: str) -> str:
        return shape(parse(source))

    def test_precedence_ladder(self):
        cases = {
            "print 1 + 2 * 3;": "(program (print (+ 1 (* 2 3))))",
            "print 1 * 2 + 3;": "(program (print (+ (* 1 2) 3)))",
            "print (1 + 2) * 3;": "(program (print (* (+ 1 2) 3)))",
            "print 1 - 2 - 3;": "(program (print (- (- 1 2) 3)))",       # 左结合
            "print 2 * 3 % 4;": "(program (print (% (* 2 3) 4)))",
            "print (1 < 2) = true;": "(program (print (= (< 1 2) true)))",  # 括号才允许把比较当值
            "print -2 * 3;": "(program (print (* -2 3)))",                # 负字面量折叠
            "print not 1 = 2;": "(program (print (not (= 1 2))))",         # not 比比较松
            "print true or false and false;":
                "(program (print (or true (and false false))))",           # and 比 or 紧
            "print a + b * c / d;": "(program (print (+ a (/ (* b c) d))))",  # */% 同级左结合
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(self.shape_of(source), expected)

    def test_statements(self):
        self.assertEqual(self.shape_of("let x : int := 1;"), "(program (let x int 1))")
        self.assertEqual(self.shape_of("x := y + 1;"), "(program (assign x (+ y 1)))")
        self.assertEqual(self.shape_of("if c then a := 1; else a := 2;"),
                         "(program (if c (assign a 1) (assign a 2)))")
        self.assertEqual(self.shape_of("while i < 3 do i := i + 1;"),
                         "(program (while (< i 3) (assign i (+ i 1))))")
        self.assertEqual(self.shape_of("{ let a : int := 1; print a; }"),
                         "(program (block (let a int 1) (print a)))")

    def test_dangling_else_binds_to_nearest_if(self):
        self.assertEqual(self.shape_of("if a then if b then print 1; else print 2;"),
                         "(program (if a (if b (print 1) (print 2))))")

    def test_empty_program(self):
        self.assertEqual(self.shape_of(""), "(program )")
        self.assertEqual(self.shape_of("   \n# 只有注释\n"), "(program )")

    def test_node_spans_cover_whole_construct(self):
        program = parse("let width : int := 3 + 4;")
        declaration = program.stmts[0]
        self.assertEqual((declaration.span.col, declaration.span.end_col), (1, 25))
        self.assertIsInstance(declaration.init, Binary)
        self.assertEqual(declaration.name_span, Span(1, 5, 1, 9))

    def test_parse_errors_point_at_the_real_culprit(self):
        cases = {
            "print 1": "分号",
            "let x int := 1;": "冒号",
            "print ;": "表达式",
            "x := ;": "表达式",
            "print 1 +;": "表达式",
            "if x then print 1; otherwise print 2;": None,       # else 缺失也能停住
            "print 1 < 2 < 3;": "连续比较",
            "}": "语句",
            "let x : number := 1;": "类型",
            "print (1 + 2;": "右括号 ')'",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                with self.assertRaises(ParseError) as ctx:
                    parse(source)
                if expected:
                    self.assertIn(expected, ctx.exception.message)
                self.assertTrue(ctx.exception.span.line >= 1)

    def test_nested_parens_guard_instead_of_stack_crash(self):
        deep = "print " + "(" * (MAX_EXPRESSION_DEPTH + 3) + "1" + ")" * (MAX_EXPRESSION_DEPTH + 3) + ";"
        with self.assertRaises(ParseError) as ctx:
            parse(deep)
        self.assertIn("嵌套过深", ctx.exception.message)

    def test_long_left_assoc_chain_does_not_blow_the_stack(self):
        program = parse("print " + " + ".join(str(i) for i in range(3000)) + ";")
        self.assertEqual(len(program.stmts), 1)

    def test_chained_comparison_is_rejected_not_silently_left_assoc(self):
        with self.assertRaises(ParseError) as ctx:
            parse("print 1 <= 2 <= 3;")
        self.assertIn("1 < x and x < 3", ctx.exception.hint)

    def test_function_and_call_shapes(self):
        cases = {
            "fun f(a : int) -> int { return a; }":
                "(program (fun f [(a int)] int (block (return a))))",
            "print f(1, 2);":
                "(program (print (call f 1 2)))",
            "print f(g(1) + 2);":
                "(program (print (call f (+ (call g 1) 2))))",
            "fun pi() -> real { return 3.0; } print pi() * 2;":
                "(program (fun pi [] real (block (return 3.0))) (print (* (call pi) 2)))",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(self.shape_of(source), expected)

    def test_function_parse_errors_point_at_the_real_culprit(self):
        cases = {
            "{ fun f() -> int { return 1; } }": "fun 只能定义在顶层",
            "fun f() int { return 1; }": "->",
            "fun f(a int) -> int { return a; }": "冒号",
            "fun f(a : int -> int { return a; }": "右括号 ')'",
            "fun f() -> int return 1;": "左花括号",
            "fun f() -> int { return 1;": "块结束的 '}'",
            "fun f() -> int { return 1 }": "分号",
            "print f(1;": "右括号 ')'",
            "print f(,1);": "表达式",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                with self.assertRaises(ParseError) as ctx:
                    parse(source)
                self.assertIn(expected, ctx.exception.message)


class TestSemantics(unittest.TestCase):
    def errors_of(self, source: str):
        return analyze(parse(source))

    def assert_single(self, source: str, fragment: str, line: int | None = None) -> None:
        errors = self.errors_of(source)
        self.assertEqual(len(errors), 1, [str(e) for e in errors])
        self.assertIn(fragment, errors[0].message)
        if line is not None:
            self.assertEqual(errors[0].span.line, line)

    def test_clean_programs_have_no_errors(self):
        for source in ("let x : int := 1; print x;",
                       "let r : real := 2; print r * 1.5;",
                       "let s : string := \"a\" + \"b\"; print s = \"ab\";",
                       "let b : bool := 1 < 2; if b then print 1;",
                       "let i : int := 0; while i < 3 do i := i + 1;",
                       "let a : int := 1; { let a : int := 2; print a; } print a;"):
            with self.subTest(source=source):
                self.assertEqual(self.errors_of(source), [])

    def test_scope_rules(self):
        self.assert_single("print y;", "未声明的变量")
        self.assert_single("y := 1;", "给未声明的变量")
        self.assert_single("let x : int := 1; let x : int := 2;", "已经声明过")
        self.assertEqual(self.errors_of("let a : int := 1; { let a : int := 2; }"), [])
        self.assert_single("if true then let x : int := 1;", "let 不能直接作为 if/while 的语句体")
        self.assert_single("while true do let x : int := 1;", "let 不能直接作为")

    def test_shadowed_init_reads_the_outer_variable(self):
        # { let b : int := b + 1; } 里的 b 是外层那个：声明符号在初始值检查之后才登记
        program = parse("let b : int := 7; { let b : int := b + 1; print b; } print b;")
        self.assertEqual(analyze(program), [])
        self.assertEqual(run_code(generate(program)).output, ["8", "7"])
        self.assertEqual(run("let b : int := 7; { let b : int := b + 1; print b; }").output, ["8"])

    def test_codegen_refuses_a_program_that_skipped_semantics(self):
        # 上一条测试原本写错了：没跑 analyze 就直接 generate，于是撞出这个 invariant——
        # 那就把它留下：未标注的 AST 不许进代码生成
        with self.assertRaises(CodegenError):
            generate(parse("let b : int := 7; print b;"))

    def test_type_rules(self):
        cases = {
            "let x : int := 1.5;": "声明为 int，但初始值是 real",
            "let x : int := 1; x := 2.5;": "不能把 real 赋给 int",
            "let x : bool := 1;": "声明为 bool，但初始值是 int",
            "print true + 1;": "bool 不参与算术",
            "print \"a\" - \"b\";": "字符串只能用 + 拼接",
            "print 1 and 2;": "and 的左边必须是 bool",
            "print not 1;": "not 只能作用于 bool",
            "let x : int := 1; if x then print 1;": "if 的条件必须是 bool",
            "let x : int := 1; while x do x := x;": "while 的条件必须是 bool",
            "print \"a\" < \"b\";": "字典序",
            "let t : bool := true; print t < t;": "bool 不支持 <",
            "print 1 = true;": "bool 不能和 int 比较",
            "print 1 + \"a\";": "字符串只能用 + 拼接",
            "let x : real := 1; x := 2;": "",          # int → real 允许
        }
        for source, fragment in cases.items():
            with self.subTest(source=source):
                errors = self.errors_of(source)
                if fragment == "":
                    self.assertEqual(errors, [], [str(e) for e in errors])
                else:
                    self.assertTrue(errors, source)
                    self.assertIn(fragment, errors[0].message)

    def test_widening_annotation_for_codegen(self):
        program = parse("let r : real := 1; print r + 2.5;")
        self.assertEqual(analyze(program), [])
        addition = program.stmts[1].expr
        self.assertEqual(addition.operand_type, "REAL")
        self.assertIsInstance(addition.left, Ident)
        self.assertEqual(addition.left.type, "REAL")

    def test_all_errors_are_reported_and_ordered(self):
        source = "print z;\nlet x : int := 1.5;\nif x then print 2;\nq := 3;\n"
        errors = self.errors_of(source)
        self.assertEqual(len(errors), 4, [str(e) for e in errors])
        self.assertEqual([e.span.line for e in errors], [1, 2, 3, 4])
        self.assertTrue(all(isinstance(e, SemanticError) for e in errors))

    def test_error_cascade_is_suppressed(self):
        # 子表达式已经报过，就不该在父表达式上再刷一条"类型不符"
        errors = self.errors_of("print (1 + true) + 2;")
        self.assertEqual(len(errors), 1, [str(e) for e in errors])

    def test_typo_suggestion(self):
        errors = self.errors_of("let hello : int := 1; print helo;")
        self.assertIn("是不是想写 'hello'", errors[0].hint)

    def test_real_to_int_hint_explains_the_design(self):
        errors = self.errors_of("let x : int := 1; x := 2.5;")
        self.assertIn("截断方式", errors[0].hint)

    def test_error_volume_is_capped(self):
        source = "".join("print undeclared%d;\n" % i for i in range(MAX_ERRORS + 20))
        errors = self.errors_of(source)
        self.assertEqual(len(errors), MAX_ERRORS + 1)
        self.assertIn("错误太多", errors[-1].message)

    def test_slots_are_monotonic_across_blocks(self):
        program = parse("let a : int := 1; { let b : int := 2; { let c : int := 3; } }")
        self.assertEqual(analyze(program), [])
        outer_block = program.stmts[1]
        self.assertEqual(outer_block.stmts[0].slot, 1)             # b
        self.assertEqual(outer_block.stmts[1].stmts[0].slot, 2)    # 内层的 c
        self.assertEqual(program.locals_count, 3)

    # ------------------------------------------------ 函数（B41 候选②）
    def test_functions_pass_and_self_recursion_is_visible(self):
        source = """fun fib(n : int) -> int {
    if n < 2 then return n;
    return fib(n - 1) + fib(n - 2);
}
print fib(10);
"""
        self.assertEqual(self.errors_of(source), [])

    def test_undefined_function_gets_a_suggestion(self):
        errors = self.errors_of("fun fib(n : int) -> int { return n; }\nprint fibb(1);")
        self.assertEqual(len(errors), 1, [str(e) for e in errors])
        self.assertIn("调用了未定义的函数 'fibb'", errors[0].message)
        self.assertIn("是不是想写 'fib'", errors[0].hint)

    def test_mutual_recursion_is_explicitly_not_supported(self):
        # f2 在后定义：f1 的体里看不到它——先定义后使用，互递归需要前向声明（不做）
        source = "fun f1(n : int) -> int { return f2(n); }\nfun f2(n : int) -> int { return f1(n); }"
        errors = self.errors_of(source)
        self.assertIn("调用了未定义的函数 'f2'", errors[0].message)
        self.assertIn("先定义后使用", errors[0].hint)

    def test_calling_a_variable_and_using_a_function_as_value(self):
        self.assert_single("let x : int := 1;\nprint x(1);", "是变量，不是函数")
        self.assert_single("fun f() -> int { return 1; }\nprint f;", "不能当值用")
        self.assert_single("fun f() -> int { return 1; }\nlet x : int := f;", "不能当值用")
        self.assert_single("fun f() -> int { return 1; }\nf := 2;", "不能作为变量赋值")

    def test_function_and_variable_names_must_not_collide(self):
        self.assert_single("fun f() -> int { return 1; }\nlet f : int := 1;",
                           "和函数重名")
        self.assert_single("let f : int := 1;\nfun f() -> int { return 1; }",
                           "和已声明的变量重名")
        self.assert_single("fun f() -> int { return 1; }\nfun f() -> int { return 2; }",
                           "已经定义过")
        self.assert_single("fun f() -> int { return 1; }\n"
                           "fun g(f : int) -> int { return f; }", "和函数重名")

    def test_call_arity_and_argument_types(self):
        head = "fun add(a : int, b : int) -> int { return a + b; }\n"
        self.assert_single(head + "print add(1);", "需要 2 个参数，收到 1 个")
        self.assert_single(head + "print add(1, 2, 3);", "需要 2 个参数，收到 3 个")
        self.assert_single("fun half(x : real) -> real { return x; }\nprint half(1.0, 2.0);",
                           "需要 1 个参数")
        self.assert_single("fun f(x : int) -> int { return x; }\nprint f(1.5);",
                           "第 1 个参数要求 int")
        self.assertEqual(self.errors_of(
            "fun f(x : real) -> real { return x * 2.0; }\nprint f(3);"), [])   # int→real 加宽

    def test_return_rules(self):
        self.assert_single("return 1;", "return 只能出现在函数体内")
        self.assert_single("fun f() -> int { return 1.5; }", "return 的值是 real")
        self.assert_single("fun f() -> bool { return 1; }", "return 的值是 int")
        # int → real 的加宽在 return 上也允许，和赋值同一套规则
        self.assertEqual(self.errors_of("fun f() -> real { return 1; }"), [])

    def test_function_body_cannot_see_globals(self):
        errors = self.errors_of("let g : int := 1;\nfun f() -> int { return g; }")
        self.assertEqual(len(errors), 1, [str(e) for e in errors])
        self.assertIn("使用了未声明的变量 'g'", errors[0].message)
        self.assertIn("没有全局变量", errors[0].hint)
        errors = self.errors_of("let g : int := 1;\nfun f() -> int { g := 2; return g; }")
        self.assertEqual(errors[0].span.line, 2)
        self.assertIn("函数体只能看到形参与自身局部变量", errors[0].hint)

    def test_function_slots_restart_from_zero(self):
        program = parse("let a : int := 1;\n"
                        "fun f(p : int) -> int { let q : int := p; return q; }\n"
                        "let b : int := 2;")
        self.assertEqual(analyze(program), [])
        definition = program.stmts[1]
        self.assertEqual(definition.locals_count, 2)       # 形参 p=0，局部 q=1
        self.assertEqual(definition.func_index, 0)
        self.assertEqual(program.locals_count, 2)          # 全局只有 a、b
        self.assertEqual(definition.body.stmts[0].slot, 1)  # q 的槽位在整个帧里是 1
        variable = definition.body.stmts[1].expr          # return q 里的 q
        self.assertEqual(variable.slot, 1)


class TestCodegen(unittest.TestCase):
    def ops(self, source: str):
        return [i.op for i in compile_source(source).instrs]

    def test_widening_emits_a_visible_i2f(self):
        code = compile_source("let r : real := 1; print r + 2.5;")
        self.assertIn(I2F, [i.op for i in code.instrs])
        # 纯整数运算不应该有 I2F
        self.assertNotIn(I2F, self.ops("let x : int := 1; print x + 2;"))

    def test_jumps_are_patched(self):
        code = compile_source("let i : int := 0; while i < 3 do i := i + 1;")
        jumps = [i for i in code.instrs if i.op in (JZ, JUMP)]
        for jump in jumps:
            self.assertNotEqual(jump.arg, 0, "跳转参数还是占位的 0")
            self.assertTrue(0 <= jump.arg < len(code.instrs), f"跳转越界 {jump.arg}")
        self.assertEqual(code.instrs[-1].op, HALT)

    def test_if_else_layout(self):
        code = compile_source("let x : int := 1; if x > 0 then print 1; else print 2;")
        ops = self.ops("let x : int := 1; if x > 0 then print 1; else print 2;")
        self.assertIn(JZ, ops)
        self.assertIn(JUMP, ops)
        # JZ 的目标必须落在 JUMP 之后（else 分支），且不超过最后一条
        jz = next(i for i in code.instrs if i.op == JZ)
        jmp = next(i for i in code.instrs if i.op == JUMP)
        self.assertGreater(jz.arg, code.instrs.index(jmp))

    def test_if_without_else_patch_lands_at_the_end(self):
        code = compile_source("let x : int := 1; if x > 0 then print 1;")
        jz = next(i for i in code.instrs if i.op == JZ)
        self.assertEqual(jz.arg, len(code.instrs) - 1)      # HALT 的位置

    def test_short_circuit_structure(self):
        for source, jump in (("let b : bool := true; print b and false;", JZ),
                             ("let b : bool := true; print b or false;", JNZ)):
            code = compile_source(source)
            ops = [i.op for i in code.instrs]
            self.assertEqual(ops.count(jump), 2, source)
            self.assertEqual(ops.count(JUMP), 1, source)
            self.assertTrue(all(i.arg != 0 or i.op == HALT for i in code.instrs
                                if i.op in (JUMP, jump, JZ, JNZ)))

    def test_instructions_carry_source_lines(self):
        code = compile_source("let i : int := 0;\nwhile i < 3 do\n  i := i + 1;")
        lines = {i.line for i in code.instrs}
        self.assertIn(2, lines)
        self.assertIn(3, lines)
        self.assertEqual(code.instrs[0].line, 1)

    def test_constant_pool_dedups_but_keeps_types_apart(self):
        code = compile_source("print 1; print 1; print 1.0; print true;")
        # 1 == 1.0 == True 在 Python 里相等，所以"去重"必须按类型判，count() 会骗人
        from tinylang.values import type_name
        by_type = {}
        for constant in code.constants:
            by_type.setdefault((type_name(constant), constant), 0)
            by_type[(type_name(constant), constant)] += 1
        self.assertEqual(sorted(by_type.values()), [1, 1, 1])      # 1、1.0、true 各一份
        self.assertEqual(len(code.constants), 3)

    def test_disassembly_mentions_source_lines(self):
        text = compile_source("let x : int := 2;\nprint x * 3;").disassemble()
        self.assertIn("第 2 行", text)
        self.assertIn("STORE", text)
        self.assertIn("BIN", text)

    def test_codegen_refuses_an_unchecked_ast(self):
        program = Program(stmts=[])
        bad = Binary(op="+", left=IntLit(value=1, span=Span(1, 1, 1, 1)),
                     right=Ident(name="x", span=Span(1, 7, 1, 7)), span=Span(1, 1, 1, 1))
        program.stmts = [__import__("tinylang.nodes", fromlist=["Print"]).Print(
            expr=bad, span=Span(1, 1, 1, 9))]
        with self.assertRaises(Exception) as ctx:
            generate(program)
        self.assertIn("语义检查", str(ctx.exception))

    # ------------------------------------------------ 函数（B41 候选②）
    def test_functions_layout_call_ret_and_table(self):
        code = compile_source("""fun add(a : int, b : int) -> int { return a + b; }
print add(2, 3);
""")
        ops = [i.op for i in code.instrs]
        self.assertIn(CALL, ops)
        self.assertIn(RET, ops)
        self.assertIn(NORET, ops)
        # 主线以 HALT 结束，函数体全部排在它之后（由入口断言间接钉住）
        self.assertEqual(len(code.functions), 1)
        info = code.functions[0]
        self.assertEqual((info.name, info.arity, info.return_type), ("add", 2, "INT"))
        self.assertGreaterEqual(info.entry, 0)
        self.assertLess(info.entry, len(code.instrs))
        self.assertEqual(code.instrs[info.entry - 1].op, HALT)   # 函数体紧跟在主线之后
        self.assertEqual(code.instrs[-1].op, NORET)              # 体尾的落点保护

    def test_call_renders_with_function_name(self):
        code = compile_source("fun twice(x : int) -> int { return x * 2; }\nprint twice(21);")
        text = code.disassemble()
        self.assertIn("CALL", text)
        self.assertIn("; twice", text)
        # CALL 的参数是函数表下标（0），不是地址——反汇编能看到名字
        self.assertIn(f"CALL   0", text)

    def test_argument_and_return_widening_emit_i2f(self):
        code = compile_source("fun f(x : real) -> real { return x; }\nprint f(2);")
        self.assertIn(I2F, [i.op for i in code.instrs])          # 实参 2 在调用点加宽
        code = compile_source("fun g(x : int) -> int { return x; }\nprint g(2);")
        self.assertNotIn(I2F, [i.op for i in code.instrs])       # int→int 不加宽
        code = compile_source("fun h() -> real { return 1; }")   # 返回值层面加宽
        self.assertIn(I2F, [i.op for i in code.instrs])


class TestRuntime(unittest.TestCase):
    def test_floor_division_matches_python_semantics(self):
        for a in (-9, -7, -1, 0, 1, 7, 9):
            for b in (-3, -1, 1, 3):
                with self.subTest(a=a, b=b):
                    result = run(f"print {a} / {b};") if a >= 0 else run(f"print {a} / {b};")
                    self.assertEqual(result.output, [str(a // b)])
                    self.assertEqual(run(f"print {a} % {b};").output, [str(a % b)])

    def test_real_division_is_exact_float(self):
        self.assertEqual(run("print 1 / 2;").output, ["0"])          # int 除法是 floor
        self.assertEqual(run("print 1.0 / 2;").output, ["0.5"])
        self.assertEqual(run("let r : real := 0.1; print r + 0.2;").output,
                         [repr(0.1 + 0.2)])

    def test_print_formatting(self):
        source = ('print 3; print 3.0; print "txt"; print true; print false; print 2.5 * 2;')
        self.assertEqual(run(source).output, ["3", "3.0", "txt", "true", "false", "5.0"])

    def test_runtime_errors_carry_the_line(self):
        cases = {
            "print 1 / 0;": "除数为 0",
            "let r : real := 0.0; print 1.0 / r;": "除数为 0",
            "let z : int := 0; print 5 % z;": "除数为 0",
            "let i : int := 1; while i > 0 do i := i + 1;": "步数超过上限",
        }
        for source, fragment in cases.items():
            with self.subTest(source=source):
                with self.assertRaises(RuntimeError_) as ctx:
                    run(source, max_steps=3000)
                self.assertIn(fragment, ctx.exception.message)
                self.assertGreaterEqual(ctx.exception.span.line, 1)

    def test_runtime_error_line_is_the_line_that_failed(self):
        source = "let i : int := 0;\nlet z : int := 0;\nprint i + 1;\nprint 10 / z;\n"
        with self.assertRaises(RuntimeError_) as ctx:
            run(source)
        self.assertEqual(ctx.exception.span.line, 4)

    def test_max_steps_is_a_real_bound(self):
        result = run("let i : int := 0; while i < 100 do { i := i + 1; }", max_steps=10_000)
        self.assertLess(result.steps, 10_000)
        with self.assertRaises(RuntimeError_):
            run("let i : int := 0; while i < 100 do { i := i + 1; }", max_steps=50)

    def test_handcrafted_bad_bytecode_is_caught(self):
        """防线测试：绕过前端直接构造非法指令，VM 必须报错而不是崩溃或静默。"""
        def run_instrs(instrs, constants=(), locals_count=1):
            code = Code(instrs=list(instrs), constants=list(constants),
                        locals_count=locals_count)
            return VM(code).run()

        with self.assertRaises(RuntimeError_) as ctx:
            run_instrs([Instr(PRINT, None, 1), Instr(HALT, None, 1)])
        self.assertIn("栈下溢", ctx.exception.message)

        with self.assertRaises(RuntimeError_):
            run_instrs([Instr(PUSH, 99, 1), Instr(HALT, None, 1)])          # 常量池越界

        with self.assertRaises(RuntimeError_):
            run_instrs([Instr(PUSH, 0, 1), Instr(LOAD, 7, 1), Instr(HALT, None, 1)],
                       constants=[1])

        with self.assertRaises(RuntimeError_):
            run_instrs([Instr(JUMP, 42, 1), Instr(HALT, None, 1)])          # 跳转越界

        with self.assertRaises(RuntimeError_):
            run_instrs([Instr(BIN, 0, 1), Instr(HALT, None, 1)])            # 少一个操作数

        with self.assertRaises(RuntimeError_):
            run_instrs([Instr(PUSH, 0, 1), Instr(PRINT, None, 1), Instr(HALT, None, 1)],
                       constants=[object()])                                 # 打不出来的值

    def test_missing_halt_is_reported(self):
        code = Code(instrs=[Instr(PUSH, 0, 1)], constants=[1], locals_count=1)
        with self.assertRaises(RuntimeError_):
            VM(code).run()

    def test_trace_records_pc_line_and_stack(self):
        result = run("let x : int := 2; print x + 1;", trace_limit=10)
        self.assertTrue(result.trace)
        text = "\n".join(step.render() for step in result.trace)
        self.assertIn("STORE", text)
        self.assertIn("PRINT", text)

    def test_pipeline_never_runs_a_program_with_errors(self):
        with self.assertRaises(Exception):
            compile_source("print y;")
        built = build("print y;")
        self.assertIsNone(built.code)
        self.assertFalse(built.ok)

    # ------------------------------------------------ 调用帧（B41 候选②）
    def test_recursion_computes_and_caller_frame_is_restored(self):
        source = """fun fib(n : int) -> int {
    if n < 2 then return n;
    return fib(n - 1) + fib(n - 2);
}
let keep : int := 41;
print fib(16);
print keep;
"""
        result = run(source)
        self.assertEqual(result.output, ["987", "41"])    # 调用不动调用者的帧
        self.assertEqual(result.locals_view, [41])        # keep=41 还在；函数帧不污染全局帧

    def test_missing_return_is_a_runtime_error_at_the_closing_brace(self):
        source = "fun f(x : int) -> int {\n    let y : int := x + 1;\n}\nprint f(1);"
        with self.assertRaises(RuntimeError_) as ctx:
            run(source)
        self.assertEqual(ctx.exception.message,
                         "函数 'f' 执行到了函数体结尾也没有遇到 return（返回类型 int）")
        self.assertEqual(ctx.exception.span.line, 3)

    def test_depth_cap_boundary_is_exact(self):
        program = ("fun down(n : int) -> int {\n"
                   "    if n = 0 then return 0;\n"
                   "    return down(n - 1);\n"
                   "}\n")
        # down(99) 恰好 100 层（顶层是第 0 层），通过；down(100) 需要第 101 层，被拒
        result = run(program + "print down(99);")
        self.assertEqual(result.output, ["0"])
        with self.assertRaises(RuntimeError_) as ctx:
            run(program + "print down(100);")
        self.assertIn(f"调用深度超过上限 {DEFAULT_MAX_CALL_DEPTH}", ctx.exception.message)
        self.assertIn("第 101 层调用被拒绝", ctx.exception.message)
        self.assertEqual(ctx.exception.span.line, 3)

    def test_handcrafted_bad_bytecode_call_defenses(self):
        """防线测试：绕过前端构造非法调用相关指令，VM 必须报错而不是崩溃。"""
        def run_instrs(instrs, constants=(), locals_count=1, functions=()):
            code = Code(instrs=list(instrs), constants=list(constants),
                        locals_count=locals_count, functions=list(functions))
            return VM(code).run()

        with self.assertRaises(RuntimeError_) as ctx:
            run_instrs([Instr(RET, None, 1), Instr(HALT, None, 1)])
        self.assertIn("RET 被执行时调用栈是空的", ctx.exception.message)

        with self.assertRaises(RuntimeError_) as ctx:
            run_instrs([Instr(NORET, None, 4), Instr(HALT, None, 1)])
        self.assertIn("NORET 被执行时不在任何函数体内", ctx.exception.message)

        with self.assertRaises(RuntimeError_) as ctx:
            run_instrs([Instr(CALL, 7, 1), Instr(HALT, None, 1)])
        self.assertIn("调用了不存在的函数编号 7", ctx.exception.message)

        bad_entry = FunctionInfo(name="ghost", entry=999, locals_count=1, arity=0)
        with self.assertRaises(RuntimeError_) as ctx:
            run_instrs([Instr(PUSH, 0, 1), Instr(CALL, 0, 1), Instr(HALT, None, 1)],
                       constants=[0], functions=[bad_entry])
        self.assertIn("入口地址越界", ctx.exception.message)

        with self.assertRaises(RuntimeError_) as ctx:      # 实参没压够就 CALL
            ok = FunctionInfo(name="f", entry=2, locals_count=2, arity=2)
            run_instrs([Instr(PUSH, 0, 1), Instr(CALL, 0, 1), Instr(RET, None, 2),
                        Instr(HALT, None, 1)], constants=[5], functions=[ok])
        self.assertIn("栈下溢", ctx.exception.message)

    def test_trace_shows_call_depth(self):
        source = "fun one(x : int) -> int { return x; }\nprint one(1);"
        result = run(source, trace_limit=50)
        text = "\n".join(step.render() for step in result.trace)
        self.assertIn("深度=0", text)     # 主线指令
        self.assertIn("深度=1", text)     # 函数体里的指令
        self.assertIn("; one", text)     # CALL 的注释带函数名

    def test_real_return_widening_in_output(self):
        result = run("fun half(x : int) -> real { return x / 2; }\nprint half(5);")
        self.assertEqual(result.output, ["2.0"])     # int 除法 floor 得 2，加宽成 real 的 2.0


class TestValuesModule(unittest.TestCase):
    def test_bool_is_not_int_even_though_python_says_so(self):
        self.assertEqual(values.type_name(True), "BOOL")
        self.assertEqual(values.type_name(1), "INT")
        self.assertEqual(values.format_value(True), "true")
        self.assertEqual(values.format_value(1), "1")

    def test_to_real_rejects_bool(self):
        with self.assertRaises(RuntimeError_):
            values.to_real(True)

    def test_format_for_floats_is_roundtrippable(self):
        for value in (0.5, 2.0, -1.25, 1e-7):
            self.assertEqual(float(values.format_value(value)), value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
