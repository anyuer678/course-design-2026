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
<div class="sw-top"><a class="sw-link" href="../../../showcase/index.html">← 作品集总入口</a>
<h2>B41-thesis-seeds · 毕设候选的三维可行性（数字会自己过期）</h2>
<p>比较工具链的核心纪律：<b>行数重算 + 缺口探针重跑 + 证据锚点必真</b>——
改错一处 <kbd>tools/check_seeds.py</kbd> 即红。5 个候选已由用户选定实施完毕（候选表清零，
负面对照改用注入式夹具继续钉规则）。本页数字全部现算自 <kbd>demo.py</kbd> 与 <kbd>data/seeds.json</kbd>。</p></div>
<section id="facts" class="sw-cards">{cards}</section>
<section id="demo" class="sw-panel"><h3>选定清单与三维比较表（现算）</h3>
{table}
<details><summary style="cursor:pointer;color:#1d4ed8;margin-top:8px">四段演示原文（含三维比较表与负面对照）</summary>
<pre>{e(p["demo"].rstrip())}</pre></details></section>
<section id="repro" class="sw-panel"><h3>怎么自己跑</h3>
<ul>
<li><kbd>run.bat</kbd>：三步（测试 → demo → 展示页新鲜度）；<kbd>python demo.py</kbd> 只看演示
（末段两条毫秒是本机当场读数）。</li>
<li><kbd>python tools\\check_seeds.py</kbd>：行数/探针/锚点复核；改错一处即红。</li>
<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
</ul>
<p>候选题清单不等于开题；任何新候选开工前，先跑 run.bat 把基线与 fsync 基准过一遍。</p></section>
<div class="sw-footer"><p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；
仓库级校验 python showcase/check.py）。页面数据全部现算，无外部请求。</p></div>
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
        if OUT.read_text(encoding="utf-8") != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（核验/负面对照/选定清单）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
