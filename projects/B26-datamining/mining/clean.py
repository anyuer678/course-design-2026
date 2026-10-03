"""mining/clean.py —— 可追溯的清洗链：注入缺陷 -> 逐步清洗 -> 报告

课程要点：真实数据挖掘的 80% 工作是清洗，而清洗最容易被糊过去的是
"每一步到底删了什么"。本模块把缺陷**按已知数量注入**合成销售明细，
清洗报告的每个计数都必须与注入数量精确对上——报告不是文案，是账本。

清洗步骤（顺序固定，每步独立计数）：
    1. dedup        完全重复行去重（保留首次出现）
    2. product      未知商品码剔除
    3. qty          数量非法（非正整数）剔除
    4. amount_fill  金额缺失 -> 按数量 × 商品单价填补（业务规则：默认价）
    5. amount_neg   金额为负 -> 视为退货单剔除（业务声明）
清洗后的行再供 Apriori 生成购物篮。
"""
from __future__ import annotations

import random

PRODUCTS = {
    "P01": ("键盘", 199.0),
    "P02": ("显示器", 999.0),
    "P03": ("鼠标", 79.0),
    "P04": ("耳机", 299.0),
    "P05": ("摄像头", 159.0),
    "P06": ("支架", 89.0),
}

# 生成器刻意让 P01 与 P02 高频同单（植入模式，规则挖掘应当能找到它）
PAIRED = ("P01", "P02")


def make_dirty_ledger(n_orders: int = 40, seed: int = 7):
    """生成含缺陷的销售明细。缺陷数量是构造时写死的，且缺陷行互不重叠——
    这样清洗报告的每个计数才能与注入数量精确对账。

    注入顺序有讲究：先在**基础行**上注入内容缺陷（互不重叠的下标），
    最后再追加重复行（复制带缺陷的行）。若先追加重复行，缺陷注入可能
    抽中重复副本（与其源行同缺陷、同被清理），账就串了。
    """
    rng = random.Random(seed)
    rows = []
    for i in range(n_orders):
        oid = f"O{i:03d}"
        # 半数订单挂"植入配对"（P01+P02 成对出现），其余随机 1~2 个商品。
        # 比例选 1/2 是探针实测：1/3 经清洗丢行后支持度掉到 0.26，
        # 达不到 0.3 的挖掘阈值，规则找不到就无从演示。
        if i % 2 == 0:
            items = [("P01",), ("P02",)] + \
                [(rng.choice(list(PRODUCTS)),) for _ in range(rng.randint(0, 1))]
        else:
            items = [(rng.choice(list(PRODUCTS)),) for _ in range(rng.randint(1, 2))]
        # 去重保序（不能用 set 迭代：字符串哈希加盐会让每次进程的
        # 迭代序不同，qty 分配跟着漂移，页面数据就不可复现了）
        dedup_items = list(dict.fromkeys(items))
        for (code,) in dedup_items:
            qty = rng.randint(1, 3)
            rows.append({"order_id": oid, "product": code, "qty": qty,
                         "amount": round(qty * PRODUCTS[code][1], 2)})

    total_before = len(rows)
    dup_count, unknown_count = 3, 2
    bad_qty_count, missing_amount_count, negative_count = 2, 3, 1

    # 内容缺陷打在互不重叠的基础行上
    defect_idx = rng.sample(range(total_before),
                            unknown_count + bad_qty_count
                            + missing_amount_count + negative_count)
    unknown_idx = set(defect_idx[:unknown_count])
    bad_qty_idx = set(defect_idx[unknown_count:unknown_count + bad_qty_count])
    missing_idx = set(defect_idx[unknown_count + bad_qty_count:
                                 unknown_count + bad_qty_count + missing_amount_count])
    negative_idx = set(defect_idx[unknown_count + bad_qty_count
                                  + missing_amount_count:])
    for i in unknown_idx:
        rows[i] = {**rows[i], "product": "P99"}       # 未知商品码
    for i in bad_qty_idx:
        rows[i] = {**rows[i], "qty": 0}               # 非正整数数量
    for i in missing_idx:
        rows[i] = {**rows[i], "amount": None}         # 金额缺失
    for i in negative_idx:
        rows[i] = {**rows[i], "amount": -abs(rows[i]["amount"] or 1.0)}

    # 追加完全重复行（复制带缺陷的行）——必须在内容缺陷之后追加
    for i in rng.sample(range(total_before), dup_count):
        rows.append(dict(rows[i]))

    return rows, {"injected": {"dup": dup_count, "unknown": unknown_count,
                               "bad_qty": bad_qty_count,
                               "missing_amount": missing_amount_count,
                               "negative": negative_count,
                               "total_before": total_before}}


def clean(rows: list[dict]) -> tuple[list[dict], dict]:
    """逐步清洗并返回 (clean_rows, report)。每个计数都是一步的账。"""
    report: dict[str, int] = {"total": len(rows)}
    seen = set()
    step1 = []
    for r in rows:
        key = tuple(sorted(r.items()))
        if key in seen:
            continue
        seen.add(key)
        step1.append(r)
    report["duplicates_removed"] = len(rows) - len(step1)

    step2 = [r for r in step1 if r["product"] in PRODUCTS]
    report["unknown_product_removed"] = len(step1) - len(step2)

    step3 = []
    bad_qty = 0
    for r in step2:
        q = r["qty"]
        if isinstance(q, int) and not isinstance(q, bool) and q > 0:
            step3.append(r)
        else:
            bad_qty += 1
    report["bad_qty_removed"] = bad_qty

    step4 = []
    filled = 0
    for r in step3:
        if r["amount"] is None:
            # 业务规则：缺失金额按 默认单价 × 数量 填补（可追溯，不凭空造数）
            r = {**r, "amount": round(PRODUCTS[r["product"]][1] * r["qty"], 2)}
            filled += 1
        step4.append(r)
    report["amount_filled"] = filled

    final = [r for r in step4 if r["amount"] > 0]
    report["returns_removed"] = len(step4) - len(final)
    report["clean"] = len(final)
    return final, report


def to_baskets(clean_rows: list[dict]) -> list[frozenset]:
    """按订单聚合购物篮：一个 order_id -> 该单出现过的商品集合。"""
    baskets: dict[str, set] = {}
    for r in clean_rows:
        baskets.setdefault(r["order_id"], set()).add(r["product"])
    return [frozenset(v) for v in baskets.values()]


def unit_price(code: str) -> float:
    return PRODUCTS[code][1]
