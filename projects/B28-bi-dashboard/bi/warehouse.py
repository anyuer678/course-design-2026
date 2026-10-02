"""bi/warehouse.py —— 仓库层：SQLite 星型模型 + **只走占位符**的筛选。

为什么用 SQLite 而不是继续在 Python 里聚合：
    BI 的分工是"聚合交给查询引擎，口径交给人写清"。但这一层最怕的是
    把筛选条件拼成 SQL 字符串——正好是 B32 里那条注入线。所以这里定的规矩是：
      1. 用户可影响的**值**一律 `?` 绑定；
      2. 用户可影响的**字段/片段**一律走 `FILTER_FIELDS` 白名单，命中的是程序自有的字符串；
      3. 表名、列名、ORDER BY 都写死在 SQL 模板里，不接受外部输入。
    这一条不是文档承诺：`tests/test_b28.py` 会拿 B32 的 `sec32.audit.sql_sites()` 扫本包，
    拼接点集合必须与 `bi/sql_policy.py` 里登记的集合**双向**一致。

星型模型：
    fact_item  (order_id, code, qty, amount)          金额粒度
    fact_order (order_id, customer_id, 时间, 状态, 时长)  订单粒度
    dim_product(code → 名称/品类/单价)                  单价来自 B26，不另立出处
    dim_customer(id → 区域/入驻月)
"""
from __future__ import annotations

import sqlite3

from bi import source as S
from mining import clean as C26

DDL = """
CREATE TABLE dim_product (
    code       TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,
    unit_price REAL NOT NULL
);
CREATE TABLE dim_customer (
    id           TEXT PRIMARY KEY,
    region       TEXT NOT NULL,
    joined_month TEXT NOT NULL
);
CREATE TABLE fact_order (
    order_id        TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES dim_customer(id),
    created_at      TEXT NOT NULL,
    created_month   TEXT NOT NULL,
    completed_at    TEXT,
    completed_month TEXT,
    status          TEXT NOT NULL,
    lead_days       INTEGER
);
CREATE TABLE fact_item (
    order_id TEXT NOT NULL REFERENCES fact_order(order_id),
    code     TEXT NOT NULL REFERENCES dim_product(code),
    qty      INTEGER NOT NULL CHECK (qty > 0),
    amount   REAL NOT NULL,
    PRIMARY KEY (order_id, code)
);
"""

# 筛选白名单：键是外部可传的过滤名，值是**程序自有的** SQL 片段。
# 分两组是因为粒度不同：品类住在明细上（要进 EXISTS 子查询），
# 月份/状态住在订单上，区域住在客户上。两条 SQL 模板里 `{item}` 槽在 `{order}` 槽之前，
# 所以下面的参数也**必须**按 item → order → customer 的顺序产出，
# 否则绑定值会串位（这是 B32 "判定顺序要用有序集合"那条教训的同类问题）。
ITEM_FIELDS = (("category", "p.category = ?"),)
ORDER_FIELDS = (("month_from", "o.completed_month >= ?"),
                ("month_to", "o.completed_month <= ?"))
CUSTOMER_FIELDS = (("region", "c.region = ?"),)
FILTER_KEYS = {key for key, _ in ITEM_FIELDS + ORDER_FIELDS + CUSTOMER_FIELDS} \
    | {"status"}
NUMERIC_FILTERS = ("month_from", "month_to")      # 参与比较而非等值
ALLOWED_STATUS = ("DONE", "CANCELLED", "OPEN")
# 成交口径：仪表盘只看成交单。把它做成常量，模板的第一个谓词参数就是它，
# 于是"改了口径"必须同时改这里和 metrics 的口径文字——两处不一致会被对拍抓红。
TRADING_STATUS = "DONE"


class FilterError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _customer_dim(orders: list[dict]) -> list[tuple]:
    """区域与入驻月由客户号确定性推出（不用哈希，保证跨进程可复现）。"""
    seen: dict[str, tuple] = {}
    for o in orders:
        cid = o["customer_id"]
        if cid not in seen:
            index = int(cid[1:])
            seen[cid] = (cid, S.REGIONS[(index - 1) % len(S.REGIONS)],
                         "2026-01" if index <= S.CUSTOMER_POOL // 2 else "2026-05")
    return sorted(seen.values())


def _product_dim() -> list[tuple]:
    rows = []
    for code, (name, price) in sorted(C26.PRODUCTS.items()):
        rows.append((code, name, S.CATEGORIES[code], price))
    return rows


def build(seed: int = S.DEFAULT_SEED,
          check_same_thread: bool = True) -> tuple[sqlite3.Connection, dict]:
    """清洗链 → 入库。返回 (连接, 装载摘要)。内存库：不落文件、不留残留。

    `check_same_thread=False` 只给 `bi/server.py` 用：`ThreadingHTTPServer`
    每个请求一条线程，而这一层**只读**（装载完就不再写），
    Python 的 sqlite3 默认是 serialized 模式（`sqlite3.threadsafety`），
    所以在只读场景下跨线程共用连接是成立的。测试里保持默认值，让误用尽早暴露。
    """
    data = S.etl(seed)
    conn = sqlite3.connect(":memory:", check_same_thread=check_same_thread)
    conn.executescript(DDL)
    conn.executemany("INSERT INTO dim_product VALUES (?,?,?,?)", _product_dim())
    conn.executemany("INSERT INTO dim_customer VALUES (?,?,?)",
                     _customer_dim(data["orders"]))
    order_rows = []
    for o in sorted(data["orders"], key=lambda r: r["order_id"]):
        completed = o["completed_at"]
        lead = None
        if completed:
            import datetime as dt
            lead = (dt.date.fromisoformat(completed)
                    - dt.date.fromisoformat(o["created_at"])).days
        order_rows.append((o["order_id"], o["customer_id"], o["created_at"],
                           o["created_at"][:7], completed,
                           completed[:7] if completed else None,
                           o["status"], lead))
    conn.executemany("INSERT INTO fact_order VALUES (?,?,?,?,?,?,?,?)", order_rows)
    item_rows = sorted((r["order_id"], r["product"], r["qty"], r["amount"])
                       for r in data["clean_rows"])
    conn.executemany("INSERT INTO fact_item VALUES (?,?,?,?)", item_rows)
    conn.commit()
    counts = {table: conn.execute(
        f"SELECT count(*) FROM {table}"      # 表名来自本模块常量，不来自输入
    ).fetchone()[0] for table in
        ("dim_product", "dim_customer", "fact_order", "fact_item")}
    counts["created_month_distinct"] = conn.execute(
        "SELECT count(DISTINCT created_month) FROM fact_order").fetchone()[0]
    return conn, {"loaded": counts, "ledger": data["ledger"],
                  "reconcile": data["reconcile"], "seed": seed,
                  "clean_rows": data["clean_rows"], "orders": data["orders"]}


def where_for(filters: dict) -> tuple[str, str, list]:
    """把筛选字典拆成 (明细粒度片段, 订单粒度片段, 绑定参数)。

    四条规矩：
      1. 值一律 `?` 绑定，片段文字只能来自上面三张白名单表；
      2. 参数顺序固定为 **status → item → order → customer**，与模板里
         `{item}`（在 EXISTS 内）先于 `{order}` 的文本顺序严格对应，
         字典的插入顺序不参与——两个客户端以不同顺序传同一组筛选必须得到同一条 SQL；
      3. 成交口径（`o.status = 'DONE'`）由模板自己写第一个谓词，
         这里只负责把参数表首位放成 "DONE"，避免"忘了勾状态"造成口径漂移；
      4. 未知键、非法月份、非法 status 全部拒绝而不是"忽略"。
    """
    if extra := (set(filters) - FILTER_KEYS):
        raise FilterError(f"未知筛选条件 {sorted(extra)}（白名单：{sorted(FILTER_KEYS)}）")
    status = filters.get("status")
    if status not in (None, "", TRADING_STATUS):
        raise FilterError(f"本仪表盘的成交口径固定为 {TRADING_STATUS}，"
                          f"不接受 status={status!r}；看取消/在途单请走 /drill 明细")
    params: list = [TRADING_STATUS]
    item_parts = []
    for key, clause in ITEM_FIELDS:
        value = filters.get(key)
        if value in (None, ""):
            continue
        item_parts.append(clause)
        params.append(value)
    order_parts = []
    for key, clause in ORDER_FIELDS + CUSTOMER_FIELDS:
        value = filters.get(key)
        if value in (None, ""):
            continue
        if key in NUMERIC_FILTERS and not _is_month(value):
            raise FilterError(f"{key} 需要形如 2026-04 的值，收到 {value!r}")
        order_parts.append(clause)
        params.append(value)
    item_clause = (" AND " + " AND ".join(item_parts)) if item_parts else ""
    order_clause = (" AND " + " AND ".join(order_parts)) if order_parts else ""
    return item_clause, order_clause, params


def _is_month(value: str) -> bool:
    # 两个坑都在这一段：连字符在下标 **4**（第一版写 5，把合法值当非法值拒了），
    # 而且形状对还不够——`2026-13` 会一路通过校验，最后返回**空结果集**。
    # 200 + 空表比 400 更糟：看板上看不出任何错，人却会照着它做决定。
    if not (isinstance(value, str) and len(value) == 7
            and value[:4].isdigit() and value[4] == "-" and value[5:].isdigit()):
        return False
    return 1 <= int(value[5:]) <= 12


def run(conn: sqlite3.Connection, template: str, filters: dict,
        extra_params: list | None = None) -> list[tuple]:
    """执行带 `{item}` / `{order}` 两个槽的模板。

    槽里只会填进 `where_for` 从白名单拼出的片段，所有值仍走占位符——
    这是"标识符位置不能绑定"的正面处理（见 B32 的 ORDER BY 一节）。
    `extra_params` **追加在末尾**，模板里的额外 `?` 也必须排在两个槽之后。
    """
    item, order, params = where_for(filters)
    sql = template.format(item=item, order=order)
    if extra_params:
        params = params + list(extra_params)
    return [tuple(r) for r in conn.execute(sql, params)]
