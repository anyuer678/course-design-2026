"""bi/sql_policy.py —— 把"这个包的 SQL 拼接点"变成**登记过的事实**。

为什么单独一个文件：仪表盘最大的长期风险不是某个数字算错，而是三个月后有人
新加一个筛选条件时顺手 `f"... WHERE x = '{value}'"`。所以这里立一条机器可查的规矩：

    `sec32.audit.sql_sites()`（B32 的静态扫描器）扫本包的每个模块，
    得到的拼接点集合必须与下面 `JUDGED` 里登记的集合**双向一致**：
      · 扫出来但没登记 → 红（新出现的拼接点，没人定性过）
      · 登记了但扫不到 → 红（形态变了或函数改名，登记表在骗人）

`JUDGED` 的三种结论含义不同，别混：
    危险            用户输入进了语句文本；本包**不允许存在**，出现即测试失败。
    形态像但安全    语句文本里拼的是程序自有的东西（表名、白名单片段），值全部 `?` 绑定。
    已缓解          历史上曾经危险、现在改对了；保留条目是为了看得到改过的痕迹。

复用 B32 而不是在本项目再写一个扫描器，是 PLAN §6"同一份逻辑不许写两遍"的直接应用。
代价也写清楚：B32 目前只完成了靶件与扫描器，它自己的测试还没补，
所以这条线暂时靠 `problems()` 的登记表自洽（见 README 的依赖说明）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# B28 的 SQL 纪律由 B32 的静态扫描器来查。接线放在**这个文件**里而不是 bi/__init__.py：
# 只有这一个消费者，就别让整包都背上一条对未完成项目的依赖。
# 依赖一个"自己的测试还没补完"的项目是要付利息的：借用的只是
# `sec32.audit.sql_sites` 这一个纯函数，它当前靠自身登记表自洽（见 README 依赖说明）。
_B32_DIR = Path(__file__).resolve().parents[2] / "B32-sec-lab"
if not (_B32_DIR / "sec32" / "audit.py").is_file():
    raise RuntimeError(f"没找到 B32 的扫描器（期望 {_B32_DIR / 'sec32' / 'audit.py'}）")
if str(_B32_DIR) not in sys.path:
    sys.path.insert(0, str(_B32_DIR))

from sec32 import audit as A32                                    # noqa: E402

PACKAGE = Path(__file__).resolve().parent
B32_DIR = _B32_DIR

# 本包允许的拼接点：(模块, 函数名) -> (结论, 理由)
#
# `run` 这一条值得单独说：扫描器把它报成"变量由拼接得到"，实际拼的是
# `params + list(extra_params)`——**两个列表**，不是字符串。扫描器只认"有 Add"的形态，
# 不区分操作数类型，所以这是一个真·误报。处理办法不是去关掉它，而是把它登记下来写清理由：
# 静态检查的价值在于"所有可疑形态都摊开由人定性"，定性必须留下文字。
JUDGED = {
    ("warehouse.py", "build"): ("形态像但安全",
                                "表名来自本函数内写死的字面量元组，不来自任何输入"),
    ("warehouse.py", "run"): ("误报（已定性）",
                              "被拼接的是绑定参数列表 params + extra_params，不是 SQL 文本；"
                              "SQL 文本只由 format 填进 where_for 产出的白名单片段"),
}
FORBIDDEN_VERDICT = "危险"


def scan() -> dict[str, list[dict]]:
    return {path.name: A32.sql_sites(path.read_text(encoding="utf-8"))
            for path in sorted(PACKAGE.glob("*.py"))}


def found_sites() -> set[tuple[str, str]]:
    return {(module, site["func"]) for module, sites in scan().items() for site in sites}


def problems() -> list[str]:
    """双向比对 + "本包不许有危险点"。"""
    found = found_sites()
    judged = set(JUDGED)
    out = [f"未登记的拼接点：{module}::{func}（先定性再入表）"
           for module, func in sorted(found - judged)]
    out += [f"登记表里的条目已扫不到：{module}::{func}"
            for module, func in sorted(judged - found)]
    out += [f"出现定性为危险的拼接点：{module}::{func}"
            for module, func in sorted(judged & found)
            if JUDGED[(module, func)][0] == FORBIDDEN_VERDICT]
    return out


def prove_scanner_has_teeth() -> dict:
    """证明这条线不是摆设：往临时副本里注入一处真拼接，扫描必须点名它。

    改的是**被扫描的源码**（B20 的规矩：不要拿"删掉断言"当反向验证）。
    """
    import shutil
    import tempfile
    from pathlib import Path as P

    work = P(tempfile.mkdtemp(prefix="b28-policy-"))
    try:
        shutil.copytree(PACKAGE, work / "bi")
        target = work / "bi" / "warehouse.py"
        text = target.read_text(encoding="utf-8")
        mutated = text.replace(
            'def _customer_dim(orders: list[dict]) -> list[tuple]:',
            'def injected_demo(region: str) -> list[tuple]:\n'
            '    return [tuple(r) for r in sqlite3.Connection.execute('
            '"SELECT * FROM dim_customer WHERE region = \'\" + region + \"\'")]\n\n\n'
            'def _customer_dim(orders: list[dict]) -> list[tuple]:', 1)
        target.write_text(mutated, encoding="utf-8")
        sites = A32.sql_sites(mutated)
        return {"mutated_func_found": any(s["func"] == "injected_demo" for s in sites),
                "site_count_delta": len(sites) - len(A32.sql_sites(text))}
    finally:
        shutil.rmtree(work, ignore_errors=True)
