"""tools/showcase.py —— B37 展示页生成器（设备故障预测：遥测 → 特征 → 三模型 → 误报解剖）。口径：showcase/SPEC.md。

数据全部现算，来源是真跑出来的 Python 产物：

- 演示：`python demo.py`（约 4 秒）六段现场输出 → 解析成结构化数据
  （数据账 / 样本账 / 三模型对比 / 阈值敏感性 / 误报解剖 / 切分对照）；
- **三张 SVG 是同一套产物**：直接内联 demo 写出的 `build/alert_budget.svg`、
  `build/dev08_temp.svg`、`build/dev08_vib.svg`（不另造数据）；
- 测试数按 tests/ 里 `def test_` 静态现数（不跑 discover——防"展示页测试调 collect"递归）。

**日志规范化（1 条，可审计）**：演示第 3 段耗时列是唯一实时测量，`N ms` → `<当场> ms`
（tools/logdiff.py 同款口径）；数据/指标全部由固定种子驱动（两遍 diff 自证）。

页面写 `web/showcase.html`；`--check` 重算比对（不写盘），过期即红。
"""
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"
BUILD = ROOT / "build"
SVGS = ("alert_budget.svg", "dev08_temp.svg", "dev08_vib.svg")
MODEL_LABELS = ("固定阈值(铭牌100/2.0)", "B23 决策树", "手写逻辑回归(L2)")


def _run(args) -> str:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(map(str, args))} 退出码 {proc.returncode}：\n"
                         f"{(proc.stdout or '')[-400:]}\n{(proc.stderr or '')[-400:]}")
    return proc.stdout


def _norm(text: str) -> str:
    # 连前导对齐空格一起吃掉：表格里耗时列宽度随读数位数变（"0.926     <当场>" vs
    # "0.926    <当场>" 曾让 --check 翻烙饼），规范化必须把对齐位移一并抹平。
    return re.sub(r" +\d+(?:\.\d+)? ms", " <当场> ms", text)


def _parse_sections(text: str) -> list:
    sections, current = [], None
    for line in text.splitlines():
        if set(line.strip()) == {"="} and line.strip():
            continue
        m = re.match(r"^\s*(\d+)\) (.+)$", line)
        if m:
            current = {"no": int(m.group(1)), "title": m.group(2), "lines": []}
            sections.append(current)
        elif current is not None:
            current["lines"].append(line.rstrip())
    return sections


def _split_cols(line: str) -> list:
    return [c.strip() for c in re.split(r"\s{2,}", line.strip()) if c.strip()]


def _kv(section: dict) -> dict:
    out = {}
    for raw in section["lines"]:
        cols = _split_cols(raw)
        if len(cols) >= 2:
            out[cols[0]] = " ".join(cols[1:])
    return out


def collect() -> dict:
    demo = _norm(_run([sys.executable, "demo.py"]))
    sections = _parse_sections(demo)
    by_no = {s["no"]: s for s in sections}
    kv1, kv2, kv3, kv4, kv5, kv6 = (_kv(by_no[i]) for i in range(1, 7))

    model_rows = []
    for raw in by_no[3]["lines"]:
        cols = _split_cols(raw)
        if cols and cols[0] in MODEL_LABELS and len(cols) >= 7:
            model_rows.append(cols[:-1])  # 去掉耗时列（已规范化，不进结构化表）

    sweep_rows = []
    for raw in by_no[4]["lines"]:
        cols = _split_cols(raw)
        if cols and cols[0] in ("best-F1", "召回≥95%", "告警预算≤24") and len(cols) >= 5:
            sweep_rows.append(cols)

    svgs = []
    for name in SVGS:
        path = BUILD / name
        svgs.append({"name": name, "bytes": path.stat().st_size,
                     "text": path.read_text(encoding="utf-8").strip()})

    method_total = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    method_core = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                      for p in sorted(TESTS.glob("test_*.py")) if p.name != "test_showcase.py")
    by_model = {row[0]: row for row in model_rows}
    tree = by_model.get("B23 决策树", [])
    lr = by_model.get("手写逻辑回归(L2)", [])
    rule = by_model.get("固定阈值(铭牌100/2.0)", [])
    facts = [
        ["测试", f"{method_total} 项（{method_core} 同步核心 + {method_total - method_core} 展示页自测；"
              f"tests/ def test_ 现数）"],
        ["数据账（模拟）", f"{kv1.get('车队/时间线', '')}；故障 {kv1.get('故障注入', '')}；"
                    f"账本 {kv1.get('数据质量账本', '')}"],
        ["样本账", f"{kv2.get('样本与排除', '')}；正样本 {kv2.get('正样本（将要故障）', '')}；"
                f"{kv2.get('切分', '')}"],
        ["三模型（best-F1）", f"阈值基线 F1 {rule[5] if len(rule) > 5 else '?'} / "
                      f"树 F1 {tree[5] if len(tree) > 5 else '?'}·AUC {tree[6] if len(tree) > 6 else '?'} / "
                      f"LR F1 {lr[5] if len(lr) > 5 else '?'}·AUC {lr[6] if len(lr) > 6 else '?'}（测试设备）"],
        ["误报解剖", f"固定阈值 {kv5.get('固定阈值误报归因', '')}"],
        ["提前量", f"{kv5.get('树运营点提前量', '')}；{kv5.get('按故障类型的接住率', '')}"],
    ]
    return {"facts": facts, "demo": demo, "model_rows": model_rows, "sweep_rows": sweep_rows,
            "svgs": svgs, "method_total": method_total,
            "auc_line": next((ln.strip() for ln in by_no[4]["lines"] if "AUC（与阈值无关）" in ln), "")}


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
table.plain{border-collapse:collapse;font-size:.88rem;margin:.5rem 0;width:100%}
table.plain th,table.plain td{border:1px solid var(--line);padding:.3rem .7rem;text-align:left;vertical-align:top}
table.plain td.num,table.plain th.num{text-align:right;font-variant-numeric:tabular-nums}
.svgbox{background:#fff;border:1px solid var(--line);border-radius:10px;padding:.6rem;overflow:auto;margin:.5rem 0}
.svgbox svg{max-width:100%;height:auto;display:block}
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


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    demo_block = e(p["demo"].rstrip())
    model_rows = "".join(
        "<tr>" + "".join(f'<td class="num">{e(c)}</td>' if i > 0 else f"<td>{e(c)}</td>"
                         for i, c in enumerate(row)) + "</tr>"
        for row in p["model_rows"])
    sweep_rows = "".join(
        "<tr>" + "".join(f'<td class="num">{e(c)}</td>' if i > 0 else f"<td>{e(c)}</td>"
                         for i, c in enumerate(row)) + "</tr>"
        for row in p["sweep_rows"])
    svg_blocks = "".join(
        f'<div class="svgbox">{s["text"]}</div>'
        f'<p class="note">build/{e(s["name"])}（{s["bytes"]} 字节，内联同一份产物）</p>'
        for s in p["svgs"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B37-industry-ai · 设备故障预测基线（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B37-industry-ai">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B35-iot-mqtt/web/showcase.html">B35</a>　·　下一件 <a href="../../../projects/B27-course-kg/web/showcase.html">B27</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B37-industry-ai · 预测性维护：遥测 → 特征 → 概率 → 阈值 → 告警</h1>
<p class="note">行业软件 + AI · <b>预测性维护不是"训一个模型"</b>：要提前多久报警、误报/漏报各罚多少、
阈值按什么口径选，全部写成可对账的清单。数据是<strong>模拟</strong>（复用 B35 的异常分类学与账本、
B23 的决策树），<strong>指标只说明口径自洽，不外推生产</strong>。下面三张图是 build/ 里的真实产物内联。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="raw">演示 · 六段原文</button>
    <button class="chip" data-tab="models">三模型与阈值（结构化）</button>
    <button class="chip" data-tab="svg">SVG 产物（真实内联）</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="raw">
      <p class="note">`python demo.py` 的完整现场输出；第 3 段耗时列是唯一实时测量（已规范化为
      &lt;当场&gt;），其余由固定种子驱动。</p>
      <pre class="code wrap">{demo_block}</pre>
    </div>
    <div data-pane-id="models" hidden>
      <p class="note">测试设备上的三模型对比（best-F1 运营点；原始输出含耗时列，此处按口径结构化）：</p>
      <table class="plain"><tr><th>模型</th><th class="num">阈值</th><th class="num">报警</th>
      <th class="num">精确率</th><th class="num">召回率</th><th class="num">F1</th><th class="num">AUC</th></tr>{model_rows}</table>
      <p class="note">同一模型的代价曲线（点列由 sweep 现算）——选点才是运营决策：</p>
      <table class="plain"><tr><th>口径</th><th class="num">阈值</th><th class="num">报警</th>
      <th class="num">精确率</th><th class="num">召回率</th></tr>{sweep_rows}</table>
      <p class="note">{e(p["auc_line"])}</p>
    </div>
    <div data-pane-id="svg" hidden>
      <p class="note">三张图都来自 `fault/report.py`（复用 B35 的手写 svgplot，两遍构建字节相同）：
      告警预算曲线 + dev-08 的温度/振动时间线（红圈 = 该设备故障点）。</p>
      {svg_blocks}
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：三步（测试 → demo（生成 build\\ 下 3 张 SVG）→ 展示页新鲜度）。</li>
    <li><kbd>python demo.py</kbd>：六段演示；<kbd>python tools\\logdiff.py a.log b.log</kbd>：两次日志规范化比对。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 demo.py 现算（测试数按 tests/ 静态现数；
  唯一实时测量=第 3 段耗时列，已按规则替换成 &lt;当场&gt;）。一切数字不外推为生产结论。</p>
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
    ap = argparse.ArgumentParser(description="B37 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（六段演示 + 三模型表 + 3 张 SVG 内联，全部现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            print(f"长度：磁盘 {len(disk)} / 现算 {len(fresh)}")
            for i, (x, y) in enumerate(zip(disk.splitlines(), fresh.splitlines())):
                if x != y:
                    print(f"首个差异行 {i}：磁盘={x[:100]!r} 现算={y[:100]!r}")
                    break
            return 1
        print("展示页新鲜：与现算逐字一致（演示/模型表/产物 SVG）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
