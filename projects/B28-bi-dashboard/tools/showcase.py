"""tools/showcase.py —— B28 展示页生成器（BI 看板"原位提升"为提交物）。口径：showcase/SPEC.md。

批次⑨「存量对齐」：本项目原本就有手写 SVG 看板（`bi/render.dashboard()`，静态导出写临时目录）。
本生成器把它**原位提升为提交物** `web/showcase.html`——看板的 SVG/表格与"每图配等价数据表"
分毫不动，只在页首加实测数字卡、页尾加"怎么自己跑"（含**指标血缘图**内嵌）与生成物标记，
并按 showcase/SPEC 补齐 `data-showcase` / 三个锚点 / 引号风格（原页用单引号属 HTML 合法但
校验器按双引号字符串比对）。

数据全部现算：看板由 `bi.render.dashboard()` 现算（与 demo/服务同一 API）；血缘图由
`bi.lineage.render()` 现算并只取 SVG+脚本+样式（**2026-10-03 修正**：原先复用 B27 渲染器的
默认来源说明把数据写成 courses.csv/prereqs.csv，属错误归属——已参数化改正）；
"六段演示原文"由真跑 `demo.py` 后引入（规范化：临时导出目录 → `<临时目录>`）。

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

SHELL_CSS = """
.sw-top{max-width:1100px;margin:12px 14px 0;padding:10px 14px;background:#fff;border:1px solid #d5d9e0;border-radius:10px}
.sw-top .sw-link{font-size:13px;color:#1d4ed8;text-decoration:none}
.sw-top h2{font-size:16px;margin:6px 0 2px}
.sw-top p{margin:2px 0;color:#5f6773;font-size:13px}
.sw-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin:10px 14px 0}
.sw-card{background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:8px 12px;font-size:13px}
.sw-card b{display:block;font-size:12px;color:#5f6773;margin-bottom:2px}
.sw-panel{max-width:1100px;margin:10px 14px 0;background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:10px 14px;font-size:14px}
.sw-panel kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid #d5d9e0;border-radius:4px;padding:0 4px;background:#fff}
.sw-panel pre{background:#0f1115;color:#e6e9ef;border-radius:8px;padding:10px 12px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.sw-footer{max-width:1100px;margin:14px;color:#5f6773;font-size:13px}
.sw-lin svg{max-width:100%;height:auto;display:block}
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
    return re.sub(r"[A-Za-z]:\\[^\s]*b28-dash[^\s]*", lambda m: "<临时目录>", text)


def _kv(lines) -> list:
    rows = []
    for raw in lines:
        cols = [c.strip() for c in re.split(r"\s{2,}", raw.strip()) if c.strip()]
        if len(cols) >= 2:
            rows.append((cols[0], " ".join(cols[1:])))
    return rows


def _find(rows: list, prefix: str) -> str:
    for k, v in rows:
        if k.startswith(prefix):
            return v
    return ""


def _trim(value: str) -> str:
    """去掉演示行尾的「← 两路一致」批注（卡片的结论另写）。"""
    return value.split("←")[0].strip()


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


def _extract(artifact: str, pattern: str, what: str) -> str:
    m = re.search(pattern, artifact, re.S)
    if not m:
        raise SystemExit(f"artifact 里找不到 {what}——提取逻辑要跟着改")
    return m.group(0)


def collect() -> dict:
    from bi import lineage as L
    from bi import render as R

    demo = _norm(_run([sys.executable, "demo.py"]))
    artifact = R.dashboard()
    lineage_html = L.render()
    lineage_svg = _extract(lineage_html, r"<svg.*?</svg>", "血缘 SVG")
    lineage_js = _extract(lineage_html, r"<script>.*?</script>", "血缘脚本")
    lineage_css = _extract(lineage_html, r"<style>.*?</style>", "血缘样式")
    lineage_note = _extract(lineage_html, r'<p class="hint">.*?</p>', "血缘来源说明")
    # 血缘样式里去掉 body/h1 两条会污染外壳的规则（其余 .node/.edge… 本页无同名类，保留）
    lineage_css = re.sub(r"(?m)^(body|h1)\s*\{[^}]*\}\n?", "", lineage_css)

    sec = _parse_sections(demo)
    s1, s2, s4, s5, s6 = (_kv(sec[i]) for i in (1, 2, 4, 5, 6))

    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    method_core = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                      for p in sorted(TESTS.glob("test_*.py")) if p.name != "test_showcase.py")
    facts = [
        ["测试", f"{method_count} 项（{method_core} 核心 + {method_count - method_core} 展示页自测）"],
        ["数据与清洗", f"脏明细 {_find(s1, '脏明细行数')} 行 → 清洗后 {_find(s1, '清洗后行数')} 行；"
                  f"五步缺陷按量注入、账本逐数对上（{_find(s1, '账本整体一致')}）"],
        ["六指标两路对拍", f"成交额 {_trim(_find(s2, '成交总额'))}；复购率 {_trim(_find(s2, '复购率'))}；"
                    f"履约 {_trim(_find(s2, '履约时长'))}；商品集中度 {_trim(_find(s2, 'TOP5 商品与集中度'))}"
                    f"——SQL 与纯 Python 参照**逐数相等**（异常清单：{_find(s2, '对拍异常清单')}）"],
        ["洞察", f"共购：{_find(s5, '篮子/频繁项集/规则')}；{_trim(_find(s5, '显示器 → 支架'))}；"
              f"分群 {_find(s5, '客户数 / k / 轮廓系数')}"],
        ["安全边界", f"B32 载荷当筛选值：{_find(s4, '载荷当品类筛的结果')}；"
                 f"表数量前/后 {_find(s4, '表数量 前/后')}；{_find(s4, '扫描器有没有牙齿')}"],
        ["看板自检", f"页面数字 == API 数字（{_find(s6, '页面里的数字是否等于 API')}）；"
                 f"自包含：{_find(s6, '页面自包含')}"],
    ]
    return {"facts": facts, "demo": demo, "artifact": artifact,
            "lineage_svg": lineage_svg, "lineage_js": lineage_js,
            "lineage_css": lineage_css, "lineage_note": lineage_note}


def _promote(artifact: str, pid: str, title: str, banner: str, cards_html: str,
             repro_html: str) -> str:
    out = artifact
    if out.lower().startswith("<!doctype html>"):
        out = "<!DOCTYPE html>" + out[len("<!doctype html>"):]
    out = out.replace("lang='zh-CN'", 'lang="zh-CN"').replace('lang="zh"', 'lang="zh-CN"')
    out = out.replace("<meta charset='utf-8'>", '<meta charset="utf-8">')
    if 'lang="zh-CN"' not in out or '<meta charset="utf-8">' not in out:
        raise SystemExit("artifact 的语言/编码声明不在预期形态——提升逻辑要跟着改")
    out = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", out, count=1, flags=re.S)
    out = out.replace("</head>", f"<style>{SHELL_CSS}</style></head>", 1)
    m = re.search(r"<body([^>]*)>", out)
    if not m or "data-showcase" in m.group(0):
        raise SystemExit("<body> 标签不在预期形态（提升逻辑要跟着改）")
    head = (f'<body data-showcase="{pid}">\n'
            f'<div class="sw-top"><a class="sw-link" href="../../../showcase/index.html">'
            f'← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B27-course-kg/web/showcase.html">B27</a>　·　下一件 <a href="../../../projects/B29-bigdata-spark/web/showcase.html">B29</a></span>　·　<a href="#lab">实时实验台</a><h2>{html.escape(banner)}</h2>'
            f'<p>本页是批次⑨「存量对齐」：本项目的自包含看板（bi/render 手写 SVG）原位提升为提交物，'
            f'图表与数据表分毫未改；上面加实测数字、下面加运行方式与指标血缘图。</p></div>\n'
            f'<section id="facts" class="sw-cards">{cards_html}</section>\n'
            f'<section id="demo">')
    out = out[:m.start()] + head + out[m.end():]
    out = out.replace("</body>", f"</section>\n{repro_html}\n"
                                 f'<section id="lab" class="sw-panel"><h3>实时实验台</h3>\n<div id="lab-slot">\n<p><b>实验台未启动</b>：本页仍是静态生成物，双击即看；启动实验台后，这块会就地变成控制台——真启停后端服务、发原始请求（字节进字节出）、看实时日志、跑演示/测试。</p>\n<ul>\n<li>双击仓库根 <kbd>lab.bat</kbd>（或终端 <kbd>python showcase\\lab.py</kbd>），然后刷新本页；</li>\n<li>只起服务不弹浏览器：<kbd>lab.bat no-open</kbd>；自检：<kbd>lab.bat selftest</kbd>。</li>\n</ul>\n</div>\n</section>\n'
                                 f'<div class="sw-footer"><p>生成物：python tools/showcase.py --write'
                                 f'（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。'
                                 f'看板与血缘图由本项目既有生成器产出。</p></div>\n<script>\n/* 实时实验台引导（双击 lab.bat 启动实验台后，页内该分节自动变成控制台） */\n"use strict";\nvar s=document.createElement("script");\ns.src=(location.protocol==="http:")?("/showcase/lab.js"):"http:\\/\\/127.0.0.1:7788/showcase/lab.js";\ndocument.body.appendChild(s);\n</script>\n</body>', 1)
    return out


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="sw-card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    repro = (
        '<section id="repro" class="sw-panel"><h3 style="margin:4px 0 6px;font-size:15px">怎么自己跑</h3>'
        "<ul><li><kbd>run.bat no-server</kbd>：前六步（环境 → 测试 → 政策核对 → 六段演示），不起服务。</li>"
        "<li><kbd>python -m bi.server --port 8010</kbd>：起真的本地服务，浏览器打开 127.0.0.1:8010（页面零外链，此地址只是运行说明）。</li>"
        "<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li></ul>"
        '<details><summary style="cursor:pointer;color:#1d4ed8">指标血缘图（每个指标都能追到清洗步骤与数据源；'
        '由 bi/lineage.py 现算，渲染复用 B27 的分层 SVG）</summary>'
        + p["lineage_css"] + f'<div class="sw-lin">{p["lineage_svg"]}</div>'
        + p["lineage_note"] + p["lineage_js"] + "</details>"
        + f'<details><summary style="cursor:pointer;color:#1d4ed8">六段演示原文'
          f'（规范化的临时导出目录已替换）</summary><pre>{e(p["demo"].rstrip())}</pre></details></section>')
    return _promote(p["artifact"], "B28-bi-dashboard",
                    "B28-bi-dashboard · 商务智能看板（课设作品集）",
                    "B28-bi-dashboard · 商务智能看板：口径当一等交付物，六指标两路对拍逐数相等",
                    cards, repro)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B28 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（看板原位提升 + 血缘图内嵌 + 现算数字卡）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（看板/血缘/数字卡）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
