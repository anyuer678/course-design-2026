"""bi/source.py —— 数据层：播种合成销售明细，然后交给 **B26 的清洗链**。

为什么数据是合成的、而且是"故意弄脏"的：
    BI 项目最容易糊过去的是"数字从哪来"。这里把来源写成可复算的程序：
    固定种子 ⇒ 每次跑出同一份明细；缺陷**按声明的数量注入** ⇒ 清洗账本的每个计数
    都能与注入数量逐数对上（`etl()["reconcile"]`）。对不上就是红的，不是"差不多"。

清洗**不重写一遍**：直接调用 B26 的 `mining.clean()`。它的五步顺序与语义
（去重 → 未知商品码 → 非法数量 → 缺失金额按默认单价补 → 负额退货剔除）
在 B26 已逐数测过；本项目只负责产生符合它形状的明细行。

三件"看起来是常识、实际上决定指标值"的事，在这里就是数据模型而不是文档：
    1. 商品**单价只有一个出处**：B26 的 `PRODUCTS`。本文件不写任何价格，
       品类是本项目的维表（`CATEGORIES`），两边不重复。
    2. 订单有**三种状态**（DONE / CANCELLED / OPEN），且 `completed_at` 只在 DONE 上有。
       销售额按**完成月**归集（钱货两讫才算成交），履约时长只统计 DONE 单。
    3. 退货单（负额）在清洗链就被剔除 ⇒ 本仪表盘的 GMV 是"**不含退货成交额**"。
       这是口径选择而不是事实，metrics 里会连着备选口径一起写。
"""
from __future__ import annotations

import datetime as dt
import random

from mining import clean as C26

MONTHS = ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09")
# 月度订单量：写死而不是随机，环比才有可解释的形状（9 月开学季冲高）。
ORDERS_PER_MONTH = {"2026-04": 120, "2026-05": 132, "2026-06": 118,
                    "2026-07": 150, "2026-08": 161, "2026-09": 183}
REGIONS = ("东区", "西区", "南区", "北区")
CATEGORIES = {"P01": "输入设备", "P02": "显示设备", "P03": "输入设备",
              "P04": "音视频", "P05": "音视频", "P06": "配件"}
# 品类数量分布偏斜（显示设备单量少但单价高）——为了让"按金额还是按件数"
# 这两种口径真的分出胜负，而不是文档里空说。
CATEGORY_PULL = {"输入设备": 0.42, "音视频": 0.33, "显示设备": 0.09, "配件": 0.16}

INJECTED = {"dup": 12, "unknown": 8, "bad_qty": 6, "missing_amount": 10,
            "negative": 5}
STATUS_WEIGHTS = [("DONE", 0.9), ("CANCELLED", 0.05), ("OPEN", 0.05)]
# 客户池大小决定复购率这个指标"有没有话可说"：864 单摊到 40 个客户身上，
# 人手三单 ⇒ 复购率恒等于 100%，指标成了装饰。放大到 800 才出现只买过一次的客户。
CUSTOMER_POOL = 800
# 6% 的单子带 10–40 天的长尾，否则均值≈中位数，"均值被长尾拉动"这句话就没有数据支撑。
TAIL_RATE, TAIL_DAYS = 0.06, (10, 40)
# 篮子共现的植入比例（见 seed_dataset 里的注释）。
AFFINITY_RATE = 0.45
# 客户池大小是**复购率能不能讲出东西**的关键：864 单摊到 40 个客户身上，
# 人手三单，复购率恒等于 100%，指标就成了装饰。池子放大到 800 之后
# 才出现"只买过一次"的客户，分子分母才有意义（首版就是栽在这里）。
CUSTOMER_POOL = 800
# 履约占多数 1–9 天，但 5% 的单拖到 10–49 天。没有这条长尾，
# "均值被长尾拉动、所以要看中位与 P90"这句话就没有数据支撑（均值≈中位数时它只是空话）。
TAIL_RATE = 0.05
DEFAULT_SEED = 20261001


def _pick_code(rng: random.Random) -> str:
    """按品类偏好抽一个商品码（品类 → 该品类下的商品均匀）。"""
    roll, acc = rng.random(), 0.0
    chosen = None
    for category, weight in CATEGORY_PULL.items():
        acc += weight
        if roll <= acc:
            chosen = category
            break
    codes = [code for code in C26.PRODUCTS if CATEGORIES[code] == chosen]
    return rng.choice(sorted(codes))


def _date_of(month: str, day: int) -> str:
    return f"{month}-{day:02d}"


def seed_dataset(seed: int = DEFAULT_SEED) -> tuple[list[dict], list[dict]]:
    """生成"脏明细 + 订单主数据"。返回 (rows, orders)。

    行的键与 B26 `clean()` 的期望一致（order_id/product/qty/amount），
    额外的 customer_id/created_at/completed_at 只是随行携带——
    `clean()` 用整行指纹去重，多带字段不影响它的判定。
    """
    rng = random.Random(seed)
    rows: list[dict] = []
    orders: list[dict] = []
    seq = 0
    for month in MONTHS:
        for _ in range(ORDERS_PER_MONTH[month]):
            seq += 1
            order_id = f"O{seq:04d}"
            created_day = rng.randint(1, 28)
            created = _date_of(month, created_day)
            status = _weighted(rng, STATUS_WEIGHTS)
            completed = None
            if status == "DONE":
                lead = rng.randint(1, 9)
                if rng.random() < TAIL_RATE:
                    lead += rng.randint(*TAIL_DAYS)
                done = dt.date.fromisoformat(created) + dt.timedelta(days=lead)
                completed = done.isoformat()          # 可能跨月：口径按完成月归集
            customer_id = f"C{rng.randint(1, CUSTOMER_POOL):03d}"
            orders.append({"order_id": order_id, "customer_id": customer_id,
                           "created_at": created, "completed_at": completed,
                           "status": status})
            # sorted() 是必须的：集合并集的字面量顺序由哈希决定，而 str 的哈希受
            # PYTHONHASHSEED 影响。顺序一漂，后面 rng.sample 抽中的"位置"就跟着漂，
            # 整份数据就不再可复现——所以这里先把商品码定序再生成明细行。
            codes = {_pick_code(rng) for _ in range(rng.randint(1, 3))}
            # 共现结构是**人为植入**的（45% 的单子触发）：买显示器的人顺手买支架。
            # 不植入就挖不出规则——随机篮子只会留下"支持度极低且提升度≈1"的噪声，
            # 那种面板看着像有结论，其实什么也没说。植入比例写在这里，不藏在数据里。
            if rng.random() < AFFINITY_RATE:
                codes.add("P06" if "P02" in codes else _pick_code(rng))
            for code in sorted(codes):
                qty = rng.randint(1, 3)
                rows.append({"order_id": order_id, "product": code, "qty": qty,
                             "amount": round(qty * C26.unit_price(code), 2),
                             "customer_id": customer_id, "created_at": created,
                             "completed_at": completed, "status": status})
    return _inject_defects(rows, orders, rng), orders


def _weighted(rng: random.Random, table: list[tuple[str, float]]) -> str:
    roll, acc = rng.random(), 0.0
    for value, weight in table:
        acc += weight
        if roll <= acc:
            return value
    return table[-1][0]


def _inject_defects(rows: list[dict], orders: list[dict],
                    rng: random.Random) -> list[dict]:
    """按 B26 的顺序注入五类缺陷：先内容缺陷，**最后**追加重复行。

    顺序不是风格问题：重复行如果先追加，缺陷注入可能抽中副本，同一缺陷会被
    两个行各算一次，账本计数就对不上注入计数了（B26 的坑，这里照搬其结论）。
    """
    total = len(rows)
    want = sum(INJECTED[k] for k in ("unknown", "bad_qty", "missing_amount",
                                     "negative"))
    idx = rng.sample(range(total), want + INJECTED["dup"])
    unknown = idx[:INJECTED["unknown"]]
    bad_qty = idx[INJECTED["unknown"]:INJECTED["unknown"] + INJECTED["bad_qty"]]
    missing = idx[INJECTED["unknown"] + INJECTED["bad_qty"]:] \
        [:INJECTED["missing_amount"]]
    # 注意这里的右端点：idx 里除了 want 个"内容缺陷"位置，还多备了 dup 个
    # "重复行副本"位置。上一版把它写成开区间切片，结果 negative 吃掉了 dup 的 12 个位置，
    # 注入 5 条退货却清出 17 条——是 etl() 的逐数对照当场报的警，不是任何一条测试。
    negative = idx[INJECTED["unknown"] + INJECTED["bad_qty"]
                   + INJECTED["missing_amount"]:want]
    for i in unknown:
        rows[i] = {**rows[i], "product": "P99"}
    for i in bad_qty:
        rows[i] = {**rows[i], "qty": 0}
    for i in missing:
        rows[i] = {**rows[i], "amount": None}
    for i in negative:
        base = rows[i]["amount"] or C26.unit_price(rows[i]["product"])
        rows[i] = {**rows[i], "amount": -round(abs(base), 2)}
    for i in idx[want:want + INJECTED["dup"]]:
        rows.append(dict(rows[i]))
    return rows


def etl(seed: int = DEFAULT_SEED) -> dict:
    """跑完整清洗链，并把"注入计数 ↔ 账本计数"的对照结果一起返回。"""
    rows, orders = seed_dataset(seed)
    clean_rows, ledger = C26.clean(rows)
    checks = [
        {"step": "duplicates_removed", "injected": INJECTED["dup"],
         "ledger": ledger["duplicates_removed"]},
        {"step": "unknown_product_removed", "injected": INJECTED["unknown"],
         "ledger": ledger["unknown_product_removed"]},
        {"step": "bad_qty_removed", "injected": INJECTED["bad_qty"],
         "ledger": ledger["bad_qty_removed"]},
        {"step": "amount_filled", "injected": INJECTED["missing_amount"],
         "ledger": ledger["amount_filled"]},
        {"step": "returns_removed", "injected": INJECTED["negative"],
         "ledger": ledger["returns_removed"]},
    ]
    for item in checks:
        item["match"] = item["injected"] == item["ledger"]
    ledger["total_injected"] = sum(INJECTED.values())
    ledger["matched"] = all(item["match"] for item in checks)
    return {"dirty_rows": rows, "clean_rows": clean_rows, "orders": orders,
            "ledger": ledger, "reconcile": checks, "seed": seed}
