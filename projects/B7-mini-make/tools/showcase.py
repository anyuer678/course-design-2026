"""tools/showcase.py —— B7 展示页生成器（Makefile 子集 + 增量构建 + 日志聚合）。口径：showcase/SPEC.md。

数据全部现算，来源是真跑出来的 Python 产物（无计时数字）：

- 自测方法数：tests/ 里 `def test_` 静态现数（不跑 discover——跑 discover 会在
  "展示页测试里再调 collect"时递归）；
- **增量构建回放**：clean → 全量构建 → 再跑（up to date）→ 触碰源文件 → 重建 → run → clean，
  全流程现场重放（输出确定，两遍逐字一致）；
- 构建日志聚合（src/logstat.py）：按消息模板归并 sample_build.log；
- 依赖图与命令：从 demo/Makefile 真解析。

页面写 `web/showcase.html`；`--check` 重算比对（不写盘），过期即红。
"""
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "showcase.html"
MAKEFILE = ROOT / "demo" / "Makefile"
TESTS = ROOT / "tests"


def _run(args, stdin_text=None) -> str:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"  # 子进程（mm.py/logstat.py）的 stdout 必须是 UTF-8，否则随控制台代码页变
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, input=stdin_text,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(map(str, args))} 退出码 {proc.returncode}：\n"
                         f"{(proc.stderr or '')[-500:]}")
    return proc.stdout


def _parse_makefile(text: str) -> list:
    """把 demo/Makefile 解析成 [{target, deps, commands}]（教学子集：target: deps + TAB 命令行）。

    跳过 `.PHONY` 这类点开头特殊目标——它不是可构建目标，混进"共 N 个目标"会误导。
    """
    targets, current = [], None
    for line in text.splitlines():
        if line.startswith("\t") and current is not None:
            current["commands"].append(line.strip())
            continue
        m = re.match(r"^([\w./-]+)\s*:\s*(.*)$", line)
        if m and not m.group(1).startswith("."):
            current = {"target": m.group(1),
                       "deps": [d for d in m.group(2).split() if d],
                       "commands": []}
            targets.append(current)
        elif m:
            current = None
    return targets


def _replay_incremental() -> str:
    """按 run.bat 的同一序列重放一次增量构建（跑完清理，仓库状态复原）。"""
    mm = [sys.executable, "src/mm.py", "-f", "demo/Makefile"]
    blocks = []

    def step(title: str, args) -> None:
        blocks.append(f"=== {title} ===\n" + _run(args).rstrip())

    step("1) clean —— 先清干净", mm + ["clean"])
    step("2) 全量构建", mm)
    step("3) 原样再跑一次 —— 期望全部跳过（up to date）", mm)
    os.utime(ROOT / "demo" / "src" / "greet.cpp", (time.time(), time.time()))
    step("4) 触碰 src/greet.cpp 的 mtime（模拟改了源码）后重建", mm)
    step("5) run —— 跑起来", mm + ["run"])
    step("6) 收尾 clean —— 仓库状态复原", mm + ["clean"])
    return "\n\n".join(blocks)


def collect() -> dict:
    # def test_ 静态现数（不跑 discover）：跑 discover 会在"本文件的测试里再调 collect"时递归
    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    transcript = _replay_incremental()
    logstat = _run([sys.executable, "src/logstat.py", "demo/sample_build.log"])
    counts = {}
    for name in ("error", "warning", "note"):
        mm = re.search(rf"^\s*{name}\s+(\d+)$", logstat, re.M)
        if mm:
            counts[name] = int(mm.group(1))
    top = []
    started = False
    for line in logstat.splitlines():
        if "顶部" in line:
            started = True
            continue
        if started and re.match(r"^\s+\d+ × ", line):
            top.append(line.strip())
    makefile_source = MAKEFILE.read_text(encoding="utf-8").rstrip()
    targets = _parse_makefile(makefile_source)
    up_to_date = transcript.count("已是最新")
    facts = [
        ["自测", f"{method_count} 个测试方法（解析/排序/增量/构建/日志聚合 + 展示页自测）"],
        ["增量构建", f"clean → 构建 → 再跑（{up_to_date} 处「已是最新」判定）→ 触碰源文件 → 重建 → run"],
        ["构建日志聚合", f"{sum(counts.values())} 条诊断：{'/'.join(f'{k} {v}' for k, v in counts.items())}，"
                    f"归并出 {len(top)} 类模板"],
        ["依赖图", f"demo/Makefile 共 {len(targets)} 个目标（{'、'.join(t['target'] for t in targets)}）"],
    ]
    return {"facts": facts, "method_count": method_count, "transcript": transcript,
            "counts": counts, "top": top, "targets": targets,
            "makefile_source": makefile_source}


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
.badge.ok{color:var(--ok);border-color:var(--ok)}
table.plain{border-collapse:collapse;font-size:.9rem;margin:.5rem 0}
table.plain th,table.plain td{border:1px solid var(--line);padding:.3rem .7rem;text-align:left}
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
    target_rows = "".join(
        f'<tr><td>{t["target"]}</td><td>{" ".join(t["deps"]) or "—"}</td>'
        f'<td>{"；".join(t["commands"])}</td></tr>' for t in payload["targets"])
    top_rows = "".join(f"<li>{html.escape(line)}</li>" for line in payload["top"])
    counts = "、".join(f"{k} {v}" for k, v in payload["counts"].items())
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B7-mini-make · 增量构建（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B7-mini-make">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B2-datastruct-lab/web/showcase.html">B2</a>　·　下一件 <a href="../../../projects/B8-mini-shell/web/showcase.html">B8</a></span>（本页双击即看，零网络依赖）</p>
<h1>B7-mini-make · Makefile 子集 + 增量构建</h1>
<p class="note">软件开发技术基础 · 手写 Makefile 子集：依赖图、环检测、mtime 增量、-j 分批并发、
失败传播；外加一个"按消息模板聚合"的构建日志统计器。下面整段构建回放是刚才现场跑的。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="replay">增量构建回放</button>
    <button class="chip" data-tab="graph">依赖图 &amp; Makefile</button>
    <button class="chip" data-tab="logs">构建日志聚合</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="replay">
      <p class="note">完整序列（先清干净）：<b>clean → 全量构建 → 再跑一次（应全部 up to date）
      → 触碰源文件 → 只重建该链 → run → 收尾 clean</b>。每一步打印执行了哪些命令、跳过了哪些目标。</p>
      <pre class="code wrap">{html.escape(payload["transcript"])}</pre>
    </div>
    <div data-pane-id="graph" hidden>
      <p class="note">依赖图来自 demo/Makefile 真解析（目标 : 依赖 + 命令行）：</p>
      <table class="plain"><tr><th>目标</th><th>依赖</th><th>命令</th></tr>{target_rows}</table>
      <p class="note">Makefile 原文：</p>
      <pre class="code wrap">{html.escape(payload["makefile_source"])}</pre>
    </div>
    <div data-pane-id="logs" hidden>
      <p class="note">构建日志聚合（按消息模板归并，数字现算）：{counts}。</p>
      <p class="note">顶部模板：</p>
      <ul class="plain-list">{top_rows}</ul>
      <p class="note">同一模板的报错会在不同行号/列号上重复出现——聚合后计数，
      这是读大构建日志的第一步。</p>
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：四步（单测 → 增量构建回放 → 日志聚合 → 展示页新鲜度）。</li>
    <li><kbd>python src\\mm.py -f demo\\Makefile -j 4 run</kbd>：并行 + 目标名一起试。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 mm.py / logstat.py 现算（不含计时数字）。
  观感归你实跑验收。</p>
</section>

<footer>
  <p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。</p>
</footer>
</main>
<script>{TOGGLE_JS}</script>
</body>
</html>
"""


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B7 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（增量构建回放 + 日志聚合 + 依赖图，全部现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（构建回放/依赖图/日志聚合）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
