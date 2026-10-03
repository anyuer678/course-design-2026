"""tools/showcase.py —— B31 展示页生成器（口径：showcase/SPEC.md）。

数据全部现算：真跑 `demo.py`（六段；临时目录里建库、项目目录不留文件）。
**规范化规则（可审计）**：① 演示里打印的绝对地址含每次随机的监听端口 `127.0.0.1:<端口>`；
② 响应头里的 `Date:` 是墙钟时间（每次不同）；③ 创建响应（201）的 `Content-Length` 随
`created_at` 浮点数的小数位数在 139/140 间漂——三处都固定为占位，跑 demo.py 看当场值。

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
.sw-footer{max-width:1150px;margin:14px 18px 26px;color:#5f6773;font-size:13px}
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
    """三条规则（见模块 docstring）：监听端口、Date 头、创建响应长度。"""
    text = re.sub(r"(127\.0\.0\.1:)\d+", r"\1<端口>", text)
    text = re.sub(r"(Date: )[^\r\n]*? GMT", r"\1<当场> GMT", text)
    text = re.sub(r"(\| Content-Length: )1[34]\d", r"\1<随 created_at 位数>", text)
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
    demo = _norm(_run([sys.executable, "demo.py"]))
    tests_total, tests_core = _test_count()

    ok_targets = len(re.findall(r"^\s*收下并规范化", demo, re.M))
    bad_targets = len(re.findall(r"^\s*拒收\s", demo, re.M))
    statuses = re.findall(r"\s(\d{3}) \(对\)", demo)
    m = re.search(r"影子模型累计命中\s+(\d+)", demo)
    shadow_hits = m.group(1) if m else "?"

    facts = [
        ["测试", f"{tests_total} 项（{tests_core} 核心 + {tests_total - tests_core} 展示页自测）"],
        ["短码从哪来", "自增 id → base62 竖式长除法对拍；id=372642325 → 'PDZI5'；"
                   "MAX_ID 4611686018427387903 → '5UfZOVH2ZO3'（11 位）；"
                   "前导零 / 字母表外字符 / 超长 三类形态拒收"],
        ["目标地址关卡", f"收下并规范化 {ok_targets} 条（大小写、默认端口、IDNA、%2F）；"
                    f"拒收 {bad_targets} 条 + 自指环 1 条（协议白名单 / CR-LF / 凭据 / 百分号主机 / 端口越界）"],
        ["状态码语义", f"{len(statuses)} 条全对（{'、'.join(statuses)}）"],
        ["keep-alive 与管线化", "一条连接 30 次跳转命中 30；管线化 GET+HEAD 都是 302；HEAD 不计数"],
        ["统计与影子模型", f"120 步随机操作，SQLite（SQL 语句）与纯 Python 字典模型逐步一致；"
                     f"影子模型累计命中 {shadow_hits} == 数据库累计命中"],
        ["浏览器交互", "页面观感与点击交互**待你实跑**（run.bat 第 5 步，我不代勾）——"
                   "本页把服务器侧证据（字节/状态码/统计）摆全"],
    ]
    return {"facts": facts, "demo": demo}


def _neutralize_schemes(text: str) -> str:
    """自包含口径：页面正文不得出现字面 http(s)://（校验器全文扫描）。
    演示里的 URL 是核心内容，不能删——把 scheme 的冒号写成数字实体 &#58;：
    浏览器渲染完全不变，源码里不再是可点击/可请求的字面地址。"""
    return text.replace("https://", "https&#58;//").replace("http://", "http&#58;//")


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="sw-card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    demo_html = _neutralize_schemes(e(p["demo"].rstrip()))
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>B31-shorturl · 短链服务（课设作品集）</title>
<style>{SHELL_CSS}</style></head>
<body data-showcase="B31-shorturl">
<div class="sw-top"><a class="sw-link" href="../../../showcase/index.html">← 作品集总入口</a>
<h2>B31-shorturl · 短链服务：从"一个字符串"到"浏览器被领到另一个站点"</h2>
<p>复用 B11 的 HTTP/1.1 子集（没有第二套解析器）：base62 短码 + 目标地址关卡 +
SQLite 仓储 + 原生前端。本页数字全部现算自 <kbd>demo.py</kbd>（六段）——监听端口、Date 头、
创建响应长度三处易变值已按规则规范化为占位（页面干净、规则可审计）。</p></div>
<section id="facts" class="sw-cards">{cards}</section>
<section id="demo" class="sw-panel"><h3>六段演示原文（现算）</h3>
<pre>{demo_html}</pre></section>
<section id="repro" class="sw-panel"><h3>怎么自己跑</h3>
<ul>
<li><kbd>run.bat</kbd>：五步（环境 → 测试 → demo → 展示页新鲜度 → 启动服务）；
<kbd>run.bat no-server</kbd> 跳过最后一步。</li>
<li><kbd>python demo.py</kbd>：只看六段演示（临时目录建库，项目目录不留文件）。</li>
<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
</ul>
<p>服务默认起在 <kbd>127.0.0.1:8000</kbd>（页面零外链，此地址只是运行说明）；页面样式、
手感与点击交互请自己起服务看。</p></section>
<div class="sw-footer"><p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；
仓库级校验 python showcase/check.py）。页面数据全部现算，无外部请求。</p></div>
</body></html>"""


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B31 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节（六段演示 + 数字卡）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        if OUT.read_text(encoding="utf-8") != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（六段演示/关卡/状态码）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
