"""mining/apriori.py —— Apriori 频繁项集挖掘 + 关联规则

课程要点：
    - 支持度 supp(S) = 含 S 的事务数 / 总事务数；频繁项集 = supp ≥ min_support
    - **反单调性（antimonotone）**：频繁项集的所有子集必然频繁。
      这是 Apriori 剪枝的全部依据——候选若含有"已知的非频繁子集"，
      连计数都不用扫，直接丢弃。
    - 置信度 conf(A→B) = supp(A∪B)/supp(A)；**提升度** lift = conf/supp(B)，
      lift > 1 才说明 A 的出现"抬升"了 B 的出现概率（否则只是 B 本来就常见）。
    - 向下闭包保证：频繁项集的任何子集一定也在频繁集合里——
      所以关联规则的后件必然有计数可查，不用回扫事务。

正确性参照：项数 n 较小时，2^n−1 个候选项集可以**全部穷举**逐个数支持度，
与 Apriori 的输出逐项对拍（tests 里的暴力参照）。剪枝统计
（candidates_generated / candidates_pruned）也纳入对拍：被剪枝的候选
必须在穷举里确实是"非频繁的"——剪对了才叫剪。
"""
from __future__ import annotations

import math
from collections import Counter
from itertools import combinations


def _candidate_join(prev: set[frozenset], k: int) -> list[frozenset]:
    """连接步：把两个 (k−1)-频繁项集（共享前 k−2 项）拼成 k 项候选。"""
    ordered = sorted(prev, key=lambda s: sorted(s))
    out = []
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            a, b = sorted(ordered[i]), sorted(ordered[j])
            if a[:-1] == b[:-1] and a[-1] != b[-1]:
                out.append(frozenset(a) | frozenset(b))
    return out


def _has_infrequent_subset(cand: frozenset, freq_set: set[frozenset],
                           k: int) -> bool:
    """剪枝步：k 项候选的任何一个 (k−1) 子集不频繁 -> 该候选必然不频繁。"""
    for sub in combinations(sorted(cand), k - 1):
        if frozenset(sub) not in freq_set:
            return True
    return False


def apriori(transactions: list, min_support: float = 0.5):
    """返回 (frequent, stats)。

    frequent: {frozenset: 计数}，所有满足 supp >= min_support 的项集。
    stats: {"n", "candidates_generated", "candidates_pruned", "scans",
            "by_size": {k: 项集数}}——剪枝有效性纳入测试。
    """
    if not 0 < min_support <= 1:
        raise ValueError("min_support 应在 (0, 1]")
    n = len(transactions)
    txs = [frozenset(t) for t in transactions]
    # 浮点防御：count/n >= min_support 等价于 count >= ceil(min_support·n − ε)
    min_count = math.ceil(min_support * n - 1e-9)

    stats = {"n": n, "candidates_generated": 0, "candidates_pruned": 0,
             "scans": 0, "by_size": {}}

    # ---- L1：直接数每个单项 ----
    c1: Counter = Counter()
    for t in txs:
        for item in t:
            c1[frozenset([item])] += 1
    freq = {s: c for s, c in c1.items() if c >= min_count}
    result = dict(freq)
    freq_set = set(freq)

    k = 2
    while freq_set:
        candidates = _candidate_join(freq_set, k)
        stats["candidates_generated"] += len(candidates)
        kept = []
        for cand in candidates:
            if _has_infrequent_subset(cand, freq_set, k):
                stats["candidates_pruned"] += 1     # 被剪掉的：无需扫描事务
            else:
                kept.append(cand)
        if not kept:
            break
        counts: Counter = Counter()
        for t in txs:
            for cand in kept:
                if cand <= t:                       # 子集判定：候选 ⊆ 事务
                    counts[cand] += 1
        stats["scans"] += 1
        new_freq = {s: c for s, c in counts.items() if c >= min_count}
        stats["by_size"][k] = len(new_freq)
        if not new_freq:
            break
        result.update(new_freq)
        freq_set = set(new_freq)
        k += 1
    return result, stats


def association_rules(frequent: dict[frozenset, int], n: int,
                      min_confidence: float = 0.6) -> list[dict]:
    """从频繁项集生成关联规则 A→B（A、B 非空，A∪B 为该频繁项集）。

    conf = supp(A∪B)/supp(A)；lift = conf/supp(B)。
    向下闭包保证后件 B 的计数必在 frequent 里。返回按置信度降序。
    """
    rules = []
    for s, count in frequent.items():
        if len(s) < 2:
            continue
        items = sorted(s)
        for r in range(1, len(items)):
            for ante_tuple in combinations(items, r):
                ante = frozenset(ante_tuple)
                cons = s - ante
                conf = count / frequent[ante]
                if conf < min_confidence:
                    continue
                supp_cons = frequent[cons] / n
                lift = conf / supp_cons if supp_cons > 0 else 0.0
                rules.append({"ante": ante, "cons": cons, "conf": conf,
                              "lift": lift, "supp": count / n})
    rules.sort(key=lambda r: (-r["conf"], -r["lift"], sorted(r["ante"])))
    return rules


def brute_force_frequent(transactions: list, min_support: float = 0.5):
    """暴力参照：穷举全部单项与组合（2^n−1），逐个数支持度。
    只用于测试对拍——指数复杂度，项数超过十几就不能跑。"""
    n = len(transactions)
    txs = [frozenset(t) for t in transactions]
    all_items: set = set()
    for t in txs:
        all_items |= t
    min_count = math.ceil(min_support * n - 1e-9)
    result: dict[frozenset, int] = {}
    for r in range(1, len(all_items) + 1):
        for combo in combinations(sorted(all_items), r):
            s = frozenset(combo)
            c = sum(1 for t in txs if s <= t)
            if c >= min_count:
                result[s] = c
    return result
