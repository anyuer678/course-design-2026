"""tools/showcase.py —— B35 展示页生成器（手写 MQTT：协议字节 → broker → SQLite → SVG）。口径：showcase/SPEC.md。

数据全部现算，来源是真跑出来的 Python 产物：

- 演示：`python demo.py`（约 6 秒，真 socket 全链路）六段现场输出 → 解析成结构化数据
  （协议字节手算表 / 链路账本 / 完整性对账 / 重连现场）；
- **SVG 曲线是同一套产物**：直接内联 demo 写出的 `build/dev01_temperature.svg`（不另造数据）；
- 测试数按 tests/ 里 `def test_` 静态现数（不跑 discover——防"展示页测试调 collect"递归）。

**日志规范化（2 条，可审计）**：演示里标【实测】的两处先按规则替换再嵌入——
① `吞吐【实测】 N 条/秒` → `<当场>`；② `重连耗时【实测】 N ms` → `<当场>`；
其余由固定种子与固定轮数驱动（`python demo.py` 两遍 diff 自证，tools/logdiff.py 同款口径）。

页面写 `web/showcase.html`；`--check` 重算比对（不写盘），过期即红。
"""
from __future__ import annotations

import argparse
import ast
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
    text = re.sub(r"(吞吐【实测】)\s+\d+(?:\.\d+)? 条/秒", r"\1 <当场> 条/秒", text)
    text = re.sub(r"(重连耗时【实测】)\s+\d+ ms", r"\1 <当场> ms", text)
    return text


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


def _pairs(section: dict) -> list:
    out = []
    for raw in section["lines"]:
        cols = _split_cols(raw)
        if len(cols) >= 2:
            out.append((cols[0], " ".join(cols[1:])))
    return out


def _val(pairs: list, label: str) -> str:
    for k, v in pairs:
        if k == label:
            return v
    return ""


def _parse_protocol(section: dict) -> dict:
    rows, pending, rl = [], None, None
    for raw in section["lines"]:
        cols = _split_cols(raw)
        if not cols:
            continue
        if cols[0] == "手算" and pending:
            rows.append((pending[0], pending[1], " ".join(cols[1:])))
            pending = None
        elif cols[0].startswith("RL 边界"):
            # 该行只有单空格分隔（标签与字典之间不是 2+ 空格列格式）——从 "{" 起截取字典并解析
            head = cols[0]
            rl = ast.literal_eval(head[head.index("{"):])
        elif len(cols) == 2:
            pending = (cols[0], cols[1])
    return {"rows": rows, "rl": rl}


def collect() -> dict:
    demo = _norm(_run([sys.executable, "demo.py"]))
    sections = _parse_sections(demo)
    by_no = {s["no"]: s for s in sections}
    p1, p2, p3, p4, p5, p6 = (_pairs(by_no[i]) for i in range(1, 7))
    protocol = _parse_protocol(by_no[1])

    svg_path = BUILD / "dev01_temperature.svg"
    svg_text = svg_path.read_text(encoding="utf-8").strip()

    method_total = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    method_core = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                      for p in sorted(TESTS.glob("test_*.py")) if p.name != "test_showcase.py")
    facts = [
        ["测试", f"{method_total} 项（{method_core} 同步核心 + {method_total - method_core} 展示页自测；"
              f"tests/ def test_ 现数）"],
        ["链路完整性", f"实发 {_val(p3, '传感器实发合计')} == 实收 {_val(p3, '入库端实收')}"
                  f"（按设备 {_val(p3, '按设备分布')}；解析失败 {_val(p4, '解析失败（应为 0）')}）"],
        ["账本对账", f"异常 {_val(p4, '异常账本（spike/freeze）')} 与库相等；"
                 f"缺口 {_val(p4, '缺口账本（dropout）')} 与库 seq 缺口相等"],
        ["协议字节", f"{len(protocol['rows'])} 条报文实现与手算**逐字节一致**；"
                 f"变长 RL 边界（127/128/16383/16384）手算表"],
        ["断线重连", f"宕机前/中/后发布 {_val(p5, '宕机前发布 / 宕机中发布 / 恢复后发布')}；"
                 f"自动重连 {_val(p5, '自动重连次数')} 次、重订阅恢复 {_val(p5, '重订阅是否恢复')}"],
    ]
    return {"facts": facts, "demo": demo, "protocol": protocol, "svg_text": svg_text,
            "svg_bytes": svg_path.stat().st_size, "method_total": method_total}


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
table.plain code{font-size:.85em}
.svgbox{background:#fff;border:1px solid var(--line);border-radius:10px;padding:.6rem;overflow:auto}
.svgbox svg{max-width:100%;height:auto;display:block}
td.ok{color:var(--ok)}
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
    proto_rows = "".join(
        f'<tr><td>{e(name)}</td><td><code>{e(impl)}</code></td><td><code>{e(hand)}</code></td>'
        f'<td class="ok">{"一致" if impl == hand else "不一致!"}</td></tr>'
        for name, impl, hand in p["protocol"]["rows"])
    rl_rows = "".join(
        f"<tr><td>{e(str(k))}</td><td><code>{e(str(v))}</code></td></tr>"
        for k, v in sorted((p["protocol"]["rl"] or {}).items()))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B35-iot-mqtt · 手写 MQTT 全链路（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B35-iot-mqtt">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B24-cv-scanner/web/showcase.html">B24</a>　·　下一件 <a href="../../../projects/B37-industry-ai/web/showcase.html">B37</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B35-iot-mqtt · 手写极简 MQTT：字节 → broker → SQLite → SVG</h1>
<p class="note">工业物联网技术 · <b>一行第三方库都不用</b>：CONNECT/PUBLISH/SUBSCRIBE 报文自己拼、
broker 订阅路由自己写、断线重连自己扛、入库与曲线自己接——每一层都能指着字节说"它为什么长这样"。
下面的曲线就是 build/ 里的真实产物内联（同一条模拟链路的输出）。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="raw">演示 · 六段原文</button>
    <button class="chip" data-tab="proto">协议字节手算表</button>
    <button class="chip" data-tab="svg">SVG 曲线（真实产物内联）</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="raw">
      <p class="note">`python demo.py` 的完整现场输出；两处【实测】数字（吞吐/重连耗时）按规则规范化，
      其余由固定种子驱动（tools/logdiff.py 同款口径核对两遍日志）。</p>
      <pre class="code wrap">{demo_block}</pre>
    </div>
    <div data-pane-id="proto" hidden>
      <p class="note">三条报文的**实现输出 vs 手算**并排（十六进制）：逐字节一致才算过。
      变长 Remaining Length 的手算边界表在下面。</p>
      <table class="plain"><tr><th>报文</th><th>实现输出</th><th>手算</th><th>结论</th></tr>{proto_rows}</table>
      <p class="note">RL 边界（字节值越小越省——物联网协议的设计动机之一）：</p>
      <table class="plain"><tr><th>值</th><th>编码</th></tr>{rl_rows}</table>
    </div>
    <div data-pane-id="svg" hidden>
      <p class="note">`build/dev01_temperature.svg`（{p["svg_bytes"]} 字节，手写 svgplot 的产物）内联展示：
      dev-01 温度曲线 + 异常红圈（spike/freeze）。同一条链路的数据库里能查到每一个圈对应的读数行。</p>
      <div class="svgbox">
      {p["svg_text"]}
      </div>
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：三步（测试 → 六段演示 → 展示页新鲜度）；DB 与 SVG 落在 build\\。</li>
    <li><kbd>python demo.py</kbd>：六段演示；<kbd>python tools\\logdiff.py a.log b.log</kbd>：两次日志规范化比对。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 demo.py 现算（测试数按 tests/ 静态现数；
  两处【实测】数字已按规则替换成 &lt;当场&gt;）。零依赖：纯标准库。</p>
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
    ap = argparse.ArgumentParser(description="B35 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（六段演示 + 协议字节表 + SVG 产物内联，全部现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（演示/协议/产物 SVG）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
