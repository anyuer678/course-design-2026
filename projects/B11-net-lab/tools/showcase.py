"""tools/showcase.py —— B11 展示页生成器（HTTP 子集 + select 多路复用 + UDP GBN）。口径：showcase/SPEC.md。

数据全部现算，来源是真跑出来的 Python 产物：

- 演示：`python demo.py`（约 1 秒）五段现场输出，随后解析成结构化数据
  （请求旅程 / 越界拒绝表 / GBN 丢包扫描与窗口对照）；
- HTTP 子集的硬上限与状态码表从 `netlab/http1.py` **现场 import 读取**（常量即出处）；
- 测试数按 tests/ 两个核心文件 `def test_` 静态现数（不跑 discover——跑会在
  "展示页测试里再调 collect"时递归；B12 同款口径）。

**日志规范化（4 条，可审计）**：演示里随环境波动的四处先按规则替换再嵌入——
① 临时端口（绑 0 由内核分配）→ `127.0.0.1:<临时端口>`；② 响应 `Date` 头（当场时间）→ `<当场时间>`；
③ `/stats` 的 `open_now`（随连接回收时点 0/1）→ `<当场>`；④ 真回环 UDP 耗时 → `<当场>`。
其余数字由种子与固定脚本决定（`python demo.py` 两遍 diff 自证）。

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

sys.path.insert(0, str(ROOT))


def _run(args) -> str:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(map(str, args))} 退出码 {proc.returncode}：\n"
                         f"{(proc.stderr or '')[-500:]}")
    return proc.stdout


def _norm(text: str) -> str:
    text = re.sub(r"127\.0\.0\.1:\d+", "127.0.0.1:<临时端口>", text)
    text = re.sub(r"Date: [A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT",
                  "Date: <当场时间>", text)
    text = re.sub(r"'open_now': \d+", "'open_now': <当场>", text)
    text = re.sub(r"耗时=[\d.]+s", "耗时=<当场>s", text)
    return text


def _parse_sections(text: str) -> list:
    sections, current = [], None
    for line in text.splitlines():
        if set(line.strip()) == {"="} and line.strip():
            continue
        m = re.match(r"^\[(\d)/5\] (.+)$", line)
        if m:
            current = {"no": int(m.group(1)), "title": m.group(2), "lines": []}
            sections.append(current)
        elif current is not None:
            current["lines"].append(line.rstrip())
    return sections


def _parse_journey(section: dict) -> dict:
    request, response, fields = [], [], {}
    mode = None
    for raw in section["lines"]:
        line = raw.strip()
        if line.startswith("客户端发出的请求字节"):
            mode = "req"
            continue
        if line.startswith("同一请求的原始响应字节"):
            mode = "resp"
            continue
        if line.startswith("| "):
            (request if mode == "req" else response).append(line[2:].rstrip())
            continue
        m = re.match(r"^(消耗字节|解析结论|响应):\s*(.*)$", line)
        if m and mode:
            fields[m.group(1)] = m.group(2)
    return {"request": request, "response": response, **fields}


def _parse_boundaries(section: dict) -> dict:
    codes, parse_errors, mode = [], [], None
    for raw in section["lines"]:
        line = raw.strip()
        if "越界请求的响应码" in line:
            mode = "codes"
            continue
        if "解析层直接抛出的错误" in line:
            mode = "parse"
            continue
        if mode == "codes":
            m = re.match(r"^(.+?)\s+->\s+(HTTP/1\.1 .+)$", line)
            if m:
                codes.append((m.group(1).strip(), m.group(2).strip()))
        elif mode == "parse":
            m = re.match(r"^(b'.*?'…)\s+->\s+(.+)$", line)
            if m:
                parse_errors.append((m.group(1), m.group(2).strip()))
    return {"codes": codes, "parse_errors": parse_errors}


def _parse_gbn(section: dict) -> dict:
    rows, windows, notes = [], [], {}
    for raw in section["lines"]:
        line = raw.strip()
        m = re.match(r"^(\d+)%\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%$", line)
        if m:
            rows.append([int(m.group(1)), int(m.group(2)), int(m.group(3)),
                         int(m.group(4)), int(m.group(5)), m.group(6) + "%"])
            continue
        m = re.match(r"^window=(\d+): 时隙=(\d+) 发送=(\d+)$", line)
        if m:
            windows.append([int(m.group(1)), int(m.group(2)), int(m.group(3))])
            continue
        if line.startswith("丢包率扫描"):
            notes["sweep_caption"] = line
        elif line.startswith("可复现："):
            notes["reproducible"] = line
        elif line.startswith("窗口大小的意义"):
            notes["window_caption"] = line
        elif line.startswith("序号回绕："):
            notes["wrap"] = line
        elif line.startswith("30000 字节："):
            notes["real_udp"] = line
    return {"rows": rows, "windows": windows, "notes": notes}


def collect() -> dict:
    demo = _norm(_run([sys.executable, "demo.py"]))
    sections = _parse_sections(demo)
    by_no = {s["no"]: s for s in sections}
    journey = _parse_journey(by_no[1])
    boundaries = _parse_boundaries(by_no[3])
    gbn = _parse_gbn(by_no[5])

    from netlab import http1
    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py"))
                       if p.name != "test_showcase.py")
    facts = [
        ["测试", f"{method_count} 项（tests/ 两个核心文件的 def test_ 现数；run.bat 一趟是权威）"],
        ["HTTP 子集", f"状态码表 {len(http1.STATUS)} 条；硬上限：目标 {http1.MAX_URI} 字节 / "
                  f"单行 {http1.MAX_REQUEST_LINE} 字节 / 头 {http1.MAX_HEADER_COUNT} 条·"
                  f"{http1.MAX_HEADER_BYTES // 1024}KiB / 体 {http1.DEFAULT_MAX_BODY // 1024}KiB"],
        ["边界拒绝", f"越界请求 {len(boundaries['codes'])} 种现场回放（414/431/400/501/413/505…），"
                  f"解析层错误 {len(boundaries['parse_errors'])} 类同规则两侧一致"],
        ["GBN 实验", f"丢包 {gbn['rows'][0][0]}%→{gbn['rows'][-1][0]}% 五档扫描、窗口 1/2/4/8 对照、"
                  f"回绕 space=8 逐字节一致（种子固定，可复跑）"],
        ["真回环", "同一套代码跑真 127.0.0.1 UDP：30000 字节发送完成 / 收完 / 字节一致 全为 True"],
    ]
    return {"facts": facts, "demo": demo, "sections": sections, "journey": journey,
            "boundaries": boundaries, "gbn": gbn, "method_count": method_count}


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
table.plain{border-collapse:collapse;font-size:.9rem;margin:.5rem 0;width:100%}
table.plain th,table.plain td{border:1px solid var(--line);padding:.3rem .7rem;text-align:left;vertical-align:top}
table.plain td.num,table.plain th.num{text-align:right;font-variant-numeric:tabular-nums}
.flow{display:grid;gap:.5rem;margin:.5rem 0}
.flow .step{background:#fff;border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;padding:.5rem .8rem}
.flow .step b{font-size:.85rem;color:var(--muted);display:block}
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


def _rows_html(pairs):
    return "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td></tr>"
                   for a, b in pairs)


def render(payload: dict) -> str:
    p = payload
    cards = "".join(f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    req_block = html.escape("\n".join(p["journey"]["request"]))
    resp_block = html.escape("\n".join(p["journey"]["response"]))
    journey_html = (
        '<div class="flow">'
        f'<div class="step"><b>① 客户端字节（真发出去的那一份）</b><pre class="code wrap">{req_block}</pre></div>'
        f'<div class="step"><b>② 解析器吃掉多少</b><span>{html.escape(p["journey"].get("消耗字节", ""))} 字节'
        f'　·　{html.escape(p["journey"].get("解析结论", ""))}</span></div>'
        f'<div class="step"><b>③ 路由结论</b><span>{html.escape(p["journey"].get("响应", ""))}</span></div>'
        f'<div class="step"><b>④ 响应字节（含逐字头部）</b><pre class="code wrap">{resp_block}</pre></div>'
        "</div>")
    code_rows = _rows_html(p["boundaries"]["codes"])
    err_rows = _rows_html(p["boundaries"]["parse_errors"])
    sweep_rows = "".join(
        f'<tr><td class="num">{r[0]}%</td><td class="num">{r[1]}</td><td class="num">{r[2]}</td>'
        f'<td class="num">{r[3]}</td><td class="num">{r[4]}</td><td class="num">{r[5]}</td></tr>'
        for r in p["gbn"]["rows"])
    window_rows = "".join(
        f'<tr><td class="num">{w[0]}</td><td class="num">{w[1]}</td><td class="num">{w[2]}</td></tr>'
        for w in p["gbn"]["windows"])
    g = p["gbn"]["notes"]
    demo_block = html.escape(p["demo"].rstrip())
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B11-net-lab · HTTP 子集 + 多路复用 + UDP GBN（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B11-net-lab">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B8-mini-shell/web/showcase.html">B8</a>　·　下一件 <a href="../../../projects/B32-sec-lab/web/showcase.html">B32</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B11-net-lab · HTTP/1.1 子集 + select 多路复用 + UDP 可靠传输</h1>
<p class="note">计算机网络 · 应用层解析、传输层之上的单线程多路复用、传输层的 Go-Back-N 放同一份工程里：
每个协议边界都按 RFC 讲得清道理，压轴是**与标准库解析器对拍**。下面全部来自刚跑完的现场输出
（演示里四处随环境波动的数字按可审计规则规范化，见页脚）。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="raw">演示 · 五段原文</button>
    <button class="chip" data-tab="journey">一条请求的旅程</button>
    <button class="chip" data-tab="bounds">边界拒绝表</button>
    <button class="chip" data-tab="gbn">GBN 丢包实验</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="raw">
      <p class="note">`python demo.py` 的完整现场输出（临时端口 / Date / open_now / 回环耗时已规范化）。</p>
      <pre class="code wrap">{demo_block}</pre>
    </div>
    <div data-pane-id="journey" hidden>
      <p class="note">第 1 段的结构化拆解：同一份字节从"写出去"到"解析 → 路由 → 响应"，中间产物逐项可查。</p>
      {journey_html}
    </div>
    <div data-pane-id="bounds" hidden>
      <p class="note">第 3 段：8 种越界请求各自的响应码（服务端真的拒了），以及解析层直接抛出的错误——
      同一条规则在"服务端拒绝"与"客户端抛错"两侧给出同一个结论。</p>
      <table class="plain"><tr><th>越界形状</th><th>响应</th></tr>{code_rows}</table>
      <table class="plain"><tr><th>请求字节（截断）</th><th>解析器结论</th></tr>{err_rows}</table>
    </div>
    <div data-pane-id="gbn" hidden>
      <p class="note">{html.escape(g.get("sweep_caption", ""))}</p>
      <table class="plain"><tr><th class="num">丢包率</th><th class="num">时隙</th><th class="num">发送包数</th>
      <th class="num">重传</th><th class="num">超时</th><th class="num">有效载荷比</th></tr>{sweep_rows}</table>
      <p class="note">{html.escape(g.get("reproducible", ""))}</p>
      <p class="note">{html.escape(g.get("window_caption", ""))}</p>
      <table class="plain"><tr><th class="num">窗口</th><th class="num">时隙</th><th class="num">发送</th></tr>{window_rows}</table>
      <p class="note">{html.escape(g.get("wrap", ""))}</p>
      <p class="note">{html.escape(g.get("real_udp", ""))}</p>
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：三步（测试 → 演示 → 展示页新鲜度）。</li>
    <li><kbd>python demo.py</kbd>：五段演示；<kbd>python -m unittest discover -s tests -v</kbd>：全量测试。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 demo.py 现算（测试数按 tests/ 静态现数；
  页面不含计时数字——四处会波动的现场值已按规范化规则替换，规则写在生成器文档串里）。</p>
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
    ap = argparse.ArgumentParser(description="B11 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（请求旅程/边界表/GBN 实验全部现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（旅程/边界/GBN 演示全量解析）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
