"""tools/showcase.py —— B13 展示页生成器（编译器透视）。口径：showcase/SPEC.md。

数据**全部现算**，来源是 programs/*.tiny 逐个过真流水线（tinylang.pipeline）：

- 6 个可运行样例：记号表（带行列）、AST（缩进版 + 单行 shape）、字节码反汇编与常量池、
  VM 与树遍历两条后端的输出对拍（本次重跑）、VM 前 12 步轨迹；
- 4 个故意报错的样例：编译期错误（语法 1 条 / 语义 4 条一次报全）与运行期错误
  （除零、第 101 层调用被深度上限 100 拒绝）的完整渲染。

页面写 `web/showcase.html`（单文件、双击即看、零网络依赖、JS 只做渲染不做业务）；
`--check` 重算比对（不写盘），过期即红。**别手改页面**——它是生成物。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tinylang.pipeline import build, run_both            # noqa: E402
from tinylang.reporting import format_ast, shape          # noqa: E402
from tinylang.vm import run_code                          # noqa: E402

OUT = ROOT / "web" / "showcase.html"
PROGRAMS = ROOT / "programs"
TESTS = ROOT / "tests"
TRACE_STEPS = 12


def _comment_of(source: str) -> str:
    for line in source.splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()
        if line.strip():
            break
    return ""


def _error_text(exc: Exception, source: str) -> str:
    render = getattr(exc, "render", None)
    return render(source) if callable(render) else str(exc)


def _collect_program(path: Path) -> dict:
    source = path.read_text(encoding="utf-8").rstrip("\n")
    built = build(source)
    entry = {"name": path.stem, "comment": _comment_of(source), "source": source,
             "stages": {}, "errors": []}
    if built.tokens:
        marks = [f"{t.kind:<8} {t.text!r:<18} 行{t.span.line} 列{t.span.col}"
                 for t in built.tokens]
        shown = marks[:60]
        if len(marks) > 60:
            shown.append(f"... 共 {len(marks)} 个记号（此处只列前 60）")
        entry["stages"]["tokens"] = "\n".join(shown)
    if built.program is not None:
        entry["stages"]["ast"] = format_ast(built.program)
        entry["stages"]["shape"] = shape(built.program)
    if built.code is not None:
        entry["stages"]["bytecode"] = built.code.disassemble()
        entry["stages"]["constants"] = repr(built.code.constants)
        entry["stages"]["locals"] = f"{built.code.locals_count} 个槽位（含函数帧局部）"
    if built.errors:
        entry["status"] = "compile_error"
        entry["errors"] = [built.report()]
        return entry
    try:
        vm, walk = run_both(source)
    except Exception as exc:                                    # noqa: BLE001 —— 故意的运行期错误
        entry["status"] = "runtime_error"
        entry["errors"] = [_error_text(exc, source)]
        return entry
    traced = run_code(built.code, trace_limit=TRACE_STEPS)
    entry["status"] = "ok"
    entry["stages"]["run"] = {
        "output": vm.output[:20] + (["..."] if len(vm.output) > 20 else []),
        "output_count": len(vm.output),
        "steps_vm": vm.steps,
        "steps_walk": walk.steps,
        "same": vm.output == walk.output,
        "trace": [step.render() for step in traced.trace],
    }
    return entry


def _test_method_count() -> int:
    total = 0
    for path in sorted(TESTS.glob("test_*.py")):
        total += len(re.findall(r"^\s*def test_", path.read_text(encoding="utf-8"), re.M))
    return total


def collect() -> dict:
    programs = [_collect_program(p) for p in sorted(PROGRAMS.glob("*.tiny"))]
    ok = [p for p in programs if p["status"] == "ok"]
    errors = [p for p in programs if p["status"] != "ok"]
    consistent = [p for p in ok if p["stages"]["run"]["same"]]
    depth = next(p for p in programs if p["name"] == "error_depth")
    depth_msg = " ".join(depth["errors"])
    assert "100" in depth_msg, "深度上限的报错里应含 100——口径变了要同步本页"
    facts = [
        ["样例程序", f"{len(programs)} 个（{len(ok)} 个可运行 + {len(errors)} 个故意报错）"],
        ["双后端对拍", f"{len(consistent)}/{len(ok)} 输出一致（VM vs 树遍历，本次重跑现算）"],
        ["测试方法", f"{_test_method_count()} 个（tests/ 里 def test_ 现数；run.bat 一趟是权威）"],
        ["调用深度上限", "100（error_depth.tiny 实测：第 101 层调用被拒绝）"],
        ["流水线", "词法 → 语法 → 语义 → 字节码 → 执行，每段都可点开看"],
    ]
    return {"facts": facts, "programs": programs, "trace_steps": TRACE_STEPS}


# ------------------------------------------------------------------ 渲染

STYLE = """
:root{--ink:#16181d;--muted:#5f6773;--line:#d5d9e0;--card:#fff;--bg:#f7f8fa;--accent:#1d4ed8;--ok:#14603a;--bad:#a41f1f;--warn:#8a5a00}
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
.chip .st{font-size:.75rem;color:var(--muted);margin-left:.3rem}
.chip.active .st{color:#dbe4ff}
.tabs{display:flex;gap:.35rem;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:.15rem}
.tab{font:inherit;font-size:.88rem;padding:.25rem .65rem;border:1px solid transparent;border-radius:6px 6px 0 0;background:none;cursor:pointer;color:var(--muted)}
.tab.active{color:var(--accent);border-color:var(--line);border-bottom-color:#fff;background:#fff;font-weight:600}
pre.code{margin:.6rem 0 0;padding:.8rem .9rem;background:#0f1115;color:#e6e9ef;border-radius:8px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace}
pre.code.wrap{white-space:pre-wrap;word-break:break-word}
.badge{display:inline-block;font-size:.8rem;padding:.08rem .55rem;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.badge.ok{color:var(--ok);border-color:var(--ok)}.badge.bad{color:var(--bad);border-color:var(--bad)}.badge.warn{color:var(--warn);border-color:var(--warn)}
.trace li{margin:.12rem 0;font:12.5px/1.5 ui-monospace,Consolas,monospace;color:#333}
ol,ul{padding-left:1.3rem}
.errblock{margin:.5rem 0}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}
"""

APP_JS = """
(function(){
  "use strict";
  var TABS = [["source","源码"],["tokens","记号"],["ast","AST"],["bytecode","字节码"],["run","运行"],["errors","报错"]];
  var state = {name: DATA.programs[0].name, tab: "source"};
  var chipBox = document.getElementById("chips");
  var tabBox = document.getElementById("tabs");
  var panel = document.getElementById("panel");
  var subtitle = document.getElementById("subtitle");
  var badge = document.getElementById("status-badge");

  function el(tag, cls, text){
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function pre(text, wrap){
    var node = el("pre", "code" + (wrap ? " wrap" : ""));
    node.textContent = text;
    return node;
  }
  function current(){
    for (var i = 0; i < DATA.programs.length; i++){
      if (DATA.programs[i].name === state.name) return DATA.programs[i];
    }
    return DATA.programs[0];
  }
  function has(p, key){ return p.stages[key] !== undefined; }
  function available(p){
    return TABS.filter(function(t){
      if (t[0] === "source") return true;
      if (t[0] === "errors") return p.errors.length > 0;
      return has(p, t[0]);
    });
  }
  function label(p){
    if (p.status === "ok") return ["运行通过", "ok"];
    if (p.status === "compile_error") return ["编译报错（故意）", "bad"];
    return ["运行期报错（故意）", "warn"];
  }
  function renderChips(){
    chipBox.replaceChildren();
    DATA.programs.forEach(function(p){
      var chip = el("button", "chip" + (p.name === state.name ? " active" : ""));
      chip.type = "button";
      chip.append(el("span", "", p.name), el("span", "st", label(p)[0]));
      chip.addEventListener("click", function(){ select(p.name); });
      chipBox.append(chip);
    });
  }
  function renderTabs(p){
    tabBox.replaceChildren();
    available(p).forEach(function(t){
      var tab = el("button", "tab" + (t[0] === state.tab ? " active" : ""), t[1]);
      tab.type = "button";
      tab.addEventListener("click", function(){ state.tab = t[0]; render(); });
      tabBox.append(tab);
    });
  }
  function renderPanel(p){
    panel.replaceChildren();
    if (state.tab === "source"){
      panel.append(el("p", "note", p.comment), pre(p.source, true));
      return;
    }
    if (state.tab === "tokens"){
      panel.append(el("p", "note", "每个记号都带行列（Span）——下面的列号就是报错时插入符会指的位置。"), pre(p.stages.tokens));
      return;
    }
    if (state.tab === "ast"){
      panel.append(el("p", "note", "单行 shape 用来一眼看优先级；缩进版是同一棵树的完整形状。"), pre(p.stages.shape + "\\n\\n" + p.stages.ast));
      return;
    }
    if (state.tab === "bytecode"){
      panel.append(el("p", "note", "栈机指令，每条都带源码行号；CALL 的注释是函数名。" + (p.stages.locals ? "（" + p.stages.locals + "）" : "")), pre(p.stages.bytecode + "\\n常量池: " + p.stages.constants));
      return;
    }
    if (state.tab === "run"){
      var run = p.stages.run;
      var line = el("p", "note");
      line.append(el("span", "badge " + (run.same ? "ok" : "bad"), run.same ? "VM 输出 == 树遍历输出" : "两条后端输出不一致！"));
      line.append(document.createTextNode("  VM 步数 " + run.steps_vm + " / 树遍历步数 " + run.steps_walk + "——步数是两种执行模型的固有差异，口径只要求输出一致。"));
      panel.append(line);
      var out = el("div");
      out.append(el("p", "note", "程序输出（" + run.output_count + " 行）："));
      out.append(pre(run.output.join("\\n")));
      out.append(el("p", "note", "VM 前 " + DATA.trace_steps + " 步轨迹："));
      var ol = el("ol", "trace");
      run.trace.forEach(function(s){ ol.append(el("li", "", s)); });
      out.append(ol);
      panel.append(out);
      return;
    }
    if (state.tab === "errors"){
      if (p.status === "compile_error") panel.append(el("p", "note", "编译期错误（红色插入符指向出错位置）："));
      else panel.append(el("p", "note", "运行期错误（静态检查挡不住的那部分，VM 带着行号报出来）："));
      p.errors.forEach(function(text){ panel.append(pre(text, true)); });
      return;
    }
  }
  function render(){
    var p = current();
    var avail = available(p);
    if (!avail.some(function(t){ return t[0] === state.tab; })) state.tab = avail[0][0];
    renderChips();
    renderTabs(p);
    subtitle.textContent = p.comment;
    var info = label(p);
    badge.textContent = info[0];
    badge.className = "badge " + info[1];
    renderPanel(p);
  }
  function select(name){ state.name = name; render(); }
  render();
})();
"""


def render(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")            # 别让 JSON 里的 </script 形态提前闭合脚本
    cards = "".join(
        f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in payload["facts"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B13-tinylang · 编译器透视（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B13-tinylang">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a>（本页双击即看，零网络依赖）</p>
<h1>B13-tinylang · 一条能完整追踪的编译流水线</h1>
<p class="note">编译原理 · 词法 → 语法 → 语义 → 字节码 → 执行：下面每个样例都可以点开看
每一段真实产物；两个后端（字节码 VM 与树遍历参照实现）的输出逐字节对拍。</p>

<h2 id="facts-title">实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2 id="demo-title">展示区：点一个程序，逐段看它怎么被编译和执行</h2>
<section id="demo" class="panel">
  <p class="note" id="subtitle"></p>
  <div class="chips" id="chips"></div>
  <div class="tabs" id="tabs"></div>
  <div id="panel"></div>
  <p class="note">状态签：<span class="badge" id="status-badge"></span></p>
</section>

<h2 id="repro-title">怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：一场自测 + 全部演示（Windows 批处理，纯 ASCII）。</li>
    <li><kbd>python demo.py</kbd>：五段终端演示（流水线逐段输出、语言取舍、错误定位、对拍、递归）。</li>
    <li><kbd>python -m unittest discover -s tests</kbd>：完整测试（含 300 例随机程序双后端对拍）。</li>
    <li><kbd>python tools/showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令从 programs/*.tiny 现算；别手改本页。
  观感与顺手程度归你实跑验收。</p>
</section>

<footer>
  <p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。</p>
</footer>
</main>
<script>const DATA = {data};</script>
<script>{APP_JS}</script>
</body>
</html>
"""


# ------------------------------------------------------------------ 入口

def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B13 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true", help="重算比对，不写盘")
    ap.add_argument("--write", action="store_true", help="写出 web/showcase.html")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（{len(payload['programs'])} 个样例的逐段产物，全部现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print(f"展示页新鲜：与现算逐字一致（{len(payload['programs'])} 个样例逐段产物 + 事实卡片）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
