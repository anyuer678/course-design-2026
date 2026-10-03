"""sec32/audit.py —— 把"这段代码还有几处危险写法"变成一个**会红**的数字。

为什么要这个模块：前三组（SQL 注入、XSS、路径穿越）都是"跑一遍看后果"，
但工程上更需要的是**静态地把危险点列出来**——因为危险点是否在，取决于有没有人
在三个月后新加一个查询时顺手用了 f-string。所以这里做两件互补的事：

1. `sql_sites()`：用 `ast`（不是正则）扫源码，找出"SQL 字符串是被拼出来的"的位置。
   做法是一条极小的污点链：函数里 `sql = <拼接表达式>` => 该变量带污点 =>
   凡 `execute/executemany/executescript(污点变量 或 内联 f-string)` 都记为一个 sink。
   **它只报告形态，不判断后果**：先转义再拼（`login_quote_doubled`）在它眼里同样是拼接点，
   这正好——静态检查的职责是"把所有可疑点摊开"，定性由登记表完成。
2. `JUDGED`：人工登记表，逐个 sink 写明**结论与理由**（危险/已缓解/形态像但安全）。
   `problems()` 做**双向比对**：扫出来但没登记 => 红；登记了但扫不到 => 红。
   这条规矩是从 B17/B18 的"依赖表双向核对"搬来的。

第二件事让第 1 件有了牙齿：扫描器只会报形态，登记表会把"这条形态到底危不危险"
变成可核对的承诺；两者一对不上就红，谁也别想悄悄漂移。
"""
from __future__ import annotations

import ast
from pathlib import Path

# 认得的 sink 分两类：sqlite3 的执行接口（`conn.execute(...)` 这种属性调用），
# 以及本项目自己的包装函数（`_rows(conn, sql)` 这种**名字调用**）。
# 这一行是静态检查最容易翻车的地方：包装函数漏登记，扫描器就会"全绿"，
# 因为真正的 `conn.execute` 藏在 `_rows/_outcome` 里面，业务函数手里只握着变量。
# 本轮实测就是这样——第一版只认属性调用，七个拼接点只扫出 1 个，
# 是 `problems()` 的双向比对（登记了却扫不到）当场把它抓出来的。
ATTR_SINKS = ("execute", "executemany", "executescript")
NAME_SINKS = ("_rows", "_outcome")
PACKAGE = Path(__file__).resolve().parent


def _is_concat(node: ast.expr) -> bool:
    """这个表达式是"把值拼进语句文本"吗？"""
    if isinstance(node, ast.JoinedStr):
        # f-string 只有**真的插值**才算拼；`f"SELECT ?"` 那种没插值的写法是安全的。
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            return True
        if isinstance(node.op, ast.Mod):                      # "…%s" % x
            return True
    return False


def _call_targets(node: ast.AST) -> list[str]:
    """取变量名形式的调用参数（用于污点回看）。"""
    return [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]


def sql_sites(source: str) -> list[dict]:
    """返回 [{"func", "lineno", "shape"}]，按行号排序。纯函数，便于对临时副本复用。"""
    tree = ast.parse(source)
    out: list[dict] = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        tainted: dict[str, int] = {}
        for stmt in ast.walk(fn):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and _is_concat(stmt.value):
                        tainted[target.id] = stmt.lineno
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            func = call.func
            is_sink = ((isinstance(func, ast.Attribute) and func.attr in ATTR_SINKS)
                       or (isinstance(func, ast.Name) and func.id in NAME_SINKS))
            if not (is_sink and call.args):
                continue
            shape = None
            # 实参逐个看，不能只看第一个：本项目的包装函数签名是 `_rows(conn, sql)`，
            # SQL 在**第二个**位置。第一版只查 args[0]，七个拼接点只扫出 1 个，
            # 抓它的是 problems() 的双向比对，不是任何一条测试。
            for arg in call.args:
                if _is_concat(arg):
                    shape = "内联拼接"
                    break
                hit = [name for name in _call_targets(arg) if name in tainted]
                if hit:
                    shape = f"变量 {hit[0]} 由拼接得到"
                    break
            if shape:
                out.append({"func": fn.name, "lineno": call.lineno, "shape": shape})
    return sorted(out, key=lambda r: r["lineno"])


def scan_file(path: Path) -> list[dict]:
    return sql_sites(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 人工登记表
# 每条：(模块, 函数名) -> (结论, 理由)。比对**只用模块+函数名**——
# 行号会随编辑漂移，把它写进判定条件就会红在无关的地方（B21 的教训）。
# `sql_sites` 仍然报告行号，但那是给人定位用的信息，不是核对条件。
JUDGED = {
    ("sqli.py", "login_concat"): ("危险", "用户名与口令直接拼进字面量，谓词可被改写"),
    ("sqli.py", "login_quote_doubled"): ("已缓解", "单引号翻倍后拼；实测挡住本表三条载荷，"
                                                  "但依赖驱动与上下文，且救不了标识符位置"),
    ("sqli.py", "search_concat"): ("危险", "等值条件可被闭合后 UNION 走另一张表"),
    ("sqli.py", "order_concat"): ("危险", "ORDER BY 是表达式位置，可造推断通道"),
    ("sqli.py", "order_whitelist"): ("形态像但安全", "拼进语句的只有白名单里程序自有的字符串，"
                                                     "用户输入从不进入语句文本"),
    ("sqli.py", "note_report_concat"): ("危险", "读取库里的值再拼一次 => 二阶注入"),
    ("sqli.py", "stacked_outcome"): ("危险", "载荷进入 SELECT 文本；本表用它比较两个执行接口的能力"),
}


def scan_package() -> dict[str, list[dict]]:
    return {path.name: scan_file(path)
            for path in sorted(PACKAGE.glob("*.py"))
            if path.name != "audit.py"}


def problems() -> list[str]:
    """双向比对：扫出来没登记 => 红；登记了扫不到 => 红。"""
    found = {(module, site["func"])
             for module, sites in scan_package().items() for site in sites}
    judged = {(module, func) for (module, func) in JUDGED}
    out = [f"扫描发现未登记的拼接点：{module}::{func}"
           for (module, func) in sorted(found - judged)]
    out += [f"登记表里的条目已扫不到（形态变了或函数改名）：{module}::{func}"
            for (module, func) in sorted(judged - found)]
    return out


def summary() -> dict:
    """四组度量的现算汇总——demo 与测试读同一份，避免两套判定。"""
    from sec32 import creds, sqli, traversal, xss

    xss_rows = xss.payload_table()
    tree = traversal.make_tree()
    try:
        rows = traversal.build_case_rows(tree)
    finally:
        _cleanup(tree["base"])
    per_handler = {}
    for handler, _ in traversal.HANDLERS:
        per_handler[handler] = {
            "escaped": sum(1 for r in rows if "skipped" not in r
                           and r[handler]["verdict"] == "ESCAPED"),
            "rejected": sum(1 for r in rows if "skipped" not in r
                            and r[handler]["verdict"] == "REJECTED"),
            "served": sum(1 for r in rows if "skipped" not in r
                          and r[handler]["verdict"] == "SERVED_INSIDE"),
        }
    m = sqli.measure()
    return {
        "sql_sites": {k: len(v) for k, v in scan_package().items()},
        "audit_problems": problems(),
        "sqli": {
            "login_leaks_vuln": sum(1 for v, _ in m["login"].values() if v["logged_in"]),
            "login_leaks_fixed": sum(1 for _, f in m["login"].values() if f["logged_in"]),
            "search_leaks_vuln": sum(1 for v, _ in m["search"].values() if v["rows"]),
            "search_leaks_fixed": sum(1 for _, f in m["search"].values() if f["rows"]),
            "second_order_leaks": sum(1 for r in m["second_order"]["concat"]
                                      if r["rows"] and r["rows"] != [("note-body",)]),
        },
        "xss": {
            "payloads": len(xss_rows),
            "vuln_flagged": sum(1 for r in xss_rows if r["vuln_evidence"]),
            "safe_flagged": sum(1 for r in xss_rows if r["safe_evidence"]),
            "roundtrip_ok": sum(1 for r in xss_rows if r["safe_roundtrip"]),
        },
        "traversal": {"cases": len(rows), "by_handler": per_handler},
        "creds": creds.cost_table(),
    }


def _cleanup(base) -> None:
    import shutil

    shutil.rmtree(base, ignore_errors=True)
