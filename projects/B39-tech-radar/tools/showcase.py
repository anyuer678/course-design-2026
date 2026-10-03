"""tools/showcase.py —— B39 展示页生成器（口径：showcase/SPEC.md）。

数据全部现算：真跑 `demo.py`（四段演示；全种子化、无计时输出——两遍运行逐字相同），
把示例记录的检查器结论、三条"改坏必须红"的负面对照、CRDT 收敛性质一起搬上页面；
示例记录本身（`docs/records/example-crdt.md`）也作为可折叠原文内嵌（它就是交付物本体）。

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
EXAMPLE = ROOT / "docs" / "records" / "example-crdt.md"

SHELL_CSS = """
body{font-family:"Microsoft YaHei",system-ui,sans-serif;margin:0;background:#f4f6f9;color:#1c2330}
.sw-top{max-width:1100px;margin:12px 18px 0;padding:10px 14px;background:#fff;border:1px solid #d5d9e0;border-radius:10px}
.sw-top .sw-link{font-size:13px;color:#1d4ed8;text-decoration:none}
.sw-top h2{font-size:16px;margin:6px 0 2px}
.sw-top p{margin:2px 0;color:#5f6773;font-size:13px}
.sw-cards{max-width:1100px;display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin:10px 18px 0}
.sw-card{background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:8px 12px;font-size:13px}
.sw-card b{display:block;font-size:12px;color:#5f6773;margin-bottom:2px}
.sw-panel{max-width:1100px;margin:10px 18px 0;background:#fff;border:1px solid #d5d9e0;border-radius:10px;padding:10px 14px;font-size:14px}
.sw-panel h3{margin:4px 0 6px;font-size:15px}
.sw-panel pre{background:#0f1115;color:#e6e9ef;border-radius:8px;padding:10px 12px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.sw-panel kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid #d5d9e0;border-radius:4px;padding:0 4px;background:#fff}
.sw-panel table{border-collapse:collapse;width:100%;font-size:13px}
.sw-panel th,.sw-panel td{border:1px solid #d5d9e0;padding:4px 8px;text-align:left;vertical-align:top}
.sw-panel th{background:#eef2f7}
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
    example = EXAMPLE.read_text(encoding="utf-8")

    m = re.search(r"检查示例记录\s+(PASS[^\n]*)", demo)
    checked = m.group(1).strip() if m else "?"
    m = re.search(r"核验的指针\s+([^\n]*)", demo)
    pointers = m.group(1).strip() if m else "?"
    reds = len(re.findall(r"RED，首条：", demo))
    m = re.search(r"收敛性（100 组置换）\s+([^\n]*)", demo)
    converge = m.group(1).strip() if m else "?"
    m = re.search(r"并列计数器的赢家\s+([^\n]*)", demo)
    winner = m.group(1).strip() if m else "?"
    m = re.search(r"性质抽查（50 组随机）\s+([^\n]*)", demo)
    props = m.group(1).strip() if m else "?"

    facts = [
        ["测试", f"{tests_total} 项（{tests_core} 核心 + {tests_total - tests_core} 展示页自测）"],
        ["示例记录检查", f"{checked}；{pointers}"],
        ["负面对照（检查器有没有牙齿）", f"{reds} 条改坏全部报红且红在该原因上"
                                    f"（删必需小节 / 指针指向不存在文件 / 假提交号）"],
        ["CRDT 收敛复现", f"100 组置换（{converge}）；并列计数器的赢家 {winner}"],
        ["性质抽查", props],
        ["记录五节结构", "问题 / 原理 / 证据（可核验指针）/ 局限与适用边界 / 复现——缺节即红"],
    ]
    return {"facts": facts, "demo": demo, "example": example}


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="sw-card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>B39-tech-radar · 技术雷达（课设作品集）</title>
<style>{SHELL_CSS}</style></head>
<body data-showcase="B39-tech-radar">
<div class="sw-top"><a class="sw-link" href="../../../showcase/index.html">← 作品集总入口</a>
<h2>B39-tech-radar · 技术雷达：记录模板 + 可机验证据 + 一次最小复现</h2>
<p>把"讲座笔记"变成<b>可核验</b>的资产：证据节里的每条指针（仓库路径 / @提交号）都会被
<kbd>tools/check_record.py</kbd> 真的去仓库和 git 里找一遍——找不到就红。本页数字全部现算自
<kbd>demo.py</kbd>（种子化、无计时输出）与示例记录本体。</p></div>
<section id="facts" class="sw-cards">{cards}</section>
<section id="demo" class="sw-panel"><h3>四段演示原文（现算）</h3>
<pre>{e(p["demo"].rstrip())}</pre></section>
<section class="sw-panel"><h3>示例记录原文 · docs/records/example-crdt.md（交付物本体）</h3>
<details><summary style="cursor:pointer;color:#1d4ed8">展开示例记录（来源栏明确写着"示例（非真实讲座）"）</summary>
<pre>{e(p["example"].rstrip())}</pre></details></section>
<section id="repro" class="sw-panel"><h3>怎么自己跑</h3>
<ul>
<li><kbd>run.bat</kbd>：三步（测试 → demo → 展示页新鲜度）；<kbd>python demo.py</kbd> 只看演示。</li>
<li>把你自己的讲座记录放进 <kbd>docs\\records\\</kbd>，跑 <kbd>python tools\\check_record.py docs\\records\\你的.md</kbd>；
红了就改——指针不存在意味着这条"证据"其实没人验证过。</li>
<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
</ul></section>
<div class="sw-footer"><p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；
仓库级校验 python showcase/check.py）。页面数据全部现算，无外部请求。</p></div>
</body></html>"""


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B39 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节（四段演示 + 示例记录内嵌）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        if OUT.read_text(encoding="utf-8") != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（检查器/负面对照/CRDT 收敛 + 示例记录）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
