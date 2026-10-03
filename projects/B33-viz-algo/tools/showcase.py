"""tools/showcase.py —— B33 展示页生成器（动画页"原位提升"为提交物）。口径：showcase/SPEC.md。

批次⑨「存量对齐」：本项目原本就有自包含动画页（`vizlab/page.build_page` 产出 build/viz.html，
不进仓库）。本生成器把它**原位提升为提交物** `web/showcase.html`——条形图/图遍历 SVG/播放控制
与"演的是真算法"的回放数据分毫不动（记录保真由本项目 11 项测试钉住），只在页首加实测数字卡、
页尾加"怎么自己跑"与生成物标记，并按 showcase/SPEC 补齐 data-showcase/三个锚点。

数据全部现算：先真跑 `demo.py`（导出记录 → 回放核对 → 生成 build/viz.html），再把该产物提升。
demo 输出无耗时数字（"本演示无耗时输出，两遍运行应逐字相同"），无需规范化。

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
BUILD = ROOT / "build"

sys.path.insert(0, str(ROOT))

SHELL_CSS = """
.sw-top{max-width:1300px;margin:12px 18px 0;padding:10px 14px;background:#fff;border:1px solid #d5d9e0;border-radius:10px}
.sw-top .sw-link{font-size:13px;color:#1d4ed8;text-decoration:none}
.sw-top h2{font-size:16px;margin:6px 0 2px}
.sw-top p{margin:2px 0;color:#5f6773;font-size:13px}
.sw-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin:10px 18px 0}
.sw-card{background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:8px 12px;font-size:13px}
.sw-card b{display:block;font-size:12px;color:#5f6773;margin-bottom:2px}
.sw-panel{max-width:1300px;margin:10px 18px 0;background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:10px 14px;font-size:14px}
.sw-panel kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid #d5d9e0;border-radius:4px;padding:0 4px;background:#fff}
.sw-panel pre{background:#0f1115;color:#e6e9ef;border-radius:8px;padding:10px 12px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.sw-footer{max-width:1300px;margin:14px 18px 26px;color:#5f6773;font-size:13px}
"""


def _run(args) -> str:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(map(str, args))} 退出码 {proc.returncode}：\n"
                         f"{(proc.stdout or '')[-400:]}\n{(proc.stderr or '')[-400:]}")
    return proc.stdout


def _parse_sections(text: str) -> dict:
    sections, current, buf = {}, None, []
    for line in text.splitlines():
        if set(line.strip()) == {"="} and line.strip():
            continue
        m = re.match(r"^\s*(\d+)\) (.+)$", line)
        if m:
            if current is not None:
                sections[current] = buf
            current, buf = int(m.group(1)), []
        elif current is not None:
            buf.append(line.rstrip())
    if current is not None:
        sections[current] = buf
    return sections


def _kv(lines) -> dict:
    out = {}
    for raw in lines:
        cols = [c.strip() for c in re.split(r"\s{2,}", raw.strip()) if c.strip()]
        if len(cols) >= 2:
            out[cols[0]] = " ".join(cols[1:])
    return out


def _promote(artifact: str, pid: str, title: str, banner: str, cards_html: str,
             repro_html: str) -> str:
    out = artifact
    if out.lower().startswith("<!doctype html>"):
        out = "<!DOCTYPE html>" + out[len("<!doctype html>"):]
    out = out.replace("lang='zh-CN'", 'lang="zh-CN"')
    if 'lang="zh-CN"' not in out:
        raise SystemExit("artifact 的 <html lang> 不是 zh-CN——提升逻辑要跟着改")
    out = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", out, count=1, flags=re.S)
    out = out.replace("</head>", f"<style>{SHELL_CSS}</style></head>", 1)
    m = re.search(r"<body([^>]*)>", out)
    if not m or "data-showcase" in m.group(0):
        raise SystemExit("<body> 标签不在预期形态（提升逻辑要跟着改）")
    head = (f'<body data-showcase="{pid}">\n'
            f'<div class="sw-top"><a class="sw-link" href="../../../showcase/index.html">'
            f'← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B29-bigdata-spark/web/showcase.html">B29</a>　·　下一件 <a href="../../../projects/B34-path-planner/web/showcase.html">B34</a></span>　·　<a href="#lab">实时实验台</a><h2>{html.escape(banner)}</h2>'
            f'<p>本页是批次⑨「存量对齐」：原自包含动画页（vizlab/page.py 的产物）原位提升为提交物，'
            f'动画/数据/控制条分毫未改。动画观感（动没动、清不清楚）仍归你实跑验收。</p></div>\n'
            f'<section id="facts" class="sw-cards">{cards_html}</section>\n'
            f'<section id="demo">')
    out = out[:m.start()] + head + out[m.end():]
    out = out.replace("</body>", f"</section>\n{repro_html}\n"
                                 f'<section id="lab" class="sw-panel"><h3>实时实验台</h3>\n<div id="lab-slot">\n<p><b>实验台未启动</b>：本页仍是静态生成物，双击即看；启动实验台后，这块会就地变成控制台——真启停后端服务、发原始请求（字节进字节出）、看实时日志、跑演示/测试。</p>\n<ul>\n<li>双击仓库根 <kbd>lab.bat</kbd>（或终端 <kbd>python showcase\\lab.py</kbd>），然后刷新本页；</li>\n<li>只起服务不弹浏览器：<kbd>lab.bat no-open</kbd>；自检：<kbd>lab.bat selftest</kbd>。</li>\n</ul>\n</div>\n</section>\n'
                                 f'<div class="sw-footer"><p>生成物：python tools/showcase.py --write'
                                 f'（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。'
                                 f'动画页由本项目既有生成器产出（演的是 build/traces 里的操作记录）。</p></div>\n<script>\n/* 实时实验台引导（双击 lab.bat 启动实验台后，页内该分节自动变成控制台） */\n"use strict";\nvar s=document.createElement("script");\ns.src=(location.protocol==="http:")?("/showcase/lab.js"):"http:\\/\\/127.0.0.1:7788/showcase/lab.js";\ndocument.body.appendChild(s);\n</script>\n</body>', 1)
    return out


def collect() -> dict:
    demo = _run([sys.executable, "demo.py"])
    artifact = (BUILD / "viz.html").read_text(encoding="utf-8")
    sec = _parse_sections(demo)
    s1, s2, s3, s4 = (_kv(sec[i]) for i in (1, 2, 3, 4))

    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    method_core = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                      for p in sorted(TESTS.glob("test_*.py")) if p.name != "test_showcase.py")
    facts = [
        ["测试", f"{method_count} 项（{method_core} 核心 + {method_count - method_core} 展示页自测）"],
        ["操作记录（C++ 导出）", f"堆排序 {s2.get('堆排序事件数', '?')} 事件（1 建堆 + 10 swap + 8 取顶 + 1 收尾）；"
                        f"三份 JSON 字节数 {s1.get('三份 JSON 字节数', '?')}"],
        ["回放保真", f"逐步回放失败 {s2.get('逐步回放失败步数（应为 0）', '?')} 步；"
                 f"终态 == 升序排序 {s2.get('最终状态 == 升序排序', '?')}；"
                 f"BFS {s2.get('BFS 步数 / 与独立参照一致', '?')}；DFS {s2.get('DFS 步数 / 与独立参照一致', '?')}"
                 f"（独立 Python 参照逐步对拍）"],
        ["页面", f"HTML {s3.get('HTML 字节数', '?')} 字节（内嵌数据 {s3.get('其中内嵌数据字节数', '?')} 字节）；"
              f"控制条：播放/暂停/单步/上一步/速度"],
        ["JS 语法体检", f"node --check 退出码 {s4.get('node --check 退出码', '?')}（无 node 则如实跳过）"],
        ["演的是真算法", "动画只移动'记录下标'，不重算算法；负面自证：改坏一条快照记录回放器必须报错（测试钉住）"],
    ]
    return {"facts": facts, "demo": demo, "artifact": artifact}


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="sw-card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    repro = (
        '<section id="repro" class="sw-panel"><h3 style="margin:4px 0 6px;font-size:15px">怎么自己跑</h3>'
        "<ul><li><kbd>run.bat</kbd>：三步（编译导出器+导出 → 测试 → demo（生成 build\\viz.html）→ 展示页新鲜度）。</li>"
        "<li><kbd>python demo.py</kbd>：导出 + 回放核对 + 生成动画页；打开 build\\viz.html 点「播放」。</li>"
        "<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li></ul>"
        f'<details><summary style="cursor:pointer;color:#1d4ed8">五段演示原文</summary>'
        f'<pre>{e(p["demo"].rstrip())}</pre></details></section>')
    return _promote(p["artifact"], "B33-viz-algo",
                    "B33-viz-algo · 算法可视化：操作记录回放（课设作品集）",
                    "B33-viz-algo · 算法可视化：B2 导出操作记录，回放成可交互动画（不重算算法）",
                    cards, repro)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B33 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（动画页原位提升 + 现算数字卡）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（动画页/数字卡）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
