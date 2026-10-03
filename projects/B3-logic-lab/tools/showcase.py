"""tools/showcase.py —— B3 展示页生成器（命题逻辑 + 二元关系）。口径：showcase/SPEC.md。

数据全部现算：

- **公式工作台**：12 条课本例题逐条过真值表，给出解析形态、逐行真值表、分类
  （重言/矛盾/可满足）、主析取/主合取范式与成真行号；
- **等价对拍**：德摩根、蕴含改写、分配律四对，逐格真值表判定等价；
- **关系样板间**：4 个关系（等价/偏序/带闭包的链条），5 种性质判定、
  传递闭包 **Warshall 与逐点 BFS 互证**、等价类划分自检。

页面写 `web/showcase.html`（单文件、双击即看、零网络依赖、JS 只做切换）；
`--check` 重算比对（不写盘），过期即红。**别手改页面**——它是生成物。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from logic3 import formula as F                            # noqa: E402
from logic3 import relation as R                           # noqa: E402
from logic3 import truth as T                              # noqa: E402

OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"

FORMULAS = [
    ("p & ~p", "矛盾式样板"),
    ("p | ~p", "排中律"),
    ("(p -> q) & p -> q", "肯定前件（重言）"),
    ("(p -> q) & (q -> r) -> (p -> r)", "假言三段论（重言）"),
    ("~(p & q)", "德摩根（左）"),
    ("~p | ~q", "德摩根（右）"),
    ("p -> q", "蕴含"),
    ("~p | q", "蕴含的等价写法"),
    ("(p | q) & ~(p & q)", "异或的手写形态"),
    ("p & (q | r)", "分配律（左）"),
    ("(p & q) | (p & r)", "分配律（右）"),
    ("(p -> q) | (q -> p)", "重言（课本习题）"),
]

EQUIVALENT_PAIRS = [
    ("~(p & q)", "~p | ~q", "德摩根律"),
    ("~(p | q)", "~p & ~q", "德摩根律（对偶）"),
    ("p -> q", "~p | q", "蕴含改写"),
    ("p & (q | r)", "(p & q) | (p & r)", "分配律"),
]

RELATION_SAMPLES = [
    ("恒等关系", 3, [(0, 0), (1, 1), (2, 2)], "最小的等价关系：每个类只有自己"),
    ("模 3 同余（6 元）", 6,
     [(i, j) for i in range(6) for j in range(6) if i % 3 == j % 3],
     "三个等价类 {0,3}、{1,4}、{2,5}——商集是一个合法划分"),
    ("整除（4 元，i 整除 j）", 4,
     [(i - 1, j - 1) for i in range(1, 5) for j in range(1, 5) if j % i == 0],
     "偏序：自反、反对称、传递"),
    ("链条 0→1→2", 3, [(0, 1), (1, 2)],
     "不传递（缺 0→2）；传递闭包会补出来，Warshall 与逐点 BFS 互证"),
]


def _classify(node) -> str:
    if T.is_tautology(node):
        return "重言式"
    if T.is_contradiction(node):
        return "矛盾式"
    return "可满足（非重言）"


def _matrix_lines(rel: R.Relation) -> str:
    head = "    " + "  ".join(str(j) for j in range(rel.n))
    rows = [head]
    for i in range(rel.n):
        rows.append(f"{i}:  " + "  ".join("1" if v else "0" for v in rel.m[i]))
    return "\n".join(rows)


def _pairs_text(rel: R.Relation) -> str:
    return "、".join(f"({i},{j})" for i, j in rel.pairs()) or "（空关系）"


def collect() -> dict:
    formulas = []
    for text, note in FORMULAS:
        node = F.parse(text)
        table = T.format_table(node)
        formulas.append({
            "text": text, "note": note, "render": F.render(node),
            "vars": len(F.variables(node)),
            "class": _classify(node),
            "rows": len(table) - 1,
            "table": "\n".join(table),
            "dnf": T.to_dnf(node), "cnf": T.to_cnf(node),
            "minterms": T.minterms(node), "maxterms": T.maxterms(node),
        })
    pairs = []
    for left, right, why in EQUIVALENT_PAIRS:
        ok = T.equivalent(F.parse(left), F.parse(right))
        pairs.append({"left": left, "right": right, "why": why, "ok": ok})
    relations = []
    for name, n, items, note in RELATION_SAMPLES:
        rel = R.Relation.from_pairs(n, items)
        warshall = rel.transitive_closure_warshall()
        bfs = rel.transitive_closure_bfs()
        entry = {
            "name": name, "note": note, "n": n, "pairs": _pairs_text(rel),
            "matrix": _matrix_lines(rel),
            "props": {
                "自反": rel.is_reflexive(), "反自反": rel.is_irreflexive(),
                "对称": rel.is_symmetric(), "反对称": rel.is_antisymmetric(),
                "传递": rel.is_transitive(),
            },
            "warshall": _pairs_text(warshall), "bfs": _pairs_text(bfs),
            "closures_same": warshall.pairs() == bfs.pairs(),
            "symmetric_closure": _pairs_text(rel.symmetric_closure()),
        }
        if rel.is_equivalence():
            classes = rel.equivalence_classes()
            entry["verdict"] = "等价关系"
            entry["classes"] = "、".join("{" + ",".join(map(str, c)) + "}" for c in classes)
            entry["partition_ok"] = not rel.check_partition()
        elif rel.is_partial_order():
            entry["verdict"] = "偏序关系"
        else:
            entry["verdict"] = "其他（看性质表）"
        relations.append(entry)
    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    facts = [
        ["公式目录", f"{len(formulas)} 条（真值表/主范式逐条现算）"],
        ["等价对拍", f"{len(pairs)} 对逐格判定（{'全部成立' if all(p['ok'] for p in pairs) else '有分叉！'}）"],
        ["关系样板", f"{len(relations)} 个（性质 + 闭包互证 + 等价类划分自检）"],
        ["测试方法", f"{method_count} 个（tests/ def test_ 现数；run.bat 一趟是权威）"],
    ]
    return {"facts": facts, "formulas": formulas, "pairs": pairs, "relations": relations}


# ------------------------------------------------------------------ 渲染

STYLE = """
:root{--ink:#16181d;--muted:#5f6773;--line:#d5d9e0;--card:#fff;--bg:#f7f8fa;--accent:#1d4ed8;--ok:#14603a;--bad:#a41f1f}
*{box-sizing:border-box}
body{margin:0;padding:1.4rem 1.1rem 3rem;background:var(--bg);color:var(--ink);font:16px/1.7 system-ui,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:71rem;margin:0 auto}
h1{font-size:1.5rem;margin:.2rem 0}h2{font-size:1.05rem;margin:1.6rem 0 .5rem}
p.note,span.note{color:var(--muted);font-size:.87rem}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(14rem,1fr));gap:.7rem;margin:.6rem 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.7rem .9rem}
.card b{display:block;font-size:.8rem;color:var(--muted);font-weight:600;margin-bottom:.15rem}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:.8rem 0}
.chips{display:flex;gap:.4rem;flex-wrap:wrap;margin:.4rem 0 .8rem}
.chip{font:inherit;font-size:.87rem;padding:.28rem .7rem;border:1px solid var(--line);border-radius:999px;background:#fff;cursor:pointer}
.chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
pre.code{margin:.6rem 0 0;padding:.8rem .9rem;background:#0f1115;color:#e6e9ef;border-radius:8px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace}
pre.code.wrap{white-space:pre-wrap;word-break:break-word}
.badge{display:inline-block;font-size:.8rem;padding:.08rem .55rem;border-radius:999px;border:1px solid var(--line);color:var(--muted);margin-right:.3rem}
.badge.ok{color:var(--ok);border-color:var(--ok)}.badge.bad{color:var(--bad);border-color:var(--bad)}
table.plain{border-collapse:collapse;font-size:.88rem;margin:.5rem 0}
table.plain th,table.plain td{border:1px solid var(--line);padding:.25rem .6rem;text-align:left}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}

/* ---------- KB 主题（token 学自 kb-ui 设计系统，2026-10-03）：统一观感 ---------- */
:root{
  --kb-primary:#3b82f6;--kb-primary-deep:#2563eb;
  --kb-primary-gradient:linear-gradient(135deg,#3b82f6,#6366f1);
  --kb-success:#16a34a;--kb-danger:#dc2626;--kb-warning:#d97706;
  --kb-bg:#ffffff;--kb-bg-elevated:#f8fafc;--kb-border:#e2e8f0;
  --kb-text-1:#0f172a;--kb-text-2:#475569;--kb-text-3:#94a3b8;
  --kb-radius-sm:4px;--kb-radius-md:6px;--kb-radius-lg:10px;
  --kb-shadow-1:0 1px 2px rgb(15 23 42 / 6%);
  --kb-shadow-2:0 4px 12px rgb(15 23 42 / 10%);
  --kb-font:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  --kb-mono:ui-monospace,Consolas,"Cascadia Mono",monospace;
  --kb-t:.2s ease;
}
body{background:#f8fafc;background-image:linear-gradient(180deg,#eff6ff 0,#f8fafc 340px,#f8fafc);
  color:var(--kb-text-1);font-family:var(--kb-font);-webkit-font-smoothing:antialiased}
body::before{content:"";display:block;height:4px;
  background:linear-gradient(90deg,var(--kb-primary),#6366f1 55%,#8b5cf6)}
a{color:var(--kb-primary-deep);text-decoration:none}
a:hover{color:#1d4ed8;text-decoration:underline}
h1,h2,h3{color:var(--kb-text-1);font-weight:650;letter-spacing:-.01em}
::selection{background:#dbeafe}
.sw-top{background:var(--kb-bg);border:1px solid var(--kb-border);
  border-radius:var(--kb-radius-lg);box-shadow:var(--kb-shadow-1)}
.sw-link{font-size:13px}
.sw-panel,.panel{background:var(--kb-bg);border:1px solid var(--kb-border);
  border-radius:var(--kb-radius-lg);box-shadow:var(--kb-shadow-1)}
.sw-card,.card{background:var(--kb-bg);border:1px solid var(--kb-border);
  border-radius:var(--kb-radius-lg);box-shadow:var(--kb-shadow-1);
  transition:box-shadow var(--kb-t),transform var(--kb-t),border-color var(--kb-t)}
.sw-card:hover,.card:hover{box-shadow:var(--kb-shadow-2);border-color:#bfdbfe;transform:translateY(-1px)}
.card b,.sw-card b{color:var(--kb-text-3);font-size:12px;letter-spacing:.02em}
.note,.muted{color:var(--kb-text-2)}
.badge{display:inline-block;font-size:.78rem;padding:.1rem .55rem;border-radius:999px;
  border:1px solid var(--kb-border);background:var(--kb-bg-elevated);color:var(--kb-text-2)}
.badge.ok{color:#047857;border-color:#a7f3d0;background:#ecfdf5}
.badge.bad{color:#b91c1c;border-color:#fecaca;background:#fef2f2}
.badge.todo,.badge.warn{color:#b45309;border-color:#fde68a;background:#fffbeb}
.chip,.pj-tab{font:inherit;font-size:.85rem;padding:.3rem .85rem;border:1px solid var(--kb-border);
  border-radius:999px;background:#fff;color:var(--kb-text-2);cursor:pointer;transition:all var(--kb-t)}
.chip:hover,.pj-tab:hover{border-color:var(--kb-primary);color:var(--kb-primary)}
.chip.active,.pj-tab.active{background:var(--kb-primary);border-color:var(--kb-primary);
  color:#fff;box-shadow:var(--kb-shadow-1)}
.chip.active:hover,.pj-tab.active:hover{color:#fff}
table{border-collapse:collapse}
table th,table td{border:1px solid var(--kb-border);padding:.42rem .65rem;text-align:left}
table th{background:var(--kb-bg-elevated);color:var(--kb-text-2);font-weight:600}
table tr:hover td{background:#f8fafc}
pre{background:#0f172a;color:#e2e8f0;border:1px solid #1e293b;
  border-radius:var(--kb-radius-lg);font-family:var(--kb-mono)}
pre code{background:none;border:none;padding:0;color:inherit}
kbd{font-family:var(--kb-mono);font-size:.85em;border:1px solid var(--kb-border);
  border-bottom-width:2px;border-radius:var(--kb-radius-sm);padding:1px 6px;
  background:var(--kb-bg-elevated);color:#334155}
code{font-family:var(--kb-mono);font-size:.9em;background:#f1f5f9;border:1px solid #e2e8f0;
  border-radius:var(--kb-radius-md);padding:1px 5px}
footer,.sw-footer{color:var(--kb-text-3);border-top:1px solid var(--kb-border)}
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


def _formula_pane(f: dict, index: int) -> str:
    hidden = "" if index == 0 else " hidden"
    bits = []
    bits.append(f'<p><b>{f["text"]}</b> —— {f["note"]} | 解析形态：<code>{f["render"]}</code> | '
                f'分类：<span class="badge {"ok" if f["class"] == "重言式" else ""}">{f["class"]}</span>'
                f'变量 {f["vars"]} 个、真值表 {f["rows"]} 行</p>')
    bits.append(f'<details><summary>真值表（{f["rows"]} 行，最后一列是行号）</summary>'
                f'<pre class="code">{f["table"]}</pre></details>')
    bits.append(f'<details><summary>主范式</summary><pre class="code wrap">主析取（成真行 '
                f'{f["minterms"]}）：{f["dnf"]}\n主合取（成假行 {f["maxterms"]}）：{f["cnf"]}</pre></details>')
    return f'<div data-pane-id="f-{index}"{hidden}>' + "".join(bits) + "</div>"


def render(payload: dict) -> str:
    cards = "".join(f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in payload["facts"])
    chips = "".join(
        f'<button class="chip" data-tab="f-{i}">{f["text"]}</button>'
        for i, f in enumerate(payload["formulas"]))
    panes = "".join(_formula_pane(f, i) for i, f in enumerate(payload["formulas"]))
    pair_rows = "".join(
        f'<tr><td><code>{p["left"]}</code></td><td><code>{p["right"]}</code></td><td>{p["why"]}</td>'
        f'<td><span class="badge {"ok" if p["ok"] else "bad"}">{"逐格相等" if p["ok"] else "有分叉"}</span></td></tr>'
        for p in payload["pairs"])
    rel_chips = "".join(
        f'<button class="chip" data-tab="r-{i}">{rel["name"]}</button>'
        for i, rel in enumerate(payload["relations"]))
    rel_panes = []
    for i, rel in enumerate(payload["relations"]):
        props = "".join(f'<span class="badge {"ok" if v else ""}">{k}：{"是" if v else "否"}</span>'
                        for k, v in rel["props"].items())
        extra = ""
        if "classes" in rel:
            extra = (f'<p>等价类：{rel["classes"]}——划分自检：'
                     f'<span class="badge {"ok" if rel["partition_ok"] else "bad"}">'
                     f'{"合法划分" if rel["partition_ok"] else "不是划分！"}</span></p>')
        rel_panes.append(
            f'<div data-pane-id="r-{i}"{" hidden" if i else ""}>'
            f'<p><b>{rel["name"]}</b>：{rel["note"]}——判定：<span class="badge ok">{rel["verdict"]}</span></p>'
            f'<p>{props}</p>'
            f'<pre class="code">关系矩阵：\n{rel["matrix"]}\n点对集：{rel["pairs"]}</pre>'
            f'<p>传递闭包（Warshall）：{rel["warshall"]} | （逐点 BFS）：{rel["bfs"]} '
            f'<span class="badge {"ok" if rel["closures_same"] else "bad"}">'
            f'{"两法一致" if rel["closures_same"] else "两法分叉！"}</span></p>'
            f'<p>对称闭包补出的点对：{rel["symmetric_closure"]}</p>{extra}</div>')
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B3-logic-lab · 命题逻辑与关系（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B3-logic-lab">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B12-algo-arena/web/showcase.html">B12</a>　·　下一件 <a href="../../../projects/B4-algebra-rsa/web/showcase.html">B4</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B3-logic-lab · 命题逻辑 + 二元关系</h1>
<p class="note">离散结构 · 递归下降解析 → 真值表与主范式；关系矩阵 → 性质判定 → 两种闭包互证。
下面每个公式、每对等价、每个关系都是现算的，切换着看。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <h3>公式工作台</h3>
  <p class="note">点一个公式：解析形态、逐行真值表、分类、主析取/主合取范式与成真/成假行号。</p>
  <div class="chips" data-tabs="formulas">{chips}</div>
  <div data-pane="formulas">{panes}</div>

  <h3>等价对拍</h3>
  <p class="note">每对公式逐格真值表判定——等价不是"看起来像"，是每一行都相等。</p>
  <table class="plain"><tr><th>左</th><th>右</th><th>为什么拿它们对拍</th><th>判定</th></tr>{pair_rows}</table>

  <h3>关系样板间</h3>
  <p class="note">点一个关系：矩阵、5 种性质、判定（等价/偏序/其他）、闭包两法互证、等价类与划分自检。</p>
  <div class="chips" data-tabs="relations">{rel_chips}</div>
  <div data-pane="relations">{"".join(rel_panes)}</div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：自测 + 五段演示（解析 / 主范式 / 等价 / 闭包 / 对拍）。</li>
    <li><kbd>python -m unittest discover -s tests</kbd>：完整测试（手算真值表、范式逐字符、固定种子对拍）。</li>
    <li><kbd>python tools/showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令从 logic3/ 现算；别手改本页。观感与顺手程度归你实跑验收。</p>
</section>

<h2 id="lab-title">实时实验台</h2>
<section id="lab" class="panel">
<div id="lab-slot">
<p class="note"><b>实验台未启动</b>：本页仍是静态生成物，双击即看；启动实验台后，这块会就地变成控制台——真启停后端服务、发原始请求（字节进字节出）、看实时日志、跑演示/测试。</p>
<ul>
<li>双击仓库根 <kbd>lab.bat</kbd>（或终端 <kbd>python showcase\\lab.py</kbd>），然后刷新本页；</li>
<li>只起服务不弹浏览器：<kbd>lab.bat no-open</kbd>；自检：<kbd>lab.bat selftest</kbd>。</li>
</ul>
</div>
</section>
<footer>
  <p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。</p>
</footer>
</main>
<script>{TOGGLE_JS}</script>
<script>
/* 实时实验台引导（双击 lab.bat 启动实验台后，页内该分节自动变成控制台） */
"use strict";
var s=document.createElement("script");
s.src=(location.protocol==="http:")?("/showcase/lab.js"):"http:\\/\\/127.0.0.1:7788/showcase/lab.js";
document.body.appendChild(s);
</script>
</body>
</html>
"""


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B3 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（{len(payload['formulas'])} 条公式 + {len(payload['relations'])} 个关系，全部现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print(f"展示页新鲜：与现算逐字一致（{len(payload['formulas'])} 条公式、"
              f"{len(payload['pairs'])} 对等价、{len(payload['relations'])} 个关系）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
