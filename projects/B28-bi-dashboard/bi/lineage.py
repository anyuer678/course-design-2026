"""bi/lineage.py —— 指标血缘图：复用 B27 的 `KnowledgeGraph` 与分层 SVG 渲染。

为什么 BI 项目要有一张血缘图：
    仪表盘上一个数字被质疑时，能救场的不是"我算过了"，而是**这张数从哪一步来的**
    能被列出来。B27 已经有一套三元组 + 传递闭包 + 分层布局 + 点击高亮的东西，
    这里借它的**结构**（节点/边/闭包/SVG），换上 BI 的关系词：
        源数据 --采集--> 脏明细 --清洗步骤--> 干净明细 --装载--> 事实表 --口径--> 指标 --渲染--> 面板
    `kind` 字段存 BI 语义，B27 的 `batch` 字段在这里当**层级号**用（0=源头，4=面板）。

借用是有代价的，写在明面上：
    B27 的渲染里节点副标题写的是"批次N"（那是课程任务的领域词），这里传的是层级号，
    读作"第 N 层"。我没有 fork 一份渲染器去改文案——复制就会有两份会各自烂掉的东西。

`problems()` 是给测试用的：每个指标必须能追溯到至少一个清洗步骤，
每个面板必须挂在至少一个指标上，图中不能有孤岛节点。这几条断言才是血缘图的价值，
画图本身不是。
"""
from __future__ import annotations

from kg import graph as G27, viz as V27

LAYER_SOURCE, LAYER_DIRTY, LAYER_CLEAN, LAYER_TABLE, LAYER_METRIC, LAYER_PANEL = range(6)

# (节点 id, 层级, 人类标签)
NODES = [
    ("seed:source", LAYER_SOURCE, "合成播种（固定种子）"),
    ("dirty:ledger", LAYER_DIRTY, "脏销售明细（5 类缺陷按量注入）"),
    ("dirty:orders", LAYER_DIRTY, "订单主数据（状态/时间）"),
    ("step:clean", LAYER_CLEAN, "B26 清洗链（去重→商品→数量→补金额→剔退货）"),
    ("table:fact_item", LAYER_TABLE, "fact_item（金额粒度）"),
    ("table:fact_order", LAYER_TABLE, "fact_order（订单粒度）"),
    ("table:dim_product", LAYER_TABLE, "dim_product（单价出自 B26，品类出自 B28）"),
    ("table:dim_customer", LAYER_TABLE, "dim_customer（区域/入驻月）"),
    ("metric:gmv", LAYER_METRIC, "成交总额"),
    ("metric:monthly_gmv", LAYER_METRIC, "月度成交额与环比"),
    ("metric:top5", LAYER_METRIC, "TOP5 与 CR5"),
    ("metric:repurchase", LAYER_METRIC, "复购率"),
    ("metric:fulfilment", LAYER_METRIC, "履约时长 P50/P90"),
    ("metric:data_quality", LAYER_METRIC, "数据质量账本"),
    ("insight:co_purchase", LAYER_METRIC, "共购规则（B26 Apriori）"),
    ("insight:segments", LAYER_METRIC, "客户分群（B26 KMeans）"),
    ("panel:kpi", LAYER_PANEL, "KPI 卡片区"),
    ("panel:trend", LAYER_PANEL, "月度趋势图"),
    ("panel:top", LAYER_PANEL, "TOP5 条形图"),
    ("panel:tables", LAYER_PANEL, "规则与分群表"),
]

# (前件, 后件, 关系, 出处)
EDGES = [
    ("seed:source", "dirty:ledger", "采集", "bi/source.seed_dataset"),
    ("seed:source", "dirty:orders", "采集", "bi/source.seed_dataset"),
    ("dirty:ledger", "step:clean", "清洗", "mining/clean.clean（B26）"),
    ("step:clean", "table:fact_item", "装载", "bi/warehouse.build"),
    ("dirty:orders", "table:fact_order", "装载", "bi/warehouse.build"),
    ("dirty:ledger", "table:dim_product", "取维", "mining/clean.PRODUCTS + bi/source.CATEGORIES"),
    ("dirty:orders", "table:dim_customer", "取维", "bi/warehouse._customer_dim"),
    ("table:fact_item", "metric:gmv", "口径", "bi/metrics.gmv"),
    ("table:fact_order", "metric:gmv", "口径", "bi/metrics.gmv"),
    ("table:fact_item", "metric:monthly_gmv", "口径", "bi/metrics.monthly"),
    ("table:fact_item", "metric:top5", "口径", "bi/metrics.top_products"),
    # 订单粒度指标的谓词里有一段 `EXISTS (SELECT 1 FROM fact_item ...)`——
    # 也就是说它们**确实**经过清洗后的明细表。第一版血缘没连这条边，
    # 于是 lineage.problems() 报"追不到任何清洗步骤"：血缘漏边被抓出来了。
    ("table:fact_item", "metric:repurchase", "口径( EXISTS 限定)", "bi/metrics.repurchase"),
    ("table:fact_order", "metric:repurchase", "口径", "bi/metrics.repurchase"),
    ("table:fact_item", "metric:fulfilment", "口径( EXISTS 限定)", "bi/metrics.fulfilment"),
    ("table:fact_order", "metric:fulfilment", "口径", "bi/metrics.fulfilment"),
    ("step:clean", "metric:data_quality", "口径", "bi/metrics.data_quality"),
    ("table:fact_item", "insight:co_purchase", "样本", "bi/insights.baskets"),
    ("table:fact_item", "insight:segments", "样本( EXISTS 限定)", "bi/insights.customer_features"),
    ("table:fact_order", "insight:segments", "样本", "bi/insights.customer_features"),
    ("metric:gmv", "panel:kpi", "渲染", "bi/render.render_html"),
    ("metric:repurchase", "panel:kpi", "渲染", "bi/render.render_html"),
    ("metric:fulfilment", "panel:kpi", "渲染", "bi/render.render_html"),
    ("metric:monthly_gmv", "panel:trend", "渲染", "bi/render.render_html"),
    ("metric:top5", "panel:top", "渲染", "bi/render.render_html"),
    ("insight:co_purchase", "panel:tables", "渲染", "bi/render.render_html"),
    ("insight:segments", "panel:tables", "渲染", "bi/render.render_html"),
]

METRIC_IDS = [n for n, _, _ in NODES if n.startswith(("metric:", "insight:"))]
CLEAN_STEPS = [n for n, layer, _ in NODES if layer == LAYER_CLEAN]
PANEL_IDS = [n for n, _, _ in NODES if n.startswith("panel:")]


def build() -> G27.KnowledgeGraph:
    g = G27.KnowledgeGraph()
    for node_id, layer, label in NODES:
        g.add_task(node_id, layer, label)
    for src, dst, kind, source in EDGES:
        g.add_edge(src, dst, kind, source)
    return g


def problems(g: G27.KnowledgeGraph | None = None) -> list[str]:
    """血缘图的自检：不是"画得好不好看"，而是"能不能追到源头"。"""
    g = g or build()
    out = []
    for metric in METRIC_IDS:
        anc = g.ancestors(metric)
        if not any(step in anc for step in CLEAN_STEPS) and metric != "metric:data_quality":
            out.append(f"{metric} 追不到任何清洗步骤（上游 {sorted(anc)}）")
        if "seed:source" not in anc:
            out.append(f"{metric} 的祖先里没有数据源节点")
    for panel in PANEL_IDS:
        if not g.ancestors(panel):
            out.append(f"面板 {panel} 是孤岛：没有任何指标渲染它")
    reachable: set = set()
    frontier = ["seed:source"]
    while frontier:
        node = frontier.pop()
        for child in g.descendants(node):
            if child not in reachable:
                reachable.add(child)
                frontier.append(child)
    reachable.add("seed:source")
    orphans = sorted(set(g.nodes) - reachable)
    if orphans:
        out.append(f"从数据源走不到的节点：{orphans}")
    return out


def render(title: str = "B28 指标血缘（数据 → 清洗 → 表 → 指标 → 面板）") -> str:
    # 来源说明必须如实：本页数据是 lineage.NODES/EDGES，不是 B27 的课程 CSV——
    # 原先复用 B27 渲染器的默认 hint（"数据来源：data/courses.csv…"）是错误归属，
    # 2026-10-03 展示层批次⑨ 抓出后由渲染器参数化修正。
    return V27.render_html(
        build(), title,
        source_note="数据来源：bi/lineage.py 的 NODES/EDGES 定义（数据 → 清洗 → 表 → 指标 → 面板；"
                    "分层 SVG 渲染复用 B27 的 kg/viz）。本页为自包含文件：{n} 个节点、{m} 条边。")
