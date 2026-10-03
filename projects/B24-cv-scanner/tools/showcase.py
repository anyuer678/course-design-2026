"""tools/showcase.py —— B24 展示页生成器（文档扫描仪：边缘检测 → 透视变换 → 二值化）。口径：showcase/SPEC.md。

数据全部现算，来源是真跑出来的 Python 产物（无计时数字）：

- 演示：`python demo.py`（约 2 秒）六段现场输出；六段全部由固定种子驱动，两遍逐字相同；
- **视觉验收画廊**：把 demo 写出的 `build/demo_*.png`（同一套产物，不另造数据）用 cv2 缩到
  宽 340px 后 base64 内联进页面——原始字节数标在每张图下（728485/244251/3069 现算）；
- 测试数按 tests/ 里 `def test_` 静态现数（不跑 discover——跑会在"展示页测试调 collect"时递归）。

页面写 `web/showcase.html`；`--check` 重算比对（不写盘），过期即红。
"""
from __future__ import annotations

import argparse
import base64
import html
import os
import re
import subprocess
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"
BUILD = ROOT / "build"

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


def _parse_sections(text: str) -> list:
    sections, current = [], None
    for line in text.splitlines():
        if set(line.strip()) == {"="} and line.strip():
            continue
        m = re.match(r"^\s*(\d+)\) (.+)$", line)
        if m:
            current = {"no": int(m.group(1)), "title": m.group(2), "lines": []}
            sections.append(current)
        elif current is not None:
            current["lines"].append(line.rstrip())
    return sections


def _split_cols(line: str) -> list:
    return [c.strip() for c in re.split(r"\s{2,}", line.strip()) if c.strip()]


def _kv(section: dict) -> dict:
    out = {}
    for raw in section["lines"]:
        cols = _split_cols(raw)
        if len(cols) >= 2:
            out[cols[0]] = " ".join(cols[1:])
    return out


def _thumb(path: Path, fmt: str = "jpeg", width: int = 340) -> dict:
    """把 build/ 里的产物缩成内联缩略图（同一份产物，确定性缩放 + 编码）。

    读文件走 `cvscan.io.load_png`（Python 读字节 + imdecode），绕开 cv2 对中文路径的坑。
    照片类画面用 JPEG（质量 82，页面体积控制）；二值图用 PNG（清晰且本就极小）。
    两者对同一输入像素都是确定性的（同机同版本库）。
    """
    from cvscan import io as cvio
    image = cvio.load_png(path)
    h, w = image.shape[:2]
    scale = width / w
    small = cv2.resize(image, (width, max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    if fmt == "jpeg":
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 82])
        mime = "jpeg"
    else:
        ok, buf = cv2.imencode(".png", small)
        mime = "png"
    if not ok:
        raise SystemExit(f"缩略图编码失败：{path}")
    return {"data_uri": f"data:image/{mime};base64," + base64.b64encode(buf.tobytes()).decode("ascii"),
            "orig_bytes": path.stat().st_size, "orig_size": f"{w}x{h}", "thumb_w": width}


def collect() -> dict:
    demo = _run([sys.executable, "demo.py"])
    sections = _parse_sections(demo)
    by_no = {s["no"]: s for s in sections}
    s1, s2, s3, s4, s5, s6 = (by_no[i] for i in range(1, 7))
    kv1, kv2, kv3, kv4, kv5, kv6 = (_kv(s) for s in (s1, s2, s3, s4, s5, s6))

    # 失败样例：五类，取「原因」做对照
    failures = []
    for raw in s5["lines"]:
        cols = _split_cols(raw)
        if len(cols) >= 2 and "应拒识" in cols[0]:
            reason = cols[1].split("原因：", 1)[-1]
            failures.append((cols[0].replace("（应拒识）", ""), reason))

    gallery = [
        ("原始“照片”（透视输入，真值四角是摆好的）", _thumb(BUILD / "demo_input.png")),
        ("检测 → 透视还原（拉正后的文档）", _thumb(BUILD / "demo_rectified.png")),
        ("Otsu 二值化（与真值掩码逐像素对账）", _thumb(BUILD / "demo_binary.png", fmt="png")),
    ]

    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    method_core = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                      for p in sorted(TESTS.glob("test_*.py")) if p.name != "test_showcase.py")
    facts = [
        ["测试", f"{method_total_str(method_count, method_core)}"],
        ["检测（固定种子）", f"角点最大误差 {kv2.get('最大误差', '')}；候选数/面积比 {kv2.get('诊断（候选数/最大面积比）', '')}"],
        ["还原质量", f"MAD {kv3.get('MAD（平均绝对差）', '')}；掩码一致率 {kv3.get('掩码像素一致率', '')}；"
                 f"前景 IoU {kv3.get('前景 IoU', '')}"],
        ["二值化", f"Otsu 阈值 {kv4.get('Otsu 阈值', '')}；与真值一致率 {kv4.get('Otsu 与真值一致率', '')}"
                f"（自适应 {kv4.get('自适应与真值一致率', '')}）"],
        ["20 种子批量", f"成功率 {kv6.get('成功率', '')}；最差角点误差 {kv6.get('角点最大误差（最差种子）', '')}、"
                   f"MAD {kv6.get('MAD（最差种子）', '')}、一致率 {kv6.get('掩码一致率（最差种子）', '')}"],
        ["失败样例", f"{len(failures)} 类全部拒识（原因落 4 种：无边缘×2、边缘密度过高、面积不达标、"
                 f"图像太小；另有\u201c空图\u201d拒识分支由测试单独覆盖）"],
    ]
    return {"facts": facts, "demo": demo, "failures": failures, "gallery": gallery,
            "method_count": method_count}


def method_total_str(total: int, core: int) -> str:
    return f"{total} 项（{core} 同步核心 + {total - core} 展示页自测；tests/ def test_ 现数）"


# ------------------------------------------------------------------ 渲染

STYLE = """
:root{--ink:#16181d;--muted:#5f6773;--line:#d5d9e0;--card:#fff;--bg:#f7f8fa;--accent:#1d4ed8;--ok:#14603a;--bad:#a41f1f;--warn:#8a5a00}
*{box-sizing:border-box}
body{margin:0;padding:1.4rem 1.1rem 3rem;background:var(--bg);color:var(--ink);font:16px/1.7 system-ui,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:71rem;margin:0 auto}
h1{font-size:1.5rem;margin:.2rem 0}h2{font-size:1.05rem;margin:1.6rem 0 .5rem}
p.note,span.note{color:var(--muted);font-size:.87rem}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:.7rem;margin:.6rem 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.7rem .9rem}
.card b{display:block;font-size:.8rem;color:var(--muted);font-weight:600;margin-bottom:.15rem}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:.8rem 0}
.chips{display:flex;gap:.4rem;flex-wrap:wrap;margin:.4rem 0 .8rem}
.chip{font:inherit;font-size:.87rem;padding:.28rem .7rem;border:1px solid var(--line);border-radius:999px;background:#fff;cursor:pointer}
.chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
pre.code{margin:.6rem 0 0;padding:.8rem .9rem;background:#0f1115;color:#e6e9ef;border-radius:8px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace}
pre.code.wrap{white-space:pre-wrap;word-break:break-word}
table.plain{border-collapse:collapse;font-size:.88rem;margin:.5rem 0;width:100%}
table.plain th,table.plain td{border:1px solid var(--line);padding:.3rem .7rem;text-align:left;vertical-align:top}
.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(14rem,1fr));gap:.8rem;margin:.6rem 0}
.gallery figure{margin:0;background:#fff;border:1px solid var(--line);border-radius:10px;padding:.5rem}
.gallery img{width:100%;height:auto;border-radius:6px;display:block;image-rendering:auto}
.gallery figcaption{font-size:.82rem;color:var(--muted);padding-top:.4rem}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}
"""

TOGGLE_JS = """
(function(){
  "use strict";
  function activate(group, id){
    var chips = document.querySelectorAll('[data-tabs="' + group + '"] [data-tab]');
    for (var i = 0; i < chips.length; i++){
      var on = chips[i].getAttribute("data-tab") === id;
      chips[i].className = on ? "chip active" : "chip";
    }
    var panes = document.querySelectorAll('[data-pane="' + group + '"] [data-pane-id]');
    for (var j = 0; j < panes.length; j++){
      panes[j].hidden = panes[j].getAttribute("data-pane-id") !== id;
    }
  }
  var lines = document.querySelectorAll("[data-tabs]");
  for (var k = 0; k < lines.length; k++){
    (function(line){
      var group = line.getAttribute("data-tabs");
      var chips = line.querySelectorAll("[data-tab]");
      for (var c = 0; c < chips.length; c++){
        chips[c].addEventListener("click", function(){
          activate(group, this.getAttribute("data-tab"));
        });
      }
      if (chips.length) activate(group, chips[0].getAttribute("data-tab"));
    })(lines[k]);
  }
})();
"""


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    cards = "".join(f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    demo_block = e(p["demo"].rstrip())
    figures = "".join(
        f'<figure><img src="{g["data_uri"]}" alt="{e(caption)}">'
        f'<figcaption>{e(caption)}<br>原产物 {g["orig_size"]}·{g["orig_bytes"]} 字节'
        f'（此处为 {g["thumb_w"]}px 宽缩略图）</figcaption></figure>'
        for caption, g in p["gallery"])
    fail_rows = "".join(f"<tr><td>{e(name)}</td><td>{e(reason)}</td></tr>" for name, reason in p["failures"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B24-cv-scanner · 文档扫描仪（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B24-cv-scanner">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a>（本页双击即看，零网络依赖）</p>
<h1>B24-cv-scanner · 文档扫描仪：边缘检测 → 透视变换 → 二值化</h1>
<p class="note">计算机视觉 · <b>期望值全是"造出来的"</b>：程序渲染一份文档、记下四角/文字掩码真值，
再按已知透视"拍成照片"——检测误差、还原质量、二值准确率全对着真值算，像素级有出处。
下面三张图是 demo 写出的**同一套产物**（缩略图内联，原尺寸 PNG 在 build/）。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="vision">视觉验收 · 三张真实产物</button>
    <button class="chip" data-tab="raw">演示 · 六段原文</button>
    <button class="chip" data-tab="fail">失败样例对照</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="vision">
      <p class="note">从左到右就是流水线的三步：透视"照片" → 拉正 → 二值化。
      缩略图由生成器对 build/ 里的原产物做确定性缩放（同一份数据，不另造）。</p>
      <div class="gallery">{figures}</div>
    </div>
    <div data-pane-id="raw" hidden>
      <p class="note">`python demo.py` 的完整现场输出（固定种子，两遍逐字相同）。</p>
      <pre class="code wrap">{demo_block}</pre>
    </div>
    <div data-pane-id="fail" hidden>
      <p class="note">五类失败样例**全部拒识**——"拒识要带原因"是这套流水线的口径。如实地说：
      纯背景与低对比落到同一条"无边缘"分支（原因文字相同），五种样例共 4 种原因；
      "空图"是第 5 条拒识分支，由测试单独覆盖。纯噪声的 37% 边缘密度与真实场景 1.1%
      差两个数量级，阈值 0.25 有大量余量。</p>
      <table class="plain"><tr><th>样例</th><th>拒识原因（现场输出）</th></tr>{fail_rows}</table>
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：三步（测试 → 六段演示 → 展示页新鲜度）；PNG 产物落在 build\\。</li>
    <li><kbd>python demo.py</kbd>：六段演示；<kbd>python -m unittest discover -s tests</kbd>：全量测试。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 demo.py 现算（测试数按 tests/ 静态现数；
  页面不含计时数字）。依赖 cv2 + numpy（装机实测在位，零新依赖）。</p>
</section>

<footer>
  <p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。</p>
</footer>
</main>
<script>{TOGGLE_JS}</script>
</body>
</html>
"""


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B24 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（六段演示 + 三张产物缩略图内联，全部现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（演示/缩略图/失败样例）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
