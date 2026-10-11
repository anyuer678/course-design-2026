"""tools/showcase.py —— B32 展示页生成器（四组漏洞版/修复版对照 + 静态扫描器）。口径：showcase/SPEC.md。

数据全部现算，来源是真跑出来的 Python 产物：

- 演示：`python demo.py`（约 5 秒）六段现场输出；第 1/2/4/5/6 段逐字稳定，解析成结构化表格；
- **第 3 段（口令派生成本）是实时测量（两次运行 ±5% 波动）**——页内把会过期的吞吐数字
  按可审计规则脱敏成 `[现场]` 占位（口径同 B12"页面不冻结计时数字"）：
    ① `N 次/秒` → `[现场] 次/秒`（含千分位与小数）
    ② `比 MD5 慢 N 倍` → `比 MD5 慢 [现场] 倍`
    ③ `N 秒跑完` / `N 小时`（百万词字典估算）→ `[现场]`
- 静态扫描器的结论从第 5 段现场输出解析（逐文件拼接点数 + 八个拼接点名单 + 双向比对行）。

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


def _run(args) -> str:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(map(str, args))} 退出码 {proc.returncode}：\n"
                         f"{(proc.stderr or '')[-500:]}")
    return proc.stdout


def _mask_live_measurements(text: str) -> str:
    text = re.sub(r"\d[\d,]*(?:\.\d+)? 次/秒", "[现场] 次/秒", text)
    text = re.sub(r"(比 MD5 慢 )\d[\d,]*( 倍)", r"\1[现场]\2", text)
    text = re.sub(r"\d[\d.]* 秒跑完", "[现场] 秒跑完", text)
    text = re.sub(r"\d[\d.]* 小时", "[现场] 小时", text)
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


def _parse_sql(section: dict) -> list:
    rows = []
    for raw in section["lines"]:
        cols = _split_cols(raw)
        if len(cols) >= 2:
            rows.append((cols[0], cols[1], cols[2] if len(cols) > 2 else ""))
    return rows


def _parse_xss(section: dict) -> list:
    """两种行型：载荷行给双侧计数；真起服务行只给本侧计数（另一侧记 None）。"""
    rows = []
    for raw in section["lines"]:
        line = raw.strip()
        if not line:
            continue
        label = _split_cols(line)[0]
        if "（漏洞版）" in line:
            rows.append((label, int(re.search(r"信号 (\d+) 条", line).group(1)), None))
        elif "（修复版）" in line:
            rows.append((label, None, int(re.search(r"信号 (\d+) 条", line).group(1))))
        else:
            rows.append((label,
                         int(re.search(r"漏洞版信号 (\d+) 条", line).group(1)),
                         int(re.search(r"修复版 (\d+) 条", line).group(1))))
    return rows


def _parse_traversal(section: dict) -> dict:
    load_rows, ref_lines = [], []
    for raw in section["lines"]:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("载荷"):
            continue
        if line.startswith(("标准库参照", "本机大小写语义")):
            ref_lines.append(line)
        else:
            load_rows.append(line)
    return {"load_rows": load_rows, "ref_lines": ref_lines}


def _parse_scanner(section: dict) -> dict:
    files, sites, notes = [], [], []
    for raw in section["lines"]:
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^([\w]+\.py)\s+(\d+) 处(?: → (.+))?$", line)
        if m:
            entry = {"file": m.group(1), "count": int(m.group(2)), "sites": []}
            if m.group(3):
                entry["sites"] = ast.literal_eval(m.group(3))
            files.append(entry)
            sites.extend(entry["sites"])
            continue
        notes.append(line)
    return {"files": files, "sites": sites, "notes": notes}


def _parse_summary(section: dict) -> list:
    rows = []
    for raw in section["lines"]:
        cols = _split_cols(raw)
        if len(cols) >= 2:
            rows.append((cols[0], " ".join(cols[1:])))
    return rows


def collect() -> dict:
    demo = _mask_live_measurements(_run([sys.executable, "demo.py"]))
    sections = _parse_sections(demo)
    by_no = {s["no"]: s for s in sections}
    sql = _parse_sql(by_no[1])
    xss = _parse_xss(by_no[2])
    traversal = _parse_traversal(by_no[4])
    scanner = _parse_scanner(by_no[5])
    summary = _parse_summary(by_no[6])

    method_total = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    method_core = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                      for p in sorted(TESTS.glob("test_*.py")) if p.name != "test_showcase.py")
    xss_vuln_total = sum(v for label, v, _f in xss if "真起服务" not in label)
    xss_payloads = sum(1 for label, _v, _f in xss if "真起服务" not in label)
    xss_fixed_total = sum(f for _l, _v, f in xss if f is not None)
    sqli_sites = next((e for e in scanner["files"] if e["file"] == "sqli.py"), None)
    audit_cols = _split_cols(scanner["notes"][0]) if scanner["notes"] else []
    stripped = re.search(r"扫出 (\d+) 处（原 (\d+) 处）",
                         next((ln for ln in scanner["notes"] if ln.startswith("把包装函数")), ""))
    facts = [
        ["测试", f"{method_total} 项（{method_core} 核心 + {method_total - method_core} 展示页自测；"
              f"tests/ def test_ 现数，run.bat 一趟是权威）"],
        ["四组对照", f"SQL {len(sql)} 行分化、XSS {xss_payloads} 载荷漏洞版共 {xss_vuln_total} 条信号"
                 f"（修复版 {xss_fixed_total} 条）、穿越判定表 {len(traversal['load_rows'])} 条载荷"],
        ["静态扫描器", f"sqli.py {sqli_sites['count'] if sqli_sites else 0} 处拼接点全在册；双向比对"
                  f"{audit_cols[1] if len(audit_cols) > 1 else ''}；摘掉包装函数后 {stripped.group(2)} → {stripped.group(1)}"],
        ["口令成本", "第 3 段是实时测量：迭代 1k→10k→100k 吞吐线性下降、PBKDF2-120k 比裸 MD5 "
                 "慢四个数量级以上（本页不冻结计时数字，见 [现场] 占位）"],
        ["边界声明", "只在本机内存库与临时目录里活动；靶件是教学样本，结论不外推、不构成攻击能力"],
    ]
    return {"facts": facts, "demo": demo, "sql": sql, "xss": xss, "traversal": traversal,
            "scanner": scanner, "summary": summary, "method_total": method_total}


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
td.bad{color:var(--bad)}td.ok{color:var(--ok)}
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
    sql_rows = "".join(
        f'<tr><td>{e(a)}</td><td class="bad">{e(b)}</td><td class="ok">{e(c)}</td></tr>' for a, b, c in p["sql"])
    xss_rows = "".join(
        f'<tr><td>{e(label)}</td>'
        f'<td class="num bad">{f"{v} 条" if v is not None else "—"}</td>'
        f'<td class="num ok">{f"{f} 条" if f is not None else "—"}</td></tr>'
        for label, v, f in p["xss"])
    trav_pre = e("\n".join(p["traversal"]["load_rows"] + p["traversal"]["ref_lines"]))
    sc_rows = "".join(
        f'<tr><td>{e(x["file"])}</td><td class="num">{x["count"]}</td></tr>' for x in p["scanner"]["files"])
    sc_sites = "".join(f"<li><code>{e(s)}</code></li>" for s in p["scanner"]["sites"])
    sc_notes = "".join(f"<li>{e(n)}</li>" for n in p["scanner"]["notes"])
    sum_rows = "".join(f'<tr><td>{e(a)}</td><td>{e(b)}</td></tr>' for a, b in p["summary"])
    demo_block = e(p["demo"].rstrip())
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B32-sec-lab · 四组漏洞版/修复版对照（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B32-sec-lab">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B11-net-lab/web/showcase.html">B11</a>　·　下一件 <a href="../../../projects/B10-minidb/web/showcase.html">B10</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B32-sec-lab · 信息安全导论：同一个错误模型，四个解析器</h1>
<p class="note">SQL 引擎、HTML 词法器、口令比较、路径解析——数据一旦在这些位置获得"语法身份"，
注入就发生。四组**并排的漏洞版与修复版**用同一份输入量差距；每条判定都要能被改动弄红。
全部只在本机内存库与临时目录里活动，靶件是教科书级最小样本。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="raw">演示 · 六段原文</button>
    <button class="chip" data-tab="labs">四组对照速览</button>
    <button class="chip" data-tab="scanner">静态扫描器</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="raw">
      <p class="note">`python demo.py` 的完整现场输出；第 3 段（口令成本）是实时测量，
      吞吐数字已按生成器文档串里的规则脱敏成 <b>[现场]</b>（页面不冻结会过期的计时数字）。</p>
      <pre class="code wrap">{demo_block}</pre>
    </div>
    <div data-pane-id="labs" hidden>
      <p class="note">SQL 组：同一份输入喂给拼接版与绑定版（或白名单版），后果逐行对照。</p>
      <table class="plain"><tr><th>用例</th><th>漏洞版</th><th>修复版</th></tr>{sql_rows}</table>
      <p class="note">HTML 组：6 个载荷在漏洞版的信号条数（修复版为 0 才是目标），外加"真起服务真发请求"
      的两行端到端取证。</p>
      <table class="plain"><tr><th>载荷 / 场景</th><th class="num">漏洞版信号</th><th class="num">修复版信号</th></tr>{xss_rows}</table>
      <p class="note">穿越组：15 条载荷 × 四种写法（判定表原文如下；修复版越界 0 是底线），
      最后两行是标准库参照与本机大小写语义的实测登记。</p>
      <pre class="code wrap">{trav_pre}</pre>
    </div>
    <div data-pane-id="scanner" hidden>
      <p class="note">`sec32/audit.py` 用 ast 扫出的拼接点（逐文件）：</p>
      <table class="plain"><tr><th>文件</th><th class="num">拼接点</th></tr>{sc_rows}</table>
      <p class="note">sqli.py 的八个拼接点（人工登记表与之双向比对：扫到没登记红、登记了扫不到红）：</p>
      <ul>{sc_sites}</ul>
      <p class="note">现场结论与"扫描器会瞎"的证明：</p>
      <ul>{sc_notes}</ul>
    </div>
  </div>
</section>

<h2>汇总（演示第 6 段）</h2>
<section class="panel"><table class="plain">{sum_rows}</table></section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：四步（测试双入口 → 政策核对 → 演示 → 展示页新鲜度）。</li>
    <li><kbd>python -m unittest discover -s tests</kbd>：全量；<kbd>python demo.py</kbd>：六段演示。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 demo.py 现算并解析（第 3 段计时脱敏；
  测试数按 tests/ def test_ 静态现数）。</p>
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
    ap = argparse.ArgumentParser(description="B32 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（四组对照/扫描器/演示全部现算；第 3 段计时脱敏）")
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
        print("展示页新鲜：与现算逐字一致（SQL/XSS/穿越/扫描器）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
