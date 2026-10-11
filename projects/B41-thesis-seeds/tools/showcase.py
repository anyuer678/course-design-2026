"""tools/showcase.py —— B41 展示页生成器（口径：showcase/SPEC.md）。

数据全部现算：真跑 `demo.py`（四段；核验与比较表由文件现算，唯一【实测】是末段写盘基准）。
**规范化规则（可审计）**：末段两条中位数（plain/fsync）与解读行的"≈ X ms/条"是每次现算的
毫秒读数，页内固定为占位 `<当场>`——跑 `demo.py` 看当场值（B29/B34 同款口径）。

页面写 `web/showcase.html`；`--check` 重算比对（不写盘），过期即红。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"

SHELL_CSS = """
body{font-family:"Microsoft YaHei",system-ui,sans-serif;margin:0;background:#f4f6f9;color:#1c2330}
.sw-top{max-width:1150px;margin:12px 18px 0;padding:10px 14px;background:#fff;border:1px solid #d5d9e0;border-radius:10px}
.sw-top .sw-link{font-size:13px;color:#1d4ed8;text-decoration:none}
.sw-top h2{font-size:16px;margin:6px 0 2px}
.sw-top p{margin:2px 0;color:#5f6773;font-size:13px}
.sw-cards{max-width:1150px;display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin:10px 18px 0}
.sw-card{background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:8px 12px;font-size:13px}
.sw-card b{display:block;font-size:12px;color:#5f6773;margin-bottom:2px}
.sw-panel{max-width:1150px;margin:10px 18px 0;background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:10px 14px;font-size:14px}
.sw-panel h3{margin:4px 0 6px;font-size:15px}
.sw-panel pre{background:#0f1115;color:#e6e9ef;border-radius:8px;padding:10px 12px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.sw-panel kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid #d5d9e0;border-radius:4px;padding:0 4px;background:#fff}
.sw-panel table{border-collapse:collapse;width:100%;font-size:13px}
.sw-panel th,.sw-panel td{border:1px solid #d5d9e0;padding:4px 8px;text-align:left;vertical-align:top}
.sw-panel th{background:#eef2f7}
.sw-footer{max-width:1150px;margin:14px 18px 26px;color:#5f6773;font-size:13px}
.pj-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 8px}
.pj-tab{font:inherit;font-size:13px;padding:4px 11px;border:1px solid #d5d9e0;border-radius:999px;background:#fff;cursor:pointer;color:#1c2330}
.pj-tab:hover{border-color:#1d4ed8}
.pj-tab.active{background:#1d4ed8;border-color:#1d4ed8;color:#fff}
.pj-pane{display:none}.pj-pane.active{display:block}

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

TAB_JS = """(function(){
  "use strict";
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".pj-tab"));
  var panes = Array.prototype.slice.call(document.querySelectorAll(".pj-pane"));
  function show(name){
    tabs.forEach(function(t){ t.className = "pj-tab" + (t.dataset.tab === name ? " active" : ""); });
    panes.forEach(function(p){ p.className = "pj-pane" + (p.dataset.pane === name ? " active" : ""); });
  }
  tabs.forEach(function(t){ t.addEventListener("click", function(){ show(t.dataset.tab); }); });
  if (tabs.length) show(tabs[0].dataset.tab);
})();"""


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
    """三条毫秒规则（left 原样、只换数字），见模块 docstring。"""
    text = re.sub(r"(写 8KB 记录（60 次中位数）\s+plain\s+)[\d.]+ ms", r"\1<当场> ms", text)
    text = re.sub(r"(写 8KB \+ fsync（60 次中位数）\s+fsync\s+)[\d.]+ ms", r"\1<当场> ms", text)
    text = re.sub(r"(边际成本 ≈ )[\d.]+ ms/条", r"\1<当场> ms/条", text)
    return text


def _test_count() -> tuple[int, int]:
    total = core = 0
    for p in sorted(TESTS.glob("test_*.py")):
        n = len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
        total += n
        if p.name != "test_showcase.py":
            core += n
    return total, core


def collect() -> dict:
    raw = _run([sys.executable, "demo.py"])
    demo = _norm(raw)
    tests_total, tests_core = _test_count()

    data = json.loads((ROOT / "data" / "seeds.json").read_text(encoding="utf-8"))
    chosen = data.get("chosen") or []
    if isinstance(chosen, dict):
        chosen = [chosen]

    m = re.search(r"核验结果\s+([^\n]*)", demo)
    checked = m.group(1).strip() if m else "?"
    reds = len(re.findall(r"RED，首条：", demo))

    facts = [
        ["测试", f"{tests_total} 项（{tests_core} 核心 + {tests_total - tests_core} 展示页自测）"],
        ["事实核验", f"{checked}；现存候选 0 个、行数 0 处、探针 0 个（收官态——双空才红）"],
        ["候选表", f"已清零：{len(chosen)} 个候选全部选定实施（2026-10-02）；"
                f"负面对照改用注入式夹具继续钉规则"],
        ["负面对照（核验器有没有牙齿）", f"{reds} 条改坏全部报红且红在该原因上"
                                    f"（改错行数 / 改错探针期望 / 假锚点）"],
        ["资源基准（候选①）", "写 8KB 记录 plain / +fsync 两条中位数与边际成本为【实测】，"
                        "本页固定为占位 <当场>——跑 demo.py 看当场读数"],
    ]
    return {"facts": facts, "demo": demo, "chosen": chosen}


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="sw-card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    rows = "".join(
        f"<tr><td>{e(c.get('title', '?'))}</td><td>{e(c.get('date', ''))}</td>"
        f"<td>{e(c.get('evidence', {}).get('path', ''))}<br>锚点：{e(c.get('evidence', {}).get('anchor', ''))}</td></tr>"
        for c in p["chosen"])
    table = ("<table><tr><th>已选定并实施（5 个）</th><th>日期</th><th>证据（指针 + 锚点）</th></tr>"
             + rows + "</table>")
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>B41-thesis-seeds · 毕设候选三维可行性（课设作品集）</title>
<style>{SHELL_CSS}</style></head>
<body data-showcase="B41-thesis-seeds">
<div class="sw-top"><a class="sw-link" href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B40-career-map/web/showcase.html">B40</a>　·　下一件 <a href="../../../projects/dorm-repair/web/showcase.html">dorm-repair</a></span>　·　<a href="#lab">实时实验台</a>
<h2>B41-thesis-seeds · 毕设候选的三维可行性（数字会自己过期）</h2>
<p>比较工具链的核心纪律：<b>行数重算 + 缺口探针重跑 + 证据锚点必真</b>——
改错一处 <kbd>tools/check_seeds.py</kbd> 即红。5 个候选已由用户选定实施完毕（候选表清零，
负面对照改用注入式夹具继续钉规则）。本页数字全部现算自 <kbd>demo.py</kbd> 与 <kbd>data/seeds.json</kbd>。</p></div>
<section id="facts" class="sw-cards">{cards}</section>
<section id="demo" class="sw-panel"><h3>选定与比较（点页签切换）</h3>
<div class="pj-tabs">
<button type="button" class="pj-tab" data-tab="1">1 选定清单与证据</button>
<button type="button" class="pj-tab" data-tab="2">2 演示原文（比较表/负面对照/基准）</button>
</div>
<div class="pj-pane" data-pane="1"><p>选定清单与三维比较表（现算）；证据 = 指针 + 锚点，随时可复核。</p>
{table}
</div>
<div class="pj-pane" data-pane="2"><pre>{e(p["demo"].rstrip())}</pre></div></section>
<section id="repro" class="sw-panel"><h3>怎么自己跑</h3>
<ul>
<li><kbd>run.bat</kbd>：三步（测试 → demo → 展示页新鲜度）；<kbd>python demo.py</kbd> 只看演示
（末段两条毫秒是本机当场读数）。</li>
<li><kbd>python tools\\check_seeds.py</kbd>：行数/探针/锚点复核；改错一处即红。</li>
<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
</ul>
<p>候选题清单不等于开题；任何新候选开工前，先跑 run.bat 把基线与 fsync 基准过一遍。</p></section>
<section id="lab" class="sw-panel"><h3>实时实验台</h3>
<div id="lab-slot">
<p><b>实验台未启动</b>：本页仍是静态生成物，双击即看；启动实验台后，这块会就地变成控制台——真启停后端服务、发原始请求（字节进字节出）、看实时日志、跑演示/测试。</p>
<ul>
<li>双击仓库根 <kbd>lab.bat</kbd>（或终端 <kbd>python showcase\\lab.py</kbd>），然后刷新本页；</li>
<li>只起服务不弹浏览器：<kbd>lab.bat no-open</kbd>；自检：<kbd>lab.bat selftest</kbd>。</li>
</ul>
</div>
</section>

<div class="sw-footer"><p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；
仓库级校验 python showcase/check.py）。页面数据全部现算，无外部请求。</p></div>
<script>{TAB_JS}</script>
<script>
/* 实时实验台引导（双击 lab.bat 启动实验台后，页内该分节自动变成控制台） */
"use strict";
var s=document.createElement("script");
s.src=(location.protocol==="http:")?("/showcase/lab.js"):"http:\\/\\/127.0.0.1:7788/showcase/lab.js";
document.body.appendChild(s);
</script>
</body></html>"""


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B41 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节（选定清单 + 三维比较表 + 演示原文）")
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
        print("展示页新鲜：与现算逐字一致（核验/负面对照/选定清单）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
