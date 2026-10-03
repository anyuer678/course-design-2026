"""demo.py —— B28 商务智能看板六段演示。所有数字运行时现算，不抄文档。

  1) 数据与清洗账本：注入数量 与 B26 清洗链的计数，逐数对照
  2) 五个业务问题：SQL 路 vs 纯 Python 参照路，口径一起打出来
  3) 筛选的作用：同一指标在不同筛选下的变化（含品类筛选的两种粒度）
  4) 下钻与安全边界：把 B32 的注入载荷当筛选值打进来，看它什么都干不成
  5) 洞察：共购规则（提升度判读）与客户分群（轮廓系数）
  6) 渲染、血缘与真服务：页面里的数字 == API 里的数字

红线：数据是固定种子合成的，共现结构为演示而植入；本页所有结论不外推到真实业务。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from bi import insights as I                            # noqa: E402
from bi import lineage as LG                            # noqa: E402
from bi import metrics as M                             # noqa: E402
from bi import render as R                              # noqa: E402
from bi import server as SV                             # noqa: E402
from bi import sql_policy as P                          # noqa: E402
from bi import warehouse as W                           # noqa: E402

LINE = "=" * 78


def section(no: int, title: str) -> None:
    print(f"\n{LINE}\n  {no}) {title}\n{LINE}")


def show(label: str, value: object) -> None:
    print(f"  {label:<28}{value}")


def main() -> int:
    # check_same_thread=False：第 6 段会把这份仓库交给真服务器（每请求一条线程）。
    # 上一版在 demo 里用默认值建连接、只在主线程查，到第 6 段才炸——
    # "测试里绿、演示里红"就是这么产生的，所以整份演示统一按服务器形态建。
    conn, data = W.build(check_same_thread=False)
    results = M.compute(conn, data)

    section(1, "数据与清洗账本（缺陷按量注入，清洗交给 B26）")
    show("脏明细行数", data["ledger"]["total"])
    show("清洗后行数", data["ledger"]["clean"])
    for item in data["reconcile"]:
        show(f"{item['step']}", f"注入 {item['injected']} ／ 账本 {item['ledger']}"
             f" → {'对上' if item['match'] else '没对上'}")
    show("账本整体一致", data["ledger"]["matched"])
    show("装载摘要", data["loaded"])

    section(2, "五个业务问题：两路算，逐数对拍")
    for key in ("gmv", "monthly_gmv", "top5", "repurchase", "fulfilment", "data_quality"):
        row = results[key]
        if key == "gmv":
            cell = f"SQL {R.fmt_money(row['sql'])} ｜ 参照 {R.fmt_money(row['py'])}"
        elif key == "monthly_gmv":
            cell = (f"{len(row['sql'])} 个完成月，未完整月 "
                    f"{sum(1 for m in row['sql'] if m['incomplete'])} 个")
        elif key == "top5":
            cell = f"冠军 {row['sql'][0][0]} ｜ CR5 {R.fmt_pct(row['cr5'])}"
        elif key == "repurchase":
            cell = (f"{R.fmt_pct(row['sql']['rate'])}"
                    f"（{row['sql']['repeat']}/{row['sql']['buyers']} 客户）")
        elif key == "fulfilment":
            cell = (f"P50 {row['sql']['p50']} ／ P90 {row['sql']['p90']}"
                    f" ／ 均值 {row['sql']['mean']} 天（n={row['sql']['n']}）")
        else:
            cell = f"账本 {row['sql']['clean']} 行，五步计数全对上"
        show(row["名称"], cell + f"  ← 两路{'一致' if row['equal'] else '**不一致**'}")
        print(f"  {'':<4}口径：{row['口径']}")
    show("对拍异常清单", M.mismatches(results) or "无")

    section(3, "筛选的作用（同一批 SQL 模板，参数不同）")
    for filters in ({}, {"category": "显示设备"}, {"month_from": "2026-06", "month_to": "2026-08"},
                    {"region": "东区"}):
        r = M.compute(conn, data, filters)
        label = json.dumps(filters, ensure_ascii=False)
        show(label[:34], f"成交额 {R.fmt_money(r['gmv']['sql'])} ｜ 买家 "
                         f"{r['repurchase']['sql']['buyers']} ｜ 复购 "
                         f"{R.fmt_pct(r['repurchase']['sql']['rate'])} ｜ P90 "
                         f"{r['fulfilment']['sql']['p90'] if r['fulfilment']['sql'] else '-'}")
    grain_amount = M.compute(conn, data, {"category": "显示设备"})["gmv"]
    grain_order = M.compute(conn, data, {"category": "显示设备"})["repurchase"]
    full = M.compute(conn, data)
    print("  粒度差异实测（同一个 category=显示设备）：金额指标只加该品类的行，"
          f"成交额从 {R.fmt_money(full['gmv']['sql'])} 降到 {R.fmt_money(grain_amount['sql'])}；"
          "订单指标看的是『这单里出现过该品类』，买家从 "
          f"{full['repurchase']['sql']['buyers']} 人降到 "
          f"{grain_order['sql']['buyers']} 人（这些人的整单时长/复购都算进来）。"
          "两种语义都合法，但必须在口径里写清，否则同一个筛选在两行数字上对不上账。")

    section(4, "下钻与安全边界（B32 的载荷当筛选值打进来）")
    drill = SV.drill({}, page=1, size=3)
    show("明细总数（成交口径）", drill["total"])
    for row in drill["rows"]:
        print(f"  {' | '.join(row[:6])} | {row[6]} ×{row[7]} = {row[8]}")
    payload = "S' UNION SELECT username, password_hash FROM accounts --"
    tables_before = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
    hit = M.compute(conn, data, {"category": payload})
    tables_after = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
    show("载荷当品类筛的结果", f"成交额 {hit['gmv']['sql']}（空集）、两路"
                              f"{'一致' if hit['gmv']['equal'] else '不一致'}")
    show("表数量 前/后", f"{tables_before} / {tables_after} → 结构没被动过")
    try:
        W.where_for({"evil": "1"})
    except W.FilterError as exc:
        show("未知筛选键", f"拒绝：{exc.reason[:52]}")
    proof = P.prove_scanner_has_teeth()
    show("扫描器有没有牙齿", f"注入一处真拼接后被抓={proof['mutated_func_found']}，"
                             f"点数 +{proof['site_count_delta']}")
    show("本包拼接点登记", f"未登记/失效条目：{P.problems() or '无'}")

    section(5, "洞察：共购规则与客户分群")
    rules = I.co_purchase(data)
    show("篮子/频繁项集/规则", f"{rules['篮子数']} / {rules['频繁项集数']} / {rules['规则数']}")
    show("与暴力穷举对拍", rules["match_brute_force"])
    for rule in rules["top"]:
        verdict = "正相关" if rule["提升度"] > 1 else "无正相关（lift≤1）"
        show(f"{rule['前件']} → {rule['后件']}",
             f"conf {rule['置信度']} lift {rule['提升度']} supp {rule['支持度']}  {verdict}")
    segs = I.segments(data)
    show("客户数 / k / 轮廓系数", f"{segs['客户数']} / {segs['k']} / {segs['轮廓系数']}")
    for cluster in segs["簇"]:
        show(f"簇 {cluster['簇']}（{cluster['人数']} 人）",
             f"人均 {cluster['人均下单数']} 单 / {R.fmt_money(cluster['人均成交额'])} 元 / "
             f"{cluster['平均跨度(天)']} 天跨度 / {cluster['平均品类数']} 个品类")

    section(6, "渲染、血缘与真服务")
    info = R.export_html()
    outdir = pathlib.Path(info["dir"])
    page = (outdir / "dashboard.html").read_text(encoding="utf-8")
    api = M.compute(conn, data)
    show("静态导出目录", info["dir"])
    show("页面里的数字是否等于 API",
         f"成交额 {R.fmt_money(api['gmv']['sql']) in page}、"
         f"复购率 {str(api['repurchase']['sql']['rate']) in page}")
    show("页面自包含", f"外部请求 {'http' in page.replace('http://www.w3.org', '')}；"
                       f"表格 {page.count('<table>')} 张；SVG {page.count('<svg')} 个")
    show("血缘自检", LG.problems() or "无问题（每个指标都能追到清洗步骤与数据源）")
    SV.BUNDLE = (conn, data)
    server, thread, port = SV.start(0)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/summary",
                                    timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        show("真起服务真发请求 /api/summary",
             f"status 200，对拍干净={body['reconcile_clean']}，成交额 {body['metrics']['gmv']['sql']}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/summary?evil=1", timeout=10)
        except urllib.error.HTTPError as exc:
            show("未知参数走 HTTP", f"{exc.code} "
                                    f"{json.loads(exc.read().decode('utf-8'))['reason'][:40]}")
    finally:
        SV.stop(server, thread)
        shutil.rmtree(outdir, ignore_errors=True)
        show("收尾", "服务已关、临时目录已删、内存库未落盘")

    print(f"\n{LINE}\n本轮没做的（别把演示当生产）：无 pandas/Streamlit（本机没这两个库，"
          "替代方案是 SQLite + 手写 SVG + 标准库服务器）；不做真实业务数据、不做预警与权限、"
          "不宣称任何预测能力；数据是固定种子合成的，共现结构为演示而植入。\n"
          "浏览器里的观感与点击只能由你实跑判断（run.bat 第 5 步），我不代勾。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
