"""B30 展示页生成器：现算 Raft 选举/复制/分区/不变式数据，渲染自包含 HTML。

页面写 `web/showcase.html`；`--check` 重算比对，过期即红。
所有数据来自固定种子的真实模拟运行（确定性：同 seed 轨迹逐次一致）。
适配 raft30/sim.py 的 dict-nodes 架构（含快照与成员变更）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raft30.hashing import ConsistentHash, NaiveShard, moved_fraction  # noqa: E402
from raft30.sim import Simulation                                     # noqa: E402

OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"


def _test_count() -> int:
    return sum(len(re.findall(r"^\s*def test_",
                              p.read_text(encoding="utf-8"), re.M))
               for p in sorted(TESTS.glob("test_*.py")))


def _run_raft_scenario(seed: int = 0) -> dict:
    """§5.4.2 经典场景：旧 leader 隔离期的未提交条目，愈合后被覆盖。"""
    sim = Simulation(n=5, seed=seed)
    sim.advance(400)
    lid = sim.leader_id()
    if lid is None:
        raise AssertionError("seed 场景未选出 leader")
    sim.partition({i: (0 if i == lid else 1) for i in range(5)})
    sim.advance(150)
    new_leader = sim.leader_id()
    if new_leader is None or new_leader == lid:
        raise AssertionError("多数派未选出新 leader")
    old_term = sim.nodes[lid].term
    new_term = sim.nodes[new_leader].term
    if new_term <= old_term:
        raise AssertionError("新 leader 任期未增长")
    sim.submit_to(lid, "ghost", "c")
    sim.submit_to(new_leader, "real", "r")
    sim.heal()
    sim.advance(400)
    ghost_leaked = any(n.sm.get("ghost") is not None for n in sim.nodes.values())
    real_values = {n.sm.get("real") for n in sim.nodes.values() if "real" in n.sm}
    sim.check_election_safety()
    sim.check_log_matching()
    sim.check_applied_consistency()
    return {"old_leader": lid, "new_leader": new_leader,
            "old_term": old_term, "new_term": new_term,
            "ghost_leaked": ghost_leaked,
            "real_ok": real_values == {"r"},
            "timeline": sim.timeline[:10]}


def _run_election(seed: int = 1) -> dict:
    sim = Simulation(n=5, seed=seed)
    sim.advance(400)
    lid = sim.leader_id()
    elections = len(sim.leader_history)
    return {"leader": lid, "elections": elections,
            "timeline": sim.timeline[:8]}


def collect() -> dict:
    elect = _run_election(seed=1)
    raft = _run_raft_scenario(seed=0)

    keys = [f"key:{i}" for i in range(2000)]
    cons_old = ConsistentHash(["n1", "n2", "n3", "n4"], vnodes=100)
    cons_new = ConsistentHash(["n1", "n2", "n3", "n4", "n5"], vnodes=100)
    moved_cons = moved_fraction(cons_old, cons_new, keys)
    moved_naive = moved_fraction(NaiveShard(4), NaiveShard(5), keys)

    test_count = sum(len(re.findall(r"^\s*def test_",
                       p.read_text(encoding="utf-8"), re.M))
                     for p in sorted(TESTS.glob("test_*.py")))

    facts = [
        ["Raft 集群", "5 节点；选举/复制/提交/分区/重启/快照/成员变更全部可模拟"],
        ["§5.4.2 场景", f"旧 leader 隔离期的未提交条目愈合后被覆盖"
                        f"（ghost 泄漏：{'有' if raft['ghost_leaked'] else '无'}）"],
        ["不变式检查", "Election Safety / Log Matching / 状态机前缀一致，逐事件断言"],
        ["一致性哈希", f"扩容 4→5 搬移 {moved_cons:.1%}（朴素取模 {moved_naive:.1%}）"],
        ["mini-RPC", "JSON 行帧 + id 关联 + 真套接字回声（测试覆盖）"],
        ["测试方法", f"{test_count} 个（tests/ 里 def test_ 现数）"],
    ]
    return {"facts": facts, "elect": elect, "raft": raft,
            "hash": {"cons": round(moved_cons, 3), "naive": round(moved_naive, 3)},
            "test_count": test_count}


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
.badge.ok{color:var(--ok);border-color:var(--ok)}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}
ol,ul{padding-left:1.3rem}

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

  function pre(text){
    var node = el("pre", "code");
    node.textContent = text;
    return node;
  }

  function show(name){
    var chips = chipBox.children;
    for (var i = 0; i < chips.length; ++i)
      chips[i].className = "chip" + (chips[i].dataset.name === name ? " active" : "");
    panel.textContent = "";
    if (name === "elect") {
      panel.appendChild(el("p", "", "seed=1：advance 400 拍后选出 leader 节点" +
        DATA.elect.leader + "（历史选举 " + DATA.elect.elections + " 次——分票被随机超时打破）"));
      panel.appendChild(pre(DATA.elect.timeline.join("\\n")));
    } else if (name === "raft54") {
      var r = DATA.raft;
      panel.appendChild(el("p", "", "旧 leader 节点" + r.old_leader +
        " 被隔离 → 多数派选出节点" + r.new_leader + "（更高任期 " + r.new_term +
        "）→ 旧 leader 隔离期写入的 ghost 条目愈合后被覆盖"));
      panel.appendChild(el("p", "", "ghost 泄漏: " +
        (r.ghost_leaked ? "有（模拟器有错！）" : "无（论文安全性成立）") +
        "；real 值全员一致: " + (r.real_ok ? "是" : "否")));
      panel.appendChild(pre(r.timeline.join("\\n")));
    } else if (name === "hash") {
      var h = DATA.hash;
      panel.appendChild(el("p", "", "扩容 4→5 节点、2000 键："));
      panel.appendChild(table([["一致性哈希", (h.cons * 100).toFixed(1) + "%"],
                               ["朴素取模", (h.naive * 100).toFixed(1) + "%"]],
                              ["方案", "键搬移比例"]));
      panel.appendChild(el("p", "note", "理想值：一致性 ≈ 1/(n+1) = 20%；朴素 ≈ 80%"));
    }
  }

  function table(rows, head){
    var t = el("table", "grid");
    if (head) {
      var hr = el("tr");
      head.forEach(function(h){ hr.appendChild(el("th", "", h)); });
      t.appendChild(hr);
    }
    rows.forEach(function(r){
      var tr = el("tr");
      r.forEach(function(cell){ tr.appendChild(el("td", "", String(cell))); });
      t.appendChild(tr);
    });
    return t;
  }

  [["elect", "选举"], ["raft54", "§5.4.2 覆盖实验"], ["hash", "一致性哈希"]]
    .forEach(function(pair){
      var chip = el("button", "chip", pair[1]);
      chip.dataset.name = pair[0];
      chip.addEventListener("click", function(){ show(pair[0]); });
      chipBox.appendChild(chip);
    });
  show("elect");
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
<title>B30-mini-raft · 分布式与云计算（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B30-mini-raft">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B10-minidb/web/showcase.html">B10</a>　·　下一件 <a href="../../../projects/B38-mini-redis/web/showcase.html">B38</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B30 · 事件驱动 Raft 模拟：选举、复制、分区与不变式</h1>
<p class="note">分布式与云计算 · 零依赖（单进程事件驱动模拟，非多进程真集群）：
同一 seed 的模拟轨迹逐次一致，所以论文安全不变式可以在**每个事件后**逐条断言
——这是模拟器相对真集群的最大好处。支持快照与单步成员变更。</p>

<h2 id="facts-title">实测数字（本页现算，固定种子可复现）</h2>
<section id="facts" class="cards">{cards}</section>

<h2 id="demo-title">展示区：选举 / §5.4.2 覆盖实验 / 一致性哈希</h2>
<section id="demo" class="panel">
  <div class="chips" id="chips"></div>
  <div id="panel"></div>
</section>

<h2 id="repro-title">怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：自测（28 项）+ 演示。</li>
    <li><kbd>python tests\test_b30.py</kbd>：28 项测试（含随机事件流不变式）。</li>
    <li><kbd>python demo.py</kbd>：分片对比 + Raft 场景演示。</li>
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
