"""demo.py —— B32 信息安全导论实验六段演示。数字全部运行时现算，不抄文档。

  1) SQL 注入：同一份输入，拼接版与绑定版的后果差多少
  2) HTML 注入：四种上下文里数据有没有拿到"语法身份"（含真 HTTP 取证）
  3) 口令存储：明文 / 无盐快摘要 / 加盐迭代 —— 用**实测吞吐**把差距算成字典成本
  4) 路径穿越：四种写法的判定表（谁在什么载荷上越界）
  5) 静态扫描器：这个包还有几处拼接点，以及"把包装函数摘掉它会不会瞎"
  6) 汇总与红线

红线（先说在演示开头，不放在脚注）：所有靶件都是本实验自己写的教学靶，只在
127.0.0.1、内存数据库与临时目录里活动；载荷是教科书级最小样本；未做完不宣称"完整防护"。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from sec32 import audit as A                            # noqa: E402
from sec32 import creds as C                            # noqa: E402
from sec32 import sqli as Q                             # noqa: E402
from sec32 import traversal as T                        # noqa: E402
from sec32 import xss as X                              # noqa: E402

LINE = "=" * 78


def section(no: int, title: str) -> None:
    print(f"\n{LINE}\n  {no}) {title}\n{LINE}")


def show(label: str, value: object) -> None:
    print(f"  {label:<30}{value}")


def main() -> int:
    print("B32 信息安全导论实验 —— 四组漏洞版/修复版对照 + 一个静态扫描器")
    print("所有数字运行时现算；靶件只在本机内存库与临时目录里活动。")

    section(1, "SQL 注入：同一份输入，拼接与绑定的后果差多少")
    data = Q.measure()
    for name, (vuln, fixed) in data["login"].items():
        verdict = ("漏洞版登入 " + str(vuln["role"]) if vuln["logged_in"] else "漏洞版被拒")
        print(f"  登录·{name:<12} {verdict:<22} 修复版："
              f"{'登入 ' + str(fixed['role']) if fixed['logged_in'] else '被拒'}")
    for name, (vuln, fixed) in data["search"].items():
        leak = "泄漏 %d 行" % len(vuln["rows"]) if vuln["rows"] else f"没拿到（{vuln['error']}）"
        print(f"  查询·{name:<12} {leak:<30} 修复版：{len(fixed['rows'])} 行")
    for name, (vuln, fixed) in data["order"].items():
        left = "%s" % ([r[0] for r in vuln["rows"]] if vuln["rows"] else vuln["error"])
        right = "%s" % ([r[0] for r in fixed["rows"]] if fixed["rows"] else fixed["error"])
        print(f"  排序·{name:<14} 漏洞版 {left:<22} 修复版 {right}")
    stacked = data["stacked"]
    show("叠句载荷 execute()", stacked["execute"])
    show("叠句载荷 executescript()", f"{stacked['executescript']}，"
                                      f"表 {stacked['tables_before']} → {stacked['tables_after']}")
    show("二阶注入（读库拼串）", "泄漏 " +
         str([r["rows"] for r in data["second_order"]["concat"] if r["rows"]][:1]))
    show("二阶注入（读库绑定）", str([c["rows"] for c in data["second_order"]["bound"]]))

    section(2, "HTML 注入：数据有没有拿到“语法身份”")
    for row in X.payload_table():
        print(f"  {row['label']:<16} 漏洞版信号 {len(row['vuln_evidence'])} 条"
              f"（{row['vuln_evidence'][0][:34] if row['vuln_evidence'] else '无'}…）"
              f"  修复版 {len(row['safe_evidence'])} 条  往返{'一致' if row['safe_roundtrip'] else '不一致'}")
    both = X.serve_both(X.PAYLOADS["脚本标签"])
    show("真起服务真发请求（漏洞版）",
         f"HTTP {both['vuln']['status']} ｜ {both['vuln']['headers'].get('content-type')} ｜ "
         f"信号 {len(both['vuln']['evidence'])} 条")
    show("真起服务真发请求（修复版）",
         f"HTTP {both['safe']['status']} ｜ 信号 {len(both['safe']['evidence'])} 条 ｜ "
         f"响应字节里含 &lt;script&gt;：{'&lt;script&gt;' in both['safe']['body']}")

    section(3, "口令存储：把“慢”算成攻击者的字典成本（本段是实时测量，两次运行会有 ±5% 波动）")
    cost = C.cost_table()
    show("MD5 单核吞吐", f"{cost['md5_per_sec']:,.0f} 次/秒")
    show("SHA-256 单核吞吐", f"{cost['sha256_per_sec']:,.0f} 次/秒（比 MD5 还快，因为 CPU 有 SHA 指令）")
    for iters, rate in sorted(cost["pbkdf2_ladder"].items()):
        print(f"  PBKDF2 迭代 {iters:>7,}            {rate:>8.1f} 次/秒")
    show("默认 120k 迭代", f"{cost['pbkdf2_default_per_sec']:.1f} 次/秒 => 比 MD5 慢 "
                           f"{cost['slowdown_vs_md5']:,.0f} 倍")
    show("100 万词字典（MD5）", f"{C.dictionary_hours(10**6, cost['md5_per_sec'])*3600:.1f} 秒跑完")
    show("100 万词字典（PBKDF2）", f"{C.dictionary_hours(10**6, cost['pbkdf2_default_per_sec']):.1f} 小时")
    effect = C.salt_effect("hunter2")
    show("无盐同口令", f"摘要相同={effect['md5_same']}（彩虹表与横向比较的前提）")
    show("加盐同口令", f"摘要相同={effect['pbkdf2_same']}，盐不同={effect['salt_differs']}")
    ent = C.token_entropy()
    show("random 令牌可复现", f"{ent['random_reproducible']}（已知种子就能重放）")
    show("secrets 令牌", f"可复现={ent['secrets_reproducible']}，唯一={ent['secrets_unique']}，"
                         f"{ent['secrets_bits_per_token']} bit/枚")

    section(4, "路径穿越：四种写法的判定表")
    tree = T.make_tree()
    try:
        rows = T.build_case_rows(tree)
    finally:
        import shutil
        shutil.rmtree(tree["base"], ignore_errors=True)
    header = f"  {'载荷':<26}{'join':<10}{'黑名单':<10}{'前缀检查':<10}{'修复版':<10}"
    print(header)
    for row in rows:
        if "skipped" in row:
            print(f"  {row['name']:<26}(跳过：{row['skipped']})")
            continue
        print(f"  {row['name']:<26}{row['join']['verdict']:<10}{row['blacklist']['verdict']:<10}"
              f"{row['prefix']['verdict']:<10}{row['guarded']['verdict']:<10}")
    ref = T.stdlib_reference()
    show("标准库参照（解一次）", f"%2e%2e%2f → {ref['unquote_2e2e2f']!r}")
    show("标准库参照（解两次）", f"%252e%252e%252f → {ref['unquote_twice_252e']!r}")
    show("本机大小写语义", f"is_relative_to 大小写无关={ref['is_relative_to_case_flip']}")

    section(5, "静态扫描器：这个包还有几处拼接点")
    sites = A.scan_package()
    for module, found in sorted(sites.items()):
        print(f"  {module:<14}{len(found)} 处" +
              (f" → {[s['func'] for s in found]}" if found else ""))
    show("登记表双向比对", A.problems() or "无（扫到没登记 / 登记了扫不到 都会红）")
    full = len(sites.get("sqli.py", []))
    saved = A.NAME_SINKS
    A.NAME_SINKS = ()
    try:
        blind = len(A.scan_package().get("sqli.py", []))
    finally:
        A.NAME_SINKS = saved
    show("把包装函数从 sink 摘掉", f"扫出 {blind} 处（原 {full} 处）——静态检查最典型的失效方式")

    section(6, "汇总")
    s = A.summary()
    show("SQL 对照结论", f"漏洞版登入 {s['sqli']['login_leaks_vuln']} 例，修复版 {s['sqli']['login_leaks_fixed']} 例"
                         "（只有正常口令那一条应当成功）")
    show("XSS 对照结论", f"{s['xss']['vuln_flagged']}/{s['xss']['payloads']} 载荷在漏洞版有信号，"
                         f"修复版 {s['xss']['safe_flagged']} 条，往返一致 {s['xss']['roundtrip_ok']} 条")
    show("穿越对照结论", f"修复版越界 {s['traversal']['by_handler']['guarded']['escaped']} 次"
                         f"（join 版 {s['traversal']['by_handler']['join']['escaped']} 次）")
    show("审计结论", s["audit_problems"] or "无未登记拼接点")
    print("\n" + LINE)
    print("本轮没做的（别把它当安全产品）：不做真实系统渗透、不做免杀/绕过 WAF、不做缓冲区溢出"
          "（PLAN 的选做项）；不声称“转义一次就安全”“绑定能救标识符”“MD5 换个盐就行”。")
    print("浏览器会不会真的执行脚本属于浏览器行为，本实验只证明到响应字节层（未验证）。")
    print("第 3 段的吞吐是**实时测量**，两次运行会有 ±5% 的自然波动（其余段落逐字一致，"
          "可用 `python demo.py > a.txt` 跑两遍 diff 自证）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
