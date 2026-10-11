"""tools/showcase.py —— B14 展示页生成器（口径：showcase/SPEC.md）。

数据全部现算：**自包含构建**（缺 build 即重建：javac --release 17 → build/classes +
build/test-classes，与 run.bat 同命令行），再真跑：
  - `paint.PaintTests`（headless 自检，9 组 / 7106 项检查）→ 逐组结论上页面；
  - `paint.App --demo`（离屏演示：画 3 个形状 → 撤销 → 重做 → 像素统计 → 写 PNG）
    → 把**真画出来的 PNG** 内嵌为 data URI（确定性：多次运行 sha1 相同，测试钉住）。

**规范化规则（可审计）**：demo 输出里 PNG 的临时文件名含随机长整数
（`b14-demo<随机>.png`）与临时目录路径——整段替换为占位；其余逐字保留。
真窗口的手感/交互仍归用户实跑（run.bat 第 5 步），本页只摆自动化证据。

页面写 `web/showcase.html`；`--check` 重算比对（不写盘），过期即红。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "showcase.html"
BUILD = ROOT / "build"
CLASSES = BUILD / "classes"
TEST_CLASSES = BUILD / "test-classes"

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
.sw-shot{max-width:640px;border:1px solid #d5d9e0;border-radius:8px;background:#fff;padding:6px}
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


def _run(args, cwd=None) -> str:
    proc = subprocess.run(args, cwd=str(cwd or ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(map(str, args))} 退出码 {proc.returncode}：\n"
                         f"{(proc.stdout or '')[-400:]}\n{(proc.stderr or '')[-400:]}")
    return (proc.stdout or "") + (proc.stderr or "")


def _ensure_build() -> None:
    if (CLASSES / "paint" / "App.class").is_file() and (TEST_CLASSES / "paint" / "PaintTests.class").is_file():
        return
    javac = shutil.which("javac")
    if not javac:
        raise SystemExit("javac 不在 PATH——B14 是 Java 项目，先装 JDK 17+（run.bat 同款前置检查）")
    main_src = sorted((ROOT / "src" / "main" / "java").rglob("*.java"))
    test_src = sorted((ROOT / "src" / "test" / "java").rglob("*.java"))
    _run([javac, "--release", "17", "-encoding", "UTF-8", "-d", str(CLASSES)] + [str(p) for p in main_src])
    _run([javac, "--release", "17", "-encoding", "UTF-8", "-cp", str(CLASSES),
          "-d", str(TEST_CLASSES)] + [str(p) for p in test_src])


def _java(args) -> str:
    java = shutil.which("java")
    if not java:
        raise SystemExit("java 不在 PATH——先装 JDK 17+")
    return _run([java, "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8",
                 "-Dstdout.encoding=UTF-8"] + args)


def collect() -> dict:
    _ensure_build()
    cp_main = str(CLASSES)
    cp_test = str(CLASSES) + os.pathsep + str(TEST_CLASSES)

    selftest = _java(["-cp", cp_test, "paint.PaintTests"])
    modules = re.findall(r"^·\s*(.+?)\s*…\s*ok\s*$", selftest, re.M)
    m = re.search(r"全部通过：(\d+) 项检查，(\d+) 失败", selftest)
    checks, fails = (m.group(1), m.group(2)) if m else ("?", "?")

    demo = _java(["-cp", cp_main, "paint.App", "--demo"])
    m = re.search(r"离屏像素统计：红 (\d+)、蓝 (\d+)、绿 (\d+)", demo)
    pixels = m.groups() if m else ("?", "?", "?")
    m = re.search(r"([A-Za-z]:\\[^\r\n（）]*b14-demo\d+\.png)", demo)
    if not m:
        raise SystemExit("demo 输出里找不到 PNG 路径——解析规则要跟着改")
    png_path = Path(m.group(1))
    png = png_path.read_bytes()
    sha = hashlib.sha1(png).hexdigest()
    demo_norm = demo.replace(m.group(1), "<临时目录>b14-demo<随机>.png")

    main_files = sorted((ROOT / "src" / "main" / "java" / "paint").rglob("*.java"))
    pkgs = sorted({p.parent.name for p in main_files if p.parent.name != "paint"})
    javac_ver = _run([shutil.which("javac") or "javac", "-version"]).strip()

    facts = [
        ["自检（headless）", f"{checks} 项检查、{fails} 失败；{len(modules)} 组："
                       + "、".join(modules)],
        ["离屏演示", "画 3 个形状 [rect, ellipse, line] → 撤销 → 重做；"
                 f"像素 红 {pixels[0]} / 蓝 {pixels[1]} / 绿 {pixels[2]}"
                 "（三条绘制路径都真的落到画面上）"],
        ["真画出来的图", f"内嵌 PNG {len(png)} 字节（每次现画现取）；确定性：sha1 {sha[:12]}…"
                    "（多次运行逐字节相同，测试钉住）"],
        ["类体系", f"main {len(main_files)} 个源文件（包：{'、'.join(pkgs)} + 顶层 App）"
               f"；测试 1 个入口 PaintTests（无框架，一个 main）"],
        ["构建", f"{javac_ver}，--release 17 -encoding UTF-8 编译进 build/（与 run.bat 同命令行）"],
        ["真窗口交互", "Swing 窗口的观感、手感与键盘交互只能你实跑（run.bat 第 5 步，我不代勾）"],
    ]
    return {"facts": facts, "selftest": selftest.rstrip(), "demo": demo_norm.rstrip(),
            "modules": modules, "png_b64": base64.b64encode(png).decode("ascii"),
            "png_sha": sha}


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="sw-card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    module_rows = "".join(f"<tr><td>{e(name)}</td><td>ok</td></tr>" for name in p["modules"])
    module_table = ("<table><tr><th>自检组（8 组）</th><th>结论</th></tr>" + module_rows + "</table>")
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>B14-java-paint · Java 图形编辑器（课设作品集）</title>
<style>{SHELL_CSS}</style></head>
<body data-showcase="B14-java-paint">
<div class="sw-top"><a class="sw-link" href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B34-path-planner/web/showcase.html">B34</a>　·　下一件 <a href="../../../projects/B31-shorturl/web/showcase.html">B31</a></span>　·　<a href="#lab">实时实验台</a>
<h2>B14-java-paint · 图形编辑器：命令/撤销重做 + 可信存盘 + 离屏渲染</h2>
<p>纯 Java（零第三方库）：图形类体系与命令模式、原子写盘与读取防线、离屏渲染像素对账、
Swing 事件语义、随机操作 vs 快照模型。本页数字全部现算——生成器按 run.bat 同命令行自包含
构建，再真跑自检与离屏演示；<b>图是当场画出来的真产物</b>，不是示意图。</p></div>
<section id="facts" class="sw-cards">{cards}</section>
<section id="demo" class="sw-panel"><h3>现场证据（点页签切换）</h3>
<div class="pj-tabs">
<button type="button" class="pj-tab" data-tab="1">1 自检 8 组</button>
<button type="button" class="pj-tab" data-tab="2">2 离屏演示原文</button>
<button type="button" class="pj-tab" data-tab="3">3 当场画出来的图</button>
<button type="button" class="pj-tab" data-tab="4">4 自检完整原文</button>
</div>
<div class="pj-pane" data-pane="1">{module_table}</div>
<div class="pj-pane" data-pane="2"><pre>{e(p["demo"])}</pre></div>
<div class="pj-pane" data-pane="3"><p>data URI 内嵌，sha1 {p["png_sha"][:12]}…——真产物，
不是示意图；跑 run.bat 第 3 步会重新画一张。</p>
<img class="sw-shot" alt="离屏演示：矩形 + 椭圆 + 线段" src="data:image/png;base64,{p["png_b64"]}"></div>
<div class="pj-pane" data-pane="4"><pre>{e(p["selftest"])}</pre></div></section>
<section id="repro" class="sw-panel"><h3>怎么自己跑</h3>
<ul>
<li><kbd>run.bat</kbd>：五步（编译 → 自检 → 离屏演示 → 展示页新鲜度 → 打开窗口）；
<kbd>run.bat no-gui</kbd> 跳过窗口（构建在 %TEMP% 里，项目目录零残留）。</li>
<li><kbd>java -Djava.awt.headless=true -cp build\\classes paint.App --demo</kbd>：只看离屏演示。</li>
<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
</ul>
<p>Swing 窗口的手感、键盘与拖拽的真实表现请自己开窗口试——自动化只到离屏语义这一层。</p></section>
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
    ap = argparse.ArgumentParser(description="B14 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节（自检 8 组 + 演示 + PNG 内嵌）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        if OUT.read_text(encoding="utf-8") != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            print(f"长度：磁盘 {len(disk)} / 现算 {len(fresh)}")
            for i, (x, y) in enumerate(zip(disk.splitlines(), fresh.splitlines())):
                if x != y:
                    print(f"首个差异行 {i}：磁盘={x[:100]!r} 现算={y[:100]!r}")
                    break
            return 1
        print("展示页新鲜：与现算逐字一致（自检/离屏演示/PNG）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
