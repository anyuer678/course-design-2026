"""tools/showcase.py —— B8 展示页生成器（mini-shell：fork/exec、管道、重定向、回收）。口径：showcase/SPEC.md。

平台说明：这个 shell 用 POSIX API（fork/execvp/pipe/dup2/waitpid），Windows 原生没有 fork，
可执行与测试都跑在 **WSL2 Ubuntu-24.04**（run.bat 是把三步交给 `wsl -e bash run.sh` 的薄包装）。
本生成器在 Windows 侧，用**一次** `wsl -d Ubuntu-24.04` 调用完成全部采集
（编译 → 双入口自测 → 六段演示 → 会话回放），按 `@@` 标记切块后解析——单次调用是为了
把 WSL 启动开销（每次约 5 秒）摊到最小。

采集内容与 run.sh 走同一套命令；规范化（1 条，可审计）：项目在 WSL 里的绝对路径
（`/mnt/c/.../B8-mini-shell`）→ `<项目根>`，页面因此不绑定某一台机器的路径。无其他可变量
（演示与回放都不打印耗时；两遍采集应逐字相同）。

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
DISTRO = "Ubuntu-24.04"


def _wsl_root() -> str:
    s = str(ROOT.resolve())
    return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")


def _collect_script() -> str:
    root = _wsl_root()
    return f"""set -u
cd "{root}" || {{ echo "@@FAIL@@ cd 失败"; exit 3; }}
mkdir -p build
gcc -std=c11 -O2 -Wall -Wextra -o build/msh src/msh.c || {{ echo "@@FAIL@@ gcc 编译失败"; exit 3; }}
export PYTHONUTF8=1

echo "@@TESTS@@"
python3 -m unittest discover -s tests > build/sc_dis.txt 2>&1; rc=$?
echo "discover-rc=$rc"
[ "$rc" -eq 0 ] || sed 's/^/  | /' build/sc_dis.txt
grep -oE "Ran [0-9]+ tests" build/sc_dis.txt | sed 's/^/discover-/'
python3 tests/test_msh.py > build/sc_dir.txt 2>&1; rc=$?
echo "direct-rc=$rc"
[ "$rc" -eq 0 ] || sed 's/^/  | /' build/sc_dir.txt
grep -oE "Ran [0-9]+ tests" build/sc_dir.txt | sed 's/^/direct-/'
rm -f build/sc_dis.txt build/sc_dir.txt

echo "@@DEMO@@"
python3 demo.py 2>&1; echo "demo-rc=$?"

echo "@@REPLAY@@"
T=build/showcase_tmp
rm -rf "$T" && mkdir -p "$T"
run_msh() {{
  ./build/msh < "$T/$1.msh" > "$T/$1.out" 2>&1
  local rc=$?
  sed 's/^/    | /' "$T/$1.out"
  echo "    -> msh 退出码 $rc"
}}
echo "--- 1) 三段管道：printf c/b/a | sort | head -2 ---"
cat > "$T/p1.msh" <<'MSH'
printf "c\\nb\\na\\n" | sort | head -2
MSH
run_msh p1
echo
echo "--- 2) 退出码口径：管道 \\$? = 最后一段 ---"
cat > "$T/p2.msh" <<'MSH'
true | false
MSH
run_msh p2
cat > "$T/p3.msh" <<'MSH'
false | true
MSH
run_msh p3
echo
echo "--- 3) 重定向：> 截断、>> 追加，再 cat 回读 ---"
cat > "$T/p4.msh" <<'MSH'
echo first > build/showcase_tmp/out.txt
MSH
run_msh p4
cat > "$T/p5.msh" <<'MSH'
echo second >> build/showcase_tmp/out.txt
cat build/showcase_tmp/out.txt
MSH
run_msh p5
echo
echo "--- 4) 内建 cd 改的是 shell 自己的 cwd（同一会话里跨行保持）---"
cat > "$T/p6.msh" <<'MSH'
cd build/showcase_tmp
pwd
MSH
run_msh p6
echo
echo "--- 5) 错误路径：找不到命令 -> 127；报错后继续执行 ---"
cat > "$T/p7.msh" <<'MSH'
no_such_command_xyz
MSH
run_msh p7
cat > "$T/p8.msh" <<'MSH'
no_such_command_xyz
echo still alive
MSH
run_msh p8
rm -rf "$T"
echo "@@DONE@@"
"""


def _wsl_available() -> bool:
    """环境探测：wsl 可调用且目标发行版存在。

    覆盖三种"本机根本没有 WSL 现场"的情形：没装 wsl（FileNotFoundError）、
    执行被安全策略拒绝（OSError/WinError 5）、发行版列表里没有 DISTRO。
    探测通过才去做真正的现场采集。
    """
    env = dict(os.environ, WSL_UTF8="1")
    try:
        probe = subprocess.run(["wsl", "-l", "-q"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env=env, timeout=30)
    except OSError:
        return False
    if probe.returncode != 0:
        return False
    names = [n.strip() for n in (probe.stdout or "").replace("\x00", "").splitlines()]
    return DISTRO in names


def _wsl(script: str) -> str:
    env = dict(os.environ)
    env["WSL_UTF8"] = "1"
    proc = subprocess.run(["wsl", "-d", DISTRO, "-e", "bash", "-c", script],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)
    if proc.returncode != 0:
        raise SystemExit(f"WSL 采集失败（退出码 {proc.returncode}）：\n"
                         f"{(proc.stdout or '')[-800:]}\n{(proc.stderr or '')[-400:]}")
    return proc.stdout


def _split_blocks(raw: str) -> dict:
    blocks, current, buf = {}, None, []
    for line in raw.splitlines():
        m = re.match(r"^@@([A-Z]+)@@$", line.strip())
        if m:
            if current:
                blocks[current] = "\n".join(buf).strip("\n")
            current, buf = m.group(1), []
            continue
        if current:
            buf.append(line)
    if current:
        blocks[current] = "\n".join(buf).strip("\n")
    return blocks


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


def collect() -> dict:
    root = _wsl_root()
    raw = _wsl(_collect_script()).replace(root, "<项目根>")
    blocks = _split_blocks(raw)
    if "FAIL" in blocks:
        raise SystemExit(f"WSL 采集报告失败：{blocks['FAIL']}")

    tests = blocks["TESTS"]
    disc_rc = re.search(r"^discover-rc=(\d+)$", tests, re.M)
    dir_rc = re.search(r"^direct-rc=(\d+)$", tests, re.M)
    disc_ran = re.search(r"^discover-Ran (\d+) tests$", tests, re.M)
    dir_ran = re.search(r"^direct-Ran (\d+) tests$", tests, re.M)
    if not (disc_rc and dir_rc and disc_ran and dir_ran):
        raise SystemExit(f"自测输出解析失败：\n{tests[-600:]}")
    if disc_rc.group(1) != "0" or dir_rc.group(1) != "0":
        raise SystemExit(f"自测未通过：\n{tests[-800:]}")
    ran = (int(disc_ran.group(1)), int(dir_ran.group(1)))
    if ran[0] != ran[1]:
        raise SystemExit(f"双入口不同数：discover {ran[0]} / 直跑 {ran[1]}（这正是要防的漂移）")

    demo = blocks["DEMO"]
    demo_rc = re.search(r"^demo-rc=(\d+)$", demo, re.M)
    if not demo_rc or demo_rc.group(1) != "0":
        raise SystemExit(f"演示未通过：\n{demo[-600:]}")
    demo = demo[: demo_rc.start()].rstrip()
    sections = _parse_sections(demo)

    replay = blocks["REPLAY"]

    exit_codes = {}
    for label, code in re.findall(r"`([^`]+)` 退出码\s+(\d+)", demo):
        exit_codes[label] = int(code)
    m = re.search(r"僵尸子进程\s+(\d+) 个", demo)
    zombies = int(m.group(1)) if m else -1
    m = re.search(r"3 条坏语法的 stderr 条数\s+(\d+)", demo)
    bad_syntax = int(m.group(1)) if m else -1
    replay_codes = re.findall(r"-> msh 退出码 (\d+)", replay)

    facts = [
        ["自测", f"{ran[0]} 项双入口同数（discover {ran[0]} / 直跑 {ran[1]}；不同数生成器直接拒绝）"],
        ["演示", f"六段实测：退出码 true/false/exit42 = "
              f"{exit_codes.get('true', '?')}/{exit_codes.get('false', '?')}/{exit_codes.get('exit 42', '?')}；"
              f"僵尸当面数 = {zombies}；{bad_syntax} 条坏语法报错后仍继续"],
        ["会话回放", f"八个脚本喂 stdin 现场重放（管道/重定向/内建/错误路径），"
                 f"退出码实测 {sorted(set(replay_codes))}"],
        ["平台", "WSL2 Ubuntu-24.04 + gcc（Windows 原生没有 fork；run.bat 是薄包装）"],
    ]
    return {"facts": facts, "tests_raw": tests, "demo": demo, "sections": sections,
            "replay": replay, "exit_codes": exit_codes, "zombies": zombies,
            "ran": ran}


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
table.plain{border-collapse:collapse;font-size:.9rem;margin:.5rem 0;width:100%}
table.plain th,table.plain td{border:1px solid var(--line);padding:.3rem .7rem;text-align:left}
table.plain td.num,table.plain th.num{text-align:right;font-variant-numeric:tabular-nums}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}

/* ---------- KB 主题（token 学自 kb-ui 设计系统，2026-10-03）：统一观感 ---------- */
:root{
  --kb-primary:#3b82f6;--kb-primary-deep:#2563eb;
  --kb-primary-gradient:linear-gradient(135deg,#3b82f6,#6366f1);
  --kb-success:#16a34a;--kb-danger:#dc2626;--kb-warning:#d97706;
  --kb-bg:#ffffff;--kb-bg-elevated:#f8fafc;--kb-border:#e2e8f0;
  --kb-text-1:#0f172a;--kb-text-2:#475569;--kb-text-3:#94a3b8;
  --kb-radius-sm:4px;--kb-radius-md:6px;--kb-radius-lg:10px;
  --kb-shadow-1:0 1px 2px rgb(15 23 42 / 6%);
  --kb-shadow-2:0 4px 12px rgb(15 23 42 / 10%);
  --kb-font:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  --kb-mono:ui-monospace,Consolas,"Cascadia Mono",monospace;
  --kb-t:.2s ease;
}
body{background:#f8fafc;background-image:linear-gradient(180deg,#eff6ff 0,#f8fafc 340px,#f8fafc);
  color:var(--kb-text-1);font-family:var(--kb-font);-webkit-font-smoothing:antialiased}
body::before{content:"";display:block;height:4px;
  background:linear-gradient(90deg,var(--kb-primary),#6366f1 55%,#8b5cf6)}
a{color:var(--kb-primary-deep);text-decoration:none}
a:hover{color:#1d4ed8;text-decoration:underline}
h1,h2,h3{color:var(--kb-text-1);font-weight:650;letter-spacing:-.01em}
::selection{background:#dbeafe}
.sw-top{background:var(--kb-bg);border:1px solid var(--kb-border);
  border-radius:var(--kb-radius-lg);box-shadow:var(--kb-shadow-1)}
.sw-link{font-size:13px}
.sw-panel,.panel{background:var(--kb-bg);border:1px solid var(--kb-border);
  border-radius:var(--kb-radius-lg);box-shadow:var(--kb-shadow-1)}
.sw-card,.card{background:var(--kb-bg);border:1px solid var(--kb-border);
  border-radius:var(--kb-radius-lg);box-shadow:var(--kb-shadow-1);
  transition:box-shadow var(--kb-t),transform var(--kb-t),border-color var(--kb-t)}
.sw-card:hover,.card:hover{box-shadow:var(--kb-shadow-2);border-color:#bfdbfe;transform:translateY(-1px)}
.card b,.sw-card b{color:var(--kb-text-3);font-size:12px;letter-spacing:.02em}
.note,.muted{color:var(--kb-text-2)}
.badge{display:inline-block;font-size:.78rem;padding:.1rem .55rem;border-radius:999px;
  border:1px solid var(--kb-border);background:var(--kb-bg-elevated);color:var(--kb-text-2)}
.badge.ok{color:#047857;border-color:#a7f3d0;background:#ecfdf5}
.badge.bad{color:#b91c1c;border-color:#fecaca;background:#fef2f2}
.badge.todo,.badge.warn{color:#b45309;border-color:#fde68a;background:#fffbeb}
.chip,.pj-tab{font:inherit;font-size:.85rem;padding:.3rem .85rem;border:1px solid var(--kb-border);
  border-radius:999px;background:#fff;color:var(--kb-text-2);cursor:pointer;transition:all var(--kb-t)}
.chip:hover,.pj-tab:hover{border-color:var(--kb-primary);color:var(--kb-primary)}
.chip.active,.pj-tab.active{background:var(--kb-primary);border-color:var(--kb-primary);
  color:#fff;box-shadow:var(--kb-shadow-1)}
.chip.active:hover,.pj-tab.active:hover{color:#fff}
table{border-collapse:collapse}
table th,table td{border:1px solid var(--kb-border);padding:.42rem .65rem;text-align:left}
table th{background:var(--kb-bg-elevated);color:var(--kb-text-2);font-weight:600}
table tr:hover td{background:#f8fafc}
pre{background:#0f172a;color:#e2e8f0;border:1px solid #1e293b;
  border-radius:var(--kb-radius-lg);font-family:var(--kb-mono)}
pre code{background:none;border:none;padding:0;color:inherit}
kbd{font-family:var(--kb-mono);font-size:.85em;border:1px solid var(--kb-border);
  border-bottom-width:2px;border-radius:var(--kb-radius-sm);padding:1px 6px;
  background:var(--kb-bg-elevated);color:#334155}
code{font-family:var(--kb-mono);font-size:.9em;background:#f1f5f9;border:1px solid #e2e8f0;
  border-radius:var(--kb-radius-md);padding:1px 5px}
footer,.sw-footer{color:var(--kb-text-3);border-top:1px solid var(--kb-border)}
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
    replay_block = e(p["replay"].rstrip())
    test_rows = "".join(
        f'<tr><td>{name}</td><td class="num">{n} 项</td></tr>'
        for name, n in (("discover 入口", p["ran"][0]), ("直跑入口", p["ran"][1])))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B8-mini-shell · fork/exec + 管道 + 重定向（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B8-mini-shell">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B7-mini-make/web/showcase.html">B7</a>　·　下一件 <a href="../../../projects/B11-net-lab/web/showcase.html">B11</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B8-mini-shell · mini-shell：进程课的总复习</h1>
<p class="note">开源操作系统 · 一行命令背后是 fork、exec、pipe、dup2、waitpid 的完整链条；
"内建命令为什么必须存在"（cd 改的是 shell 自己的状态）与"管道为什么需要 N-1 根管子"
都在实现里给出答案。**僵尸进程是去 /proc 里当面数的**。下面全部来自刚在
WSL2 Ubuntu-24.04 里跑完的现场输出（生成器用一次 wsl 调用完成编译+双入口自测+演示+回放）。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <div class="chips" data-tabs="panels">
    <button class="chip" data-tab="demo6">演示 · 六段</button>
    <button class="chip" data-tab="replay">会话回放（脚本喂 stdin）</button>
    <button class="chip" data-tab="dual">双入口自测</button>
  </div>
  <div data-pane="panels">
    <div data-pane-id="demo6">
      <p class="note">`python3 demo.py` 的完整现场输出（在 WSL 里跑；项目绝对路径已规范化为 &lt;项目根&gt;）。</p>
      <pre class="code wrap">{demo_block}</pre>
    </div>
    <div data-pane-id="replay" hidden>
      <p class="note">八个命令脚本逐个喂给 <kbd>./build/msh</kbd>（stdin 重定向，非交互），
      每步打印输出与 msh 自身的退出码——管道口径、重定向落盘、内建 cd、错误路径都在这一段里现场发生。</p>
      <pre class="code wrap">{replay_block}</pre>
    </div>
    <div data-pane-id="dual" hidden>
      <p class="note">双入口同数是本项目的硬口径：discover 与直跑必须报同一个数（生成器在采集时
      对此做断言，不同数直接拒绝出页）。原始采集输出：</p>
      <table class="plain"><tr><th>入口</th><th class="num">测试数</th></tr>{test_rows}</table>
      <pre class="code wrap">{e(p["tests_raw"])}</pre>
    </div>
  </div>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>（Windows 侧）：WSL 里跑编译+自测+演示 → 展示页新鲜度 → 展示页测试。</li>
    <li><kbd>bash run.sh</kbd>（WSL 里）：等价入口；交互用 <kbd>./build/msh</kbd>（Ctrl-D 退出）。</li>
    <li><kbd>python tools\\showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令经 WSL 真跑（编译+24 项双入口自测+六段演示+八脚本回放）
  现算；页面不含计时数字，两遍采集逐字相同（唯一规范化项：项目路径 → &lt;项目根&gt;）。</p>
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
<script>{TOGGLE_JS}</script>
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
    ap = argparse.ArgumentParser(description="B8 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    if not _wsl_available():
        print(f"[skip] WSL 或发行版 {DISTRO} 不可用——本页数据需要 WSL 现场采集，"
              "当前机器无法执行（退出码 3：仓库级校验按 SKIP 记账，不算失败）")
        return 3
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（WSL 现场：双入口 {payload['ran'][0]} 项 + 六段演示 + 八脚本回放）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print("展示页新鲜：与现算逐字一致（WSL 现场采集）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
