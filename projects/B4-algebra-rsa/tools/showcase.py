"""tools/showcase.py —— B4 展示页生成器（数论底座 + 教学 RSA + 群判定 + 集合论）。口径：showcase/SPEC.md。

数据全部现算：

- **教学 RSA**：确定性密钥（seed=42）现生成、逐字节回读、以及"同明文两次同密文"的
  确定性缺陷演示（教科书 RSA 不能直接用于秘密保护——页面上明说）；
- **数论底座**：egcd 递推/迭代两版互拍、Bézout 系数验证、平方-乘 vs 朴素幂的乘法计数、
  CRT 与逐项验证；
- **群判定器**：6 张运算表（2 张真群 + 4 张坏表），四条定义逐条判定并给出反例；
- **集合与函数**：容斥公式 vs 暴力并集、幂集规模、函数三档性质（单射/满射/双射）与拒绝原因。

页面写 `web/showcase.html`；`--check` 重算比对（不写盘），过期即红。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algebra import groups as G                          # noqa: E402
from algebra import numbertheory as NT                   # noqa: E402
from algebra import rsa as RSA                           # noqa: E402
from algebra import sets as S                            # noqa: E402

OUT = ROOT / "web" / "showcase.html"
TESTS = ROOT / "tests"

GROUP_SAMPLES = [
    ("Z6 加法表", "教科书第一款群：6 个元素、可交换", lambda: G.add_table(6)[1]),
    ("U(8) 乘法单位表", "与 8 互素的乘法单位：4 个元素的小群", lambda: G.mul_units_table(8)[1]),
    ("坏表①：不封闭", "出现了元素编号 2，但表里只有 0/1", lambda: [[0, 1], [1, 2]]),
    ("坏表②：没有单位元", "全零表：结合律成立，但谁都不是单位元", lambda: [[0, 0], [0, 0]]),
    ("坏表③：缺逆元", "有单位元 0，但元素 2 怎么乘都回不到它", lambda: [[0, 1, 2], [1, 0, 2], [2, 2, 2]]),
    ("坏表④：不结合", "模 3 减法：封闭，但结合律当场翻车", lambda: [[0, 2, 1], [1, 0, 2], [2, 1, 0]]),
]


def _table_lines(table, labels=None) -> str:
    n = len(table)
    head = "    " + "  ".join((labels[i] if labels else str(i)) for i in range(n))
    rows = [head]
    for i in range(n):
        rows.append(f"{labels[i] if labels else i}:  " + "  ".join(str(v) for v in table[i]))
    return "\n".join(rows)


def _collect_rsa() -> dict:
    key = RSA.generate_keypair(seed=42)
    message = 2025
    cipher = RSA.encrypt(key, message)
    back = RSA.decrypt(key, cipher)
    text = "B4 数论演示"
    blocks = RSA.encrypt_text(key, text)
    restored = RSA.decrypt_text(key, blocks)
    again = RSA.encrypt(key, message)
    return {
        "p": key.p, "q": key.q, "n": key.n, "phi": key.phi, "e": key.e, "d": key.d,
        "message": message, "cipher": cipher, "back": back, "roundtrip": RSA.verify_roundtrip(key, message),
        "text": text, "blocks": blocks, "restored": restored,
        "deterministic": cipher == again,
    }


def _collect_numbertheory() -> dict:
    a, b = 1071, 462
    g1, x1, y1 = NT.egcd(a, b)
    g2, x2, y2 = NT.egcd_iter(a, b)
    stats = {}
    value = NT.mod_pow(7, 65537, 10 ** 9 + 7, stats)
    fast = stats.get("multiplications", 0) + stats.get("squarings", 0)
    naive = 65536
    residues, moduli = [2, 3, 2], [3, 5, 7]
    crt_value = NT.crt(residues, moduli)
    return {
        "egcd": {"g": g1, "x": x1, "y": y1, "same": (g1, x1, y1) == (g2, x2, y2),
                 "bezout": a * x1 + b * y1 == g1},
        "modpow": {"value": value, "fast": fast, "naive": naive},
        "crt": {"residues": residues, "moduli": moduli, "value": crt_value,
                "checks": [(crt_value % m, r) for r, m in zip(residues, moduli)]},
        "inverse": NT.mod_inverse(17, 3120),
    }


def _collect_groups() -> list:
    out = []
    for name, note, factory in GROUP_SAMPLES:
        table = factory()
        report = G.check_group(table)
        entry = {"name": name, "note": note, "table": _table_lines(table),
                 "explain": report.explain(),
                 "ok": report.ok, "closure_ok": report.closure_ok, "assoc_ok": report.assoc_ok,
                 "identity": report.identity, "inverses_ok": report.inverses_ok,
                 "abelian": None, "abelian_witness": None}
        if report.ok:
            entry["abelian"] = G.is_abelian(table)
            entry["abelian_witness"] = G.abelian_witness(table)
        out.append(entry)
    return out


def _collect_sets() -> dict:
    A, B, C = frozenset({1, 2, 3, 4, 5}), frozenset({4, 5, 6}), frozenset({2, 4, 7})
    ie = S.inclusion_exclusion([A, B, C])
    brute = len(A | B | C)
    terms = {"|A|": len(A), "|B|": len(B), "|C|": len(C),
             "|A∩B|": len(A & B), "|A∩C|": len(A & C), "|B∩C|": len(B & C),
             "|A∩B∩C|": len(A & B & C)}
    dom = frozenset({1, 2, 3})
    cod = frozenset({"a", "b", "c"})
    functions = [
        ("双射 {1->a, 2->b, 3->c}", {(1, "a"), (2, "b"), (3, "c")}),
        ("非单射 {1->a, 2->a, 3->b}", {(1, "a"), (2, "a"), (3, "b")}),
        ("非满射 {1->a, 2->b, 3->b}", {(1, "a"), (2, "b"), (3, "b")}),
        ("不是函数：1 有两像", {(1, "a"), (1, "b"), (2, "c"), (3, "c")}),
        ("不是函数：取值出陪域", {(1, "a"), (2, "z"), (3, "c")}),
    ]
    checked = []
    for name, pairs in functions:
        # 喂有序序偶：check_function 内部对"一个输入多个输出"的候选是按传入序收集的，
        # set 的迭代序随 PYTHONHASHSEED 变——页面对拍会因此飘（本页开发时实测抓到）。
        rep = S.check_function(sorted(pairs), dom, cod)
        checked.append({"name": name, "is_function": rep.is_function,
                        "injective": rep.injective, "surjective": rep.surjective,
                        "bijective": rep.bijective, "reasons": rep.reasons})
    return {"ie": ie, "brute": brute, "terms": terms,
            "power": len(S.power_set(frozenset({1, 2, 3, 4}))),
            "complement": sorted(frozenset({1, 2, 3, 4, 5}) - B),
            "functions": checked}


def collect() -> dict:
    method_count = sum(len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
                       for p in sorted(TESTS.glob("test_*.py")))
    rsa = _collect_rsa()
    nt = _collect_numbertheory()
    groups_data = _collect_groups()
    sets_data = _collect_sets()
    ok_groups = sum(1 for g in groups_data if g["ok"])
    facts = [
        ["RSA 教学密钥", f"p={rsa['p']}、q={rsa['q']}、n={rsa['n']}（{len(str(rsa['n']))} 位）——种子 42 可复现"],
        ["加密回读", f"逐字节往返{'成功' if rsa['restored'] == rsa['text'] else '失败！'}；同明文两次密文"
                  f"{'相同（教科书 RSA 的确定性缺陷，页面下方明说）' if rsa['deterministic'] else '不同'}"],
        ["快速幂成本", f"7^65537 mod 1e9+7：平方-乘 {nt['modpow']['fast']} 次乘法 vs 朴素 {nt['modpow']['naive']} 次"],
        ["群判定器", f"{len(groups_data)} 张表：{ok_groups} 张是群、{len(groups_data) - ok_groups} 张坏表带反例"],
        ["测试方法", f"{method_count} 个（tests/ def test_ 现数；run.bat 一趟是权威）"],
    ]
    return {"facts": facts, "rsa": rsa, "nt": nt, "groups": groups_data, "sets": sets_data}


# ------------------------------------------------------------------ 渲染

STYLE = """
:root{--ink:#16181d;--muted:#5f6773;--line:#d5d9e0;--card:#fff;--bg:#f7f8fa;--accent:#1d4ed8;--ok:#14603a;--bad:#a41f1f;--warn:#8a5a00}
*{box-sizing:border-box}
body{margin:0;padding:1.4rem 1.1rem 3rem;background:var(--bg);color:var(--ink);font:16px/1.7 system-ui,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:71rem;margin:0 auto}
h1{font-size:1.5rem;margin:.2rem 0}h2{font-size:1.05rem;margin:1.6rem 0 .5rem}h3{font-size:.98rem;margin:1.2rem 0 .4rem}
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
.badge{display:inline-block;font-size:.8rem;padding:.08rem .55rem;border-radius:999px;border:1px solid var(--line);color:var(--muted);margin-right:.3rem}
.badge.ok{color:var(--ok);border-color:var(--ok)}.badge.bad{color:var(--bad);border-color:var(--bad)}.badge.warn{color:var(--warn);border-color:var(--warn)}
footer{color:var(--muted);font-size:.85rem;margin-top:2.2rem}
kbd{font-family:ui-monospace,Consolas,monospace;font-size:.85em;border:1px solid var(--line);border-radius:4px;padding:0 .3rem;background:#fff}
.callout{border-left:4px solid var(--warn);background:#fff8e6;padding:.5rem .8rem;border-radius:0 8px 8px 0;font-size:.88rem}
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
    cards = "".join(f'<div class="card"><b>{k}</b><span>{v}</span></div>' for k, v in payload["facts"])
    rsa, nt = payload["rsa"], payload["nt"]
    ie, terms = payload["sets"], payload["sets"]["terms"]
    group_chips = "".join(
        f'<button class="chip" data-tab="g-{i}">{g["name"]}</button>' for i, g in enumerate(payload["groups"]))
    group_panes = []
    for i, g in enumerate(payload["groups"]):
        badges = (f'<span class="badge {"ok" if g["closure_ok"] else "bad"}">封闭：{"是" if g["closure_ok"] else "否"}</span>'
                  f'<span class="badge {"ok" if g["assoc_ok"] else "bad"}">结合：{"是" if g["assoc_ok"] else "否"}</span>'
                  f'<span class="badge {"ok" if g["identity"] is not None else "bad"}">单位元：'
                  f'{g["identity"] if g["identity"] is not None else "无"}</span>'
                  f'<span class="badge {"ok" if g["inverses_ok"] else "bad"}">逆元：{"齐" if g["inverses_ok"] else "缺"}</span>')
        abelian = ""
        if g["abelian"] is not None:
            if g["abelian"]:
                abelian = '<span class="badge ok">交换（abelian_witness=None）</span>'
            else:
                t = g["abelian_witness"]
                abelian = f'<span class="badge bad">不交换：见证 {t[:3]} -> {t[3]} != {t[4]}</span>'
        verdict = ('<span class="badge ok">是群</span>' if g["ok"] else '<span class="badge bad">不是群</span>')
        explain = "；".join(g["explain"])
        group_panes.append(
            f'<div data-pane-id="g-{i}"{" hidden" if i else ""}>'
            f'<p>{verdict}{badges}{abelian}</p>'
            f'<p class="note">{g["note"]}——判定依据：{explain}</p>'
            f'<pre class="code">运算表：\n{g["table"]}</pre></div>')
    func_rows = "".join(
        f'<tr><td>{f["name"]}</td>'
        f'<td>{"是" if f["is_function"] else "不是"}</td>'
        f'<td>{"是" if f["injective"] else "否"}</td>'
        f'<td>{"是" if f["surjective"] else "否"}</td>'
        f'<td>{"是" if f["bijective"] else "否"}</td>'
        f'<td class="note">{"；".join(f["reasons"]) or "——"}</td></tr>'
        for f in payload["sets"]["functions"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B4-algebra-rsa · 数论与代数（课设作品集）</title>
<style>{STYLE}</style>
</head>
<body data-showcase="B4-algebra-rsa">
<main>
<p class="note"><a href="../../../showcase/index.html">← 作品集总入口</a> <span style="white-space:nowrap">　·　上一件 <a href="../../../projects/B3-logic-lab/web/showcase.html">B3</a>　·　下一件 <a href="../../../projects/B5-cpu-sim/web/showcase.html">B5</a></span>　·　<a href="#lab">实时实验台</a>（本页双击即看，零网络依赖）</p>
<h1>B4-algebra-rsa · 数论底座 + 教学 RSA + 群判定</h1>
<p class="note">集合论与代数 · 欧几里得与 Bézout、平方-乘快速幂、CRT、教学 RSA 的逐字节回读与
"确定性"红牌；四条群公理逐条判定（含三张坏表的反例）；集合容斥与函数三档性质。</p>

<h2>实测数字（本页现算）</h2>
<section id="facts" class="cards">{cards}</section>

<h2>展示区</h2>
<section id="demo" class="panel">
  <h3>教学 RSA（明文 -> 密文 -> 回读）</h3>
  <pre class="code wrap">密钥（seed=42，确定性生成）：p={rsa["p"]}  q={rsa["q"]}  n=p·q={rsa["n"]}  φ=(p-1)(q-1)={rsa["phi"]}
公开指数 e={rsa["e"]}    私密指数 d={rsa["d"]}（e·d ≡ 1 mod φ）
明文 m={rsa["message"]}   加密 c=m^e mod n = {rsa["cipher"]}   解密 c^d mod n = {rsa["back"]}
往返校验：{"成功" if rsa["roundtrip"] else "失败"}
文本「{rsa["text"]}」→ 分块密文 {rsa["blocks"]} → 回读「{rsa["restored"]}」：{"逐字节一致" if rsa["restored"] == rsa["text"] else "不一致！"}
同明文再加密一次：{"密文相同（c1 == c2）" if rsa["deterministic"] else "密文不同"}</pre>
  <p class="callout">红牌：这是教科书 RSA——确定性、无填充、小素数。同明文两次同密文（如上）意味着
  可猜测攻击成立；它只用来讲原理，绝不用于真实秘密保护。工程上的修法（OAEP 填充、大素数、恒定时间运算）
  在 README 的练习里。</p>

  <h3>数论底座（成本是数出来的）</h3>
  <pre class="code wrap">egcd(1071, 462)：g={nt["egcd"]["g"]}，x={nt["egcd"]["x"]}，y={nt["egcd"]["y"]}（递推版）
              迭代版 {'给出相同结果' if nt["egcd"]["same"] else '分叉了！'}
Bézout 验证：1071·x + 462·y = {nt["egcd"]["g"]}：{"成立" if nt["egcd"]["bezout"] else "不成立！"}
mod_pow(7, 65537, 1e9+7) = {nt["modpow"]["value"]}
  平方-乘：{nt["modpow"]["fast"]} 次乘法；朴素逐个乘：{nt["modpow"]["naive"]} 次 —— 差 {nt["modpow"]["naive"] // nt["modpow"]["fast"]} 倍
mod_inverse(17, 3120) = {nt["inverse"]}（教学密钥里 d 就是用它在算）
CRT：x ≡ 2 (mod 3) ≡ 3 (mod 5) ≡ 2 (mod 7) 的解 x = {nt["crt"]["value"]}
  逐项验证：{"、".join(f"{v} % {m} = {v % m}（期望 {r}）" for (v, m), r in zip([(nt["crt"]["value"], m) for m in nt["crt"]["moduli"]], nt["crt"]["residues"]))}</pre>

  <h3>群判定器（四条定义 + 反例）</h3>
  <p class="note">点一张表：封闭 / 结合 / 单位元 / 逆元逐条判定；坏表给反例，好表再判交换性。</p>
  <div class="chips" data-tabs="groups">{group_chips}</div>
  <div data-pane="groups">{"".join(group_panes)}</div>

  <h3>集合与函数</h3>
  <pre class="code wrap">A={{{",".join(map(str, sorted({1, 2, 3, 4, 5})))}}}  B={{{",".join(map(str, sorted({4, 5, 6})))}}}  C={{{",".join(map(str, sorted({2, 4, 7})))}}}
容斥：{terms["|A|"]}+{terms["|B|"]}+{terms["|C|"]}-{terms["|A∩B|"]}-{terms["|A∩C|"]}-{terms["|B∩C|"]}+{terms["|A∩B∩C|"]} = {ie}
  暴力并集：|A∪B∪C| = {payload["sets"]["brute"]} —— {"两法一致" if ie == payload["sets"]["brute"] else "两法分叉！"}
幂集：|2^{{1,2,3,4}}| = {payload["sets"]["power"]}（2^4）
差集：A \\ B = {payload["sets"]["complement"]}</pre>
  <table class="plain"><tr><th>函数样板（D=1,2,3 -> C=a,b,c）</th><th>是函数</th><th>单射</th><th>满射</th><th>双射</th><th>理由</th></tr>{func_rows}</table>
</section>

<h2>怎么自己跑</h2>
<section id="repro" class="panel">
  <ul>
    <li><kbd>run.bat</kbd>：自测 + 六段演示（数论 / RSA / 群表 / 集合 / 函数 / 对拍）。</li>
    <li><kbd>python -m unittest discover -s tests</kbd>：完整测试（手算 + 双实现对拍 + 暴力参照）。</li>
    <li><kbd>python tools/showcase.py --write</kbd>：重新生成本页；<kbd>--check</kbd> 重算比对、过期即红。</li>
  </ul>
  <p class="note">本页是生成物：数据由上面这条命令从 algebra/ 现算；别手改本页。观感与顺手程度归你实跑验收。</p>
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
    ap = argparse.ArgumentParser(description="B4 展示页生成器（口径：showcase/SPEC.md）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])
    payload = collect()
    fresh = render(payload)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(fresh, encoding="utf-8", newline="\n")
        print(f"已写出 {OUT.relative_to(ROOT)}：{len(fresh.encode('utf-8'))} 字节"
              f"（RSA/数论/群表/集合全部现算）")
        return 0
    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} 不存在——跑 python tools/showcase.py --write")
            return 1
        disk = OUT.read_text(encoding="utf-8")
        if disk != fresh:
            print("展示页与现算不一致（页面过期或手改过）：跑 python tools/showcase.py --write")
            return 1
        print(f"展示页新鲜：与现算逐字一致（RSA 回读、{len(payload['groups'])} 张群表、"
              f"容斥与函数样板）。")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
