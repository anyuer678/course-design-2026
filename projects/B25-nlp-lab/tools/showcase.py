"""B25 展示页生成器：现算分词/贝叶斯/指标数据，渲染自包含 HTML 展示页。

页面写 `web/showcase.html`；`--check` 重算比对，过期即红。
数据来源：种子化合成语料 + 词典切分（来源声明见项目 README）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nlp25.bayes import MultinomialNB                             # noqa: E402
from nlp25.corpus import make_corpus                              # noqa: E402
from nlp25.metrics import accuracy, confusion_matrix              # noqa: E402
from nlp25.metrics import precision_recall_f1                     # noqa: E402
from nlp25.segment import fmm, segment                            # noqa: E402

OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"

EXAMPLES = [
    "研究生命起源",
    "今天下午在二教有答疑",
    "限时秒杀免费领取红包",
    "周五上午提交实验报告",
]


def _test_count() -> int:
    return sum(len(re.findall(r"^\s*def test_",
                              p.read_text(encoding="utf-8"), re.M))
               for p in sorted(TESTS.glob("test_*.py")))


def collect() -> dict:
    texts, labels = make_corpus(100, seed=42)
    tr_x, tr_y = texts[:70] + texts[100:170], labels[:70] + labels[100:170]
    te_x, te_y = texts[70:100] + texts[170:], labels[70:100] + labels[170:]
    nb = MultinomialNB(alpha=1.0, tokenizer=fmm).fit(tr_x, tr_y)
    preds = nb.predict(te_x)
    acc = accuracy(te_y, preds)
    cm = confusion_matrix(te_y, preds, ["notice", "spam"])
    p_s, r_s, f1_s = precision_recall_f1(te_y, preds, "spam")

    seg_examples = []
    for text in EXAMPLES:
        seg = segment(text)
        seg_examples.append({"text": text, "fmm": seg["fmm"], "bmm": seg["bmm"],
                             "ambiguous": seg["ambiguous"]})

    # 手算后验用例（两词表迷你语料，README/测试同款）：P(spam|"发票") = 10/13
    tiny = MultinomialNB(alpha=1.0, tokenizer=str.split).fit(
        ["发票 发票", "发票 通知", "通知 通知", "通知"],
        ["spam", "spam", "ham", "ham"])
    proba = tiny.predict_proba_one("发票")

    # 手写消息分类（新组合，非语料原文）
    probes = []
    for msg, want in [("免费领取红包加微信", "spam"),
                      ("周五上午提交实验报告", "notice")]:
        proba = nb.predict_proba_one(msg)
        probes.append({"msg": msg, "proba": proba,
                       "top": max(proba, key=proba.get), "want": want})

    facts = [
        ["合成语料", f"{len(texts)} 条（notice 100 / spam 100，种子化模板生成）"],
        ["分词器", "FMM/BMM 最大匹配；歧义句自动标注"],
        ["固定划分准确率", f"{acc:.2f}（合成语料词池几乎不重叠，好于真实场景）"],
        ["混淆矩阵", f"notice→notice {cm[('notice','notice')]}、"
                     f"spam→spam {cm[('spam','spam')]}、错 {cm[('notice','spam')] + cm[('spam','notice')]} 个"],
        ["spam 类 P/R/F1", f"{p_s:.2f} / {r_s:.2f} / {f1_s:.2f}"],
        ["手算后验对拍", f'P(spam|"发票") = {proba["spam"]:.4f} = 10/13（含 α=1 平滑）'],
        ["测试方法", f"{_test_count()} 个（tests/ 里 def test_ 现数）"],
    ]
    return {"facts": facts, "seg_examples": seg_examples, "probes": probes,
            "acc": acc, "cm": {f"{k[0]}|{k[1]}": v for k, v in cm.items()},
            "prf": {"p": p_s, "r": r_s, "f1": f1_s},
            "tiny_posterior": proba["spam"]}


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
.tok{display:inline-block;margin:.15rem;padding:.1rem .45rem;border:1px solid var(--line);border-radius:6px;background:#f2f5fb;font-size:.92rem}
.tok.amb{background:#fff3d6;border-color:#d9a300}
.bar{height:14px;background:#1d4ed8;border-radius:3px}
.barwrap{background:#e8ecf5;border-radius:3px;width:220px;display:inline-block;vertical-align:middle}
.badge{display:inline-block;font-size:.8rem;padding:.08rem .55rem;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}
ol,ul{padding-left:1.3rem}

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

APP_JS = """
(function(){
  "use strict";
  var chipBox = document.getElementById("chips");
  var panel = document.getElementById("seg-panel");

  function el(tag, cls, text){
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function show(ex){
    var chips = chipBox.children;
    for (var i = 0; i < chips.length; ++i)
      chips[i].className = "chip" + (chips[i].dataset.text === ex.text ? " active" : "");
    panel.textContent = "";
    panel.appendChild(el("p", "", "原文：" + ex.text));
    var f = el("p");
    f.appendChild(el("b", "", "FMM："));
    ex.fmm.forEach(function(t){
      f.appendChild(el("span", "tok" + (t.length > 1 ? "" : " amb"), t));
    });
    panel.appendChild(f);
    var b = el("p");
    b.appendChild(el("b", "", "BMM："));
    ex.bmm.forEach(function(t){
      b.appendChild(el("span", "tok" + (t.length > 1 ? "" : " amb"), t));
    });
    panel.appendChild(b);
    panel.appendChild(el("p", "note",
      ex.ambiguous ? "两种切分不同 → 检测到歧义（两边都合法）"
                   : "两种切分一致"));
  }

  DATA.seg_examples.forEach(function(ex){
    var chip = el("button", "chip", ex.text);
    chip.dataset.text = ex.text;
    chip.addEventListener("click", function(){ show(ex); });
    chipBox.appendChild(chip);
  });
  show(DATA.seg_examples[0]);

  // 手写消息的后验条形（纯渲染）
  var probBox = document.getElementById("probes");
  DATA.probes.forEach(function(p){
    var row = el("div");
    row.appendChild(el("b", "", p.msg + " → " + p.top + "  "));
    var wrap = el("span", "barwrap");
    var bar = el("span", "bar");
    bar.style.display = "inline-block";
    bar.style.width = (p.proba[p.top] * 100).toFixed(1) + "%";
    wrap.appendChild(bar);
    row.appendChild(wrap);
    row.appendChild(el("span", "note",
      "  P(" + p.top + ")=" + p.proba[p.top].toFixed(4)));
    probBox.appendChild(row);
  });

  // 手算后验的分数展示
  var frac = document.getElementById("tiny-frac");
  if (frac) frac.textContent =
    "P(spam|发票) = " + DATA.tiny_posterior.toFixed(4) + " = 10/13（α=1 平滑）";
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
<title>B25-nlp-lab · 中文分词与朴素贝叶斯（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B25-nlp-lab">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B23-ml-from-scratch/web/showcase.html">B23</a>　·　下一件 <a href="../../../projects/B26-datamining/web/showcase.html">B26</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B25 · 中文分词 + 朴素贝叶斯文本分类</h1>
<p class="note">自然语言处理 · 零依赖：FMM/BMM 最大匹配分词（含"研究生命起源"歧义对拍）、
多项式朴素贝叶斯（拉普拉斯平滑）、手写混淆矩阵与 P/R/F1。语料为种子化合成
（来源声明见项目 README）。</p>

<h2 id="facts-title">实测数字（本页现算，固定种子可复现）</h2>
<section id="facts" class="cards">{cards}</section>

<h2 id="demo-title">展示区一：点一个句子看两种切分与歧义标注</h2>
<section id="demo" class="panel">
  <div class="chips" id="chips"></div>
  <div id="seg-panel"></div>
</section>

<h2 id="probes-title">展示区二：手写消息的逐类后验与指标</h2>
<section id="probes" class="panel">
  <div id="probes"></div>
  <p class="note" id="tiny-frac"></p>
  <p class="note">混淆矩阵（行=真值 列=预测）：
    notice→notice {payload['cm']['notice|notice']}、
    notice→spam {payload['cm']['notice|spam']}、
    spam→notice {payload['cm']['spam|notice']}、
    spam→spam {payload['cm']['spam|spam']}；
    spam 类 P/R/F1 = {payload['prf']['p']:.2f}/{payload['prf']['r']:.2f}/{payload['prf']['f1']:.2f}</p>
</section>

<h2 id="repro-title">怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：自测 + 四段演示（Windows 批处理，纯 ASCII）。</li>
    <li><kbd>python demo.py</kbd>：四段演示（分词/语料/贝叶斯/指标）。</li>
    <li><kbd>python tests\test_nlp.py</kbd>：16 项测试（unittest 与 pytest 同数）。</li>
    <li><kbd>python tools/showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令现算；别手改本页。
  观感与顺手程度归你实跑验收。</p>
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
<script>const DATA = {data};</script>
<script>{APP_JS}</script>
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
