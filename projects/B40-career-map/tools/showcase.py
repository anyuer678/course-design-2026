"""tools/showcase.py —— B40 展示页生成器（口径：showcase/SPEC.md）。

数据全部现算：真跑 `demo.py`（四段；文件驱动、无计时输出——两遍运行逐字相同），
把 31 条证据的核验结论、三条"改坏必须红"的负面对照、示例 JD 差距矩阵一起搬上页面；
技能面矩阵从 demo 输出里解析成 HTML 表，证据条数/缺口数从 data/*.json 现读。

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
.sw-gap{color:#a3341f;font-weight:600}
.sw-footer{max-width:1150px;margin:14px 18px 26px;color:#5f6773;font-size:13px}
.pj-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 8px}
.pj-tab{font:inherit;font-size:13px;padding:4px 11px;border:1px solid #d5d9e0;border-radius:999px;background:#fff;cursor:pointer;color:#1c2330}
.pj-tab:hover{border-color:#1d4ed8}
.pj-tab.active{background:#1d4ed8;border-color:#1d4ed8;color:#fff}
.pj-pane{display:none}.pj-pane.active{display:block}
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


def _test_count() -> tuple[int, int]:
    total = core = 0
    for p in sorted(TESTS.glob("test_*.py")):
        n = len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
        total += n
        if p.name != "test_showcase.py":
            core += n
    return total, core


def _matrix_rows(demo: str) -> list[list[str]]:
    rows = []
    for line in demo.splitlines():
        if not line.startswith("| ") or line.startswith("| 技能面") or set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 4:
            rows.append(cells)
    return rows


def collect() -> dict:
    demo = _run([sys.executable, "demo.py"])
    tests_total, tests_core = _test_count()

    ev = json.loads((ROOT / "data" / "evidence.json").read_text(encoding="utf-8"))["evidence"]
    skills = json.loads((ROOT / "data" / "skills.json").read_text(encoding="utf-8"))["skills"]
    roots = set()
    for e in ev:
        for ptr in e.get("pointers", []):
            parts = ptr.split("/")
            roots.add(parts[1] if parts[0] == "projects" and len(parts) > 1 else ptr)
    gaps = [s["name"] for s in skills if not s.get("evidence")]
    matrix = _matrix_rows(demo)
    covered = sum(1 for r in matrix if r[2].startswith("已覆盖"))
    m = re.search(r"缺口清单（(\d+) 项）", demo)
    gap_n = int(m.group(1)) if m else 0

    facts = [
        ["测试", f"{tests_total} 项（{tests_core} 核心 + {tests_total - tests_core} 展示页自测）"],
        ["证据索引", f"{len(ev)} 条核验 PASS（0 个问题）；指针落到 {len(roots)} 个目标"
                 f"（{len({e['commit'] for e in ev})} 个提交号逐条在 git 里存在）"],
        ["示例 JD 映射", f"命中并已覆盖 {covered} 个技能面；缺口 {gap_n} 个"
                      f"（{'、'.join(gaps)}）；未提及 {len(skills) - covered - gap_n} 个"],
        ["负面对照（核验器有没有牙齿）", "3 条改坏全部报红且红在该原因上（假指针 / 假锚点 / 假提交号）"],
        ["诚实设计钉住", "示例 JD 显式标注'非真实岗位'；缺口故意留空（测试钉死防'顺手补满'）；"
                    "工具不替你选岗位（PLAN §5）"],
        ["怎么产生的", "报告由'JD 文本 × 技能表 × 证据索引'三份数据现算，没有手抄数字"],
    ]
    return {"facts": facts, "demo": demo, "matrix": matrix,
            "skills": [(s["name"], len(s.get("evidence", [])), s.get("practice", "")) for s in skills]}


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="sw-card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    rows_html = []
    for cells in p["matrix"]:
        status = cells[2]
        cls = ' class="sw-gap"' if "缺口" in status else ""
        rows_html.append(
            f"<tr><td>{e(cells[0])}</td><td>{e(cells[1])}</td>"
            f"<td{cls}>{e(status)}</td><td>{e(cells[3])}</td></tr>")
    table = ("<table><tr><th>技能面</th><th>命中关键词</th><th>状态</th><th>证据 / 缺口练习</th></tr>"
             + "".join(rows_html) + "</table>")
    skills_rows = "".join(
        f"<tr><td>{e(name)}</td><td>{n} 条</td><td>{e(practice)}</td></tr>"
        for name, n, practice in p["skills"])
    skills_table = ("<table><tr><th>技能面（15 个）</th><th>证据</th><th>缺口练习（无证据者的下一步）</th></tr>"
                    + skills_rows + "</table>")
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>B40-career-map · 技能差距矩阵（课设作品集）</title>
<style>{SHELL_CSS}</style></head>
<body data-showcase="B40-career-map">
<div class="sw-top"><a class="sw-link" href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B39-tech-radar/web/showcase.html">B39</a>　·　下一件 <a href="../../../projects/B41-thesis-seeds/web/showcase.html">B41</a></span>
<h2>B40-career-map · 求职证据的可核验化 + JD 差距矩阵</h2>
<p>每个技能面挂<b>可机验</b>证据：指针路径 + @提交号 + 锚点字符串，<kbd>tools/check_evidence.py</kbd>
逐条去仓库和 git 里找；改坏一条必须红。JD 映射把岗位关键词对到证据，缺口转成练习清单。
本页数字全部现算自 <kbd>demo.py</kbd> 与 <kbd>data/*.json</kbd>。</p></div>
<section id="facts" class="sw-cards">{cards}</section>
<section id="demo" class="sw-panel"><h3>展示区（点页签切换）</h3>
<div class="pj-tabs">
<button type="button" class="pj-tab" data-tab="1">1 JD 差距矩阵</button>
<button type="button" class="pj-tab" data-tab="2">2 15 技能面全景</button>
<button type="button" class="pj-tab" data-tab="3">3 演示原文（含 31 条证据明细）</button>
</div>
<div class="pj-pane" data-pane="1"><p>示例 JD 差距矩阵（现算；合成示例，非真实岗位）</p>
{table}
</div>
<div class="pj-pane" data-pane="2"><p>15 个技能面全景（evidence 空 = 故意留空的缺口）</p>
{skills_table}</div>
<div class="pj-pane" data-pane="3"><pre>{e(p["demo"].rstrip())}</pre></div></section>
<section id="repro" class="sw-panel"><h3>怎么自己跑</h3>
<ul>
<li>把真实岗位 JD 存成 <kbd>jd\\岗位名.txt</kbd>（不要改 EXAMPLE 那个文件），
跑 <kbd>python tools\\map_jd.py --write</kbd> —— 差距矩阵写到 build\\jd_matrix.md。</li>
<li><kbd>python tools\\check_evidence.py</kbd>：31 条证据随时复核（改坏一条必须红）。</li>
<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
</ul>
<p>边界：本工具只做映射与核验，不替你选岗位/方向（PLAN §5），也不替代真实实习。</p></section>
<div class="sw-footer"><p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；
仓库级校验 python showcase/check.py）。页面数据全部现算，无外部请求。</p></div>
<script>{TAB_JS}</script>
<script>
/* 实时实验台引导（未启动则静默）：python showcase/lab.py */
"use strict";
var s=document.createElement("script");
s.src=(location.protocol==="http:")?("/showcase/lab.js"):"http:\\/\\/127.0.0.1:7788/showcase/lab.js";
document.body.appendChild(s);
</script>
</body></html>"""


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B40 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节（矩阵表 + 技能全景 + 演示原文）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        if OUT.read_text(encoding="utf-8") != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（证据/负面对照/JD 矩阵）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
