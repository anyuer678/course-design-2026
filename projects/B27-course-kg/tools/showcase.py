"""tools/showcase.py —— B27 展示页生成器（课程图谱：交互页"原位提升"为提交物）。口径：showcase/SPEC.md。

批次⑨「存量对齐」：本项目原本就有自包含交互页（`kg/viz.render_html`，demo 写到临时目录、退出即清）。
本生成器把它**原位提升为提交物** `web/showcase.html`——原页的 SVG/JS/CSS 与"点节点高亮闭包"的
交互分毫不动，只在页首加实测数字卡、页尾加"怎么自己跑"与生成物标记，并按 showcase/SPEC 补齐
`data-showcase` / 三个锚点 / `lang="zh-CN"`。

数据全部现算：图谱直接来自 `data/*.csv`（与 demo 同一 API，不走第二份实现）；闭包/解锁/缺口/路径
由 `kg.graph` 现算；"四段演示原文"由真跑 `demo.py` 后引入（规范化：临时目录路径 → `<临时目录>`）。

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

sys.path.insert(0, str(ROOT))


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
    """演示里唯一波动的：临时目录路径（mkdtemp 随机后缀）。"""
    # 用函数替换：替换串里的反斜杠会触发 re 模板转义（bad escape \k）
    return re.sub(r"[A-Za-z]:\\[^\s]*\\kg_graph\.html",
                  lambda m: "<临时目录>\\kg_graph.html", text)


SHELL_CSS = """
.sw-top{max-width:1100px;margin:12px 18px 0;padding:10px 14px;background:#fff;border:1px solid #d5d9e0;border-radius:10px}
.sw-top .sw-link{font-size:13px;color:#1d4ed8;text-decoration:none}
.sw-top h2{font-size:16px;margin:6px 0 2px}
.sw-top p{margin:2px 0;color:#5f6773;font-size:13px}
.sw-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:8px;margin:10px 18px 0}
.sw-card{background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:8px 12px;font-size:13px}
.sw-card b{display:block;font-size:12px;color:#5f6773;margin-bottom:2px}
.sw-panel{max-width:1100px;margin:10px 18px 0;background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:10px 14px;font-size:14px}
.sw-panel kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid #d5d9e0;border-radius:4px;padding:0 4px;background:#fff}
.sw-panel pre{background:#0f1115;color:#e6e9ef;border-radius:8px;padding:10px 12px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.sw-footer{max-width:1100px;margin:14px 18px 26px;color:#5f6773;font-size:13px}
"""


def _promote(artifact: str, pid: str, title: str, banner: str, cards_html: str,
             repro_html: str) -> str:
    """把项目自己的自包含 HTML 原位提升为展示页：只做合规补齐，不动原内容。"""
    out = artifact
    out = out.replace('<html lang="zh">', '<html lang="zh-CN">')
    if 'lang="zh-CN"' not in out:
        raise SystemExit("artifact 的 <html lang> 不是 zh / zh-CN——提升逻辑要跟着改")
    out = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", out, count=1, flags=re.S)
    out = out.replace("</head>", f"<style>{SHELL_CSS}</style></head>", 1)
    m = re.search(r"<body([^>]*)>", out)
    if not m or "data-showcase" in m.group(0):
        raise SystemExit("<body> 标签不在预期形态（提升逻辑要跟着改）")
    head = (f'<body data-showcase="{pid}">\n'
            f'<div class="sw-top"><a class="sw-link" href="../../../showcase/index.html">'
            f'← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B37-industry-ai/web/showcase.html">B37</a>　·　下一件 <a href="../../../projects/B28-bi-dashboard/web/showcase.html">B28</a></span>　·　<a href="#lab">实时实验台</a><h2>{html.escape(banner)}</h2>'
            f'<p>本页是批次⑨「存量对齐」：原自包含交互页（{html.escape(pid)} 自己的生成器产物）'
            f'原位提升为提交物，交互与数据分毫未改；上面加实测数字、下面加运行方式。</p></div>\n'
            f'<section id="facts" class="sw-cards">{cards_html}</section>\n'
            f'<section id="demo">')
    out = out[:m.start()] + head + out[m.end():]
    out = out.replace("</body>", f"</section>\n{repro_html}\n"
                                 f'<section id="lab" class="sw-panel"><h3>实时实验台</h3>\n<div id="lab-slot">\n<p><b>实验台未启动</b>：本页仍是静态生成物，双击即看；启动实验台后，这块会就地变成控制台——真启停后端服务、发原始请求（字节进字节出）、看实时日志、跑演示/测试。</p>\n<ul>\n<li>双击仓库根 <kbd>lab.bat</kbd>（或终端 <kbd>python showcase\\lab.py</kbd>），然后刷新本页；</li>\n<li>只起服务不弹浏览器：<kbd>lab.bat no-open</kbd>；自检：<kbd>lab.bat selftest</kbd>。</li>\n</ul>\n</div>\n</section>\n'
                                 f'<div class="sw-footer"><p>生成物：python tools/showcase.py --write'
                                 f'（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。'
                                 f'交互页本身由本项目既有生成器产出。</p></div>\n<script>\n/* 实时实验台引导（双击 lab.bat 启动实验台后，页内该分节自动变成控制台） */\n"use strict";\nvar s=document.createElement("script");\ns.src=(location.protocol==="http:")?("/showcase/lab.js"):"http:\\/\\/127.0.0.1:7788/showcase/lab.js";\ndocument.body.appendChild(s);\n</script>\n</body>', 1)
    return out


def collect() -> dict:
    from kg.graph import load_default
    from kg.viz import render_html

    g = load_default()
    demo = _norm(_run([sys.executable, "demo.py"]))
    artifact = render_html(g)

    kinds = {}
    for e in g.edges:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    anc_b9 = " / ".join(sorted(g.ancestors("B9")))
    des_b11 = len(g.descendants("B11"))
    done12 = {"B1", "B2", "B5", "B6", "B7", "B8"}
    miss8 = g.missing_prereqs("B18", done12)
    done3 = {"B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "B11", "B12"}
    miss5 = g.missing_prereqs("B18", done3)
    path = g.learning_path("B18")

    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    method_core = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                      for p in sorted(TESTS.glob("test_*.py")) if p.name != "test_showcase.py")
    facts = [
        ["图谱", f"{len(g.nodes)} 个任务节点 / {len(g.edges)} 条边（先修 {kinds.get('先修', 0)} · "
              f"概念支撑 {kinds.get('概念支撑', 0)} · 迭代阶段 {kinds.get('迭代阶段', 0)}；每条边带 source 列）"],
        ["闭包查询", f"B9 的全部先修（含间接）= {anc_b9}（与测试内独立 DFS 交叉验证）"],
        ["解锁", f"B11 解锁 {des_b11} 个下游任务（含 B31/B30/B35/B38 与其下游）"],
        ["缺先修与路径", f"做完批次 1-2 后做 B18 还缺 {len(miss8)} 项；做完批次 3 后缺 {len(miss5)} 项；"
                   f"通往 B18 的学习路径 {len(path)} 步"],
        ["交互", "点击任意节点：红色高亮其全部先修（含间接）、蓝色高亮解锁后继——纯内嵌 JSON + 手写 JS，零外部请求"],
        ["测试", f"{method_count} 项（{method_core} 核心 + {method_count - method_core} 展示页自测）"],
    ]
    return {"facts": facts, "demo": demo, "artifact": artifact, "path": path,
            "miss8": sorted(miss8), "miss5": sorted(miss5), "des_b11": des_b11,
            "n_nodes": len(g.nodes), "n_edges": len(g.edges)}


# ------------------------------------------------------------------ 渲染

def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="sw-card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    repro = (
        '<section id="repro" class="sw-panel"><h3 style="margin:4px 0 6px;font-size:15px">怎么自己跑</h3>'
        "<ul><li><kbd>run.bat</kbd>：三步（自测 → 四段演示 → 展示页新鲜度）。</li>"
        "<li><kbd>python demo.py</kbd>：四段演示（交互 HTML 写临时目录、退出即清）。</li>"
        "<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li></ul>"
        '<p class="sw-note" style="color:#5f6773;font-size:13px">学习路径（现算，' + str(len(p["path"])) + " 步）："
        + e(" -> ".join(p["path"])) + "</p>"
        '<details><summary style="cursor:pointer;color:#1d4ed8">四段演示原文（规范化的临时目录路径已替换）</summary>'
        f'<pre>{e(p["demo"].rstrip())}</pre></details></section>')
    return _promote(p["artifact"], "B27-course-kg",
                    "B27-course-kg · 课程先修知识图谱（课设作品集）",
                    f"B27-course-kg · 课程先修知识图谱：{p['n_nodes']} 门任务、"
                    f"{p['n_edges']} 条带来源的依赖边",
                    cards, repro)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B27 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（交互页原位提升 + 现算数字卡）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（交互页/数字卡/路径）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
