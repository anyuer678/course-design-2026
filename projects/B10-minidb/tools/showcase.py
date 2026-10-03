"""B10 展示页生成器：现算 WAL 恢复/事务/sqlite 对拍数据，渲染自包含 HTML。

页面写 `web/showcase.html`；`--check` 重算比对，过期即红。
所有数据来自本次运行的真实 Engine（临时目录，跑完即删）。
"""
import argparse
import json
import os
import random
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minidb.engine import Engine                                   # noqa: E402

OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"
NAMES = ["alice", "bob", "carol", "dave", "eve"]


def _test_count() -> int:
    return sum(len(re.findall(r"^\s*def test_",
                              p.read_text(encoding="utf-8"), re.M))
               for p in sorted(TESTS.glob("test_*.py")))


def _sqlite_battery(rounds: int = 300, seed: int = 2026, tmp: str = "") -> int:
    """与 tests 同款的 sqlite3 对拍：mini 引擎 vs sqlite3 逐行一致。
    任何一轮分叉都会抛断言失败——返回一致轮数。"""
    mini = Engine(os.path.join(tmp, "db"))
    mini.verbose = False
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE u (id INTEGER PRIMARY KEY, name TEXT, "
                "age INTEGER, score REAL)")
    mini.execute("CREATE TABLE u (id INTEGER, name TEXT, age INTEGER, "
                 "score REAL, PRIMARY KEY id)")
    rng = random.Random(seed)
    for i in range(200):
        age = rng.choice([rng.randint(10, 60), None])
        sql = (f"INSERT INTO u VALUES ({i}, '{NAMES[i % 5]}', "
               f"{age if age is not None else 'NULL'}, "
               f"{round(rng.uniform(0, 100), 2)})")
        mini.execute(sql)
        con.execute(sql)
    agree = 0
    for _ in range(rounds):
        cond = rng.choice(["age > 30", "age <= 25", "name = 'alice'",
                           "score >= 50.0", "age IS NOT NULL"])
        order = rng.choice(["", " ORDER BY age, id", " ORDER BY score DESC, id"])
        sql = f"SELECT id, name FROM u WHERE {cond}{order}"
        mini_rows = [tuple(r.values()) for r in mini.execute(sql)]
        sql_rows = [tuple(r) for r in con.execute(sql)]
        if mini_rows != sql_rows:
            raise AssertionError(f"对拍分叉: {sql}")
        agree += 1
    return agree


def collect() -> dict:
    facts = []
    demo: dict = {}
    checks: dict = {}
    with tempfile.TemporaryDirectory() as tmp:
        # ---- WAL 恢复：写库 -> 不 CHECKPOINT 直接重开（模拟崩溃）----
        path = os.path.join(tmp, "db")
        eng = Engine(path)
        eng.verbose = False
        eng.execute("CREATE TABLE users (id INTEGER, name TEXT, PRIMARY KEY id)")
        eng.execute("INSERT INTO users VALUES (1, 'alice')")
        eng.execute("INSERT INTO users VALUES (2, 'bob')")
        wal_lines = len(eng.wal)
        reopened = Engine(path)
        reopened.verbose = False
        got = [r["id"] for r in reopened.execute("SELECT id FROM users ORDER BY id")]
        demo["wal"] = {"wal_lines": wal_lines, "recovered_ids": got}
        checks["recovery"] = got == [1, 2]

        # ---- CHECKPOINT：快照落盘、WAL 清空 ----
        reopened.execute("CHECKPOINT")
        wal_alive = os.path.exists(path + ".wal")
        after_cp = len(Engine(path).execute("SELECT id FROM users"))
        demo["checkpoint"] = {"wal_alive": wal_alive, "rows": after_cp}
        checks["checkpoint"] = (not wal_alive) and after_cp == 2

        # ---- 事务回滚 ----
        eng2 = Engine()
        eng2.verbose = False
        eng2.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
        eng2.execute("INSERT INTO t VALUES (1, 'keep')")
        eng2.execute("BEGIN")
        eng2.execute("INSERT INTO t VALUES (2, 'lost')")
        eng2.execute("DELETE FROM t WHERE id = 1")
        eng2.execute("ROLLBACK")
        kept = [r["id"] for r in eng2.execute("SELECT * FROM t")]
        demo["rollback"] = {"kept": kept}
        checks["rollback"] = kept == [1]

        # ---- sqlite 对拍 ----
        agree = _sqlite_battery(tmp=tmp)
        checks["agree"] = agree

    facts = [
        ["存储引擎", "B+ 树索引 + 页式快照 + WAL 预写日志"],
        ["WAL 恢复", f"重启回放 {wal_lines} 条日志，{len(got)} 行完整（模拟崩溃）"],
        ["CHECKPOINT", "快照落盘后 WAL 清空，从快照恢复同样完整"],
        ["事务回滚", "BEGIN 内的插入与删除被 ROLLBACK 原样还原"],
        ["sqlite3 对拍", f"{agree} 轮随机 SQL 逐行一致（mini vs sqlite3）"],
        ["测试方法", f"{_test_count()} 个（tests/ 里 def test_ 现数）"],
    ]
    return {"facts": facts, "demo": demo, "checks": checks}


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
.badge{display:inline-block;font-size:.8rem;padding:.08rem .55rem;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.badge.ok{color:var(--ok);border-color:var(--ok)}.badge.bad{color:var(--bad);border-color:var(--bad)}
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
    var d = DATA.demo[name];
    if (name === "wal") {
      panel.appendChild(el("p", "", "写入 3 条语句（建表 + 2 插入），未 CHECKPOINT 直接重启："));
      panel.appendChild(el("p", "", "WAL 日志 " + d.wal_lines + " 条 → 回放后恢复 " +
        d.recovered_ids.join(", ") + " —— 已提交数据零丢失"));
    } else if (name === "checkpoint") {
      panel.appendChild(el("p", "", "CHECKPOINT 后：WAL 文件" +
        (d.wal_alive ? "仍存在" : "已清空") + "，从快照恢复 " + d.rows + " 行"));
    } else if (name === "rollback") {
      panel.appendChild(el("p", "", "BEGIN 后插入 id=2、删除 id=1，ROLLBACK → 剩 " +
        d.kept.join(", ") + "（事务内的改动全部消失）"));
    } else if (name === "battery") {
      panel.appendChild(el("p", "", DATA.checks.agree + " 轮随机 SQL：mini 引擎与" +
        " sqlite3 的查询结果逐行一致（含 ORDER BY / IS NULL / 三值逻辑）"));
    }
  }

  [["wal", "WAL 恢复"], ["checkpoint", "CHECKPOINT"], ["rollback", "事务回滚"],
   ["battery", "sqlite 对拍"]].forEach(function(pair){
    var chip = el("button", "chip", pair[1]);
    chip.dataset.name = pair[0];
    chip.addEventListener("click", function(){ show(pair[0]); });
    chipBox.appendChild(chip);
  });
  show("wal");
})();
"""


def render(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    cards = "".join(
        f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in payload["facts"])
    checks = payload["checks"]
    badges = "".join(
        f'<span class="badge {"ok" if v else "bad"}">{k}: {"ok" if v else "fail"}</span> '
        for k, v in checks.items())
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B10-minidb · WAL + 事务 + 对拍（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B10-minidb">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B32-sec-lab/web/showcase.html">B32</a>　·　下一件 <a href="../../../projects/B30-mini-raft/web/showcase.html">B30</a></span>（本页双击即看，零网络依赖）</p>
<h1>B10 · 教学数据库：B+ 树索引 + WAL 恢复 + 事务 + sqlite 对拍</h1>
<p class="note">数据库系统 · 无第三方依赖：词法/语法解析 → 计划器 → 执行器 →
B+ 树 → WAL → 崩溃恢复。压轴是与 sqlite3 的随机 SQL 对拍。</p>

<h2 id="facts-title">实测数字（本页现算，临时目录真实跑库）</h2>
<section id="facts" class="cards">{cards}</section>

<h2 id="demo-title">展示区：四个真实场景（每次生成现跑一遍）</h2>
<section id="demo" class="panel">
  <p class="note">本页生成时真实跑了四个场景，结果：
    {badges}</p>
  <div class="chips" id="chips"></div>
  <div id="panel"></div>
</section>

<h2 id="repro-title">怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：自测（36 项，含 sqlite3 对拍）+ 六段演示。</li>
    <li><kbd>python tests\test_minidb.py</kbd>：只跑自测。</li>
    <li><kbd>python demo.py</kbd>：六段演示（CRUD → 计划器 → 约束 → JOIN → 事务 → 恢复）。</li>
    <li><kbd>python tools/showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令现算；别手改本页。
  观感与顺手程度归你实跑验收。</p>
</section>

<footer>
  <p>生成物：python tools/showcase.py --write（口径见 showcase/SPEC.md；仓库级校验 python showcase/check.py）。</p>
</footer>
</main>
<script>const DATA = {data};</script>
<script>{APP_JS}</script>
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
