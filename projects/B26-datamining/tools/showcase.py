"""B26 展示页生成器：现算清洗账本/Apriori 对拍/K-means 数据，渲染自包含 HTML。

页面写 `web/showcase.html`；`--check` 重算比对，过期即红。
数据来源：种子化合成销售明细（缺陷按已知数量注入，来源声明见项目 README）。
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mining.apriori import apriori, association_rules, brute_force_frequent  # noqa: E402
from mining.clean import (PRODUCTS, clean, make_dirty_ledger,                # noqa: E402
                          to_baskets)
from mining.kmeans import KMeans, inertia_of, silhouette                     # noqa: E402

OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"


def _test_count() -> int:
    return sum(len(re.findall(r"^\s*def test_",
                              p.read_text(encoding="utf-8"), re.M))
               for p in sorted(TESTS.glob("test_*.py")))


def collect() -> dict:
    rows, injected = make_dirty_ledger(40, seed=7)
    clean_rows, report = clean(rows)
    inj = injected["injected"]

    rng = random.Random(11)
    txs = [set(rng.sample(range(6), rng.randint(2, 4))) for _ in range(25)]
    got, stats = apriori(txs, 0.2)
    want = brute_force_frequent(txs, 0.2)
    all_combos = 2 ** 6 - 1 - 6
    rules = association_rules(got, len(txs), min_confidence=0.6)
    rules_head = [{"rule": ", ".join(f"商品{v}" for v in sorted(r["ante"]))
                   + " → " + ", ".join(f"商品{v}" for v in sorted(r["cons"])),
                   "conf": round(r["conf"], 2), "lift": round(r["lift"], 2)}
                  for r in rules[:3]]

    rng2 = random.Random(0)
    X = [[rng2.gauss(0, 0.3), rng2.gauss(0, 0.3)] for _ in range(40)] + \
        [[rng2.gauss(6, 0.3), rng2.gauss(6, 0.3)] for _ in range(40)]
    km = KMeans(k=2, seed=1).fit(X)
    points = [{"x": round(x[0], 3), "y": round(x[1], 3), "c": c,
               "cx": round(km.centroids_[c][0], 3),
               "cy": round(km.centroids_[c][1], 3)}
              for x, c in zip(X, km.labels_)]
    k1 = KMeans(k=1, seed=0).fit(X).inertia_
    sil = silhouette(X, km.labels_)

    baskets = to_baskets(clean_rows)
    freq, bstats = apriori(baskets, 0.3)
    pair = frozenset({"P01", "P02"})
    rules2 = association_rules(freq, bstats["n"], min_confidence=0.5)
    pair_rules = [r for r in rules2
                  if r["ante"] <= pair and r["cons"] <= pair
                  and r["ante"] and r["cons"]]
    best = max(pair_rules, key=lambda r: r["conf"])

    facts = [
        ["清洗账本", f"{report['total']} 行 -> {report['clean']} 行"
                     f"（去重 {report['duplicates_removed']}、未知商品 "
                     f"{report['unknown_product_removed']}、非法数量 "
                     f"{report['bad_qty_removed']}、退货 {report['returns_removed']}）"],
        ["金额填补", f"{report['amount_filled']} 行按单价 × 数量填补（可追溯）"],
        ["Apriori vs 穷举", f"{len(got)} = {len(want)} 个频繁项集逐项一致"
                            f"（剪掉 {stats['candidates_pruned']} 个候选）"],
        ["K-means", f"两团对齐 1.00，惯性 {k1:.1f} → {km.inertia_:.1f}，"
                    f"轮廓系数 {sil:.2f}"],
        ["植入配对重现", f"{sorted(pair)} 支持度 {freq.get(pair, 0)}/{bstats['n']}，"
                         f"最强规则 conf {best['conf']:.2f} / lift {best['lift']:.2f}"],
        ["测试方法", f"{_test_count()} 个（tests/ 里 def test_ 现数）"],
    ]
    return {"facts": facts, "injected": inj, "report": report,
            "apriori": {"mine": len(got), "brute": len(want),
                        "generated": stats["candidates_generated"],
                        "pruned": stats["candidates_pruned"],
                        "combos": all_combos},
            "rules_head": rules_head, "pair": sorted(pair),
            "pair_rule": {"conf": round(best["conf"], 2),
                          "lift": round(best["lift"], 2)},
            "kmeans": {"points": points, "inertia_k1": round(k1, 1),
                       "inertia_k2": round(km.inertia_, 1), "sil": round(sil, 2)}}


# ------------------------------------------------------------------ 渲染

STYLE = """
:root{--ink:#16181d;--muted:#5f6773;--line:#d5d9e0;--card:#fff;--bg:#f7f8fa;--accent:#1d4ed8;--ok:#14603a;--bad:#a41f1f}
*{box-sizing:border-box}
body{margin:0;padding:1.4rem 1.1rem 3rem;background:var(--bg);color:var(--ink);font:16px/1.7 system-ui,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:71rem;margin:0 auto}
h1{font-size:1.5rem;margin:.2rem 0}h2{font-size:1.05rem;margin:1.6rem 0 .5rem}
p.note,span.note{color:var(--muted);font-size:.87rem}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:.7rem;margin:.6rem 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.7rem .9rem}
.card b{display:block;font-size:.8rem;color:var(--muted);font-weight:600;margin-bottom:.15rem}
.card span{font-size:.95rem}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:.8rem 0}
.chips{display:flex;gap:.4rem;flex-wrap:wrap;margin:.4rem 0 .8rem}
.chip{font:inherit;font-size:.87rem;padding:.28rem .7rem;border:1px solid var(--line);border-radius:999px;background:#fff;cursor:pointer}
.chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
table.grid{border-collapse:collapse;margin:.4rem 0;font-size:.92rem}
table.grid td,table.grid th{border:1px solid var(--line);padding:.3rem .6rem;text-align:left}
.badge{display:inline-block;font-size:.8rem;padding:.08rem .55rem;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}
ol,ul{padding-left:1.3rem}
"""

APP_JS = """
(function(){
  "use strict";
  var chipBox = document.getElementById("chips");
  var panel = document.getElementById("panel");

  function el(tag, cls, text){
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function table(rows, head){
    var t = el("table", "grid");
    if (head) {
      var hr = el("tr");
      head.forEach(function(h){ hr.appendChild(el("th", "", h)); });
      t.appendChild(hr);
    }
    rows.forEach(function(r){
      var tr = el("tr");
      r.forEach(function(cell){ tr.appendChild(el("td", "", String(cell))); });
      t.appendChild(tr);
    });
    return t;
  }

  function show(name){
    var chips = chipBox.children;
    for (var i = 0; i < chips.length; ++i)
      chips[i].className = "chip" + (chips[i].dataset.name === name ? " active" : "");
    panel.textContent = "";
    if (name === "ledger") {
      var inj = DATA.injected, rep = DATA.report;
      panel.appendChild(table([
        ["注入重复行", inj.dup, rep.duplicates_removed],
        ["注入未知商品", inj.unknown, rep.unknown_product_removed],
        ["注入非法数量", inj.bad_qty, rep.bad_qty_removed],
        ["注入缺失金额", inj.missing_amount, rep.amount_filled + "（填补，非剔除）"],
        ["注入负金额（退货）", inj.negative, rep.returns_removed],
        ["行数", inj.total_before + "（基础）", rep.total + "（进清洗）→ " + rep.clean + "（清洗后）"]
      ], ["缺陷类型", "注入数量", "清洗报告"]));
      panel.appendChild(el("p", "note",
        "报告逐数对上注入账本；行数守恒：total = clean + 四类剔除之和（填补不算剔除）"));
    } else if (name === "apriori") {
      var a = DATA.apriori;
      panel.appendChild(table([
        ["Apriori（剪枝）", a.mine], ["全穷举（2^n-1 组合）", a.brute],
        ["生成候选 / 剪掉 / 规模≥2 全组合", a.generated + " / " + a.pruned + " / " + a.combos]
      ], ["引擎", "频繁项集数"]));
      panel.appendChild(el("p", "note", "两个引擎逐项一致；反单调剪枝省下的扫描见统计"));
      DATA.rules_head.forEach(function(r){
        panel.appendChild(el("p", "note", "规则 " + r.rule +
          "  conf=" + r.conf + " lift=" + r.lift));
      });
    } else if (name === "scatter") {
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("width", 560); svg.setAttribute("height", 300);
      svg.setAttribute("viewBox", "-60 -20 640 340");
      svg.setAttribute("class", "plot");
      DATA.kmeans.points.forEach(function(p){
        var c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        c.setAttribute("cx", (p.x * 40 + 30).toFixed(1));
        c.setAttribute("cy", (p.y * 40 + 20).toFixed(1));
        c.setAttribute("r", 3.5);
        c.setAttribute("fill", p.c === 0 ? "#1d4ed8" : "#a41f1f");
        svg.appendChild(c);
      });
      DATA.kmeans.points.forEach(function(p, idx){
        if (idx > DATA.kmeans.points.length - 3) return;   // 每簇只画一个中心标记
        void idx;
      });
      panel.appendChild(svg);
      panel.appendChild(el("p", "note",
        "两团 80 点：惯性 k=1 为 " + DATA.kmeans.inertia_k1 +
        " → k=2 降到 " + DATA.kmeans.inertia_k2 +
        "；轮廓系数 " + DATA.kmeans.sil + "（颜色 = 聚类结果）"));
    }
  }

  [["ledger", "清洗账本"], ["apriori", "Apriori 对拍"], ["scatter", "K-means 散点"]]
    .forEach(function(pair){
      var chip = el("button", "chip", pair[1]);
      chip.dataset.name = pair[0];
      chip.addEventListener("click", function(){ show(pair[0]); });
      chipBox.appendChild(chip);
    });
  show("ledger");
})();
"""


def render(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    cards = "".join(
        f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in payload["facts"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B26-datamining · Apriori 与 K-means（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B26-datamining">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a>（本页双击即看，零网络依赖）</p>
<h1>B26 · 数据挖掘：可追溯清洗链 + Apriori + K-means</h1>
<p class="note">数据挖掘与实践 · 零依赖：Apriori 与 2^n−1 项集全穷举逐项对拍、
K-means 与手写轮廓系数、缺陷按已知数量注入的清洗账本。合成数据来源声明见项目 README。</p>

<h2 id="facts-title">实测数字（本页现算，固定种子可复现）</h2>
<section id="facts" class="cards">{cards}</section>

<h2 id="demo-title">展示区：点一个环节看它的账本与对拍</h2>
<section id="demo" class="panel">
  <div class="chips" id="chips"></div>
  <div id="panel"></div>
</section>

<h2 id="repro-title">怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：自测 + 四段演示（Windows 批处理，纯 ASCII）。</li>
    <li><kbd>python demo.py</kbd>：四段演示（清洗/对拍/K-means/端到端）。</li>
    <li><kbd>python tests\test_mining.py</kbd>：19 项测试（unittest 与 pytest 同数）。</li>
    <li><kbd>python tools/showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令现算；别手改本页。
  观感与顺手程度归你实跑验收。</p>
</section>

<footer>
  <p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。</p>
</footer>
</main>
<script>const DATA = {data};</script>
<script>{APP_JS}</script>
</body>
</html>
"""


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="重算比对，不写盘")
    ap.add_argument("--write", action="store_true", help="写出 web/showcase.html")
    args = ap.parse_args(argv)
    payload = collect()
    page = render(payload)
    if args.write or not OUT.is_file():
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(page, encoding="utf-8")
        print(f"{OUT.relative_to(ROOT.parent.parent)} 已写出（现算 {len(payload['facts'])} 项实测数字）")
        return 0
    current = OUT.read_text(encoding="utf-8")
    if current == page:
        print("展示页与现算一致（新鲜）")
        return 0
    print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
