"""tools/showcase.py —— B14 展示页生成器（口径：showcase/SPEC.md）。

数据全部现算：**自包含构建**（缺 build 即重建：javac --release 17 → build/classes +
build/test-classes，与 run.bat 同命令行），再真跑：
  - `paint.PaintTests`（headless 自检，8 组 / 7054 项检查）→ 逐组结论上页面；
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
"""


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
<div class="sw-top"><a class="sw-link" href="../../../showcase/index.html">← 作品集总入口</a>
<h2>B14-java-paint · 图形编辑器：命令/撤销重做 + 可信存盘 + 离屏渲染</h2>
<p>纯 Java（零第三方库）：图形类体系与命令模式、原子写盘与读取防线、离屏渲染像素对账、
Swing 事件语义、随机操作 vs 快照模型。本页数字全部现算——生成器按 run.bat 同命令行自包含
构建，再真跑自检与离屏演示；<b>图是当场画出来的真产物</b>，不是示意图。</p></div>
<section id="facts" class="sw-cards">{cards}</section>
<section id="demo" class="sw-panel"><h3>自检 8 组（headless 现场输出）</h3>
{module_table}
<h3 style="margin-top:10px">离屏演示原文（现算；PNG 临时文件名已规范化）</h3>
<pre>{e(p["demo"])}</pre>
<h3 style="margin-top:10px">当场画出来的图（data URI 内嵌，sha1 {p["png_sha"][:12]}…）</h3>
<img class="sw-shot" alt="离屏演示：矩形 + 椭圆 + 线段" src="data:image/png;base64,{p["png_b64"]}">
<details style="margin-top:8px"><summary style="cursor:pointer;color:#1d4ed8">自检总输出原文（含逐组检查数）</summary>
<pre>{e(p["selftest"])}</pre></details></section>
<section id="repro" class="sw-panel"><h3>怎么自己跑</h3>
<ul>
<li><kbd>run.bat</kbd>：五步（编译 → 自检 → 离屏演示 → 展示页新鲜度 → 打开窗口）；
<kbd>run.bat no-gui</kbd> 跳过窗口（构建在 %TEMP% 里，项目目录零残留）。</li>
<li><kbd>java -Djava.awt.headless=true -cp build\\classes paint.App --demo</kbd>：只看离屏演示。</li>
<li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
</ul>
<p>Swing 窗口的手感、键盘与拖拽的真实表现请自己开窗口试——自动化只到离屏语义这一层。</p></section>
<div class="sw-footer"><p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；
仓库级校验 python showcase/check.py）。页面数据全部现算，无外部请求。</p></div>
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
            return 1
        print("展示页新鲜：与现算逐字一致（自检/离屏演示/PNG）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
