"""tools/showcase.py —— B5 展示页生成器（单周期 vs 五级流水线）。口径：showcase/SPEC.md。

数据全部现算，来源都是**真跑出来的 C++ 产物**（无计时数字，输出确定可对拍）：

- 自测（tests.exe）：42 项断言（ISA/汇编器/单周期性质/流水线 vs 单周期逐字节一致）；
- bubble.asm 双模型对拍（cpu-sim.exe）：单周期 159 周期 vs 流水线 219 周期、
  寄存器一致、排序结果；
- **流水线时空图**（cpu-sim.exe --chart）：逐周期解析成 5 列（IF/ID/EX/MEM/WB）表格，
  S（停顿）/F（冲刷）着色；bubble 与 loop 两套。

生成前若 build/cpu-sim.exe 不存在会先按 run.bat 的同一命令行编译（自包含）。
页面写 `web/showcase.html`；`--check` 重算比对（不写盘），过期即红。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "showcase.html"
BUILD = ROOT / "build"
GXX = ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-static", "-Iinclude"]


def _ensure_built():
    if not (BUILD / "cpu-sim.exe").is_file() or not (BUILD / "tests.exe").is_file():
        BUILD.mkdir(exist_ok=True)
        for src, out in (("tests/test_cpu.cpp", "tests.exe"), ("src/main.cpp", "cpu-sim.exe")):
            proc = subprocess.run(GXX + [src, "-o", f"build/{out}"], cwd=str(ROOT),
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
            if proc.returncode != 0:
                raise SystemExit(f"编译 {src} 失败（先跑 run.bat 检查工具链）：\n{proc.stderr[-800:]}")


def _run(args) -> str:
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(args)} 退出码 {proc.returncode}：\n{(proc.stderr or '')[-500:]}")
    return proc.stdout


def _candidates_from_asm(path: Path) -> list:
    """时空图每格只会印"指令名"或"指令名+标签"；用汇编源里的词表做最长匹配。"""
    text = path.read_text(encoding="utf-8")
    labels = re.findall(r"^(\w+):", text, re.M)
    ops = set()
    for line in text.splitlines():
        line = line.split(";")[0].split("#")[0].strip()
        if not line or line.endswith(":"):
            continue
        ops.add(line.split()[0])
    cands = {"S", "F"} | ops
    for lab in labels:
        for op in ops:
            cands.add(f"{op} {lab}")
    return sorted(cands, key=len, reverse=True)


def parse_chart(text: str, asm: Path) -> dict:
    """把 --chart 输出解析成 {rows: [[IF,ID,EX,MEM,WB]×cycles], summary}。

    列格式 = 每格 `%-9s` + 单空格；超宽（如 "beq nextpass"）会把该行后续列右推——
    用"模拟器宽度模型"复原阶段号（bubble/loop 两套全量验证 0 误判）。
    """
    cands = _candidates_from_asm(asm)
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip().startswith("cycle"))
    rows = []
    for line in lines[start + 1:]:
        m = re.match(r"\s*\d+\s", line)
        if not m:
            break
        body = line[m.end() - 1:]
        base = 8 - (m.end() - 1)
        stages = [""] * 5
        sim, pos, ok = base, 0, True
        while pos < len(body):
            while pos < len(body) and body[pos] == " ":
                pos += 1
            if pos >= len(body):
                break
            token = None
            for cand in cands:
                if body.startswith(cand, pos) and (pos + len(cand) >= len(body)
                                                   or body[pos + len(cand)] == " "):
                    token = cand
                    break
            if token is None:
                ok = False
                break
            while sim < pos:
                sim += 10
            stage = (sim - base) // 10
            if sim != pos or not (0 <= stage <= 4) or stages[stage]:
                ok = False
                break
            stages[stage] = token
            sim += max(len(token), 9) + 1
            pos += len(token)
        if not ok:
            raise SystemExit(f"时空图解析失败：{line!r}")
        rows.append(stages)
    summary = next((l.strip() for l in lines if l.startswith("总共")), "")
    cycles = next((l.strip() for l in lines if l.startswith("程序：")), "")
    return {"rows": rows, "summary": summary, "caption": cycles}


def _parse_demo(text: str) -> dict:
    out = {"raw": text.strip()}
    m = re.search(r"单周期：(\d+) 周期", text)
    out["single_cycles"] = int(m.group(1)) if m else 0
    m = re.search(r"流水线：(\d+) 周期（停顿 (\d+)、冲刷 (\d+)）", text)
    if m:
        out["pipeline_cycles"], out["stalls"], out["flushes"] = map(int, m.groups())
    m = re.search(r"排序结果：mem\[0\.\.4\] = ([\d ]+)", text)
    out["sorted"] = m.group(1).strip() if m else ""
    m = re.search(r"程序：(.+?)（(\d+) 条指令）", text)
    if m:
        out["program"], out["instructions"] = m.group(1), int(m.group(2))
    out["consistent"] = "双模型寄存器一致：是" in text
    return out


def collect() -> dict:
    _ensure_built()
    selftest = _run([str(BUILD / "tests.exe")])
    m = re.search(r"结果：(\d+) 项断言，(\d+) 项失败", selftest)
    assertions, failures = (int(m.group(1)), int(m.group(2))) if m else (0, -1)
    demo_bubble = _parse_demo(_run([str(BUILD / "cpu-sim.exe"), "programs/bubble.asm"]))
    demo_loop = _parse_demo(_run([str(BUILD / "cpu-sim.exe"), "programs/loop.asm"]))
    chart_bubble = parse_chart(_run([str(BUILD / "cpu-sim.exe"), "--chart", "programs/bubble.asm"]),
                               ROOT / "programs" / "bubble.asm")
    chart_loop = parse_chart(_run([str(BUILD / "cpu-sim.exe"), "--chart", "programs/loop.asm"]),
                             ROOT / "programs" / "loop.asm")
    facts = [
        ["自测断言", f"{assertions} 项、失败 {failures}（ISA/汇编器/单周期性质/双模型逐字节一致）"],
        ["bubble.asm", f"{demo_bubble.get('instructions', '?')} 条指令：单周期 {demo_bubble['single_cycles']} 周期"
                    f" vs 流水线 {demo_bubble['pipeline_cycles']} 周期（停顿 {demo_bubble['stalls']}）"],
        ["双模型一致", f"寄存器逐字节一致：{'是' if demo_bubble['consistent'] else '否！'}"
                    f"；排序结果 mem[0..4] = {demo_bubble['sorted']}"],
        ["loop.asm 流水线", f"{demo_loop['pipeline_cycles']} 周期（停顿 {demo_loop['stalls']}、冲刷 {demo_loop['flushes']}）"],
        ["时空图", f"bubble {len(chart_bubble['rows'])} 行 / loop {len(chart_loop['rows'])} 行，逐格解析 0 误判"],
    ]
    return {"facts": facts, "assertions": assertions, "failures": failures,
            "bubble": demo_bubble, "loop": demo_loop,
            "chart_bubble": chart_bubble, "chart_loop": chart_loop}


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
.scroll{max-height:30rem;overflow:auto;border:1px solid var(--line);border-radius:8px;margin-top:.5rem}
table.st{width:100%;border-collapse:collapse;font:12.5px/1.4 ui-monospace,Consolas,monospace}
table.st th{position:sticky;top:0;background:#f0f2f6;color:var(--muted);font-weight:600;text-align:left;padding:.25rem .45rem;border-bottom:1px solid var(--line)}
table.st td{padding:.12rem .45rem;border-bottom:1px solid #eef0f4;white-space:pre}
table.st td.cyc{color:var(--muted);text-align:right}
td.s{background:#fff4d6;color:#8a5a00;font-weight:700;text-align:center}
td.f{background:#fdecec;color:#a41f1f;font-weight:700;text-align:center}
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


def _chart_table(chart: dict) -> str:
    head = ("<tr><th>周期</th><th>IF</th><th>ID</th><th>EX</th><th>MEM</th><th>WB</th></tr>")
    rows = []
    for i, cells in enumerate(chart["rows"], start=1):
        tds = [f'<td class="cyc">{i}</td>']
        for cell in cells:
            cls = ' class="s"' if cell == "S" else (' class="f"' if cell == "F" else "")
            tds.append(f"<td{cls}>{cell or '·'}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<div class="scroll"><table class="st">{head}{"".join(rows)}</table></div>')


def render(payload: dict) -> str:
    cards = "".join(f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in payload["facts"])
    b = payload["bubble"]
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B5-cpu-sim · 单周期 vs 五级流水线（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B5-cpu-sim">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B4-algebra-rsa/web/showcase.html">B4</a>　·　下一件 <a href="../../../projects/B6-asm-lab/web/showcase.html">B6</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B5-cpu-sim · 单周期 CPU + 五级流水线</h1>
<p class="note">数字设计与计算机原理 · 手写 ISA/汇编器/两种执行模型：单周期与五级流水线跑同一份程序，
最终状态必须逐字节一致；流水线的每个周期、每个停顿（S）与冲刷（F）都在时空图里。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="dual">双模型对拍（bubble.asm）</button>
    <button class="chip" data-tab="chart-b">时空图 · bubble（{len(payload["chart_bubble"]["rows"])} 周期）</button>
    <button class="chip" data-tab="chart-l">时空图 · loop（{len(payload["chart_loop"]["rows"])} 周期）</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="dual">
      <p>程序 {b.get("program", "")}（{b.get("instructions", "?")} 条指令）。
      <span class="badge {"ok" if b["consistent"] else "bad"}">双模型寄存器逐字节一致：{"是" if b["consistent"] else "否"}</span>
      <span class="badge warn">流水线 {b["pipeline_cycles"]} 周期 vs 单周期 {b["single_cycles"]} 周期（停顿 {b["stalls"]}、冲刷 {b["flushes"]}）</span></p>
      <p>排序结果 <code>mem[0..4] = {b["sorted"]}</code>（两模型跑的是同一段汇编）。</p>
      <pre class="code wrap">{b["raw"]}</pre>
    </div>
    <div data-pane-id="chart-b" hidden>
      <p class="note">{payload["chart_bubble"]["caption"]}——{payload["chart_bubble"]["summary"]}
      （S = 停顿，琥珀色；F = 冲刷，红色；·= 该周期该段为空）</p>
      {_chart_table(payload["chart_bubble"])}
    </div>
    <div data-pane-id="chart-l" hidden>
      <p class="note">{payload["chart_loop"]["caption"]}——{payload["chart_loop"]["summary"]}</p>
      {_chart_table(payload["chart_loop"])}
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：三步（自测 → 双模型对拍 → 时空图）。</li>
    <li><kbd>build\\cpu-sim.exe --chart programs\\loop.asm</kbd>：给你自己的程序画时空图。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 build\\cpu-sim.exe 现算（不含任何计时数字——
  周期数才是确定性的）。观感与顺手程度归你实跑验收。</p>
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
    ap = argparse.ArgumentParser(description="B5 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（自测 {payload['assertions']} 断言 + 两份时空图真跑现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（双模型对拍 + bubble/loop 时空图）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
