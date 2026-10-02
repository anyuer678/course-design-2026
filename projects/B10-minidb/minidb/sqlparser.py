"""minidb/sqlparser.py —— SQL 子集：词法 + 递归下降

支持（够跑一套真实业务表 + 对拍 sqlite）：
    CREATE TABLE name (col INTEGER|TEXT|REAL, ... , PRIMARY KEY(col))
    INSERT INTO name VALUES (...), (...)
    SELECT cols|* FROM name [alias] [INNER] JOIN name [alias] ON expr ...
        [WHERE expr] [ORDER BY col [ASC|DESC] [,...]] [LIMIT n]
    DELETE FROM name WHERE expr
    UPDATE name SET col=字面量, ... WHERE expr
    BEGIN / COMMIT / ROLLBACK / CHECKPOINT
表达式：比较 = != < <= > >=、IS [NOT] NULL、AND OR NOT、括号、
        字面量（数字/负数/字符串/NULL）、列名（可用 表名.列名 限定）。
        注意 UPDATE 的 SET 右侧只能是字面量，不支持 col + 1 这类算术。
"""
from __future__ import annotations

import re


class SqlError(ValueError):
    pass


KEYWORDS = {
    "CREATE", "TABLE", "INSERT", "INTO", "VALUES", "SELECT", "FROM", "WHERE",
    "ORDER", "BY", "LIMIT", "DELETE", "UPDATE", "SET", "AND", "OR", "NOT",
    "PRIMARY", "KEY", "INTEGER", "TEXT", "REAL", "ASC", "DESC", "BEGIN",
    "COMMIT", "ROLLBACK", "CHECKPOINT", "NULL", "IS",
    "JOIN", "INNER", "ON", "AS",
}

TOKEN_RE = re.compile(r"""
    \s*(?:
        (?P<num>\d+\.\d+|\d+)
      | (?P<str>'[^']*')
      | (?P<word>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)
      | (?P<op><=|>=|!=|=|<|>|\(|\)|,|\*|-|\+)
    )""", re.VERBOSE)


def tokenize(sql: str) -> list[tuple[str, object]]:
    toks: list[tuple[str, object]] = []
    pos = 0
    while pos < len(sql):
        m = TOKEN_RE.match(sql, pos)
        if not m:
            if sql[pos:].strip() == "":
                break
            raise SqlError(f"无法解析的记号: {sql[pos:pos+10]!r}")
        pos = m.end()
        if m.group("num") is not None:
            text = m.group("num")
            toks.append(("num", float(text) if "." in text else int(text)))
        elif m.group("str") is not None:
            toks.append(("str", m.group("str")[1:-1]))
        elif m.group("word") is not None:
            w = m.group("word")
            # 限定列名 users.id 整体就是一个标识符，不能当关键字
            toks.append((w.upper(), w) if w.upper() in KEYWORDS else ("ident", w))
        else:
            toks.append(("op", m.group("op")))
    return toks


# ------------------------------------------------- AST 用 tuple 表示
# ("create", table, [(col, type)], pk)
# ("insert", table, [rows])
# ("select", (table, alias), cols, where, order, limit, joins, labels)
#     joins  = [(table, alias, on_expr), ...]（无 JOIN 时为空，旧位置不变）
#     labels = 与 cols 对齐的输出名，None 表示沿用列名（cols == ["*"] 时为空表）
# ("is_null", x) / ("is_not_null", x)：只有它们返回真值；`x = NULL` 是 UNKNOWN
# ("delete", table, where) / ("update", table, sets, where)
# ("begin",) ("commit",) ("rollback",) ("checkpoint",)


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def peek(self) -> tuple[str, object]:
        return self.toks[self.i] if self.i < len(self.toks) else ("eof", None)

    def eat(self, kind: str) -> object:
        k, v = self.peek()
        if k != kind:
            raise SqlError(f"期望 {kind}，实际 {k}({v!r})")
        self.i += 1
        return v

    # ---------- 表达式（优先级：NOT > 比较 > AND > OR）----------
    def expr(self):
        return self.or_expr()

    def or_expr(self):
        left = self.and_expr()
        while self.peek()[0] == "OR":
            self.eat("OR")
            left = ("or", left, self.and_expr())
        return left

    def and_expr(self):
        left = self.not_expr()
        while self.peek()[0] == "AND":
            self.eat("AND")
            left = ("and", left, self.not_expr())
        return left

    def not_expr(self):
        if self.peek()[0] == "NOT":
            self.eat("NOT")
            return ("not", self.not_expr())
        return self.cmp_expr()

    def cmp_expr(self):
        left = self.atom()
        k, v = self.peek()
        if k == "op" and v in ("=", "!=", "<", "<=", ">", ">="):
            self.i += 1
            right = self.atom()
            return ("cmp", v, left, right)
        if k == "IS":                            # IS NULL / IS NOT NULL
            self.eat("IS")
            if self.peek()[0] == "NOT":
                self.eat("NOT")
                self.eat("NULL")
                return ("is_not_null", left)
            self.eat("NULL")
            return ("is_null", left)
        return left

    def atom(self):
        k, v = self.peek()
        if k == "ident":
            self.i += 1
            return ("col", v)
        if k == "NULL":
            self.i += 1
            return ("null",)
        if k in ("num", "str") or (k == "op" and v in ("-", "+")):
            return ("lit", self.value())
        if k == "op" and v == "(":
            self.eat("op")
            inner = self.expr()
            self.eat("op")
            return inner
        raise SqlError(f"表达式里出现意外记号 {v!r}")

    def value(self):
        """字面量：数字（可带正负号）/ 字符串 / NULL。VALUES 与表达式共用。"""
        k, v = self.peek()
        if k == "op" and v in ("-", "+"):
            self.i += 1
            num = self.eat("num")
            return -num if v == "-" else num
        if k in ("num", "str"):
            self.i += 1
            return v
        if k == "NULL":
            self.i += 1
            return None
        raise SqlError(f"期望字面量，实际 {k}({v!r})")

    # ---------- 语句 ----------
    def statement(self):
        k, _ = self.peek()
        if k == "CREATE":
            return self.create()
        if k == "INSERT":
            return self.insert()
        if k == "SELECT":
            return self.select()
        if k == "DELETE":
            return self.delete()
        if k == "UPDATE":
            return self.update()
        if k == "BEGIN":
            self.eat("BEGIN")
            return ("begin",)
        if k == "COMMIT":
            self.eat("COMMIT")
            return ("commit",)
        if k == "ROLLBACK":
            self.eat("ROLLBACK")
            return ("rollback",)
        if k == "CHECKPOINT":
            self.eat("CHECKPOINT")
            return ("checkpoint",)
        raise SqlError(f"不支持的语句: {k}")

    def ident(self) -> str:
        return str(self.eat("ident"))

    def create(self):
        self.eat("CREATE")
        self.eat("TABLE")
        table = self.ident()
        self.eat("op")
        cols = []
        pk = None
        while True:
            k, v = self.peek()
            if k == "PRIMARY":
                self.eat("PRIMARY")
                self.eat("KEY")
                if self.peek() == ("op", "("):   # PRIMARY KEY (col) 带括号写法
                    self.eat("op")
                    pk = self.ident()
                    self.eat("op")
                else:                            # PRIMARY KEY col 简写
                    pk = self.ident()
            else:
                name = self.ident()
                type_tok, type_v = self.peek()
                if type_tok not in ("INTEGER", "TEXT", "REAL"):
                    raise SqlError(f"不支持的类型 {type_v!r}")
                self.i += 1
                cols.append((name, type_v))
            if self.peek() == ("op", ","):
                self.eat("op")
                continue
            break
        self.eat("op")
        if not cols:
            raise SqlError("表至少要有一列")
        if pk is not None and pk not in [c for c, _ in cols]:
            raise SqlError(f"PRIMARY KEY {pk} 不在列中")
        return ("create", table, cols, pk)

    def insert(self):
        self.eat("INSERT")
        self.eat("INTO")
        table = self.ident()
        self.eat("VALUES")
        rows = []
        while True:
            self.eat("op")                        # (
            row = [self.value()]
            while self.peek() == ("op", ","):
                self.eat("op")
                row.append(self.value())
            self.eat("op")                        # )
            rows.append(row)
            if self.peek() == ("op", ","):
                self.eat("op")
                continue
            break
        return ("insert", table, rows)

    def table_ref(self) -> tuple[str, str | None]:
        """表名 [别名]：别名用于 JOIN 里写 u.id 这种限定列名。"""
        name = self.ident()
        alias = None
        if self.peek()[0] == "AS":
            self.eat("AS")
            alias = self.ident()
        elif self.peek()[0] == "ident":
            alias = self.eat("ident")
        return name, alias

    def from_clause(self):
        base = self.table_ref()
        joins = []
        while self.peek()[0] in ("INNER", "JOIN"):
            if self.peek()[0] == "INNER":
                self.eat("INNER")
            self.eat("JOIN")
            right = self.table_ref()
            self.eat("ON")
            joins.append((right[0], right[1], self.expr()))
        return base, joins

    def select(self):
        self.eat("SELECT")
        cols, labels = [], []        # cols=取哪一列；labels=输出键（None=沿用列名）
        if self.peek() == ("op", "*"):
            self.eat("op")
            cols = ["*"]
        else:
            while True:
                cols.append(self.ident())
                if self.peek()[0] == "AS":
                    self.eat("AS")
                    labels.append(self.ident())
                else:
                    labels.append(None)
                if self.peek() == ("op", ","):
                    self.eat("op")
                    continue
                break
        self.eat("FROM")
        base, joins = self.from_clause()
        where = None
        if self.peek()[0] == "WHERE":
            self.eat("WHERE")
            where = self.expr()
        order = []                               # [(列名, 是否DESC)]
        if self.peek()[0] == "ORDER":
            self.eat("ORDER")
            self.eat("BY")
            while True:
                col = self.ident()
                desc = False
                if self.peek()[0] == "DESC":
                    self.eat("DESC")
                    desc = True
                elif self.peek()[0] == "ASC":
                    self.eat("ASC")
                order.append((col, desc))
                if self.peek() == ("op", ","):
                    self.eat("op")
                    continue
                break
        limit = None
        if self.peek()[0] == "LIMIT":
            self.eat("LIMIT")
            limit = int(self.eat("num"))
        return ("select", base, cols, where, order, limit, joins, labels)

    def delete(self):
        self.eat("DELETE")
        self.eat("FROM")
        table = self.ident()
        where = None
        if self.peek()[0] == "WHERE":
            self.eat("WHERE")
            where = self.expr()
        return ("delete", table, where)

    def update(self):
        self.eat("UPDATE")
        table = self.ident()
        self.eat("SET")
        sets = []
        while True:
            col = self.ident()
            self.eat("op")
            val = self.atom()
            sets.append((col, val))
            if self.peek() == ("op", ","):
                self.eat("op")
                continue
            break
        where = None
        if self.peek()[0] == "WHERE":
            self.eat("WHERE")
            where = self.expr()
        return ("update", table, sets, where)


def parse(sql: str):
    p = Parser(tokenize(sql))
    stmt = p.statement()
    if p.peek()[0] != "eof":
        raise SqlError(f"语句末尾有多余内容: {p.peek()!r}")
    return stmt
