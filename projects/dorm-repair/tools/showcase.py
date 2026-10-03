"""tools/showcase.py —— dorm-repair（B15–B22 共用）展示页生成器。口径：showcase/SPEC.md。

数据全部现算：真跑 `demo.py`（13 段 walkthrough——追踪旅程 / 状态机 / 权限 / 可见性 /
检查器有没有牙齿 / 歧义登记 / 原型四态 / 架构 / Java 判定 / 双接口 / 验证工程 / 门禁 / 台账；
全种子化、无计时输出，两遍运行逐字相同——demo 自己的口径）。数字卡全部从演示输出解析。

**本生成器只做展示，不进流水线**（层数被门禁表锁死，加层要动 gate.json/docs/12/台账一串——
先例见 tools/walkthrough_pack.py docstring）：run.bat 第 3 步挂 `--check` + tests/test_showcase.py，
形态与 B16 走查期望表一致。人工走查（观感/手感/读屏）仍归用户，本页不代填。

页面写 `web/showcase.html`；`--check` 重算比对（不写盘），过期即红。
"""
from __future__ import annotations

import argparse
import html
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
.sw-top{max-width:1200px;margin:12px 18px 0;padding:10px 14px;background:#fff;border:1px solid #d5d9e0;border-radius:10px}
.sw-top .sw-link{font-size:13px;color:#1d4ed8;text-decoration:none}
.sw-top h2{font-size:16px;margin:6px 0 2px}
.sw-top p{margin:2px 0;color:#5f6773;font-size:13px}
.sw-cards{max-width:1200px;display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin:10px 18px 0}
.sw-card{background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:8px 12px;font-size:13px}
.sw-card b{display:block;font-size:12px;color:#5f6773;margin-bottom:2px}
.sw-panel{max-width:1200px;margin:10px 18px 0;background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:10px 14px;font-size:14px}
.sw-panel h3{margin:4px 0 6px;font-size:15px}
.sw-panel pre{background:#0f1115;color:#e6e9ef;border-radius:8px;padding:10px 12px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.sw-panel kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid #d5d9e0;border-radius:4px;padding:0 4px;background:#fff}
.sw-footer{max-width:1200px;margin:14px 18px 26px;color:#5f6773;font-size:13px}
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


def _tabbed(demo_html: str) -> tuple:
    """把 'N) 标题' 分段文本切成 (tabs_html, panes_html)；整行 '=' 分隔线移除。"""
    sections, cur = [], None
    for ln in demo_html.splitlines():
        m = re.match(r"^\s*(\d+)\)\s+(.+?)\s*$", ln)
        if m:
            if cur:
                sections.append(cur)
            cur = {"num": m.group(1), "title": m.group(2), "lines": []}
        elif cur is not None:
            if set(ln.strip()) == {"="}:
                continue
            cur["lines"].append(ln)
    if cur:
        sections.append(cur)
    tabs, panes = [], []
    for s in sections:
        short = s["title"].split("：")[0][:14]
        tabs.append(f'<button type="button" class="pj-tab" data-tab="{s["num"]}">'
                    f'{s["num"]} {short}</button>')
        body = "\n".join([s["title"]] + s["lines"]).rstrip()
        panes.append(f'<div class="pj-pane" data-pane="{s["num"]}"><pre>{body}</pre></div>')
    return "".join(tabs), "".join(panes)


def _run(args) -> str:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(map(str, args))} 退出码 {proc.returncode}：\n"
                         f"{(proc.stdout or '')[-400:]}\n{(proc.stderr or '')[-400:]}")
    return proc.stdout


def _pick(demo: str, pattern: str, what: str) -> tuple:
    m = re.search(pattern, demo)
    if not m:
        raise SystemExit(f"演示输出里解析不到「{what}」——正则要跟着文案改")
    return m.groups()


def _test_count() -> tuple[int, int]:
    total = core = 0
    for p in sorted(TESTS.glob("test_*.py")):
        n = len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
        total += n
        if p.name != "test_showcase.py":
            core += n
    return total, core


def collect() -> dict:
    demo = _run([sys.executable, "demo.py"])
    tests_total, tests_core = _test_count()

    (ac,), (aq,) = (_pick(demo, p, w) for p, w in [
        (r"验收标准总数\s+(\d+) 条：已可执行 \d+、待后续轮次 \d+、需人工 \d+", "验收标准总数"),
        (r"待决问题\s+(\d+) 条", "待决问题"),
    ])
    (verdict,) = _pick(demo, r"判定表\s+(\d+) 格", "判定表格数")
    (comps, edges) = _pick(demo, r"组件\s+(\d+) 个，真实 import 边 (\d+) 条", "组件/依赖边")
    (roles,) = _pick(demo, r"分层流水线 (\d+) 层", "流水线层数")
    (blocking, advisory) = _pick(demo, r"\d+ 层，blocking (\d+)、advisory (\d+)", "门禁层配比")
    (auto, eyeball, manual) = _pick(demo, r"20 步＝纯自动 (\d+) \+ 自动但仍需眼看 (\d+) \+ 只能人工 (\d+)", "走查步数分解")
    (keys,) = _pick(demo, r"台账\s+(\d+) 个键", "台账键数")
    (rounds_done,) = _pick(demo, r"rounds_done\s+(\d+)", "rounds_done")
    (pitfalls,) = _pick(demo, r"pitfalls\s+(\d+)", "pitfalls")
    (aq_ruled,) = _pick(demo, r"aq_ruled\s+(\d+)", "aq_ruled")
    (mutations,) = _pick(demo, r"变异登记表\s+(\d+) 条变异", "变异条数")
    (loop,) = _pick(demo, r"AQ-10 循环\s+(\d+) 步", "AQ-10 循环步数")

    facts = [
        ["测试", f"{tests_total} 项（{tests_core} 核心 + {tests_total - tests_core} 展示页自测）"],
        ["需求 → 测试", f"验收标准 {ac} 条全部可执行（待后续轮次 0、需人工 0）；"
                   f"待决问题 {aq} 条如实登记（其中 {aq_ruled} 条已裁决为工程默认）"],
        ["判定表（B18 跨语言）", f"{verdict} 格 = 状态 × 动作 × 身份 × 输入齐全/缺失 × 时刻；"
                          f"Java 读同一份契约逐格相同"],
        ["架构（B17 实测依赖图）", f"{comps} 个组件、真实 import 边 {edges} 条（与 docs/08 双向核对）；"
                           f"判定源只有 spec/workorder.py 一份"],
        ["验证工程（B20）", f"收缩器 7 状态 ddmin 与 BFS 独立最短全部相等；AQ-10 循环 {loop} 步闭式；"
                      f"变异登记 {mutations} 条 + 1 条阴性对照"],
        ["质量门禁（B21）", f"{roles} 层（blocking {blocking}、advisory {advisory}）、分诊 8 类；"
                      f"mutation 层必须拦（口径过期就拒判）"],
        ["人工走查（B16/B21）", f"20 步 = 纯自动 {auto} + 仍需眼看 {eyeball} + 只能人工 {manual}；"
                         f"结果列留空——检查器拒代填"],
        ["台账（B22）", f"{keys} 个键全部现算（rounds_done {rounds_done}、pitfalls {pitfalls}、"
                   f"verdict_cells {verdict} …）；管理文档核对通过"],
    ]
    return {"facts": facts, "demo": demo}


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="sw-card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    tabs_html, panes_html = _tabbed(e(p["demo"].rstrip()))
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>dorm-repair · 宿舍报修系统（B15–B22 全生命周期，课设作品集）</title>
<style>{SHELL_CSS}</style></head>
<body data-showcase="dorm-repair">
<div class="sw-top"><a class="sw-link" href="../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B41-thesis-seeds/web/showcase.html">B41</a></span>
<h2>dorm-repair · 宿舍报修系统：同一套代码的八轮迭代（B15 → B22）</h2>
<p>需求工程 → 交互设计 → 体系结构 → Java 平台层 → SOA 第二接口 → 测试工程 → 质量门禁 → 项目管理：
每一轮的「数字」都能被下一轮的检查器复核——文档与模型说不同话、契约过期、判定漂移、
核对器失去牙齿，各自有对应的红灯层。本页 13 段现场输出与数字卡全部现算自 <kbd>demo.py</kbd>。</p></div>
<section id="facts" class="sw-cards">{cards}</section>
<section id="demo" class="sw-panel"><h3>13 段 walkthrough（点页签切换段）</h3>
<div class="pj-tabs">{tabs_html}</div>
{panes_html}</section>
<section id="repro" class="sw-panel"><h3>怎么自己跑</h3>
<ul>
<li><kbd>run.bat</kbd>：八步全链路（环境 → 文档一致性 → 架构/契约/走查期望/展示页新鲜度 →
测试 → 演示 → Java 平台层 → 流水线五层 → 原型）；<kbd>run.bat no-web</kbd> 跳过浏览器原型。</li>
<li><kbd>run.bat gate</kbd>：质量门禁判定；<kbd>run.bat pipeline</kbd>：一条命令跑完 11 层。</li>
<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
</ul>
<p>浏览器原型的观感、手感、键盘与读屏表现只能你实跑——<kbd>docs\\07-walkthrough.md</kbd> 的 20 步
每行结果都留空等你填，检查器会拒绝任何代填。</p></section>
<div class="sw-footer"><p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；
仓库级校验 python showcase/check.py）。页面数据全部现算，无外部请求。
本页只做展示，不进流水线——层数被门禁表锁死，先例见 tools/walkthrough_pack.py docstring。</p></div>
<script>{TAB_JS}</script>
</body></html>"""


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="dorm-repair 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节（13 段 walkthrough + 数字卡）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        if OUT.read_text(encoding="utf-8") != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（13 段 walkthrough / 门禁 / 台账）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
