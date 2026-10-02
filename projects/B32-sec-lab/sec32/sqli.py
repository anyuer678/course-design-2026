"""sec32/sqli.py —— SQL 注入：同一份用户输入，两种把值送进数据库的写法，后果差多少。

课程概念（"注入"的定义）：
    **注入不是"用户输入了危险字符"，而是"用户输入被当成了程序代码的一部分解析"。**
    SQL 里单引号是字符串字面量的**语法边界**。边界符号如果可以由数据携带，数据就能提前
    关闭自己的引号，把后面的文字升格成**语句**。参数绑定做的事很朴素：值永远不进语法分析，
    只进值槽位。

这个模块刻意把"漏洞版"和"修复版"**并排放**：相同的表、相同的种子数据、相同的输入，
只有送进 SQL 的方式不同。对照才有证据价值。

四条线 + 一条诚实附注，每条都对应一个能被改动弄红的度量（见 tests/test_b32.py）：
    1. `login_*`        谓词改写：注释截断密码检查、恒真条件返回全部账号。
    2. `search_*`       UNION 跨表取凭据——**列数必须对齐**，载荷能否成立取决于此。
    3. `order_*`        排序位置是**表达式**，不是值槽：占位符绑列名会变成"按常量排序"的
                        **静默无效**（比报错更危险，因为没人会去查它），所以只能白名单。
    4. `note_report_*`  二阶注入：写入时绑定得很安全，**读取时**再拼一次就前功尽弃。
    5. 诚实附注        课本上最出名的那条 `' OR '1'='1` 在**本实验的谓词结构里不成立**，
                        因为 AND 优先级高于 OR。注入能否成立取决于语法与优先级，
                        不取决于载荷是否"看起来很经典"——所以本文件所有结论都是实测的。

还有一件课本讲得含糊的事：叠句执行（`; DROP TABLE ...`）。本项目驱动 `sqlite3` 的
`execute()` **只允许一条语句**，第二条抛 ProgrammingError；`executescript()` 照单执行。
同一段载荷，两个接口的后果完全不同——**危害程度取决于执行接口的能力**，不是载荷文本。
"""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE students (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    dorm    TEXT NOT NULL,
    phone   TEXT NOT NULL
);
CREATE TABLE accounts (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL
);
CREATE TABLE notes (
    author TEXT NOT NULL,
    body   TEXT NOT NULL
);
"""

# 种子数据刻意让 id 顺序与 phone 顺序不同，否则"按常量排序"的静默无效看不出来。
STUDENTS = [
    (1, "张三", "A-101", "13800000003"),
    (2, "李四", "B-202", "13800000001"),
    (3, "王五", "C-303", "13800000002"),
]
ACCOUNTS = [
    ("stu01", "sha256$aaaa", "student"),
    ("admin", "sha256$TOP_SECRET", "admin"),
]

# 教科书级最小载荷。只对本实验自建的临时表生效，不构成对任何真实系统的能力。
#
# 读这些载荷时要看一件事：**它们为什么需要结尾的 `--`**。因为拼接模板长这样
# `... = '{用户输入}'`，右半边那个引号是模板自带的；载荷若不让它消失（注释掉、
# 或让自己的最后一个字面量正好被它闭合），剩下的 SQL 就不是合法语法，直接报错。
# 同理 UNION 那条还要求**列数与左侧对齐**——少一列就是 OperationalError。
# "危险字符"从来不充分，**能否重建合法语法**才是。
PAYLOAD_COMMENT = "admin' --"                    # 截断密码检查
PAYLOAD_OR_TRUE = "' OR '1'='1' --"              # 谓词恒真 + 注释收尾
PAYLOAD_PRECEDENCE = "' OR '1'='1"               # 出名但**在这里不成立**的那条
PAYLOAD_UNION = ("x' UNION SELECT username, password_hash, role FROM accounts --")
PAYLOAD_UNION_BAD_ARITY = ("x' UNION SELECT username, password_hash "
                           "FROM accounts --")
PAYLOAD_BOOL_TRUE = ("CASE WHEN (SELECT count(*) FROM accounts WHERE role='admin')>0 "
                     "THEN phone ELSE id END")
PAYLOAD_BOOL_FALSE = ("CASE WHEN (SELECT count(*) FROM accounts WHERE role='root')>0 "
                      "THEN phone ELSE id END")
PAYLOAD_SECOND_ORDER = "x' UNION SELECT password_hash FROM accounts WHERE role='admin"
PAYLOAD_STACKED = "A-101'; DROP TABLE students; --"


def fresh_db() -> sqlite3.Connection:
    """每个场景一份全新的内存库：对照两侧必须从同一状态出发。"""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO students VALUES (?,?,?,?)", STUDENTS)
    conn.executemany("INSERT INTO accounts VALUES (?,?,?)", ACCOUNTS)
    conn.commit()
    return conn


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[tuple]:
    return [tuple(r) for r in conn.execute(sql, args)]


def _outcome(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> dict:
    """把一次执行的结果统一成 {sql, args, rows, error}，让对照表可读。"""
    try:
        return {"sql": sql, "args": args, "rows": _rows(conn, sql, args),
                "error": None}
    except sqlite3.Error as exc:
        return {"sql": sql, "args": args, "rows": [],
                "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------- 1 登录
def login_concat(conn: sqlite3.Connection, username: str, password: str) -> dict:
    """漏洞版：把用户输入拼进字面量。正常输入时它工作得好好的——
    这正是注入能活到生产环境的原因。"""
    sql = ("SELECT role FROM accounts WHERE username = '" + username
           + "' AND password_hash = '" + password + "'")
    out = _outcome(conn, sql)
    out["logged_in"] = bool(out["rows"])
    out["role"] = out["rows"][0][0] if out["rows"] else None
    return out


def login_bound(conn: sqlite3.Connection, username: str, password: str) -> dict:
    """修复版：值走占位符，输入不进语法分析。"""
    sql = ("SELECT role FROM accounts WHERE username = ? "
           "AND password_hash = ?")
    out = _outcome(conn, sql, (username, password))
    out["logged_in"] = bool(out["rows"])
    out["role"] = out["rows"][0][0] if out["rows"] else None
    return out


def login_quote_doubled(conn: sqlite3.Connection, username: str,
                        password: str) -> dict:
    """半吊子修复的代表：把单引号翻倍再拼。

    实测它在**这一驱动的这一上下文**里挡住了上面三条载荷，但它是"转义一遍再拼"这一
    类方案的代表——正确性依赖字符集、执行模式与上下文，而且**对标识符位置无能为力**
    （见 `order_concat`）。课本结论：绑定，不要转义。
    """
    def esc(text: str) -> str:
        return text.replace("'", "''")
    sql = ("SELECT role FROM accounts WHERE username = '" + esc(username)
           + "' AND password_hash = '" + esc(password) + "'")
    out = _outcome(conn, sql)
    out["logged_in"] = bool(out["rows"])
    out["role"] = out["rows"][0][0] if out["rows"] else None
    return out


# ---------------------------------------------------------------- 2 查询取数
def search_concat(conn: sqlite3.Connection, keyword: str) -> dict:
    """漏洞版：等值查询里拼关键词；载荷对齐列数后就能 UNION 走另一张表。"""
    return _outcome(conn,
                    f"SELECT id, name, dorm FROM students WHERE name = '{keyword}'")


def search_bound(conn: sqlite3.Connection, keyword: str) -> dict:
    """修复版：UNION 载荷在这里只是一段**查不到的字符串**。"""
    return _outcome(conn, "SELECT id, name, dorm FROM students WHERE name = ?",
                    (keyword,))


def like_search_bound(conn: sqlite3.Connection, keyword: str) -> dict:
    """模糊查询的正确写法：通配符在**参数里**拼，而不是拼进语句文本。

    顺手量一个不是注入但会超出预期的边界：`%` 与 `_` 是 LIKE 的元字符，用户输入里带着
    它们会**扩大**匹配范围。要精确匹配就转义元字符并声明 ESCAPE 子句。
    """
    loose = _outcome(conn, "SELECT id, name FROM students WHERE name LIKE ?",
                     (f"%{keyword}%",))
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    strict = _outcome(conn,
                      "SELECT id, name FROM students WHERE name LIKE ? ESCAPE '\\'",
                      (f"%{escaped}%",))
    return {"loose": loose, "strict": strict,
            "widened": len(loose["rows"]) - len(strict["rows"])}


# ---------------------------------------------------------------- 3 标识符位置
SORT_COLUMNS = ("id", "name", "dorm", "phone")
DIRECTIONS = ("asc", "desc")


def order_concat(conn: sqlite3.Connection, column: str) -> dict:
    """漏洞版：列名拼进 ORDER BY。**这个位置没有占位符可写**，所以它是白名单的活。"""
    return _outcome(conn,
                    f"SELECT id, name, phone FROM students ORDER BY {column}")


def order_bound(conn: sqlite3.Connection, column: str) -> dict:
    """反面教材的"看起来安全"：用占位符绑列名。

    实测：SQLite 把绑进来的值当**常量**，排序变成按常量排 ⇒ 结果等于不排序，
    而且**不报错**。与 `order_concat(..., "phone")` 的真实排序一比就看出来了。
    """
    return _outcome(conn, "SELECT id, name, phone FROM students ORDER BY ?",
                    (column,))


def order_whitelist(conn: sqlite3.Connection, column: str,
                    direction: str = "asc") -> dict:
    """修复版：列名与方向都查白名单，拼进语句的**只可能是程序自己写的字符串**。"""
    key = column.strip().lower()
    if key not in SORT_COLUMNS:
        return {"sql": None, "args": (), "rows": [],
                "error": "COLUMN_NOT_ALLOWED"}
    if direction.strip().lower() not in DIRECTIONS:
        return {"sql": None, "args": (), "rows": [],
                "error": "DIRECTION_NOT_ALLOWED"}
    sql = (f"SELECT id, name, phone FROM students ORDER BY {key} "
           f"{direction.strip().lower()}")
    return _outcome(conn, sql)


# ---------------------------------------------------------------- 4 二阶注入
def note_add(conn: sqlite3.Connection, author: str, body: str) -> dict:
    """写入是安全绑定的 ⇒ 载荷**原样进了库**。它的杀伤要等读取那一次。"""
    out = _outcome(conn, "INSERT INTO notes VALUES (?, ?)", (author, body))
    conn.commit()
    return out


def note_report_concat(conn: sqlite3.Connection, author: str) -> dict:
    """漏洞版报表：把**库里的值**拼进语句 ⇒ 二阶注入。

    要点：入参绑定过一次，不构成下游的安全保证。危险的是 sink，不是 source。
    """
    return _outcome(conn,
                    f"SELECT body FROM notes WHERE author = '{author}'")


def note_report_bound(conn: sqlite3.Connection, author: str) -> dict:
    return _outcome(conn, "SELECT body FROM notes WHERE author = ?", (author,))


def note_digest_concat(conn: sqlite3.Connection) -> list[dict]:
    """真实应用里"二阶"的发生方式：先把库里的值读出来，再拿它当过滤条件拼一次。

    这里读 `SELECT author FROM notes`，逐个当参数用——库里存的载荷因此获得第二次生命。
    """
    out = []
    for (author,) in _rows(conn, "SELECT author FROM notes"):
        out.append(note_report_concat(conn, author) | {"author_from_db": author})
    return out


# ---------------------------------------------------------------- 5 叠句能力
def stacked_outcome(conn: sqlite3.Connection, payload: str) -> dict:
    """同一段叠句载荷分别交给两个执行接口，量各自的能力边界。"""
    sql = f"SELECT name FROM students WHERE dorm = '{payload}'"
    out: dict = {"sql": sql}
    try:
        _rows(conn, sql)
        out["execute"] = "no-error"
    except sqlite3.Error as exc:
        out["execute"] = f"{type(exc).__name__}"
    before = _rows(conn, "SELECT count(*) FROM sqlite_master WHERE type='table'")[0][0]
    try:
        conn.executescript(sql)
        out["executescript"] = "no-error"
    except sqlite3.Error as exc:
        out["executescript"] = f"{type(exc).__name__}"
    after = _rows(conn, "SELECT count(*) FROM sqlite_master WHERE type='table'")[0][0]
    out["tables_before"], out["tables_after"] = before, after
    out["tables_dropped"] = before - after
    return out


# ---------------------------------------------------------------- 汇总
def measure() -> dict:
    """跑完五类场景，返回**实测**结果。demo 与测试都读这里，避免两套判定漂移。"""
    conn = fresh_db()
    login_cases = {
        "正常口令": (login_concat(conn, "admin", "sha256$TOP_SECRET"),
                     login_bound(conn, "admin", "sha256$TOP_SECRET")),
        "注释截断": (login_concat(conn, PAYLOAD_COMMENT, "随便填"),
                     login_bound(conn, PAYLOAD_COMMENT, "随便填")),
        "恒真+注释": (login_concat(conn, PAYLOAD_OR_TRUE, "x"),
                      login_bound(conn, PAYLOAD_OR_TRUE, "x")),
        "课本载荷（优先级坑）": (login_concat(conn, PAYLOAD_PRECEDENCE, "x"),
                                 login_bound(conn, PAYLOAD_PRECEDENCE, "x")),
    }
    search_cases = {
        "UNION 取凭据": (search_concat(conn, PAYLOAD_UNION),
                         search_bound(conn, PAYLOAD_UNION)),
        "UNION 列数不对": (search_concat(conn, PAYLOAD_UNION_BAD_ARITY),
                           search_bound(conn, PAYLOAD_UNION_BAD_ARITY)),
    }
    order_cases = {
        "合法输入（两侧必须一致）": (order_concat(conn, "phone"),
                                     order_whitelist(conn, "phone")),
        "推断通道（前提真）": (order_concat(conn, PAYLOAD_BOOL_TRUE),
                               order_whitelist(conn, PAYLOAD_BOOL_TRUE)),
        "推断通道（前提假）": (order_concat(conn, PAYLOAD_BOOL_FALSE),
                               order_whitelist(conn, PAYLOAD_BOOL_FALSE)),
        "绑参当列名（静默无效）": (order_concat(conn, "phone"),
                                   order_bound(conn, "phone")),
    }
    note_add(conn, PAYLOAD_SECOND_ORDER, "note-body")
    second_order = {
        "concat": note_digest_concat(conn),
        "bound": [note_report_bound(conn, PAYLOAD_SECOND_ORDER)],
    }
    return {"login": login_cases, "search": search_cases, "order": order_cases,
            "second_order": second_order,
            "stacked": stacked_outcome(fresh_db(), PAYLOAD_STACKED),
            "like_meta": like_search_bound(conn, "%")}
