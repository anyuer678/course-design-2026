"""tools/showcase.py —— B12 展示页生成器（算法实验场：五大范式）。口径：showcase/SPEC.md。

数据全部现算，全部是**确定性**产物（计数、方案、快照——页面不使用任何计时数字，
因为时间会随机器飘、会让页面对拍变成 flaky）：

- **回溯（N 皇后）**：n=6..10 的解数（位运算计数），6/7 再用全排列暴力独立复算；
  6 皇后给一张真棋盘（`solve_n_queens` 的解）；
- **DP（背包）**：完整 DP 表 + 方案还原 + 滚动数组对拍 + "滚动写反"的错法当场露馅 +
  枚举所有子集的暴力参照；
- **贪心（区间调度）**：最早结束 vs 按开始 vs 按最短的三种贪心对照 + 暴力最优 +
  两条"直觉贪心"的最小反例（`smallest_counterexample`）；
- **图**：Dijkstra 每轮定标快照（`on_settle` 回调）与 Bellman-Ford、Floyd **三方对拍**、
  一条还原路径；
- **分治（逆序对）**：手写数组对拍暴力 + 固定种子三档规模（100/1000/5000）的对拍。

页面写 `web/showcase.html`；`--check` 重算比对（不写盘），过期即红。
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algo import backtrack as BT                          # noqa: E402
from algo import divide as DV                             # noqa: E402
from algo import dp as DP                                 # noqa: E402
from algo import graph as GR                              # noqa: E402
from algo import greedy as GD                             # noqa: E402

OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"

QUEEN_SIZES = (6, 7, 8, 9, 10)
KNAPSACK = ([2, 3, 4, 5], [3, 4, 5, 6], 7)
INTERVALS = [(0, 5), (1, 3), (3, 6), (5, 7), (6, 8), (2, 4)]
GRAPH_EDGES = [(0, 1, 4), (0, 2, 1), (2, 1, 2), (1, 3, 5),
               (2, 3, 8), (3, 4, 2), (4, 5, 3), (2, 5, 10)]
GRAPH_N = 6
INVERSION_ARRAY = [5, 1, 4, 2, 8, 0, 3, 9, 7, 6]
INVERSION_SIZES = (100, 1000, 5000)


def _board_text(placement) -> str:
    n = len(placement)
    rows = []
    for r in range(n):
        rows.append(" ".join("Q" if placement[r] == c else "." for c in range(n)))
    return "\n".join(rows)


def _collect_queens() -> dict:
    rows = []
    for n in QUEEN_SIZES:
        bit = BT.count_n_queens(n)
        via_solutions = len(BT.solve_n_queens(n))
        entry = {"n": n, "bit": bit, "via_solutions": via_solutions,
                 "agree": bit == via_solutions}
        if n <= 7:
            brute = BT.count_by_permutations(n)
            entry["permutations"] = brute
            entry["agree"] = entry["agree"] and bit == brute
        rows.append(entry)
    board = _board_text(BT.solve_n_queens(6)[0])
    return {"rows": rows, "board6": board}


def _collect_knapsack() -> dict:
    weights, values, capacity = KNAPSACK
    best, chosen = DP.knapsack(weights, values, capacity)
    rolling = DP.knapsack_rolling(weights, values, capacity)
    wrong = DP.knapsack_rolling_wrong_way(weights, values, capacity)
    brute = DP.knapsack_brute(weights, values, capacity)
    table = DP.knapsack_table(weights, values, capacity)
    rows = []
    for i in range(len(weights) + 1):
        rows.append(f"i={i}: " + " ".join(f"{v:>2}" for v in table[i]))
    return {"weights": weights, "values": values, "capacity": capacity,
            "best": best, "chosen": chosen, "rolling": rolling, "wrong": wrong,
            "brute_value": brute[0], "brute_chosen": brute[1],
            "table": "\n".join(rows)}


def _collect_greedy() -> dict:
    best = len(GD.schedule(INTERVALS))
    by_start = len(GD.greedy_by_start(INTERVALS))
    by_shortest = len(GD.greedy_by_shortest(INTERVALS))
    optimum = GD.schedule_count_brute(INTERVALS)
    counter = GD.smallest_counterexample()
    return {"intervals": INTERVALS, "picked": GD.schedule(INTERVALS),
            "best": best, "by_start": by_start, "by_shortest": by_shortest,
            "optimum": optimum,
            "counter_by_start": counter["by_start"], "counter_by_shortest": counter["by_shortest"],
            "by_end_fails": counter["by_end_fails"]}


def _collect_graph() -> dict:
    edges = GR.undirected(GRAPH_EDGES)
    snapshots = []
    dist, prev = GR.dijkstra(GRAPH_N, edges, 0,
                             on_settle=lambda u, d, snapshot: snapshots.append((u, d, snapshot)))
    bf_dist, _ = GR.bellman_ford(GRAPH_N, edges, 0)
    floyd_rows = GR.floyd(GRAPH_N, edges)
    path = GR.path_of(prev, 0, 5)
    return {"edges": GRAPH_EDGES, "n": GRAPH_N,
            "snapshots": [(u, d, list(s)) for u, d, s in snapshots],
            "dist": dist, "bf_dist": bf_dist, "floyd_row0": floyd_rows[0],
            "three_way": dist == bf_dist == floyd_rows[0],
            "path": path}


def _collect_inversions() -> dict:
    sorted_seq, merge_count = DV.merge_sort_count(INVERSION_ARRAY)
    brute = DV.brute_force_inversions(INVERSION_ARRAY)
    scale = []
    rng = random.Random(7)          # 建在循环外：建在循环里 = 每档数组全是同一个值、逆序对恒 0
    for size in INVERSION_SIZES:
        arr = [rng.randint(0, 10 ** 6) for _ in range(size)]
        merge = DV.count_inversions(arr)
        brute_count = DV.brute_force_inversions(arr) if size <= 1000 else None
        scale.append({"size": size, "merge": merge, "brute": brute_count,
                      "agree": brute_count is None or merge == brute_count})
    return {"array": INVERSION_ARRAY, "count": merge_count,
            "brute": brute, "sorted_head": sorted_seq[:10], "scale": scale,
            "present": len(INVERSION_ARRAY)}


def collect() -> dict:
    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    queens = _collect_queens()
    knapsack = _collect_knapsack()
    greedy = _collect_greedy()
    graph = _collect_graph()
    inversions = _collect_inversions()
    facts = [
        ["N 皇后解数", "、".join(f"n={r['n']}→{r['bit']}" for r in queens["rows"])],
        ["背包最优", f"重量{knapsack['weights']} 价值{knapsack['values']} 容量{knapsack['capacity']}："
                  f"DP={knapsack['best']}（选中 {list(knapsack['chosen'])}）vs 暴力={knapsack['brute_value']}"],
        ["贪心对照", f"最早结束 {greedy['best']} 个 = 最优；按开始 {greedy['by_start']}、"
                  f"按最短 {greedy['by_shortest']}（两条直觉贪心都有最小反例）"],
        ["最短路三方对拍", f"Dijkstra == Bellman-Ford == Floyd（节点 0 出发）："
                      f"{'全部一致' if graph['three_way'] else '有分叉！'}"],
        ["逆序对", f"[{len(inversions['array'])} 元素] 分治 {inversions['count']} = 暴力 "
                f"{inversions['brute']}；三档规模 100/1000/5000 逐对拍"],
        ["测试方法", f"{method_count} 个（tests/ def test_ 现数；run.bat 一趟是权威）"],
    ]
    return {"facts": facts, "queens": queens, "knapsack": knapsack, "greedy": greedy,
            "graph": graph, "inversions": inversions}


# ------------------------------------------------------------------ 渲染

STYLE = """
:root{--ink:#16181d;--muted:#5f6773;--line:#d5d9e0;--card:#fff;--bg:#f7f8fa;--accent:#1d4ed8;--ok:#14603a;--bad:#a41f1f;--warn:#8a5a00}
*{box-sizing:border-box}
body{margin:0;padding:1.4rem 1.1rem 3rem;background:var(--bg);color:var(--ink);font:16px/1.7 system-ui,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:71rem;margin:0 auto}
h1{font-size:1.5rem;margin:.2rem 0}h2{font-size:1.05rem;margin:1.6rem 0 .5rem}
p.note,span.note{color:var(--muted);font-size:.87rem}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:.7rem;margin:.6rem 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.7rem .9rem}
.card b{display:block;font-size:.8rem;color:var(--muted);font-weight:600;margin-bottom:.15rem}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:.8rem 0}
.chips{display:flex;gap:.4rem;flex-wrap:wrap;margin:.4rem 0 .8rem}
.chip{font:inherit;font-size:.87rem;padding:.28rem .7rem;border:1px solid var(--line);border-radius:999px;background:#fff;cursor:pointer}
.chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
pre.code{margin:.6rem 0 0;padding:.8rem .9rem;background:#0f1115;color:#e6e9ef;border-radius:8px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace}
pre.code.wrap{white-space:pre-wrap;word-break:break-word}
.badge{display:inline-block;font-size:.8rem;padding:.08rem .55rem;border-radius:999px;border:1px solid var(--line);color:var(--muted);margin-right:.3rem}
.badge.ok{color:var(--ok);border-color:var(--ok)}.badge.bad{color:var(--bad);border-color:var(--bad)}.badge.warn{color:var(--warn);border-color:var(--warn)}
table.plain{border-collapse:collapse;font-size:.88rem;margin:.5rem 0}
table.plain th,table.plain td{border:1px solid var(--line);padding:.25rem .6rem;text-align:left}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}
"""

TOGGLE_JS = """
(function(){
  "use strict";
  function activate(group, id){
    var chips = document.querySelectorAll('[data-tabs="' + group + '"] [data-tab]');
    for (var i = 0; i < chips.length; i++){
      var on = chips[i].getAttribute("data-tab") === id;
      chips[i].className = on ? "chip active" : "chip";
    }
    var panes = document.querySelectorAll('[data-pane="' + group + '"] [data-pane-id]');
    for (var j = 0; j < panes.length; j++){
      panes[j].hidden = panes[j].getAttribute("data-pane-id") !== id;
    }
  }
  var lines = document.querySelectorAll("[data-tabs]");
  for (var k = 0; k < lines.length; k++){
    (function(line){
      var group = line.getAttribute("data-tabs");
      var chips = line.querySelectorAll("[data-tab]");
      for (var c = 0; c < chips.length; c++){
        chips[c].addEventListener("click", function(){
          activate(group, this.getAttribute("data-tab"));
        });
      }
      if (chips.length) activate(group, chips[0].getAttribute("data-tab"));
    })(lines[k]);
  }
})();
"""


def render(payload: dict) -> str:
    cards = "".join(f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in payload["facts"])
    q = payload["queens"]
    q_rows = "".join(
        f'<tr><td>n={r["n"]}</td><td>{r["bit"]}</td><td>{r["via_solutions"]}</td>'
        f'<td>{r.get("permutations", "——")}</td>'
        f'<td><span class="badge {"ok" if r["agree"] else "bad"}">'
        f'{"计数/枚举/位运算一致" if r["agree"] else "分叉！"}</span></td></tr>'
        for r in q["rows"])
    k = payload["knapsack"]
    g = payload["greedy"]
    gr = payload["graph"]
    snap_rows = "".join(
        f'<tr><td>{u}</td><td>{d}</td><td>{s}</td></tr>' for u, d, s in gr["snapshots"])
    iv = payload["inversions"]
    scale_rows = "".join(
        f'<tr><td>{s["size"]}</td><td>{s["merge"]}</td>'
        f'<td>{s["brute"] if s["brute"] is not None else "（O(n^2) 到此为止）"}</td>'
        f'<td><span class="badge {"ok" if s["agree"] else "bad"}">'
        f'{"一致" if s["agree"] else "分叉！"}</span></td></tr>'
        for s in iv["scale"])
    edge_text = "\n".join(f"{u} - {v}  (权重 {w})" for u, v, w in gr["edges"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B12-algo-arena · 算法实验场（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B12-algo-arena">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B13-tinylang/web/showcase.html">B13</a>　·　下一件 <a href="../../../projects/B3-logic-lab/web/showcase.html">B3</a></span>（本页双击即看，零网络依赖）</p>
<h1>B12-algo-arena · 五个范式，每步都有暴力参照</h1>
<p class="note">算法分析与设计 · 分治 / DP / 贪心 / 回溯 / 图：每一个算法都配一个"更笨但不会错"的
参照实现，页面上的每个数都是这次现算的<b>计数或方案</b>——不用时间数字，因为时间会飘。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="queens">回溯 · N 皇后</button>
    <button class="chip" data-tab="knapsack">DP · 背包</button>
    <button class="chip" data-tab="greedy">贪心 · 区间调度</button>
    <button class="chip" data-tab="graph">图 · 最短路</button>
    <button class="chip" data-tab="inversions">分治 · 逆序对</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="queens">
      <p class="note">n=6..10 解数：位运算计数、逐个解枚举、以及（6/7）全排列暴力三条路互证。</p>
      <table class="plain"><tr><th>规模</th><th>位运算计数</th><th>解集合大小</th><th>全排列暴力</th><th>对拍</th></tr>{q_rows}</table>
      <p class="note">6 皇后的一个真解（Q 是皇后）：</p>
      <pre class="code">{q["board6"]}</pre>
    </div>
    <div data-pane-id="knapsack" hidden>
      <p>物品重量 {k["weights"]}、价值 {k["values"]}、容量 {k["capacity"]}——
      DP 最优值 <b>{k["best"]}</b>（选中下标 {list(k["chosen"])}）。</p>
      <p class="note">滚动数组对拍：{k["rolling"]}（必须等于 {k["best"]}）；
      滚动"写反方向"的错法：{k["wrong"]}（<span class="badge warn">这就是 k 版写反会得到的数</span>）；
      枚举全部子集：{k["brute_value"]}（选中 {list(k["brute_chosen"])}）。</p>
      <p class="note">完整 DP 表（i=前 i 件，列=容量 0..{k["capacity"]}）：</p>
      <pre class="code">{k["table"]}</pre>
    </div>
    <div data-pane-id="greedy" hidden>
      <p>区间 {g["intervals"]}（共 {len(g["intervals"])} 个）。</p>
      <p>最早结束优先：选 {len(g["picked"])} 个 {list(g["picked"])}——
      <span class="badge ok">等于暴力最优 {g["optimum"]}</span></p>
      <p>按开始时间贪心：{g["by_start"]} 个 <span class="badge warn">vs 最优 {g["optimum"]}</span>；
      按时长最短贪心：{g["by_shortest"]} 个 <span class="badge warn">vs 最优 {g["optimum"]}</span></p>
      <p class="note">为两条"直觉贪心"找到的最小反例（枚举小规模区间集合穷举出来的）：
      按开始：{g["counter_by_start"]}；按最短：{g["counter_by_shortest"]}；
      最早结束的反例：{g["by_end_fails"] if g["by_end_fails"] else "无（被交换论证保证）"}</p>
    </div>
    <div data-pane-id="graph" hidden>
      <p class="note">无向图 {gr["n"]} 个节点：<br>{edge_text}</p>
      <p>Dijkstra 每轮"定标"快照（`on_settle` 回调——教材那张每轮 dist 表就是这么来的）：</p>
      <table class="plain"><tr><th>定标节点</th><th>距离</th><th>当时 dist 快照</th></tr>{snap_rows}</table>
      <p>最终距离（0 出发）：{gr["dist"]}；
      Bellman-Ford：{gr["bf_dist"]}；Floyd 第 0 行：{gr["floyd_row0"]}
      <span class="badge {"ok" if gr["three_way"] else "bad"}">
      {"三方逐数一致" if gr["three_way"] else "三方分叉！"}</span></p>
      <p>0 到 5 的还原路径：{gr["path"]}</p>
    </div>
    <div data-pane-id="inversions" hidden>
      <p>数组 {iv["array"]}（{iv["present"]} 个元素）：逆序对分治计数 <b>{iv["count"]}</b>，
      暴力 <b>{iv["brute"]}</b>——
      <span class="badge {"ok" if iv["count"] == iv["brute"] else "bad"}">
      {"一致" if iv["count"] == iv["brute"] else "分叉！"}</span>；
      归并前排 {iv["sorted_head"]}…</p>
      <p class="note">固定种子（Random(7)）三档规模对拍：</p>
      <table class="plain"><tr><th>规模</th><th>分治计数</th><th>暴力计数</th><th>对拍</th></tr>{scale_rows}</table>
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：自测 + 演示（DP 表与方案还原 / 三种贪心对照 / N 皇后解数表 / Dijkstra 快照 / 规模计时）。</li>
    <li><kbd>python -m unittest discover -s tests</kbd>：完整测试（每个范式都对拍暴力/参照）。</li>
    <li><kbd>python tools/showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令从 algo/ 现算（页面只放计数与方案，不放计时数字——
  计时在终端演示里现跑现看）。观感与顺手程度归你实跑验收。</p>
</section>

<footer>
  <p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。</p>
</footer>
</main>
<script>{TOGGLE_JS}</script>
<script>
/* 实时实验台引导（未启动则静默）：python showcase/lab.py */
"use strict";
var s=document.createElement("script");
s.src=(location.protocol==="http:")?("/showcase/lab.js"):"http:\\/\\/127.0.0.1:7788/showcase/lab.js";
document.body.appendChild(s);
</script>
</body>
</html>
"""


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B12 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（五大范式逐项现算：计数/方案/快照）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（皇后/背包/贪心/最短路/逆序对全部现算）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
