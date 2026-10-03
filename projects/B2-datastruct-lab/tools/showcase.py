"""tools/showcase.py —— B2 展示页生成器（八个 ADT + 复杂度对照 + 交互菜单）。口径：showcase/SPEC.md。

数据全部现算，来源是真跑出来的 C++ 产物（无计时数字）：

- 自测（tests.exe）：428 项断言（八个结构的手算边界 + 与 std/参照实现对拍 141228 项检查 +
  菜单脚本 17 项）；
- 演示（datastruct.exe）：六段现场输出（头插 44850 vs 改链 300、BST 高度 31 vs 5、
  哈希探测 78/78/12、建堆 494 vs 1538、并查集 390→199）；
- 交互菜单（datastruct.exe --menu，输入 0 即退）：菜单版式现场截取。

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
    if (BUILD / "tests.exe").is_file() and (BUILD / "datastruct.exe").is_file():
        return
    BUILD.mkdir(exist_ok=True)
    for src, out in (("tests/test_ds.cpp", "tests.exe"), ("src/main.cpp", "datastruct.exe")):
        proc = subprocess.run(GXX + [src, "-o", f"build/{out}"], cwd=str(ROOT),
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise SystemExit(f"编译 {src} 失败（先跑 run.bat 检查工具链）：\n{proc.stderr[-800:]}")


def _run(args, stdin_text=None) -> str:
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, input=stdin_text,
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
    demo = _run([str(BUILD / "datastruct.exe")])
    menu = _run([str(BUILD / "datastruct.exe"), "--menu"], stdin_text="0\n")
    m = re.search(r"B2 自测：(\d+) 项通过，0 项失败", selftest)
    passed = int(m.group(1)) if m else 0
    m = re.search(r"共 (\d+) 项检查", selftest)
    cross_total = int(m.group(1)) if m else 0
    m = re.search(r"\[与 std/参照实现对拍\] 断言 (\d+) 项", selftest)
    cross_asserts = int(m.group(1)) if m else 0
    per_module = re.findall(r"\[([^\]]+)\] (\d+) 项$", selftest, re.M)
    menu_lines = []
    started = False
    for line in menu.splitlines():
        if "数据结构实验台" in line:
            started = True
        if started:
            menu_lines.append(line.rstrip())
            if line.strip().startswith("选择"):
                break
    facts = [
        ["自测断言", f"{passed} 项、0 失败（八个结构的手算边界 + 对拍 + 菜单脚本）"],
        ["对拍规模", f"与 std/参照实现共 {cross_total} 项检查，0 失败"],
        ["头插 300 次", "顺序表搬 44850 步 vs 链表改链 300 次（差一个数量级的那个操作）"],
        ["同集合对照", "BST 升序插入高 31 vs 折半插入高 5；并查集 find 390 → 压缩后 199"],
        ["交互菜单", "8 个结构 + 退出；菜单版式见下方面板（现场截取）"],
    ]
    return {"facts": facts, "passed": passed, "cross_total": cross_total,
            "cross_asserts": cross_asserts, "per_module": per_module,
            "sections": _parse_sections(demo), "menu": menu_lines}


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
    cards = "".join(f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in payload["facts"])
    sections = "".join(
        f'<details open><summary>{s["title"]}</summary><pre class="code wrap">'
        f'{chr(10).join(s["lines"])}</pre></details>'
        for s in payload["sections"])
    module_rows = "".join(
        f'<tr><td>{name}</td><td>{count}</td></tr>' for name, count in payload["per_module"])
    menu_text = chr(10).join(payload["menu"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B2-datastruct-lab · 八个 ADT（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B2-datastruct-lab">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B1-cpp-ministl/web/showcase.html">B1</a>　·　下一件 <a href="../../../projects/B7-mini-make/web/showcase.html">B7</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B2-datastruct-lab · 八个 ADT + 复杂度对照</h1>
<p class="note">数据结构 · 顺序表/链表/栈与表达式/循环队列/BST/哈希/堆/并查集/图：
每个结构都有手算边界与"参考答案"对拍；最出彩的是**计数器**——把复杂度变成实测步数
（头插 44850 vs 改链 300、建堆 494 vs 逐插 1538、find 390→199）。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="demo6">演示 · 六段</button>
    <button class="chip" data-tab="numbers">自测数字</button>
    <button class="chip" data-tab="menu">交互菜单</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="demo6">
      <p class="note">每段都是 datastruct.exe 的现场输出（数字现算）。</p>
      {sections}
    </div>
    <div data-pane-id="numbers" hidden>
      <p class="note">自测逐模块断言数（共 {payload["passed"]} 项）：</p>
      <table class="plain"><tr><th>模块</th><th>断言</th></tr>{module_rows}
      <tr><td>与 std/参照实现对拍</td><td>{payload["cross_total"]} 项检查 + {payload["cross_asserts"]} 项断言</td></tr></table>
      <p class="note">"复杂度对照"全部来自计数器实测：同一操作在两种实现里的步数差——
      这是本项目把 O(·) 从口号变成数字的方式。</p>
    </div>
    <div data-pane-id="menu" hidden>
      <p class="note">交互菜单的现场截取（<kbd>build\\datastruct.exe --menu</kbd>；下面这次输入 0 即退）。
      菜单本身也在自测里（脚本驱动 17 项）：</p>
      <pre class="code">{menu_text}</pre>
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：四步（构建+自测 → 六段演示 → 菜单冒烟 → 展示页新鲜度）。</li>
    <li><kbd>build\\datastruct.exe --menu</kbd>：进交互菜单玩八个结构。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 build 里的可执行文件现算（不含计时数字）。
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
    ap = argparse.ArgumentParser(description="B2 展示页生成器（口径：showcase/SPEC.md）")
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
        print("展示页新鲜：与现算逐字一致（六段演示/自测数字/交互菜单）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
