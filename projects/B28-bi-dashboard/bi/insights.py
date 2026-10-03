"""bi/insights.py —— 洞察层：共购规则与客户分群，挖掘算法**直接调 B26**，不重写。

这层在 BI 里的位置：指标回答"是多少"，挖掘回答"哪些东西总是一起出现、
客户自然分成几堆"。它是描述性的，不是因果的——面板文字必须这样写，
否则仪表盘会给人一种"解释了原因"的错觉。

两件事是硬要求，不是风格：
    1. **规则要与暴力穷举对拍**。B26 的 `brute_force_frequent` 只用于测试参照
       （指数复杂度，本项目项数只有 6，能跑）。Apriori 的结果必须与它逐数一致。
    2. **分群要报轮廓系数**，并说清"k 是我挑的"。k 由参数给定（不是自动选模），
       所以面板上写的是"按 k=3 划分的结果"，而不是"客户分成三类"这种事实句。

样本量的边界也写在这里：轮廓系数是 O(n^2) 的，所以分群面板只对**抽样子集**
（种子化、按客户号排序后取前 N 个）计算，全量的簇标签照样给。抽样是为了算得动，
不是为了好看，README 的局限一节会连着这条一起写。
"""
from __future__ import annotations

import datetime as dt

from bi import metrics as M
from bi import source as S
from mining import apriori as A26
from mining import clean as C26
from mining import kmeans as K26

FEATURE_NAMES = ("下单数", "成交额", "首末跨度(天)", "涉及品类数")
SAMPLE_FOR_SILHOUETTE = 60          # O(n^2) 的预算上限，抽样是种子化的、可复现


def baskets(data: dict, filters: dict | None = None) -> list[frozenset]:
    """购物篮 = 一个成交订单里出现的商品集合（与 B26 的 `to_baskets` 同定义）。

    口径：只有 DONE 单参与；品类筛选作用于篮内成员（篮子只留该品类的商品），
    这与指标层"订单类筛选作用于订单"是**两种不同语义**，写在面板文字里。
    """
    rows = M.rows_in_scope(data["clean_rows"], data["orders"], filters or {})
    grouped: dict[str, set] = {}
    for r, _ in rows:
        grouped.setdefault(r["order_id"], set()).add(r["product"])
    return [frozenset(v) for v in grouped.values()]


def co_purchase(data: dict, filters: dict | None = None,
                min_support: float = 0.03, min_confidence: float = 0.35) -> dict:
    txs = baskets(data, filters)
    frequent, stats = A26.apriori(txs, min_support)
    rules = A26.association_rules(frequent, stats["n"], min_confidence)
    brute = A26.brute_force_frequent(txs, min_support)
    top = [{"前件": "/".join(sorted(C26.PRODUCTS[i][0] for i in r["ante"])),
            "后件": "/".join(sorted(C26.PRODUCTS[i][0] for i in r["cons"])),
            "置信度": round(r["conf"], 3), "提升度": round(r["lift"], 3),
            "支持度": round(r["supp"], 3)} for r in rules[:5]]
    return {"id": "co_purchase", "名称": "共购关联规则",
            "口径": f"篮=成交订单的商品集合（品类筛选会先裁篮内成员）；"
                    f"min_support={min_support}、min_confidence={min_confidence}；"
                    "提升度>1 才叫正相关，规则是**描述性**的，不代表因果",
            "篮子数": stats["n"], "频繁项集数": len(frequent),
            "规则数": len(rules), "top": top,
            "剪枝": {"生成候选": stats["candidates_generated"],
                     "被剪": stats["candidates_pruned"], "扫描轮数": stats["scans"]},
            "match_brute_force": brute == frequent}


def customer_features(data: dict, filters: dict | None = None) -> tuple[list[str], list[list[float]]]:
    """每个成交客户一行：下单数、成交额、首末跨度、涉及品类数。"""
    filters = filters or {}
    scope = M.orders_in_scope(data["clean_rows"], data["orders"], filters)
    by_customer: dict[str, dict] = {}
    item_of: dict[str, list[dict]] = {}
    for r, o in M.rows_in_scope(data["clean_rows"], data["orders"], filters):
        item_of.setdefault(o["order_id"], []).append(r)
    for o in scope:
        rows = item_of.get(o["order_id"], [])
        bucket = by_customer.setdefault(
            o["customer_id"], {"orders": set(), "amount": 0.0, "days": [],
                               "cats": set()})
        bucket["orders"].add(o["order_id"])
        bucket["amount"] += sum(r["amount"] for r in rows)
        bucket["days"].append(o["created_at"])
        bucket["cats"].update(S.CATEGORIES[r["product"]] for r in rows)
    ids = sorted(by_customer)
    matrix = []
    for cid in ids:
        b = by_customer[cid]
        days = sorted(dt.date.fromisoformat(d) for d in b["days"])
        matrix.append([len(b["orders"]), round(b["amount"], 2),
                       (days[-1] - days[0]).days, len(b["cats"])])
    return ids, matrix


def _sample(ids: list[str], matrix: list[list[float]], limit: int) -> tuple[list[str], list[list[float]]]:
    """种子化等距抽样：客户号已排序，所以抽样结果与 dict 顺序无关。"""
    if len(matrix) <= limit:
        return ids, matrix
    step = len(matrix) / limit
    picks = [int(i * step) for i in range(limit)]
    return [ids[i] for i in picks], [matrix[i] for i in picks]


def segments(data: dict, filters: dict | None = None, k: int = 3,
             seed: int = 0) -> dict:
    ids, matrix = customer_features(data, filters)
    if len(matrix) < k:
        return {"id": "segments", "名称": "客户分群", "跳过": f"客户数 {len(matrix)} < k={k}",
                "口径": "特征=下单数/成交额/首末跨度/品类数；z-score 标准化后 KMeans",
                "簇": [], "轮廓系数": None}
    model = K26.KMeans(k=k, seed=seed).fit(matrix)
    sample_ids, sample_x = _sample(ids, matrix, SAMPLE_FOR_SILHOUETTE)
    sample_model = K26.KMeans(k=k, seed=seed).fit(sample_x)
    sil = K26.silhouette(sample_x, sample_model.labels_)
    clusters = []
    for label in range(k):
        members = [i for i, lab in enumerate(model.labels_) if lab == label]
        if not members:
            continue
        clusters.append({
            "簇": label, "人数": len(members),
            "人均下单数": round(sum(matrix[i][0] for i in members) / len(members), 2),
            "人均成交额": round(sum(matrix[i][1] for i in members) / len(members), 2),
            "平均跨度(天)": round(sum(matrix[i][2] for i in members) / len(members), 1),
            "平均品类数": round(sum(matrix[i][3] for i in members) / len(members), 2),
        })
    return {"id": "segments", "名称": "客户分群",
            "口径": f"特征向量=({', '.join(FEATURE_NAMES)})；KMeans k={k}、seed={seed}、"
                    f"初始中心取自数据点本身；轮廓系数在**等距抽样的 {len(sample_x)} 个客户**上算"
                    "（该指标 O(n^2)），全量簇标签照给；k 是人挑的，不是数据说的",
            "客户数": len(matrix), "抽样人数": len(sample_x), "k": k, "簇": clusters,
            "轮廓系数": round(sil, 3), "迭代轮数": model.iterations_,
            "空簇事件": model.empty_cluster_events_,
            "惯性": round(model.inertia_, 2)}


def panels(data: dict, filters: dict | None = None) -> dict:
    return {"co_purchase": co_purchase(data, filters),
            "segments": segments(data, filters)}
