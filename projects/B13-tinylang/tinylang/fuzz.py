"""tinylang/fuzz.py —— 随机程序生成器（测试与演示共用语料）。

生成"应当通过语义检查并能正常跑完"的程序文本：它自己维护类型与作用域，
和检查器用的是同一套规则。如果它产出的程序被检查器拒绝，对拍测试会**失败**而不是跳过——
那说明两处的类型规则走偏了，正是这类测试最有价值的时刻。

三个刻意的设计：
* 循环计数变量被"锁定"，随机语句不许改写它，循环因此必然有界；
* 除数一律经过 `nonzero()` 变换（`x*x + 1`），干净语料里不会偶然踩到除零；
* 但保留"短路陷阱"：`(g != 0) and (10 / (g) > 0)`——哪一边把 and 当成两个操作数都要算，
  g 为 0 时就会当场除零，短路语义于是被随机语料反复检查。

函数（B41 候选②的增量）：
* 程序开头先生成 1–3 个函数：随机形参（0–2 个）、随机返回类型，体里只有
  let/assign/print + 结尾必有的 return——**不生成循环**，终止性一眼可见；
* **函数体只调用更早定义的函数**（登记在体生成之后），调用图无环 → 运行必终止、
  深度自然有界；主程序里可以调用任何已定义函数；
* 函数体里看不到全局变量（语言规则），生成器的可见名字也要跟着"换地板"，
  否则会生成"给未声明变量赋值"的坏程序——对拍测试会当场红；
* 调用作为表达式原子出现；**实参里不再套调用**（call_allowed=False）——
  嵌套调用（f(g(x))）由手写语料与递归样例覆盖，生成器保持"一眼能读懂"。

**重建说明（2026-10-02）**：本文件在一次误删事故里丢失，且没有任何存储留下逐字全文
（它当时的生成方式见事故记录：从测试文件里切出类体再拼模块头，而那份测试文件已被同一次
改动改写）。这里按上面的设计说明与 `tests/test_against_reference.py` 的调用面重建，
由那套测试（300 个随机程序、双引擎逐字节对拍 + 最终变量状态比对）验收——
**功能等价经实测，但不保证与原文件逐字相同。**
"""
from __future__ import annotations

import random

INTS, REALS, BOOLS, STRINGS = "INT", "REAL", "BOOL", "STRING"
LOWER = {INTS: "int", REALS: "real", BOOLS: "bool", STRINGS: "string"}

STRING_ALPHABET = "abcXYZ 019"
MAX_LOOP_STEPS = 3


class ProgramGen:
    """文本级生成器：一边拼字符串，一边维护作用域与类型。

    不做 AST 组装、也不回填——跟着检查器的规则走一遍，本身就验证了"规则能被一致地实现两次"。
    """

    def __init__(self, rng: random.Random, *, allow_short_circuit_trap: bool = True):
        self.rng = rng
        self.scopes: list[dict[str, str]] = [{}]      # 名字 -> 类型；末位是当前作用域
        self.locked: set[str] = set()                 # 循环计数变量：不许被随机赋值改写
        self.lines: list[str] = []
        self.seq = 0
        self.allow_short_circuit_trap = allow_short_circuit_trap
        self.functions: dict[str, tuple[list[str], str]] = {}   # 名字 -> (形参类型, 返回类型)
        self.func_seq = 0
        self.call_allowed = True      # 实参生成期间临时关掉（不生成嵌套调用）
        self.visible_floor = 0        # 函数体内只看本函数的作用域（看不到全局）

    # ---------------------------------------------------------------- 命名与作用域
    def fresh_name(self) -> str:
        self.seq += 1
        return f"v{self.seq}"

    def visible(self, want: str | None = None) -> list[str]:
        names: list[str] = []
        for scope in self.scopes[self.visible_floor:]:
            for name, type_name in scope.items():
                if want is None or type_name == want:
                    names.append(name)
        return names

    def new_var(self, type_name: str) -> str:
        name = self.fresh_name()
        self.scopes[-1][name] = type_name
        return name

    def _emit(self, indent: int, text: str) -> None:
        self.lines.append("    " * indent + text)

    # ---------------------------------------------------------------- 表达式
    def nonzero(self, type_name: str, depth: int) -> str:
        """`x*x + 1`：恒不为零，且不引入新变量。整数保持整数，实数保持实数。"""
        text, _ = self.expr(type_name, depth + 1)
        return f"({text} * {text} + 1)"

    def expr(self, want: str, depth: int) -> tuple[str, str]:
        """返回 (文本, 类型)。类型可能比 want"窄"（int 对 real），由赋值处显式加宽。"""
        if depth > 3:
            return self.atom(want)
        roll = self.rng.random()
        if want in (INTS, REALS) and roll < 0.35:
            return self.arith(want, depth)
        if want == BOOLS and roll < 0.55:
            return self.boolean(depth)
        if want == STRINGS and roll < 0.3:
            left, _ = self.atom(STRINGS)
            right, _ = self.atom(STRINGS)
            return f"({left} + {right})", STRINGS
        return self.atom(want)

    def atom(self, want: str) -> tuple[str, str]:
        if self.call_allowed and self.functions and self.rng.random() < 0.3:
            call = self.call_atom(want)
            if call is not None:
                return call
        candidates = self.visible(want)
        if want == REALS:
            candidates = candidates + self.visible(INTS)      # 唯一允许的自动加宽
        if want != STRINGS and candidates and self.rng.random() < 0.5:
            name = self.rng.choice(candidates)
            type_name = (INTS if name in self.locked and want == REALS and
                         name not in self.visible(REALS) else self._type_of(name))
            return name, type_name
        if want == INTS:
            return str(self.rng.randint(-9, 20)), INTS
        if want == REALS:
            return f"{self.rng.randint(-9, 9)}.{self.rng.randint(0, 99):02d}", REALS
        if want == BOOLS:
            return self.rng.choice(("true", "false")), BOOLS
        return '"%s"' % "".join(self.rng.choice(STRING_ALPHABET)
                                for _ in range(self.rng.randint(0, 6))), STRINGS

    def _type_of(self, name: str) -> str:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise KeyError(name)

    # ---------------------------------------------------------------- 函数（B41 候选②）
    def call_atom(self, want: str) -> tuple[str, str] | None:
        """挑一个返回类型兼容的函数生成调用；实参里不再套调用（nesting 交给手写语料）。"""
        candidates = [name for name, (_, return_type) in self.functions.items()
                      if return_type == want
                      or (return_type == INTS and want == REALS)]    # 唯一允许的加宽
        if not candidates:
            return None
        name = self.rng.choice(candidates)
        param_types, return_type = self.functions[name]
        saved = self.call_allowed
        self.call_allowed = False
        try:
            args = []
            for type_name in param_types:
                text, _ = self.expr(type_name, 2)     # 参数保持浅：深处只出原子
                args.append(text)
        finally:
            self.call_allowed = saved
        return f"{name}({', '.join(args)})", return_type

    def declare_function(self) -> None:
        self.func_seq += 1
        name = f"f{self.func_seq}"
        param_types = [self.rng.choice((INTS, INTS, REALS, BOOLS))
                       for _ in range(self.rng.randint(0, 2))]
        return_type = self.rng.choice((INTS, INTS, REALS, BOOLS))
        params = ", ".join(f"p{index} : {LOWER[type_name]}"
                           for index, type_name in enumerate(param_types, 1))
        self._emit(0, f"fun {name}({params}) -> {LOWER[return_type]} {{")
        self.scopes.append({f"p{index}": type_name
                            for index, type_name in enumerate(param_types, 1)})
        saved_floor = self.visible_floor
        self.visible_floor = len(self.scopes) - 1      # 函数体看不到全局
        try:
            for _ in range(self.rng.randint(1, 3)):
                roll = self.rng.random()
                if roll < 0.4:
                    self.declare()
                elif roll < 0.8:
                    self.assign()
                else:
                    self.print_stmt(0)
            text, _ = self.expr(return_type, 0)
            self._emit(0, f"return {text};")
        finally:
            self.visible_floor = saved_floor
            self.scopes.pop()
        self._emit(0, "}")
        self._emit(0, "")
        # 登记放在体生成之后：函数体只能调用更早定义的函数，调用图无环 → 运行必终止
        self.functions[name] = (param_types, return_type)

    def arith(self, want: str, depth: int) -> tuple[str, str]:
        op = self.rng.choice(("+", "-", "*", "/", "%")) if want == INTS else \
            self.rng.choice(("+", "-", "*", "/"))
        left, left_type = self.expr(want, depth + 1)
        if op in ("/", "%"):
            right = self.nonzero(want, depth + 1)              # 除数恒非零
        else:
            right, _ = self.expr(want, depth + 1)
        result_type = REALS if REALS in (left_type, want) else want
        return f"({left} {op} {right})", result_type

    def boolean(self, depth: int, trap_ok: bool = False) -> tuple[str, str]:
        """`trap_ok=True` 只由**语句级条件**传入：短路陷阱必须整体当一个条件。

        教训（实测）：陷阱写成 `(g != 0) and (10 / (g) > 0)` 只在"整体是条件"时安全；
        一旦它被 `not` 或别的 `and` 拆开（例如 `not (g != 0) and (10 / (g) > 0)`），
        守卫就反号了——g 为 0 时左边为真，除法照样执行，随机语料于是踩出真除零。
        这不是引擎的错，是生成器把陷阱放错了位置（300 例里 11 例）。
        """
        roll = self.rng.random()
        if roll < 0.2:
            operand, _ = self.expr(BOOLS, depth + 1) if not trap_ok else                 self.boolean(depth + 1, trap_ok=False)
            return f"(not {operand})", BOOLS
        if roll < 0.5:
            left, _ = self.boolean(depth + 1, trap_ok=False)
            right, _ = self.boolean(depth + 1, trap_ok=False)
            return f"({left} {self.rng.choice(('and', 'or'))} {right})", BOOLS
        if roll < 0.65 and trap_ok and self.allow_short_circuit_trap and self.visible(INTS):
            # 短路陷阱：g 可能是 0，只有短路语义才不除零
            g = self.rng.choice(self.visible(INTS))
            return f"({g} != 0) and (10 / ({g}) > 0)", BOOLS
        type_name = self.rng.choice((INTS, REALS, BOOLS))
        if type_name == BOOLS:
            left, _ = self.expr(BOOLS, depth + 1)
            right, _ = self.expr(BOOLS, depth + 1)
            return f"({left} {self.rng.choice(('=', '!='))} {right})", BOOLS
        if type_name == REALS and not self.visible(REALS) and self.visible(INTS):
            type_name = INTS
        if type_name == INTS and not self.visible(INTS):
            type_name = REALS
        left, _ = self.expr(type_name, depth + 1)
        right, _ = self.expr(type_name, depth + 1)
        op = self.rng.choice(("<", "<=", ">", ">=", "=", "!="))
        return f"({left} {op} {right})", BOOLS

    # ---------------------------------------------------------------- 语句
    def stmt(self, depth: int) -> None:
        roll = self.rng.random()
        if depth >= 2:
            roll = min(roll, 0.49)          # 深处只允许 let/assign/print，防止嵌套爆炸
        if roll < 0.24:
            self.declare()
        elif roll < 0.46:
            self.assign()
        elif roll < 0.72:
            self.print_stmt(depth)
        elif roll < 0.88:
            self.if_stmt(depth)
        else:
            self.while_stmt(depth)

    def declare(self) -> None:
        type_name = self.rng.choice((INTS, INTS, REALS, BOOLS, STRINGS))
        # 顺序要紧：**先算初值、后登记名字**。反过来会让初值里引用到自己
        # （实测生成过 `let v3 : real := (v3 - v3);` —— 对拍测试当场把它判红）。
        text, _ = self.expr(type_name, 0)
        name = self.new_var(type_name)
        self._emit(0, f"let {name} : {LOWER[type_name]} := {text};")

    def assign(self) -> None:
        candidates = [n for n in self.visible() if n not in self.locked]
        if not candidates:
            self.declare()
            return
        name = self.rng.choice(candidates)
        wanted = self._type_of(name)
        text, _ = self.expr(wanted, 0)
        self._emit(0, f"{name} := {text};")

    def print_stmt(self, depth: int) -> None:
        type_name = self.rng.choice((INTS, REALS, BOOLS, STRINGS))
        text, _ = self.expr(type_name, depth + 1)
        self._emit(0, f"print {text};")

    def if_stmt(self, depth: int) -> None:
        cond, _ = self.boolean(0, trap_ok=True)
        self._emit(0, f"if {cond} then {{")
        self._block(depth + 1)
        if self.rng.random() < 0.5:
            self._emit(0, "} else {")
            self._block(depth + 1)
        self._emit(0, "}")

    def while_stmt(self, depth: int) -> None:
        ints = [n for n in self.visible(INTS) if n not in self.locked]
        if ints:
            counter = self.rng.choice(ints)
        else:
            # 没有可用计数变量时**必须真的声明它**：只在作用域表里登记而不产出 let，
            # 生成的就是"用了未声明变量"的坏程序——那会让对拍测试红，而不是让生成器看起来正常。
            counter = self.new_var(INTS)
            self._emit(0, f"let {counter} : int := 0;")
        steps = self.rng.randint(1, MAX_LOOP_STEPS)
        self._emit(0, f"{counter} := {steps};")
        self._emit(0, f"while {counter} > 0 do {{")
        self.locked.add(counter)                    # 锁住计数变量：body 里不许改写它
        try:
            self._block(depth + 1)
        finally:
            self.locked.discard(counter)
        self._emit(0, f"{counter} := {counter} - 1;")
        self._emit(0, "}")

    def _deepen(self, depth: int) -> None:
        for _ in range(self.rng.randint(1, 3)):
            self.stmt(depth)

    def _block(self, depth: int) -> None:
        """块 `{ … }` 在语言里**开新作用域**：块里 let 出来的名字出了块就不可见。

        第一版生成器没跟着开作用域，于是 288 个随机程序被检查器拒绝（"使用了未声明的变量"）——
        这正是对拍测试该做的事：生成器自己的规则和检查器走偏了，测试立刻红。
        """
        self.scopes.append({})
        try:
            self._deepen(depth)
        finally:
            self.scopes.pop()

    # ---------------------------------------------------------------- 入口
    def program(self, n_statements: int) -> str:
        self.lines = []
        for _ in range(self.rng.randint(1, 3)):
            self.declare_function()
        for _ in range(max(1, n_statements)):
            self.stmt(0)
            self._emit(0, "")
        return "\n".join(self.lines) + "\n"
