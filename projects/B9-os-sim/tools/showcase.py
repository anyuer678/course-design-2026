"""tools/showcase.py —— B9 展示页生成器（操作系统模拟器）。口径：showcase/SPEC.md。

数据全部现算，来源是真跑出来的 C++ 产物（无计时数字）：

- 自测（tests.exe）：183 项断言（调度手算对拍 / 页面置换教科书数值与 Belady 异常 /
  银行家 / FAT 边界 / 生产者-消费者逐条不丢不重）；
- 演示（os-sim.exe）：调度五套的等待/周转与**甘特图**（渲染成时间轴色块）、
  页面置换缺页表（3/4 帧 × 四种算法）、银行家三幕、FAT 写删复满盘、生产者-消费者计数。

生成前若 build 缺可执行文件会先按 run.bat 的同一命令（mingw32-make）重建。
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


def _ensure_built():
    if (BUILD / "os-sim.exe").is_file() and (BUILD / "tests.exe").is_file():
        return
    proc = subprocess.run(["mingw32-make"], cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not (BUILD / "os-sim.exe").is_file():
        raise SystemExit(f"构建失败（先跑 run.bat 检查工具链）：\n{(proc.stderr or proc.stdout)[-800:]}")


def _run(args) -> str:
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(map(str, args))} 退出码 {proc.returncode}：\n"
                         f"{(proc.stderr or '')[-500:]}")
    return proc.stdout


def _block(text: str, header: str) -> list:
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if header in l), None)
    if start is None:
        return []
    out = []
    for line in lines[start + 1:]:
        if line.startswith("==") or not line.startswith("  "):
            break
        if line.strip():
            out.append(line.rstrip())
    return out


def parse_sched(text: str) -> list:
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*(FCFS|SJF|优先级|RR q=\d+)\s+等待 ([\d.]+)\s+周转 ([\d.]+)\s+甘特图：(.*)$", line)
        if not m:
            continue
        gantt = [(p, int(a), int(b)) for p, a, b in
                 re.findall(r"(P\d)\[(\d+),(\d+)\]", m.group(4))]
        out.append({"name": m.group(1), "wait": float(m.group(2)),
                    "turnaround": float(m.group(3)), "gantt": gantt})
    return out


def parse_paging(text: str) -> dict:
    rows = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d)\s*\|\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", line)
        if m:
            rows.append({"frames": int(m.group(1)),
                         "faults": {"FIFO": int(m.group(2)), "LRU": int(m.group(3)),
                                    "Clock": int(m.group(4)), "OPT": int(m.group(5))}})
    belady = next((l.strip() for l in text.splitlines() if "Belady" in l), "")
    note = next((l.strip() for l in text.splitlines() if l.strip().startswith("注意")), "")
    ref = next((l.strip() for l in text.splitlines() if "参考串" in l), "")
    return {"rows": rows, "belady": belady, "note": note, "ref": ref}


def collect() -> dict:
    _ensure_built()
    selftest = _run([str(BUILD / "tests.exe")])
    m = re.search(r"结果：(\d+) 项断言，(\d+) 项失败", selftest)
    assertions, failures = (int(m.group(1)), int(m.group(2))) if m else (0, -1)
    demo = _run([str(BUILD / "os-sim.exe")])
    sched = parse_sched(demo)
    paging = parse_paging(demo)
    banker = _block(demo, "银行家算法")
    fat = _block(demo, "FAT 文件系统")
    pc = _block(demo, "生产者-消费者")
    facts = [
        ["自测断言", f"{assertions} 项、失败 {failures}（调度/置换/银行家/FAT/生产者-消费者）"],
        ["调度对照", f"{len(sched)} 套算法的等待/周转与甘特图（同一教材例子）"],
        ["Belady 异常", paging["belady"]],
        ["银行家三幕", f"初始安全序列 + {len(banker) - 1} 次请求裁决（批准/资源不足/不安全回滚）"],
        ["生产者-消费者", pc[-1] if pc else ""],
    ]
    return {"facts": facts, "assertions": assertions, "failures": failures,
            "sched": sched, "paging": paging, "banker": banker, "fat": fat, "pc": pc}


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
.badge{display:inline-block;font-size:.8rem;padding:.08rem .55rem;border-radius:999px;border:1px solid var(--line);color:var(--muted);margin-right:.3rem}
.badge.ok{color:var(--ok);border-color:var(--ok)}.badge.warn{color:var(--warn);border-color:var(--warn)}
table.plain{border-collapse:collapse;font-size:.9rem;margin:.5rem 0}
table.plain th,table.plain td{border:1px solid var(--line);padding:.3rem .7rem;text-align:left}
.grow{display:flex;align-items:center;gap:.6rem;margin:.4rem 0}
.grow .lbl{width:5.5rem;font-size:.88rem;color:var(--muted);flex:none;text-align:right}
.grow .stat{flex:none;font-size:.82rem;color:var(--muted);width:14rem}
.tl{position:relative;height:1.35rem;background:#eef0f6;border-radius:4px;flex:1;min-width:20rem}
.tl i{position:absolute;top:0;bottom:0;color:#fff;font-size:.68rem;line-height:1.35rem;text-align:center;overflow:hidden;font-style:normal}
.tl i.tight{font-size:.6rem}
.p1{background:#2563eb}.p2{background:#0d9488}.p3{background:#d97706}.p4{background:#9333ea}
.axis{display:flex;margin:.2rem 0 0;color:var(--muted);font-size:.72rem}
.axis .lbl{width:5.5rem;flex:none}
.axis .tl{background:none;height:.9rem;border-top:1px solid var(--line);border-radius:0}
.axis .tl span{position:absolute;transform:translateX(-50%)}
ul.plain-list{margin:.3rem 0;padding-left:1.2rem}
ul.plain-list li{margin:.15rem 0}
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


def _gantt(payload: dict) -> str:
    span = max((b for algo in payload["sched"] for _, _, b in algo["gantt"]), default=1)
    rows = []
    for algo in payload["sched"]:
        segs = []
        for proc, a, b in algo["gantt"]:
            left = a / span * 100
            width = (b - a) / span * 100
            cls = f"p{proc[1]}"
            tight = " tight" if width < 4 else ""
            segs.append(f'<i class="{cls}{tight}" style="left:{left:.4f}%;width:{width:.4f}%" '
                        f'title="{proc}[{a},{b}]">{proc}</i>')
        rows.append(
            f'<div class="grow"><span class="lbl">{algo["name"]}</span>'
            f'<span class="tl">{"".join(segs)}</span>'
            f'<span class="stat">等待 {algo["wait"]:.2f} / 周转 {algo["turnaround"]:.2f}</span></div>')
    ticks = "".join(f'<span style="left:{t / span * 100:.4f}%">{t}</span>'
                    for t in range(0, span + 1, 4))
    rows.append(f'<div class="axis"><span class="lbl">时间</span>'
                f'<span class="tl">{ticks}</span><span class="stat"></span></div>')
    return "".join(rows)


def render(payload: dict) -> str:
    cards = "".join(f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in payload["facts"])
    pg = payload["paging"]
    pg_rows = "".join(
        f'<tr><td>{r["frames"]}</td><td>{r["faults"]["FIFO"]}</td><td>{r["faults"]["LRU"]}</td>'
        f'<td>{r["faults"]["Clock"]}</td><td>{r["faults"]["OPT"]}</td></tr>'
        for r in pg["rows"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B9-os-sim · 操作系统模拟器（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B9-os-sim">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B6-asm-lab/web/showcase.html">B6</a>　·　下一件 <a href="../../../projects/B1-cpp-ministl/web/showcase.html">B1</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B9-os-sim · 调度 / 置换 / 银行家 / FAT / 生产者-消费者</h1>
<p class="note">操作系统原理 · 五个模块都对着教科书例子与手算数值自测：
调度五套算法画成同一条时间轴；页面置换把 Belady 异常当场示众；银行家三幕含"不安全就回滚"；
FAT 演示删除后块复用与满盘回滚；生产者-消费者是 4 线程 10 万条消息的逐条对账。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="sched">调度 · 甘特图</button>
    <button class="chip" data-tab="paging">页面置换</button>
    <button class="chip" data-tab="banker">银行家算法</button>
    <button class="chip" data-tab="fat">FAT 文件系统</button>
    <button class="chip" data-tab="pc">生产者-消费者</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="sched">
      <p class="note">同一批作业（教材例子），五种调度策略的甘特图与等待/周转时间：</p>
      {_gantt(payload)}
      <p class="note">颜色 = 进程；RR(q=2) 的入队约定是「新到达先入队、到期回队尾」，
      q 极大时退化为 FCFS（两个等待时间相同）。</p>
    </div>
    <div data-pane-id="paging" hidden>
      <p class="note">{pg["ref"]}；缺页次数表：</p>
      <table class="plain"><tr><th>帧数</th><th>FIFO</th><th>LRU</th><th>Clock</th><th>OPT</th></tr>{pg_rows}</table>
      <p class="note">{pg["belady"]}</p>
      <p class="note">{pg["note"]}</p>
    </div>
    <div data-pane-id="banker" hidden>
      <ul class="plain-list">{"".join(f"<li>{line}</li>" for line in payload["banker"])}</ul>
      <p class="note">"不安全就拒绝并回滚"是重点：拒绝之后的 Available 必须回到请求前的值。</p>
    </div>
    <div data-pane-id="fat" hidden>
      <ul class="plain-list">{"".join(f"<li>{line}</li>" for line in payload["fat"])}</ul>
      <p class="note">分配失败既不泄漏块也不破坏旧内容——测试里专门有满盘/空文件/失败回滚的边界断言。</p>
    </div>
    <div data-pane-id="pc" hidden>
      <ul class="plain-list">{"".join(f"<li>{line}</li>" for line in payload["pc"])}</ul>
      <p class="note">4 线程（2 生产者 + 2 消费者）10 万条消息逐条比对：不丢、不重、不错值。</p>
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：三步（构建 → 183 项断言自测 → 全模块演示）。</li>
    <li><kbd>build\\os-sim.exe sched</kbd>：单独看调度模块（同理 paging / banker / fat / pc）。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 build\\os-sim.exe 现算（不含计时数字）。
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
    ap = argparse.ArgumentParser(description="B9 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（自测 {payload['assertions']} 断言 + 五模块演示真跑现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（调度甘特图/置换表/银行家/FAT/生产者-消费者）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
