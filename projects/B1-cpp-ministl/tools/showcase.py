"""tools/showcase.py —— B1 展示页生成器（手写容器 + 与 std 对拍）。口径：showcase/SPEC.md。

数据全部现算，来源是真跑出来的 C++ 产物（无计时数字）：

- 自测（tests.exe）：268 项断言（vector/list/string 边界、RAII、待办回读、
  与 std 容器三类随机操作序列对拍 253086 项检查）；
- 演示（ministl-demo.exe）：五段现场输出（增长曲线 4→8→16、迭代器稳定性、
  UTF-8 按字节记账、待办存盘回读对账、三类对拍计数 14907/22960/26439）。

生成前若 build 缺可执行文件会按 run.bat 的同一命令行重建。
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
    if (BUILD / "tests.exe").is_file() and (BUILD / "ministl-demo.exe").is_file():
        return
    BUILD.mkdir(exist_ok=True)
    for src, out in (("tests/test_ministl.cpp", "tests.exe"), ("src/main.cpp", "ministl-demo.exe")):
        proc = subprocess.run(GXX + [src, "-o", f"build/{out}"], cwd=str(ROOT),
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise SystemExit(f"编译 {src} 失败（先跑 run.bat 检查工具链）：\n{proc.stderr[-800:]}")


def _run(args) -> str:
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(map(str, args))} 退出码 {proc.returncode}：\n"
                         f"{(proc.stderr or '')[-500:]}")
    return proc.stdout


def _parse_sections(text: str) -> list:
    sections, current = [], None
    for line in text.splitlines():
        if re.match(r"^\s*\d\) ", line):
            current = {"title": line.strip(), "lines": []}
            sections.append(current)
        elif set(line.strip()) == {"="} and line.strip():
            continue
        elif current is not None and line.strip():
            current["lines"].append(line.rstrip())
    return [s for s in sections if s["lines"]]


def collect() -> dict:
    _ensure_built()
    selftest = _run([str(BUILD / "tests.exe")])
    demo = _run([str(BUILD / "ministl-demo.exe")])
    m = re.search(r"B1 自测：(\d+) 项通过，0 项失败", selftest)
    passed = int(m.group(1)) if m else 0
    m = re.search(r"共 (\d+) 项检查", selftest)
    cross_total = int(m.group(1)) if m else 0
    m = re.search(r"\[与 std 容器对拍\] 断言 (\d+) 项", selftest)
    cross_asserts = int(m.group(1)) if m else 0
    per_module = re.findall(r"\[([^\]]+)\] (\d+) 项$", selftest, re.M)
    cross_types = {}
    # 演示里三类行的对齐空格数不同（"list   对拍：" 三个空格）——用 \s+ 而不是单个空格
    for name, count in re.findall(r"(\w+)\s+对拍：\s*\d+ 种子 × \d+ 步 = (\d+) 项", demo):
        cross_types[name] = int(count)
    m = re.search(r"合计 (\d+) 项检查", demo)
    demo_total = int(m.group(1)) if m else 0
    facts = [
        ["自测断言", f"{passed} 项、0 失败（边界 + RAII + 待办回读 + 与 std 对拍）"],
        ["对拍规模", f"三类随机操作序列共 {cross_total} 项检查，0 失败（种子固定）"],
        ["演示对拍", f"五段演示里的三类对拍合计 {demo_total} 项（"
                  + "、".join(f"{k} {v}" for k, v in cross_types.items()) + "）"],
        ["增长曲线", "push_back 容量轨迹 4 → 8 → 16（翻倍增长，深拷贝互不影响）"],
    ]
    return {"facts": facts, "passed": passed, "cross_total": cross_total,
            "cross_asserts": cross_asserts, "per_module": per_module,
            "cross_types": cross_types, "demo_total": demo_total,
            "sections": _parse_sections(demo)}


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
details{margin:.4rem 0}
summary{cursor:pointer;color:var(--accent)}
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
    sections = "".join(
        f'<details open><summary>{s["title"]}</summary><pre class="code wrap">'
        f'{chr(10).join(s["lines"])}</pre></details>'
        for s in payload["sections"])
    module_rows = "".join(
        f'<tr><td>{name}</td><td>{count}</td></tr>' for name, count in payload["per_module"])
    type_rows = "".join(
        f'<tr><td>{name}</td><td>{count}</td></tr>' for name, count in payload["cross_types"].items())
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B1-cpp-ministl · 手写容器（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B1-cpp-ministl">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B9-os-sim/web/showcase.html">B9</a>　·　下一件 <a href="../../../projects/B2-datastruct-lab/web/showcase.html">B2</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B1-cpp-ministl · 手写 vector / list / string + 待办清单</h1>
<p class="note">计算机程序设计基础(C++) · 三个容器的边界、RAII、深拷贝与自追加语义逐个钉住，
每个容器都拿标准库当"参考答案"跑随机操作序列对拍；另有一个用这三个容器写的待办清单
（存盘 → 回读 → 逐字段对账）。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="demo5">演示 · 五段</button>
    <button class="chip" data-tab="numbers">对拍与边界数字</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="demo5">
      <p class="note">每段都是 ministl-demo.exe 的现场输出。</p>
      {sections}
    </div>
    <div data-pane-id="numbers" hidden>
      <p class="note">自测逐模块断言数（共 {payload["passed"]} 项）：</p>
      <table class="plain"><tr><th>模块</th><th>断言</th></tr>{module_rows}
      <tr><td>与 std 容器对拍（三类随机序列）</td><td>{payload["cross_total"]} 项检查 + {payload["cross_asserts"]} 项断言</td></tr></table>
      <p class="note">五段演示里的三类对拍计数（种子固定，可复跑）：</p>
      <table class="plain"><tr><th>容器</th><th>逐元素/逐次检查</th></tr>{type_rows}
      <tr><td>合计</td><td>{payload["demo_total"]}</td></tr></table>
      <p class="note">"改坏必须被抓"是这套测试的口径：边界 + 随机对拍 + 种子固定，
      失败可复现。</p>
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：三步（自测 → 五段演示 → 展示页新鲜度）。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 build 里的可执行文件现算（不含计时数字）。
  演示自带说明"无耗时输出，两遍运行应逐字相同"。观感归你实跑验收。</p>
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
    ap = argparse.ArgumentParser(description="B1 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（自测 {payload['passed']} 断言 + 对拍 {payload['cross_total']} 项检查真跑现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（自测/五段演示/三类对拍）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
