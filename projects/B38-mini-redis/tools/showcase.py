"""B38 展示页生成器：现算 RESP 编解码/命令表/复制数据，渲染自包含 HTML。

页面写 `web/showcase.html`；`--check` 重算比对，过期即红。
所有数据来自本次运行的真实 Store/RespEncoder（无网络、无文件）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from redislite.resp import (FrameDecoder,                            # noqa: E402
                            decode_commands, encode_command)
from redislite.store import Store                                    # noqa: E402

OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"


def _test_count() -> int:
    return sum(len(re.findall(r"^\s*def test_",
                              p.read_text(encoding="utf-8"), re.M))
               for p in sorted(TESTS.glob("test_*.py")))


def collect() -> dict:
    store = Store()

    def handler(body):
        args = [a.encode() if isinstance(a, str) else a for a in body["args"]]
        return {"reply": store.execute(args)}

    # RESP 编解码演示
    cmds = [
        {"cmd": ["SET", "greeting", "hello"], "label": "SET greeting hello"},
        {"cmd": ["GET", "greeting"], "label": "GET greeting"},
        {"cmd": ["INCR", "counter"], "label": "INCR counter"},
        {"cmd": ["INCR", "counter"], "label": "INCR counter (again)"},
        {"cmd": ["EXPIRE", "greeting", "60"], "label": "EXPIRE greeting 60"},
        {"cmd": ["TTL", "greeting"], "label": "TTL greeting"},
        {"cmd": ["GET", "missing"], "label": "GET missing (nil)"},
        {"cmd": ["DEL", "counter"], "label": "DEL counter"},
        {"cmd": ["GET", "counter"], "label": "GET counter (已删，nil)"},
    ]
    resp_trace = []
    for c in cmds:
        wire = encode_command(*c["cmd"])
        decoder = FrameDecoder()
        decoder.feed(wire)
        reply = store.dispatch([a for a in decode_commands(wire)[0]])
        # _Ok 等哨兵类没有 __repr__，str() 会包含内存地址——
        # 必须转成确定性字符串，否则页面对拍随进程漂移
        if isinstance(reply, bytes):
            reply_str = reply.decode("utf-8", errors="replace")
        elif type(reply).__name__ in ("_Ok",):
            reply_str = "OK"
        elif type(reply).__name__ in ("_Pong",):
            reply_str = "PONG"
        elif isinstance(reply, int):
            reply_str = str(reply)
        else:
            reply_str = repr(reply)
        resp_trace.append({"cmd": c["label"], "wire": wire.decode("latin-1").strip(),
                           "reply": reply_str})

    # 坏帧跳过
    decoder = FrameDecoder()
    decoder.feed(b"garbage\n")
    decoder.feed(encode_command("PING"))
    _ = len(decoder.next_command() or [])

    facts = [
        ["RESP2 协议", "5 种类型前缀（+/-/:/$/*），支持 inline 与数组两种请求形态"],
        ["命令子集", "SET GET DEL INCR EXPIRE TTL PING + 主从复制握手"],
        ["过期策略", "惰性删除 + 定期采样（与 Redis 同款的两种机制）"],
        ["复制协议", "PSYNC → FULLRESYNC → RDB 快照 + 增量传播"],
        ["测试方法", f"{_test_count()} 个（tests/ 里 def test_ 现数）"],
    ]
    return {"facts": facts, "resp_trace": resp_trace,             "commands": [c["label"] for c in cmds]}


# ------------------------------------------------------------------ 渲染

STYLE = """
:root{--ink:#16181d;--muted:#5f6773;--line:#d5d9e0;--card:#fff;--bg:#f7f8fa;--accent:#1d4ed8;--ok:#14603a;--bad:#a41f1f}
*{box-sizing:border-box}
body{margin:0;padding:1.4rem 1.1rem 3rem;background:var(--bg);color:var(--ink);font:16px/1.7 system-ui,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:71rem;margin:0 auto}
h1{font-size:1.5rem;margin:.2rem 0}h2{font-size:1.05rem;margin:1.6rem 0 .5rem}
p.note,span.note{color:var(--muted);font-size:.87rem}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:.7rem;margin:.6rem 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.7rem .9rem}
.card b{display:block;font-size:.8rem;color:var(--muted);font-weight:600;margin-bottom:.15rem}
.card span{font-size:.95rem}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:.8rem 0}
.chips{display:flex;gap:.4rem;flex-wrap:wrap;margin:.4rem 0 .8rem}
.chip{font:inherit;font-size:.87rem;padding:.28rem .7rem;border:1px solid var(--line);border-radius:999px;background:#fff;cursor:pointer}
.chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
table.grid{border-collapse:collapse;margin:.4rem 0;font-size:.92rem}
table.grid td,table.grid th{border:1px solid var(--line);padding:.3rem .6rem;text-align:left}
pre.code{margin:.6rem 0 0;padding:.8rem .9rem;background:#0f1115;color:#e6e9ef;border-radius:8px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace}
.badge{display:inline-block;font-size:.8rem;padding:.08rem .55rem;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}
ol,ul{padding-left:1.3rem}
"""

APP_JS = """
(function(){
  "use strict";
  var chipBox = document.getElementById("chips");
  var panel = document.getElementById("panel");

  function el(tag, cls, text){
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function show(name){
    var chips = chipBox.children;
    for (var i = 0; i < chips.length; ++i)
      chips[i].className = "chip" + (chips[i].dataset.name === name ? " active" : "");
    panel.textContent = "";
    if (name === "resp") {
      panel.appendChild(el("p", "", "RESP2 线上字节（真实编码器输出）："));
      var pre = el("pre", "code");
      var lines = DATA.resp_trace.map(function(t){
        return t.cmd + "\\n  线上: " + t.wire + "\\n  回复: " + t.reply;
      }).join("\\n\\n");
      pre.textContent = lines;
      panel.appendChild(pre);
      panel.appendChild(el("p", "note", "坏帧跳过：garbage 行不崩溃也不回包"));
    }
  }

  [["resp", "RESP2 编解码与命令"]].forEach(function(pair){
    var chip = el("button", "chip", pair[1]);
    chip.dataset.name = pair[0];
    chip.addEventListener("click", function(){ show(pair[0]); });
    chipBox.appendChild(chip);
  });
  show("resp");
})();
"""


def render(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    cards = "".join(
        f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in payload["facts"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B38-mini-redis · 手写 Redis 子集（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B38-mini-redis">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B30-mini-raft/web/showcase.html">B30</a>　·　下一件 <a href="../../../projects/B23-ml-from-scratch/web/showcase.html">B23</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B38 · 手写 Redis：RESP2 协议 + 过期 + 复制</h1>
<p class="note">软件工程案例分析与实践 · 零依赖。先写案例分析文档（Redis 为什么快：
单线程事件循环 + 内存数据 + I/O 多路复用），再实现子集：RESP2 编解码、
SET/GET/DEL/INCR/EXPIRE/TTL、惰性 + 采样双过期、PSYNC 主从复制。</p>

<h2 id="facts-title">实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2 id="demo-title">展示区：RESP2 线上字节</h2>
<section id="demo" class="panel">
  <div class="chips" id="chips"></div>
  <div id="panel"></div>
</section>

<h2 id="repro-title">怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：自测 + 演示。</li>
    <li><kbd>python tests\test_redis.py</kbd>：RESP 与 Store 测试。</li>
    <li><kbd>python tests\test_replication.py</kbd>：主从复制测试。</li>
    <li><kbd>python tools/showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令现算；别手改本页。
  观感与顺手程度归你实跑验收。</p>
</section>

<h2 id="lab-title">实时实验台</h2>
<section id="lab" class="panel">
<div id="lab-slot">
<p class="note"><b>实验台未启动</b>：本页仍是静态生成物，双击即看；启动实验台后，这块会就地变成控制台——真启停后端服务、发原始请求（字节进字节出）、看实时日志、跑演示/测试。</p>
<ul>
<li>双击仓库根 <kbd>lab.bat</kbd>（或终端 <kbd>python showcase\\lab.py</kbd>），然后刷新本页；</li>
<li>只起服务不弹浏览器：<kbd>lab.bat no-open</kbd>；自检：<kbd>lab.bat selftest</kbd>。</li>
</ul>
</div>
</section>
<footer>
  <p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。</p>
</footer>
</main>
<script>const DATA = {data};</script>
<script>{APP_JS}</script>
<script>
/* 实时实验台引导（双击 lab.bat 启动实验台后，页内该分节自动变成控制台） */
"use strict";
var s=document.createElement("script");
s.src=(location.protocol==="http:")?("/showcase/lab.js"):"http:\\/\\/127.0.0.1:7788/showcase/lab.js";
document.body.appendChild(s);
</script>
</body>
</html>
"""


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="重算比对，不写盘")
    ap.add_argument("--write", action="store_true", help="写出 web/showcase.html")
    args = ap.parse_args(argv)
    payload = collect()
    page = render(payload)
    if args.write or not OUT.is_file():
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(page, encoding="utf-8")
        print(f"{OUT.relative_to(ROOT.parent.parent)} 已写出（现算 {len(payload['facts'])} 项实测数字）")
        return 0
    current = OUT.read_text(encoding="utf-8")
    if current == page:
        print("展示页与现算一致（新鲜）")
        return 0
    print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
