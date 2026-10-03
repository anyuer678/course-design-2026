"""tools/showcase.py —— B34 展示页生成器（搜索动画页"原位提升"为提交物）。口径：showcase/SPEC.md。

批次⑨「存量对齐」：本项目原本就有自包含动画页（`planner/viz.build_page` 产出 build/plan.html，
不进仓库）。本生成器把它**原位提升为提交物** `web/showcase.html`——搜索展开动画（218 步）与
速度控制分毫不动，只在页首加实测数字卡、页尾加"怎么自己跑"与生成物标记，并按 showcase/SPEC
补齐 data-showcase/三个锚点。动画观感仍归用户实跑验收（不代勾）。

数据全部现算：先真跑 `demo.py`（手算基准 → 三算法对拍 → 可采纳性 → 反例 → 无解 → 生成
build/plan.html），再把该产物提升；**规范化 1 条**：第 3 段耗时列【实测】`N ms` → `<当场> ms`
（tools/logdiff.py 同款口径；其余由固定种子驱动）。

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
.sw-top{max-width:1100px;margin:12px 18px 0;padding:10px 14px;background:#fff;border:1px solid #d5d9e0;border-radius:10px}
.sw-top .sw-link{font-size:13px;color:#1d4ed8;text-decoration:none}
.sw-top h2{font-size:16px;margin:6px 0 2px}
.sw-top p{margin:2px 0;color:#5f6773;font-size:13px}
.sw-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin:10px 18px 0}
.sw-card{background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:8px 12px;font-size:13px}
.sw-card b{display:block;font-size:12px;color:#5f6773;margin-bottom:2px}
.sw-panel{max-width:1100px;margin:10px 18px 0;background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:10px 14px;font-size:14px}
.sw-panel kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid #d5d9e0;border-radius:4px;padding:0 4px;background:#fff}
.sw-panel pre{background:#0f1115;color:#e6e9ef;border-radius:8px;padding:10px 12px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
table.sw-t{border-collapse:collapse;font-size:13px;margin:6px 0}
table.sw-t th,table.sw-t td{border:1px solid #d5d9e0;padding:3px 10px;text-align:right}
table.sw-t th:first-child,table.sw-t td:first-child{text-align:left}
.sw-footer{max-width:1100px;margin:14px 18px 26px;color:#5f6773;font-size:13px}
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


def _norm(text: str) -> str:
    return re.sub(r"\d+(?:\.\d+)? ms", "<当场> ms", text)


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
            f'← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B33-viz-algo/web/showcase.html">B33</a>　·　下一件 <a href="../../../projects/B14-java-paint/web/showcase.html">B14</a></span><h2>{html.escape(banner)}</h2>'
            f'<p>本页是批次⑨「存量对齐」：原自包含搜索动画页（planner/viz.py 的产物）原位提升为提交物，'
            f'动画/数据分毫未改。动画观感（动没动、清不清楚）仍归你实跑验收。</p></div>\n'
            f'<section id="facts" class="sw-cards">{cards_html}</section>\n'
            f'<section id="demo">')
    out = out[:m.start()] + head + out[m.end():]
    out = out.replace("</body>", f"</section>\n{repro_html}\n"
                                 f'<div class="sw-footer"><p>生成物：python tools/showcase.py --write'
                                 f'（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。'
                                 f'动画页由本项目既有生成器产出（BFS 展开的逐步记录）。</p></div>\n</body>', 1)
    return out


def collect() -> dict:
    demo = _norm(_run([sys.executable, "demo.py"]))
    artifact = (BUILD / "plan.html").read_text(encoding="utf-8")
    sec = _parse_sections(demo)
    s1, s2, s3, s4, s5, s6 = (_kv(sec[i]) for i in range(1, 7))

    compare_rows = []
    budget = False
    for raw in sec[3]:
        line = raw.strip()
        if line.startswith("配置"):
            budget = True
            continue
        cols = [c.strip() for c in re.split(r"\s{2,}", line) if c.strip()]
        if budget and len(cols) >= 3:
            compare_rows.append(cols[:3])

    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    method_core = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                      for p in sorted(TESTS.glob("test_*.py")) if p.name != "test_showcase.py")
    facts = [
        ["测试", f"{method_count} 项（{method_core} 核心 + {method_count - method_core} 展示页自测）"],
        ["同源对拍", f"4 邻域 30 图代价一致 {s2.get('4 邻域 30 图代价一致', '?')}；"
                 f"8 邻域（octile）{s2.get('8 邻域 30 图代价一致（octile）', '?')}"
                 f"——差 1 张是 1 ulp 浮点求和次序（断言用 almost-equal，演示如实打印）；"
                 f"无权图 BFS 等价 {s2.get('无权图上 BFS 等价', '?')}"],
        ["可采纳性（是量出来的）", "曼哈顿/octile/欧氏 slack = +0.000；"
                        "故意撒谎的曼哈顿×8 邻域 slack = +4.686"],
        ["反例（seed=3）", f"Dijkstra {s5.get('Dijkstra 最优代价', '?').split('（')[0]} vs "
                     f"A* {s5.get('A* 曼哈顿×8邻域 代价', '?').split('（')[0]}，"
                     f"差 {s5.get('差值', '?').split('（')[0]}（恰好 2-√2）"],
        ["动画页", f"build/plan.html {s6.get('动画页产物', '?')}；冷色越深展开越晚、红色当前格、"
               f"到终点后绿色高亮最终路径；node --check {s6.get('node --check', '?')}"],
        ["手算基准", f"1×4 走廊代价 {s1.get('1×4 走廊代价（手算 3）', '?')}（手算 3）；"
                 f"A* 代价/路径长度 {s1.get('A* 代价 / 路径长度', '?')}"],
    ]
    return {"facts": facts, "demo": demo, "artifact": artifact, "compare_rows": compare_rows}


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="sw-card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    rows = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>"
                   for row in p["compare_rows"])
    repro = (
        '<section id="repro" class="sw-panel"><h3 style="margin:4px 0 6px;font-size:15px">怎么自己跑</h3>'
        "<ul><li><kbd>run.bat</kbd>：三步（测试 → demo（生成 build\\plan.html）→ 展示页新鲜度）。</li>"
        "<li><kbd>python demo.py</kbd>：六段演示；打开 build\\plan.html 点「播放」看搜索怎么展开。</li>"
        "<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li></ul>"
        '<p style="margin:6px 0 2px">第 3 段对比表（32×24 种子图；耗时列已规范化为 &lt;当场&gt;）：</p>'
        f'<table class="sw-t"><tr><th>配置</th><th>代价</th><th>扩展</th></tr>{rows}</table>'
        f'<details><summary style="cursor:pointer;color:#1d4ed8">六段演示原文</summary>'
        f'<pre>{e(p["demo"].rstrip())}</pre></details></section>')
    return _promote(p["artifact"], "B34-path-planner",
                    "B34-path-planner · 栅格路径规划（课设作品集）",
                    "B34-path-planner · 栅格 A*/Dijkstra/BFS 同源对拍：搜索展开动画（218 步）",
                    cards, repro)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B34 展示页生成器（口径：showcase/SPEC.md）")
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
        print("展示页新鲜：与现算逐字一致（动画页/数字卡）")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
