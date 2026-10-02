"""B26-datamining 四段演示：清洗账本 → Apriori 对拍 → K-means → 端到端

全程零依赖、零文件写入（合成数据由固定种子生成）。断言失败计入退出码。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mining.apriori import apriori, association_rules, brute_force_frequent
from mining.clean import PRODUCTS, clean, make_dirty_ledger, to_baskets
from mining.kmeans import KMeans, inertia_of, silhouette

FAILS = []


def check(cond, msg):
    print(f"    {'✔' if cond else '✘'} {msg}")
    if not cond:
        FAILS.append(msg)


def show(title):
    print(f"\n{'=' * 62}\n {title}\n{'=' * 62}")


# ---------------------------------------------------------------- 1
def demo_clean():
    show("第一段：清洗账本 —— 每一步删了什么，都是一笔账")
    rows, injected = make_dirty_ledger(40, seed=7)
    clean_rows, report = clean(rows)
    inj = injected["injected"]
    print(f"    注入缺陷（构造时写死）: 重复 {inj['dup']}、未知商品 {inj['unknown']}、"
          f"非法数量 {inj['bad_qty']}、金额缺失 {inj['missing_amount']}、"
          f"退货负金额 {inj['negative']}")
    print(f"    清洗报告: 总 {report['total']} 行 -> 去重 {report['duplicates_removed']}、"
          f"剔除未知商品 {report['unknown_product_removed']}、非法数量 "
          f"{report['bad_qty_removed']}、退货 {report['returns_removed']}、"
          f"填补金额 {report['amount_filled']}，剩 {report['clean']} 行")
    check(report["duplicates_removed"] == inj["dup"]
          and report["unknown_product_removed"] == inj["unknown"]
          and report["bad_qty_removed"] == inj["bad_qty"]
          and report["amount_filled"] == inj["missing_amount"]
          and report["returns_removed"] == inj["negative"],
          "清洗报告逐数对上注入账本")
    removed = (report["duplicates_removed"] + report["unknown_product_removed"]
               + report["bad_qty_removed"] + report["returns_removed"])
    check(report["total"] == report["clean"] + removed, "行数守恒（填补不算剔除）")
    return clean_rows


# ---------------------------------------------------------------- 2
def demo_apriori():
    show("第二段：Apriori vs 穷举 —— 两个引擎逐项对拍")
    rng = __import__("random").Random(11)
    txs = [set(rng.sample(range(6), rng.randint(2, 4))) for _ in range(25)]
    got, stats = apriori(txs, 0.2)
    want = brute_force_frequent(txs, 0.2)
    print(f"    25 个事务、6 种商品：Apriori {len(got)} 个频繁项集，"
          f"穷举 {len(want)} 个")
    check(got == want, "两引擎结果逐项一致")
    all_combos = 2 ** 6 - 1 - 6
    print(f"    剪枝统计: 生成候选 {stats['candidates_generated']} 个 "
          f"(规模≥2 的全组合共 {all_combos} 个)，剪掉 "
          f"{stats['candidates_pruned']} 个——反单调性省下的扫描")

    freq, n = got, len(txs)
    rules = association_rules(freq, n, min_confidence=0.6)
    print(f"    关联规则（置信度 ≥ 0.6）{len(rules)} 条，前 3 条：")
    for r in rules[:3]:
        a = ", ".join(f"商品{v}" for v in sorted(r["ante"]))
        c = ", ".join(f"商品{v}" for v in sorted(r["cons"]))
        print(f"      {a} -> {c}  conf={r['conf']:.2f} lift={r['lift']:.2f}")
    check(all(r["lift"] > 0 for r in rules), "提升度全部为正")


# ---------------------------------------------------------------- 3
def demo_kmeans():
    show("第三段：K-means —— 团块聚类与轮廓系数")
    rng = __import__("random").Random(0)
    X = [[rng.gauss(0, 0.3), rng.gauss(0, 0.3)] for _ in range(40)] + \
        [[rng.gauss(6, 0.3), rng.gauss(6, 0.3)] for _ in range(40)]
    truth = [0] * 40 + [1] * 40
    km = KMeans(k=2, seed=1).fit(X)
    acc_a = sum(1 for t, p in zip(truth, km.labels_) if t == p) / len(truth)
    aligned = max(acc_a, 1 - acc_a)
    print(f"    两团各 40 点（间隔明显）: 迭代 {km.iterations_} 次，"
          f"与真值对齐 {aligned:.2f}")
    check(aligned == 1.0, "间隔明显的两团被完美分开")
    k1 = KMeans(k=1, seed=0).fit(X).inertia_
    print(f"    惯性: k=1 为 {k1:.1f}（解析等式 = 总方差），"
          f"k=2 降到 {km.inertia_:.1f}")
    check(abs(k1 - inertia_of(X)) < 1e-9 and km.inertia_ < k1,
          "k=1 惯性 = 总方差；k=2 更小")
    sil = silhouette(X, km.labels_)
    print(f"    轮廓系数 {sil:.3f}（接近 1 = 簇内紧簇间远）")
    check(sil > 0.8, "轮廓系数 > 0.8")


# ---------------------------------------------------------------- 4
def demo_pipeline(clean_rows):
    show("第四段：端到端 —— 清洗后的明细变成购物篮与业务规则")
    baskets = to_baskets(clean_rows)
    print(f"    {len(clean_rows)} 行明细聚成 {len(baskets)} 个购物篮")
    freq, stats = apriori(baskets, 0.3)
    rules = association_rules(freq, stats["n"], min_confidence=0.5)
    pair = frozenset({"P01", "P02"})
    print(f"    频繁项集 {len(freq)} 个；植入模式 "
          f"{sorted(pair)} 支持度 {freq.get(pair, 0)}/{stats['n']}")
    check(pair in freq, "植入的 P01+P02 配对被挖掘出来")
    pair_rules = [r for r in rules
                  if r["ante"] <= pair and r["cons"] <= pair
                  and r["ante"] and r["cons"]]
    best = max(pair_rules, key=lambda r: r["conf"])
    a = ", ".join(sorted(best["ante"]))
    c = ", ".join(sorted(best["cons"]))
    name_a = PRODUCTS[a][0]
    name_c = PRODUCTS[c][0]
    print(f"    最强规则: 买{name_a} -> 也买{name_c}  "
          f"conf={best['conf']:.2f} lift={best['lift']:.2f}")
    print(f"    业务解读：lift > 1 说明这对商品确实被同一单连带购买，")
    print(f"    可用于捆绑促销/推荐位——而不是 {name_c} 本来就卖得多。")
    check(best["conf"] >= 0.6 and best["lift"] > 1.0,
          "植入模式以规则形式重现（conf ≥ 0.6 且 lift > 1）")


def main() -> int:
    print("B26-datamining 演示（纯标准库，零依赖）")
    clean_rows = demo_clean()
    demo_apriori()
    demo_kmeans()
    demo_pipeline(clean_rows)
    print(f"\n{'=' * 62}")
    if FAILS:
        print(f"演示存在 {len(FAILS)} 处失败：")
        for f in FAILS:
            print(f"  ✘ {f}")
        return 1
    print("四段演示全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
