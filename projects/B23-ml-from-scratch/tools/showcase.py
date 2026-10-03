"""B23 展示页生成器：从真实产物现算数据，渲染自包含 HTML 展示页。

页面写 `web/showcase.html`（单文件、双击即看、零网络依赖、JS 只做渲染
不做业务）；`--check` 重算比对（不写盘），过期即红。**别手改页面**——
它是生成物。数据全部来自本次运行的真实模型输出（固定种子，可复现）。
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml import data as mldata                                    # noqa: E402
from ml.knn import KNN                                           # noqa: E402
from ml.linear import LinearRegression, accuracy, r2_score       # noqa: E402
from ml.neuralnet import MLP                                     # noqa: E402
from ml.perceptron import Perceptron                             # noqa: E402
from ml.tree import DecisionTree                                 # noqa: E402

OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"


def _gradient_check_worst() -> float:
    """与 tests 里的梯度检查同一套做法：中心差分 vs 手写反传。"""
    rng = random.Random(11)
    X = [[rng.uniform(-1, 1), rng.uniform(-1, 1)] for _ in range(12)]
    y = ["L" if x[0] + x[1] > 0 else "R" for x in X]
    net = MLP([2, 3, 2], seed=1, lr=0.5, epochs=100)
    net.fit(X, y, classes=["L", "R"])
    Y1h = [[1.0 if c == lab else 0.0 for c in ["L", "R"]] for lab in y]
    gradW, gradB = net.backprop(X, Y1h)
    eps = 1e-6
    worst = 0.0
    for l in range(len(net.W)):
        for j in range(len(net.W[l])):
            for i in range(len(net.W[l][j])):
                orig = net.W[l][j][i]
                net.W[l][j][i] = orig + eps
                lp = net.loss(X, Y1h)
                net.W[l][j][i] = orig - eps
                lm = net.loss(X, Y1h)
                net.W[l][j][i] = orig
                num = (lp - lm) / (2 * eps)
                worst = max(worst, abs(num - gradW[l][j][i])
                            / max(1e-8, abs(num) + abs(gradW[l][j][i])))
    return worst


def collect() -> dict:
    X, y = mldata.load_iris()
    tr, te = mldata.train_test_split(len(X), 0.2, seed=42)
    Xtr, Xte = mldata.standardize([X[i] for i in tr], [X[i] for i in te])
    ytr, yte = [y[i] for i in tr], [y[i] for i in te]

    knn = KNN(k=3).fit(Xtr, ytr)
    acc_knn = accuracy(yte, knn.predict(Xte))
    tree = DecisionTree(criterion="entropy", max_depth=4).fit(Xtr, ytr)
    acc_tree = accuracy(yte, tree.predict(Xte))
    root_feat = mldata.IRIS_FEATURES[tree.root_.feature]
    root_thr = tree.root_.threshold

    net = MLP([4, 8, 3], seed=42, lr=0.1, epochs=300, batch_size=16)
    net.fit(Xtr, ytr)
    acc_bp = accuracy(yte, net.predict(Xte))

    # 感知机：setosa 二分类（花瓣两特征，线性可分）
    Ptr = [[X[i][2], X[i][3]] for i in tr]
    Pte = [[X[i][2], X[i][3]] for i in te]
    ytr_b = [1 if lab == "setosa" else -1 for lab in ytr]
    yte_b = [1 if lab == "setosa" else -1 for lab in yte]
    perc = Perceptron(max_epochs=200).fit(Ptr, ytr_b)
    acc_perc = accuracy(yte_b, perc.predict(Pte))

    # 线性回归：花萼两特征 -> 花瓣长（标准化后闭式解）
    X2 = [[row[0], row[1]] for row in X]
    y3 = [row[2] for row in X]
    Ltr, Lte = mldata.standardize([X2[i] for i in tr], [X2[i] for i in te])
    lin = LinearRegression().fit_closed_form(Ltr, [y3[i] for i in tr])
    gd = LinearRegression().fit_gd(Ltr, [y3[i] for i in tr], lr=0.1, epochs=8000)
    lin_diff = max(abs(a - b) for a, b in zip(lin.coef_, gd.coef_))
    r2 = r2_score([y3[i] for i in te], lin.predict(Lte))

    grad_worst = _gradient_check_worst()

    # XOR 对照
    Xx = [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]]
    xor_perc = Perceptron(max_epochs=200).fit(Xx, [-1, 1, 1, -1])
    acc_xor_perc = accuracy([-1, 1, 1, -1], xor_perc.predict(Xx))
    xor_bp = MLP([2, 4, 2], seed=3, lr=0.5, epochs=2000).fit(Xx, ["A", "B", "B", "A"])
    acc_xor_bp = accuracy(["A", "B", "B", "A"], xor_bp.predict(Xx))

    # 月牙对照
    Xm, ym = mldata.make_moons(200, noise=0.15, seed=7)
    moon_perc = Perceptron(max_epochs=300).fit(Xm, [1 if v else -1 for v in ym])
    acc_moon_perc = accuracy([1 if v else -1 for v in ym], moon_perc.predict(Xm))
    moon_bp = MLP([2, 16, 2], seed=5, lr=0.5, epochs=800).fit(Xm, ym)
    acc_moon_bp = accuracy(ym, moon_bp.predict(Xm))

    test_count = sum(len(re.findall(r"^\s*def test_",
                       p.read_text(encoding="utf-8"), re.M))
                     for p in sorted(TESTS.glob("test_*.py")))

    facts = [
        ["数据", "Iris 150 行三类均衡；切分 120/30（seed=42）"],
        ["KNN(k=3) 测试精度", f"{acc_knn:.2f}（标准化后，实测阈值 ≥0.9）"],
        ["决策树(熵,深度4)", f"{acc_tree:.2f}；根分裂 {root_feat} ≤ {root_thr:.2f}"],
        ["BP 网络(4-8-3)", f"{acc_bp:.2f}；损失 {net.loss_history_[0]:.2f} → "
                           f"{net.loss_history_[-1]:.2f}"],
        ["感知机(setosa二分)", f"{acc_perc:.2f}（花瓣特征线性可分）"],
        ["线性回归 R^2", f"{r2:.3f}（闭式解 vs GD 差 {lin_diff:.1e}）"],
        ["梯度检查", f"最大相对误差 {grad_worst:.1e}（数值 vs 手写反传）"],
        ["XOR 对照", f"感知机 {acc_xor_perc:.2f} vs BP {acc_xor_bp:.2f}"],
        ["月牙对照", f"感知机 {acc_moon_perc:.2f} vs BP {acc_moon_bp:.2f}"],
        ["测试方法", f"{test_count} 个（tests/ 里 def test_ 现数）"],
    ]
    models = [
        {"name": "knn", "label": f"KNN(k=3) {acc_knn:.2f}",
         "rows": [["测试精度", f"{acc_knn:.3f}"], ["k", "3"],
                  ["预处理", "z-score（只用训练集统计量）"],
                  ["说明", "惰性学习：预测 O(n·d) 扫全库"]]},
        {"name": "tree", "label": f"决策树 {acc_tree:.2f}",
         "rows": [["测试精度", f"{acc_tree:.3f}"],
                  ["根分裂", f"{root_feat} ≤ {root_thr:.3f}"],
                  ["准则", "熵（信息增益），贪心含零增益分裂"],
                  ["说明", "XOR 零增益悖论：不纯即分裂才学得会"]]},
        {"name": "bp", "label": f"BP {acc_bp:.2f}",
         "rows": [["测试精度", f"{acc_bp:.3f}"], ["结构", "4-8-3 softmax"],
                  ["梯度检查", f"最差 {grad_worst:.1e}"],
                  ["损失", f"{net.loss_history_[0]:.2f} → "
                           f"{net.loss_history_[-1]:.2f}"]]},
        {"name": "perc", "label": f"感知机 {acc_perc:.2f}",
         "rows": [["setosa 二分测试精度", f"{acc_perc:.3f}"],
                  ["XOR 上限", f"{acc_xor_perc:.2f}（≤75% 是线性判别的天花板）"],
                  ["月牙", f"{acc_moon_perc:.2f}（不可分探测器）"]]},
        {"name": "lin", "label": f"线性回归 R^2={r2:.2f}",
         "rows": [["R^2(测试)", f"{r2:.3f}"],
                  ["闭式解 vs GD", f"最大差 {lin_diff:.1e}"],
                  ["说明", "标准化决定 GD 收敛速度"]]},
        {"name": "xor", "label": "XOR 对照",
         "rows": [["感知机", f"{acc_xor_perc:.2f}"], ["BP 网络", f"{acc_xor_bp:.2f}"],
                  ["结论", "非线性激活是多层网络的全部意义"]]},
    ]
    return {"facts": facts, "models": models, "loss": net.loss_history_[:120],
            "meta": {"acc_knn": acc_knn, "acc_tree": acc_tree, "acc_bp": acc_bp}}


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
svg.plot{background:#fff;border:1px solid var(--line);border-radius:8px}
.badge{display:inline-block;font-size:.8rem;padding:.08rem .55rem;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}
ol,ul{padding-left:1.3rem}
"""

APP_JS = """
(function(){
  "use strict";
  var state = {name: DATA.models[0].name};
  var chipBox = document.getElementById("chips");
  var panel = document.getElementById("panel");

  function el(tag, cls, text){
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function showModel(name){
    state.name = name;
    var chips = chipBox.children;
    for (var i = 0; i < chips.length; ++i)
      chips[i].className = "chip" + (chips[i].dataset.name === name ? " active" : "");
    var model = null;
    for (var k = 0; k < DATA.models.length; ++k)
      if (DATA.models[k].name === name) model = DATA.models[k];
    panel.textContent = "";
    var table = el("table", "grid");
    model.rows.forEach(function(row){
      var tr = el("tr");
      tr.appendChild(el("td", "", row[0]));
      tr.appendChild(el("td", "", row[1]));
      table.appendChild(tr);
    });
    panel.appendChild(table);
  }

  DATA.models.forEach(function(m){
    var chip = el("button", "chip", m.label);
    chip.dataset.name = m.name;
    chip.addEventListener("click", function(){ showModel(m.name); });
    chipBox.appendChild(chip);
  });
  showModel(state.name);

  // 损失曲线（纯渲染：数据是训练时记录的 history）
  var svg = document.getElementById("loss-curve");
  var hist = DATA.loss;
  if (svg && hist.length > 1) {
    var w = 560, h = 120, pad = 8;
    var maxL = Math.max.apply(null, hist), minL = Math.min.apply(null, hist);
    var pts = hist.map(function(v, i){
      var x = pad + i * (w - 2 * pad) / (hist.length - 1);
      var y = h - pad - (v - minL) * (h - 2 * pad) / (maxL - minL || 1);
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    var poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    poly.setAttribute("points", pts);
    poly.setAttribute("fill", "none");
    poly.setAttribute("stroke", "#1d4ed8");
    poly.setAttribute("stroke-width", "1.5");
    svg.appendChild(poly);
  }
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
<title>B23-ml-from-scratch · 手写机器学习五算法（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B23-ml-from-scratch">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B38-mini-redis/web/showcase.html">B38</a>　·　下一件 <a href="../../../projects/B25-nlp-lab/web/showcase.html">B25</a></span>（本页双击即看，零网络依赖）</p>
<h1>B23 · 纯标准库手写机器学习：五个算法与它们的参照答案</h1>
<p class="note">人工智能导论 · 无 NumPy/scikit-learn：线性回归（正规方程 + 梯度下降）、
感知机、KNN、决策树、BP 网络全手写。参照答案三路对拍：数值梯度 vs 手写反传、
测试内独立参照实现、Fisher 公开统计锚点。</p>

<h2 id="facts-title">实测数字（本页现算，固定种子可复现）</h2>
<section id="facts" class="cards">{cards}</section>

<h2 id="demo-title">展示区：点一个模型看它的实测细节</h2>
<section id="demo" class="panel">
  <div class="chips" id="chips"></div>
  <div id="panel"></div>
  <p class="note">损失曲线（BP，Iris 训练前 120 轮）：</p>
  <svg id="loss-curve" class="plot" width="560" height="120" viewBox="0 0 560 120"></svg>
</section>

<h2 id="repro-title">怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：自测 + 五段演示（Windows 批处理，纯 ASCII）。</li>
    <li><kbd>python demo.py</kbd>：五段演示（数据/线性回归/感知机/KNN+树/BP）。</li>
    <li><kbd>python tests\test_ml.py</kbd>：33 项测试（unittest 与 pytest 同数）。</li>
    <li><kbd>python tools/showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令从真实模型输出现算；别手改本页。
  观感与顺手程度归你实跑验收。</p>
</section>

<footer>
  <p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。</p>
</footer>
</main>
<script>const DATA = {data};</script>
<script>{APP_JS}</script>
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
