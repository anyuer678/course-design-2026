"""datascope/mining.py —— 挖掘引擎适配层：import B26 真实实现，零重写。

    - apriori：B26 mining.apriori（支持度/置信度/提升度 + 反单调剪枝）
      适配为"CSV 的两列（分组列 + 项列）→ 购物篮 → 频繁项集 + 规则"；
    - kmeans：B26 mining.KMeans（种子化初始中心、空簇处理、确定性）
      适配为"CSV 的若干数值列 → 聚类标签 + 质心 + 惯性/轮廓"。

适配层只做三件事：取列、转数值（坏值报行号）、结果转 JSON 安全形状
（frozenset/float→JSON）。算法语义零改动——metrics 与直接调用引擎对拍（tests）。
"""
from __future__ import annotations

from mining.apriori import apriori as b26_apriori
from mining.apriori import association_rules as b26_rules
from mining.kmeans import KMeans, silhouette as b26_silhouette

from .dataset import Table


def apriori_from_rows(table: Table, *, group_col: str, item_col: str,
                      min_support: float = 0.5,
                      min_confidence: float = 0.6) -> dict:
    """购物篮关联挖掘：group_col 聚成事务，item_col 为项。"""
    if group_col not in table.columns or item_col not in table.columns:
        raise ValueError(f"列不存在，可用：{table.columns}")
    rows = table.rows
    if not rows:
        raise ValueError("没有数据行（先导入或清洗出数据）")
    baskets: dict[str, set] = {}
    for index, row in enumerate(rows):
        group, item = row.get(group_col, ""), row.get(item_col, "")
        if group.strip() == "" or item.strip() == "":
            raise ValueError(f"第 {index + 1} 行（数据行）：{group_col!r} 或 "
                             f"{item_col!r} 为空，无法聚篮")
        baskets.setdefault(group, set()).add(item)
    transactions = [frozenset(v) for v in baskets.values()]
    frequent, stats = b26_apriori(transactions, min_support)
    rules = b26_rules(frequent, stats["n"], min_confidence)
    itemsets = [{"items": sorted(s), "count": c,
                 "support": round(c / stats["n"], 4)}
                for s, c in sorted(frequent.items(), key=lambda kv: (-kv[1], sorted(kv[0])))]
    return {
        "task": "apriori",
        "itemsets": itemsets,
        "rules": [{"ante": sorted(r["ante"]), "cons": sorted(r["cons"]),
                   "confidence": round(r["conf"], 4), "lift": round(r["lift"], 4),
                   "support": round(r["supp"], 4)} for r in rules],
        "stats": stats,
        "params": {"group_col": group_col, "item_col": item_col,
                   "min_support": min_support, "min_confidence": min_confidence},
        "notes": "引擎 = B26 mining.apriori（原项目 import，未重写）",
    }


def kmeans_from_rows(table: Table, *, columns: list[str], k: int,
                     seed: int = 0, max_iters: int = 100) -> dict:
    """数值列聚类：columns 按顺序组成特征向量，坏值报行号。"""
    if not columns:
        raise ValueError("columns 不能为空（至少一列数值特征）")
    for name in columns:
        if name not in table.columns:
            raise ValueError(f"列 {name!r} 不存在，可用：{table.columns}")
    X, index_of = [], []
    for index, row in enumerate(table.rows):
        vector = []
        for name in columns:
            value = (row.get(name, "") or "").strip()
            if value == "":
                raise ValueError(f"第 {index + 1} 行（数据行）：{name!r} 为空，"
                                 f"聚类前先用 fill_missing 补齐")
            try:
                vector.append(float(value))
            except ValueError:
                raise ValueError(f"第 {index + 1} 行（数据行）：{name}={value!r} "
                                 f"不是数字（先 to_number 或清洗）") from None
        X.append(vector)
        index_of.append(index)
    model = KMeans(k=k, seed=seed, max_iters=max_iters).fit(X)
    return {
        "task": "kmeans",
        "labels": model.labels_,
        "centroids": model.centroids_,
        "metrics": {"inertia": round(model.inertia_, 4),
                    "iterations": model.iterations_,
                    "silhouette": round(b26_silhouette(X, model.labels_), 4),
                    "empty_cluster_events": model.empty_cluster_events_},
        "params": {"columns": columns, "k": k, "seed": seed,
                   "max_iters": max_iters},
        "notes": "引擎 = B26 mining.KMeans（原项目 import，未重写）",
    }
