"""bi/render.py —— 展示层：手写 SVG 的自包含看板（零图表库、零外部请求）。

为什么自己画 SVG：本机没有 matplotlib / plotly / pandas（2026-10-02 实测），
而 PLAN §8 要求先说明体积与替代方案再安装。替代方案就是 B27 已经验证过的路子：
字符串拼 SVG，浏览器原生就能渲染。

三条渲染纪律，都是有测试钉住的：
    1. **所有动态文本走 `_e()` 转义**（`html.escape(quote=True)`）。筛选值会被回显到页面上，
       这一层与 B32 讲的是同一个错误模型：数据不该有语法身份。
    2. **图里标的数字必须等于 API 返回的数字**。测试直接把 `str(value)` 往页面里找，
       找不到就是红的——不允许"图是示意图"这种交代。
    3. **每张图旁边配一份等价的数据表**（`<table>`）。图给人看形状，表给人看数；
       读屏与打印时也不会丢信息。

`export_html()` 默认写到**临时目录**：仓库里不留生成物，
"跑一遍看板就多出一个 html"这种事不该发生（B27 同样处理）。
"""
from __future__ import annotations

import html
import tempfile
from pathlib import Path

from bi import insights as I
from bi import lineage as L
from bi import metrics as M
from bi import warehouse as W

CHART_W, CHART_H, PAD = 640, 260, 36


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def fmt_money(value: float | None) -> str:
    return "-" if value is None else f"{value:,.0f}"


def fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value}%"


def bar_chart(rows: list[tuple[str, float]], title: str, unit: str) -> str:
    """横向条形图：适合商品名 + 金额这种"名字长、数值大"的数据。"""
    if not rows:
        return f'<svg viewBox="0 0 {CHART_W} 60" role="img"><text x="8" y="30">（无数据）</text></svg>'
    width_max = CHART_W - 220
    top = max(v for _, v in rows) or 1
    parts = [f'<svg viewBox="0 0 {CHART_W} {len(rows) * 34 + 40}" role="img" '
             f'aria-label="{_e(title)}">']
    parts.append(f'<text class="ttl" x="8" y="20">{_e(title)}（{_e(unit)}）</text>')
    for i, (label, value) in enumerate(rows):
        y = 40 + i * 34
        w = max(2, round(value / top * width_max))
        parts.append(f'<rect x="140" y="{y}" width="{w}" height="20" class="bar">'
                     f'<title>{_e(label)}: {value}</title></rect>')
        parts.append(f'<text x="132" y="{y + 15}" class="lbl" text-anchor="end">{_e(label)}</text>')
        parts.append(f'<text x="{140 + w + 6}" y="{y + 15}" class="val">{fmt_money(value)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def line_chart(series: list[dict], title: str) -> str:
    """月度折线 + 柱：未完整月用空心点标出来，不藏也不参与解读。"""
    if not series:
        return f'<svg viewBox="0 0 {CHART_W} 60" role="img"><text x="8" y="30">（无数据）</text></svg>'
    amounts = [row["amount"] for row in series]
    top = max(amounts) or 1
    step = (CHART_W - 2 * PAD) / max(1, len(series) - 1)
    pts, bars = [], []
    for i, row in enumerate(series):
        x = PAD + i * step
        y = CHART_H - PAD - row["amount"] / top * (CHART_H - 2 * PAD)
        pts.append((x, y, row))
        cls = "bar tail" if row["incomplete"] else "bar"
        bars.append(f'<rect class="{cls}" x="{x - 12:.1f}" y="{y:.1f}" width="24" '
                    f'height="{CHART_H - PAD - y:.1f}"><title>{_e(row["month"])}: '
                    f'{row["amount"]}</title></rect>')
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts)
    parts = [f'<svg viewBox="0 0 {CHART_W} {CHART_H + 46}" role="img" aria-label="{_e(title)}">']
    parts.append(f'<text class="ttl" x="8" y="20">{_e(title)}（元；空心=未完整月）</text>')
    parts.extend(bars)
    parts.append(f'<polyline fill="none" class="line" points="{poly}"/>')
    for x, y, row in pts:
        cls = "pt tail" if row["incomplete"] else "pt"
        parts.append(f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="4"/>')
        parts.append(f'<text class="lbl" x="{x:.1f}" y="{CHART_H - PAD + 16}" '
                     f'text-anchor="middle">{_e(row["month"][2:])}</text>')
        if row["mom_pct"] is not None:
            parts.append(f'<text class="val" x="{x:.1f}" y="{y - 8:.1f}" '
                         f'text-anchor="middle">{row["mom_pct"]}%</text>')
    parts.append("</svg>")
    return "".join(parts)


def gauge(percent: float | None, title: str) -> str:
    """环形百分比：复购率这种"一个数就是结论"的指标。"""
    value = 0.0 if percent is None else percent
    r, cx, cy = 52, 70, 70
    circ = 2 * 3.14159 * r
    dash = circ * value / 100.0
    return (f'<svg viewBox="0 0 140 150" role="img" aria-label="{_e(title)}">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" class="ring-bg" fill="none" stroke-width="14"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" class="ring" fill="none" stroke-width="14" '
            f'stroke-dasharray="{dash:.1f} {circ - dash:.1f}" transform="rotate(-90 {cx} {cy})"/>'
            f'<text x="{cx}" y="{cy + 6}" class="big" text-anchor="middle">'
            f'{_e(fmt_pct(percent))}</text>'
            f'<text x="70" y="142" class="lbl" text-anchor="middle">{_e(title)}</text></svg>')


def _table(headers: list[str], rows: list[list[object]], caption: str) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>"
                   for row in rows)
    return (f'<figure><figcaption>{_e(caption)}</figcaption>'
            f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></figure>')


STYLE = """
body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:24px;color:#182029;background:#fbfcfe}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:26px 0 8px}
.grid{display:flex;flex-wrap:wrap;gap:14px}.card{background:#fff;border:1px solid #dfe5ee;
border-radius:10px;padding:12px 14px;min-width:210px}
.kpi{font-size:24px;font-weight:600}.muted{color:#5c6b7f;font-size:12px}
.caliber{background:#fff8e6;border:1px solid #f0d48a;border-radius:8px;padding:8px 10px;
font-size:12px;margin:6px 0}
svg{background:#fff;border:1px solid #dfe5ee;border-radius:10px;max-width:100%}
.ttl{font-size:12px;fill:#182029}.lbl{font-size:11px;fill:#5c6b7f}.val{font-size:11px;fill:#182029}
.big{font-size:18px;font-weight:600}.bar{fill:#4d7dd6}.bar.tail{fill:#c9d6ea}
.line{stroke:#e2574c;stroke-width:2}.pt{fill:#e2574c}.pt.tail{fill:#fff;stroke:#e2574c}
.ring-bg{stroke:#e6ebf3}.ring{stroke:#4d7dd6}
table{border-collapse:collapse;font-size:12px;margin:6px 0}th,td{border:1px solid #dfe5ee;
padding:4px 8px;text-align:right}th:first-child,td:first-child{text-align:left}
caption{text-align:left;font-size:12px;color:#5c6b7f}a{color:#2f5fbf}
"""


def render(results: dict, panels: dict, filters: dict, meta: dict) -> str:
    chips = "".join(f'<span class="muted">{_e(k)}={_e(v)}</span> ' for k, v in sorted(filters.items()))
    monthly = results["monthly_gmv"]["sql"]
    gmv = results["gmv"]
    repur = results["repurchase"]
    fulfil = results["fulfilment"]
    top5 = results["top5"]
    quality = results["data_quality"]
    lead_sql = fulfil["sql"]
    card_rows = [
        (gmv, fmt_money(gmv["sql"]) + " 元"),
        (repur, fmt_pct(repur["sql"]["rate"])
         + f'（{repur["sql"]["repeat"]}/{repur["sql"]["buyers"]} 客户）'),
        (fulfil, "-" if not lead_sql else
         f'{lead_sql["p50"]} / {lead_sql["p90"]} 天（均值 {lead_sql["mean"]}）'),
        (top5, fmt_pct(top5["cr5"]) + " 集中度"),
    ]
    cards = "".join(
        f'<div class="card"><div class="muted">{_e(row["名称"])}</div>'
        f'<div class="kpi">{_e(cell)}</div>'
        f'<div class="caliber">{_e(row["口径"])}</div></div>'
        for row, cell in card_rows)
    rules = panels["co_purchase"]
    segs = panels["segments"]
    body = [
        "<h1>B28 商务智能看板 · 完成月口径 · 合成数据</h1>",
        f'<p class="muted">当前筛选：{chips or "（无）"} ｜ 种子 {meta["seed"]} ｜ '
        f'清洗后明细 {quality["sql"]["clean"]} 行 ｜ '
        f'<a href="/api/summary">JSON 口径</a> ｜ <a href="/lineage">指标血缘图</a></p>',
        f'<div class="grid">{cards}</div>',
        line_chart(monthly, "月度成交额与环比"),
        _table(["完成月", "成交额", "环比%", "未完整月"],
               [[r["month"], fmt_money(r["amount"]),
                 "-" if r["mom_pct"] is None else r["mom_pct"],
                 "是" if r["incomplete"] else ""] for r in monthly],
               "月度趋势数据表（与图同源）"),
        bar_chart([(name, amount) for name, amount, _ in top5["sql"]], "TOP5 商品（按金额）", "元"),
        _table(["商品", "金额", "件数"], [[n, fmt_money(a), u] for n, a, u in top5["sql"]],
               "TOP5 明细；按件数的冠军是 "
               + (str(top5["by_units"][0][0]) if top5["by_units"] else "（无数据）")),
        gauge(repur["sql"]["rate"], "复购率"),
        _table(["特征", "SQL 路", "参照路"],
               [["成交总额", fmt_money(gmv["sql"]), fmt_money(gmv["py"])],
                ["买家数", repur["sql"]["buyers"], repur["py"]["buyers"]],
                ["复购客户", repur["sql"]["repeat"], repur["py"]["repeat"]],
                ["履约样本数", fulfil["sql"]["n"] if fulfil["sql"] else "-", fulfil["py"]["n"] if fulfil["py"] else "-"],
                ["履约 P50/P90", f'{fulfil["sql"]["p50"]}/{fulfil["sql"]["p90"]}' if fulfil["sql"] else "-",
                 f'{fulfil["py"]["p50"]}/{fulfil["py"]["p90"]}' if fulfil["py"] else "-"]],
               "两路对拍结果（同一次计算，两个实现）"),
        _table(["前件", "后件", "置信度", "提升度", "支持度"],
               [[r["前件"], r["后件"], r["置信度"], r["提升度"], r["支持度"]] for r in rules["top"]],
               f'共购规则（篮 {rules["篮子数"]} 个，频繁项集 {rules["频繁项集数"]}，'
               f'与暴力穷举一致：{rules["match_brute_force"]}）；提升度≤1 的行不代表正相关'),
        _table(["簇", "人数", "人均下单数", "人均成交额", "平均跨度(天)", "平均品类数"],
               [[c["簇"], c["人数"], c["人均下单数"], fmt_money(c["人均成交额"]),
                 c["平均跨度(天)"], c["平均品类数"]] for c in segs["簇"]],
               f'客户分群（k={segs.get("k", "-")}；轮廓系数 {segs["轮廓系数"]}，'
               f'在抽样 {segs.get("抽样人数", "-")} 人（共 {segs.get("客户数", "-")} 人）上算）；'
               f'k 与 seed 都是人挑的参数，不是数据选出来的'),
        _table(["清洗步骤", "注入", "账本", "对上"],
               [[c["step"], c["injected"], c["ledger"], "是" if c["match"] else "否"]
                for c in quality["py"]],
               "数据质量账本（缺陷来自 B26 的清洗链）"),
        '<p class="muted">数据是固定种子合成的，共现结构为演示而植入；'
        '本页结论不外推到任何真实业务。</p>',
    ]
    return ("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
            f"<title>B28 商务智能看板</title><style>{STYLE}</style></head><body>"
            + "".join(body) + "</body></html>")


def dashboard(filters: dict | None = None, bundle: tuple | None = None) -> str:
    conn, data = bundle or W.build()
    filters = filters or {}
    results = M.compute(conn, data, filters)
    panels = I.panels(data, filters)
    return render(results, panels, filters, {"seed": data["seed"]})


def export_html(outdir: Path | None = None) -> dict:
    """静态导出：看板 + 血缘页。默认写临时目录，仓库里不留生成物。"""
    outdir = Path(outdir) if outdir else Path(tempfile.mkdtemp(prefix="b28-dash-"))
    outdir.mkdir(parents=True, exist_ok=True)
    conn, data = W.build()
    paths = {"dashboard": outdir / "dashboard.html", "lineage": outdir / "lineage.html"}
    paths["dashboard"].write_text(dashboard(bundle=(conn, data)), encoding="utf-8")
    paths["lineage"].write_text(L.render(), encoding="utf-8")
    return {"dir": str(outdir), **{k: str(v) for k, v in paths.items()}}
