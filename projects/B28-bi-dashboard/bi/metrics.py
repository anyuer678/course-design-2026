"""bi/metrics.py —— 指标层：口径写进代码，每个数字都有**两条独立算法**产出。

BI 项目里最贵的错误不是算错，而是"同一个指标名在两个地方算出两个数，
而没人说清哪个对"。这里用两条规矩顶住它：

1. **口径是指标的一部分**，不是注释。每个指标带一段 `definition` 文本，
   写明：时间字段用哪个（下单日还是完成日）、哪些状态计入、分子分母是什么、
   除零怎么办、月末尾巴算不算。改口径必须同时改这段文字，对拍会盯着它。
2. **两路对拍**：SQL 是被交付的执行器，纯 Python 是它的**参照实现**。
   两份独立写，由 `reconcile()` 逼它们逐数相等。
   （这不是 PLAN §6 反对的"同一份逻辑写两遍"——那条反对的是实现和测试各写一份解析器；
   这里是刻意的跨实现对拍，与 B18 的 Python/Java 判定表、B26 的 Apriori/全枚举同一路。）

一件最容易藏起来的歧义，这里摊开写（就是 `筛选粒度`）：
    同一个"品类=显示设备"筛选，在**金额类**指标里作用于明细行（只加这个品类的钱），
    在**订单类**指标里作用于订单（只要这单里出现过该品类，整单的时长/复购都算）。
    两种语义都对，但必须说清——不然"按品类筛选后的复购率"没人能复算。

关于"完成月"：数据只造到 2026-09-28 的下单日，而完成要加 1–9 天，
于是 **2026-10 只可能是跨月尾巴**，不是完整月。趋势面板照实画 7 个点，
但把 `incomplete` 标出来，环比与解读只看完整月。
"""
from __future__ import annotations

import sqlite3

from bi import source as S
from bi import warehouse as W

# 两套 FROM：金额粒度（从明细出发）与订单粒度（从订单出发 + EXISTS 限定品类）。
# `{item}` 槽都在 `{order}` 槽之前，与 `where_for` 的参数顺序一一对应。
ITEM_FROM = ("FROM fact_item i JOIN fact_order o ON o.order_id = i.order_id "
             "JOIN dim_product p ON p.code = i.code "
             "JOIN dim_customer c ON c.id = o.customer_id "
             "WHERE o.status = ?{item}{order}")
ORDER_FROM = ("FROM fact_order o JOIN dim_customer c ON c.id = o.customer_id "
              "WHERE o.status = ? AND EXISTS (SELECT 1 FROM fact_item i "
              "JOIN dim_product p ON p.code = i.code "
              "WHERE i.order_id = o.order_id{item}){order}")

GMV_SQL = "SELECT round(sum(i.amount), 2) " + ITEM_FROM
MONTH_SQL = ("SELECT o.completed_month, round(sum(i.amount), 2) " + ITEM_FROM
             + " GROUP BY 1 ORDER BY 1")
TOP_SQL = ("SELECT p.name, round(sum(i.amount), 2), sum(i.qty) " + ITEM_FROM
           + " GROUP BY p.name ORDER BY 2 DESC, 1 ASC LIMIT 5")
BUYERS_SQL = "SELECT count(DISTINCT o.customer_id) " + ORDER_FROM
REPEAT_SQL = ("SELECT count(*) FROM (SELECT o.customer_id " + ORDER_FROM
              + " GROUP BY o.customer_id HAVING count(DISTINCT o.order_id) >= 2)")
LEAD_AGG_SQL = ("SELECT count(*), round(avg(o.lead_days), 2) " + ORDER_FROM
                + " AND o.lead_days IS NOT NULL")
LEAD_VALUE_SQL = ("SELECT o.lead_days " + ORDER_FROM + " AND o.lead_days IS NOT NULL"
                  + " ORDER BY o.lead_days ASC LIMIT 1 OFFSET ?")


# ---------------------------------------------------------------- 参照实现
def _pass(order: dict, filters: dict) -> bool:
    """纯 Python 侧的谓词，与 `warehouse` 的白名单片段逐条对应。

    两张表必须同步改；`tests` 里有一条专门证明"改了 SQL 片段忘了改这里会红"。
    """
    if order["status"] != W.TRADING_STATUS:
        return False
    month = (order["completed_at"] or "")[:7]
    if not month:
        return False
    if filters.get("month_from") and month < filters["month_from"]:
        return False
    if filters.get("month_to") and month > filters["month_to"]:
        return False
    if filters.get("region") and _region_of(order["customer_id"]) != filters["region"]:
        return False
    return True


def _region_of(customer_id: str) -> str:
    index = int(customer_id[1:])
    return S.REGIONS[(index - 1) % len(S.REGIONS)]


def rows_in_scope(clean_rows: list[dict], orders: list[dict],
                   filters: dict) -> list[tuple[dict, dict]]:
    """金额粒度的参照集合：明细行必须自己命中品类筛选（只加这个品类的钱）。"""
    by_id = {o["order_id"]: o for o in orders}
    out = []
    for r in clean_rows:
        o = by_id[r["order_id"]]
        if not _pass(o, filters):
            continue
        if filters.get("category") and S.CATEGORIES[r["product"]] != filters["category"]:
            continue
        out.append((r, o))
    return out


def orders_in_scope(clean_rows: list[dict], orders: list[dict],
                     filters: dict) -> list[dict]:
    """订单粒度的参照集合：只要该单**出现过**命中品类就整单入选（与 ORDER_FROM 同语义）。"""
    touching: set[str] = set()
    for r in clean_rows:
        if not filters.get("category") or S.CATEGORIES[r["product"]] == filters["category"]:
            touching.add(r["order_id"])
    return [o for o in orders
            if o["order_id"] in touching and _pass(o, filters)]


# ---------------------------------------------------------------- 指标
def gmv(conn: sqlite3.Connection, data: dict, filters: dict) -> dict:
    sql = W.run(conn, GMV_SQL, filters)
    py = round(sum(r["amount"] for r, _ in rows_in_scope(
        data["clean_rows"], data["orders"], filters)), 2)
    return {"id": "gmv", "名称": "成交总额", "unit": "元",
            "口径": "只计 status=DONE；金额=Σ(单价×数量)；按**完成月**归集；"
                    "退货单（负额）已在清洗链剔除 ⇒ 这是不含退货的成交额；"
                    "品类筛选作用于明细行",
            "sql": (sql[0][0] if sql and sql[0][0] is not None else 0.0), "py": py,
            # 上一版这条没有 equal 字段，而 mismatches() 用的是 `row.get("equal", True)`——
            # 于是 GMV 这个最重要的指标**从来没被对拍检查过**，还一直显示"干净"。
            # 缺字段与字段为假必须是两回事，见 mismatches() 的新写法。
            "equal": (sql[0][0] if sql and sql[0][0] is not None else 0.0) == py}


def monthly(conn, data, filters) -> dict:
    sql_rows = [(m, amt) for m, amt in W.run(conn, MONTH_SQL, filters)]
    buckets: dict[str, float] = {}
    for r, o in rows_in_scope(data["clean_rows"], data["orders"], filters):
        month = o["completed_at"][:7]
        buckets[month] = round(buckets.get(month, 0.0) + r["amount"], 2)
    py_rows = sorted(buckets.items())
    last_created = max(o["created_at"][:7] for o in data["orders"])
    series, prev = [], None
    for month, amount in sql_rows:
        mom = None if prev in (None, 0) else round((amount - prev) / prev * 100, 1)
        series.append({"month": month, "amount": amount, "mom_pct": mom,
                       "incomplete": month > last_created})
        prev = amount
    return {"id": "monthly_gmv", "名称": "月度成交额与环比", "unit": "元",
            "口径": f"横轴是**完成月**；环比=(本月-上月)/上月×100，首月与上月为 0 记 None；"
                    f"晚于最晚下单月（{last_created}）的月份是跨月尾巴，标 incomplete "
                    "不参与趋势解读",
            "sql": series, "py": py_rows,
            "equal": [(row["month"], row["amount"]) for row in series] == py_rows}


def top_products(conn, data, filters) -> dict:
    sql_rows = [(n, a, u) for n, a, u in W.run(conn, TOP_SQL, filters)]
    amount: dict[str, float] = {}
    units: dict[str, int] = {}
    for r, _ in rows_in_scope(data["clean_rows"], data["orders"], filters):
        name = S.C26.PRODUCTS[r["product"]][0]
        amount[name] = round(amount.get(name, 0.0) + r["amount"], 2)
        units[name] = units.get(name, 0) + r["qty"]
    ranked = sorted(amount.items(), key=lambda kv: (-kv[1], kv[0]))
    by_units = sorted(units.items(), key=lambda kv: (-kv[1], kv[0]))
    total = sum(amount.values())
    py_rows = [(n, amount[n], units[n]) for n, _ in ranked[:5]]
    return {"id": "top5", "名称": "TOP5 商品与集中度", "unit": "元 / %",
            "口径": "排名按**金额**，并列按名称升序（保证可复现）；CR5=TOP5 金额÷总金额；"
                    "同时给按件数的 TOP5 作对照——两种口径的冠军可以不是同一个商品",
            "sql": sql_rows, "py": py_rows,
            "by_units": by_units[:5],
            "cr5": round(sum(v for _, v in ranked[:5]) / total * 100, 1) if total else None,
            "equal": sql_rows == py_rows}


def repurchase(conn, data, filters) -> dict:
    buyers = W.run(conn, BUYERS_SQL, filters)[0][0]
    repeat = W.run(conn, REPEAT_SQL, filters)[0][0]
    scope = orders_in_scope(data["clean_rows"], data["orders"], filters)
    per_customer: dict[str, set] = {}
    for o in scope:
        per_customer.setdefault(o["customer_id"], set()).add(o["order_id"])
    py_buyers, py_repeat = len(per_customer), sum(
        1 for ids in per_customer.values() if len(ids) >= 2)
    rate = lambda b, r: round(r / b * 100, 1) if b else None  # noqa: E731
    return {"id": "repurchase", "名称": "复购率", "unit": "%",
            "口径": "分母=窗口内至少成交 1 单的客户，分子=成交 ≥2 单的客户；"
                    "窗口按完成月；同一单买两件不同商品**不算**复购（按订单去重）；"
                    "品类筛选作用于订单（该单出现过该品类即入选）",
            "sql": {"buyers": buyers, "repeat": repeat, "rate": rate(buyers, repeat)},
            "py": {"buyers": py_buyers, "repeat": py_repeat,
                   "rate": rate(py_buyers, py_repeat)},
            "equal": (buyers, repeat) == (py_buyers, py_repeat)}


def fulfilment(conn, data, filters) -> dict:
    import datetime as dt
    scope = []
    for o in orders_in_scope(data["clean_rows"], data["orders"], filters):
        if o["completed_at"]:
            scope.append((dt.date.fromisoformat(o["completed_at"])
                          - dt.date.fromisoformat(o["created_at"])).days)
    lead = sorted(scope)
    n = len(lead)
    if not n:
        return {"id": "fulfilment", "名称": "履约时长", "unit": "天",
                "口径": "完成日减下单日；只统计 DONE 单；空集时全部记 None",
                "sql": None, "py": None, "equal": True, "n": 0}

    def at(q: float) -> int:
        """分位数定义：最近秩的下取整。两路用同一条公式，写在唯一一处。"""
        return lead[min(n - 1, int((n - 1) * q))]

    count, sql_mean = W.run(conn, LEAD_AGG_SQL, filters)[0]
    p50 = W.run(conn, LEAD_VALUE_SQL, filters, [int((count - 1) * 0.5)])[0][0]
    p90 = W.run(conn, LEAD_VALUE_SQL, filters, [int((count - 1) * 0.9)])[0][0]
    py = {"n": n, "mean": round(sum(lead) / n, 2), "p50": at(0.5), "p90": at(0.9),
          "max": lead[-1]}
    return {"id": "fulfilment", "名称": "履约时长", "unit": "天",
            "口径": "完成日-下单日的整数天；只统计 DONE 单；分位数取 "
                    "`lead[min(n-1, int((n-1)*q))]`（两路同一公式）；"
                    "均值被长尾拉动，所以均值/中位/P90 三个都给",
            "sql": {"n": count, "mean": sql_mean, "p50": p50, "p90": p90},
            "py": py,
            "equal": (count, sql_mean, p50, p90)
            == (py["n"], py["mean"], py["p50"], py["p90"])}


def data_quality(conn, data, filters) -> dict:
    ledger = data["ledger"]
    return {"id": "data_quality", "名称": "数据质量账本", "unit": "行",
            "口径": "缺陷按声明数量注入，清洗由 B26 的 mining.clean 执行；"
                    "账本每个计数必须与注入计数逐数对上；"
                    "本指标描述数据本身，不受筛选影响",
            "sql": ledger, "py": data["reconcile"],
            "equal": ledger["matched"] and all(c["match"] for c in data["reconcile"])}


METRICS = (gmv, monthly, top_products, repurchase, fulfilment, data_quality)


def compute(conn: sqlite3.Connection, data: dict,
            filters: dict | None = None) -> dict:
    """跑全部指标，按指标 `id` 归档；两路是否一致留在每个结果的 `equal` 字段里。"""
    filters = filters or {}
    results = {}
    for fn in METRICS:
        row = fn(conn, data, filters)
        results[row["id"]] = row
    return results


def mismatches(results: dict) -> list[str]:
    """两路对拍的结论。缺 `equal` 字段与字段为假**同样是红**——
    缺字段说明这个指标根本没在被打量，比数值不一致更危险。"""
    out = []
    for row in results.values():
        if "equal" not in row:
            out.append(f"{row['id']}（{row['名称']}）：没有对拍结论（缺 equal 字段）")
        elif not row["equal"]:
            out.append(f"{row['id']}（{row['名称']}）")
    return out
