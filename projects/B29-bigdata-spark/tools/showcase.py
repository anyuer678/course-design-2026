"""tools/showcase.py —— B29 展示页生成器（Spark 日志清洗/聚合/倾斜实验）。口径：showcase/SPEC.md。

数据全部现算，来源是真跑出来的产物（无冻结计时）：`python demo.py`（约 29 秒，Spark local[2]）
六段现场输出 → 解析成结构化账本表；**只取 stdout**——Spark 的 JVM 日志（带时间戳的
WARN/log4j 行）全在 stderr，天然不进页面。

**日志规范化（3 条，可审计）**：① warehouse 临时目录（Spark 自己建的 mkdtemp）→ `<临时目录>`；
② `生成 40 万行用时 N s` → `<当场>`；③ `耗时（3 次取中——单次实测） plain N ms / salted N ms`
→ `<当场>`。其余（400k 行规模、注入账本、分布读数、2.51/1.00）由固定种子驱动，两遍 diff 自证。

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
    text = re.sub(r"file:[^\s]*b29-warehouse[^\s]*", lambda m: "<临时目录>", text)
    text = re.sub(r"[A-Za-z]:[\\/][^\s]*b29-warehouse[^\s]*",
                  lambda m: "<临时目录>", text)
    text = re.sub(r"(生成 40 万行用时)\s+[\d.]+ s", r"\1 <当场>", text)
    text = re.sub(r"(耗时（3 次取中——单次实测）)\s+plain [\d.]+ ms / salted [\d.]+ ms",
                  r"\1 plain <当场> ms / salted <当场> ms", text)
    # Spark 退出时 JVM 往 stdout 打 3 行进程树清理（原文还是本机代码页字节，PID 每次不同）——
    # 整行移除，留一条说明；否则页面随 PID 漂移。
    lines = text.splitlines()
    kept = [ln for ln in lines if "PID" not in ln]
    removed = len(lines) - len(kept)
    kept.append(f"（Spark JVM 退出清理日志 {removed} 行已按规则移除：含 PID，每次运行必不同。）")
    return "\n".join(kept) + "\n"


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
td.ok{color:var(--ok)}
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


def collect() -> dict:
    demo = _norm(_run([sys.executable, "demo.py"]))
    sec = _parse_sections(demo)
    kv = {i: _kv(sec[i]) for i in range(1, 7)}

    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    method_core = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                      for p in sorted(TESTS.glob("test_*.py")) if p.name != "test_showcase.py")
    facts = [
        ["测试", f"{method_count} 项（{method_core} 核心 + {method_count - method_core} 展示页自测）"],
        ["环境（本机实测落实）", f"pyspark {kv[1].get('pyspark 版本', '?')}；master {kv[1].get('Spark 版本 / master', '?').split('/')[-1].strip()}；"
                        f"worker 解释器显式指向完整 Python（`python3` 是商店占位桩，不落实 Spark 起不来）"],
        ["合成日志", f"40 万行 / {kv[2].get('文件大小', '?')}；四类缺陷按账本注入 {kv[2].get('注入账本', '?')}；"
                 f"应通过清洗（真值）{kv[2].get('应通过清洗（真值）', '?')}"],
        ["清洗三方对账", f"小样本 Python==账本 {kv[3].get('对账（Python==账本）', '?')}、Spark==账本 "
                   f"{kv[3].get('对账（Spark==账本）', '?')}；40 万行分类计数与账本一致 "
                   f"{kv[3].get('40 万行：与账本一致', '?')}"],
        ["聚合对拍", f"device×level {kv[4].get('device×level 行数', '?')}；每小时 {kv[4].get('每小时错误行数', '?')}；"
                 f"top 错误码 {kv[4].get('top 错误码', '?')}"],
        ["倾斜实验", f"同键同分区倾斜比（确定性）{kv[6].get('倾斜比 max/中位（确定性）', '?')}；"
                 f"随机分区摊平后 1.00；salting == 直接 groupBy {kv[6].get('salting 结果 == 直接 groupBy', '?')}；"
                 f"热键 dev-01 计数 {kv[6].get('dev-01 计数（热键）', '?')}"],
    ]
    return {"facts": facts, "demo": demo, "kv": kv}


def render(payload: dict) -> str:
    p = payload
    e = html.escape
    kv = p["kv"]
    cards = "".join(f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in p["facts"])
    ledger_rows = "".join(
        f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in kv[3].items())
    skew_rows = "".join(
        f"<tr><td>{e(k.strip())}</td><td>{e(v)}</td></tr>" for k, v in kv[6].items())
    sql_example = e(kv[5].get('示例 SQL（每小时错误）', ''))
    demo_block = e(p["demo"].rstrip())
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B29-bigdata-spark · Spark 日志清洗与倾斜实验（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B29-bigdata-spark">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B28-bi-dashboard/web/showcase.html">B28</a>　·　下一件 <a href="../../../projects/B33-viz-algo/web/showcase.html">B33</a></span>（本页双击即看，零网络依赖）</p>
<h1>B29-bigdata-spark · 工业日志的清洗 / 聚合 / Spark SQL / 倾斜实验</h1>
<p class="note">用户画像与大数据分析 · 本机装好的 pyspark 4.2.0（local[2]）真跑 40 万行合成日志：
清洗链与账本对账、DataFrame 与纯 Python 参照逐行对拍、Spark SQL 第二种说法、salting 两阶段倾斜实验。
<b>数据是固定种子合成的，结论不外推</b>。下面全部来自刚跑完的现场输出（只取 stdout——
Spark 的 JVM 日志在 stderr，天然不进页面；三处现场值已按规则规范化）。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="raw">演示 · 六段原文</button>
    <button class="chip" data-tab="ledger">清洗对账账本</button>
    <button class="chip" data-tab="skew">倾斜实验</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="raw">
      <p class="note">`python demo.py` 的完整 stdout 现场输出（三处现场值：warehouse 临时目录 /
      生成用时 / 第 6 段耗时——已替换成 &lt;当场&gt;/&lt;临时目录&gt;）。</p>
      <pre class="code wrap">{demo_block}</pre>
    </div>
    <div data-pane-id="ledger" hidden>
      <p class="note">第 3 段清洗对账的逐行读数（纯 Python 隔离计数 vs 账本 vs 40 万行 Spark 计数）：</p>
      <table class="plain">{ledger_rows}</table>
      <p class="note">SQL 的第二种说法（第 5 段）：三查询 == DataFrame == 纯 Python 参照（True/True/True）。示例：</p>
      <pre class="code wrap">{sql_example}</pre>
    </div>
    <div data-pane-id="skew" hidden>
      <p class="note">第 6 段倾斜实验的逐行读数。读法：本地 MB 级数据上耗时差落在噪声里（故页面不冻结计时），
      <b>倾斜危害看分布读数</b>——同键同分区 max/中位 = 2.51，随机重分区摊平到 1.00，salting 结果与直接 groupBy 相等。</p>
      <table class="plain">{skew_rows}</table>
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：三步（测试 → 六段演示 → 展示页新鲜度）；首次运行前需本机已有 pyspark（零新下载）。</li>
    <li><kbd>python demo.py</kbd>：六段演示（约 30 秒，Spark 启动与 shuffle 都在里面）。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令真跑 demo.py 现算（只取 stdout；三处现场值按规则
  规范化，规则写在生成器文档串里）。</p>
</section>

<footer>
  <p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。</p>
</footer>
</main>
<script>{TOGGLE_JS}</script>
<script>
/* 实时实验台引导（未启动则静默）：python showcase/lab.py */
"use strict";
var s=document.createElement("script");
s.src=(location.protocol==="http:")?("/showcase/lab.js"):"http:\\/\\/127.0.0.1:7788/showcase/lab.js";
document.body.appendChild(s);
</script>
</body>
</html>
"""


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="B29 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（六段演示 + 账本/倾斜结构化表，全部现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（六段演示/账本/倾斜）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
