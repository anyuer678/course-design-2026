"""B27-course-kg 四段演示：数据 → 闭包查询 → 缺先修模拟 → 可视化 HTML

HTML 写到临时目录（打印路径供打开），不在项目目录留文件。
断言失败计入退出码。
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kg.graph import load_default
from kg.viz import render_html

FAILS = []


def check(cond, msg):
    print(f"    {'[ok]' if cond else '[fail]'} {msg}")
    if not cond:
        FAILS.append(msg)


def show(title):
    print(f"\n{'=' * 62}\n {title}\n{'=' * 62}")


def demo_data(g):
    show("第一段：图谱数据 —— 41 门任务与 PLAN §3 的依赖边")
    batches = {}
    for t, info in g.nodes.items():
        batches.setdefault(info["batch"], []).append(t)
    for b in sorted(batches):
        print(f"    批次 {b}: {' '.join(batches[b])}")
    kinds = {}
    for e in g.edges:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print(f"    关系边 {len(g.edges)} 条，按类型: {kinds}")
    check(len(g.nodes) == 41, "41 个任务节点")
    check(sum(kinds.values()) == len(g.edges), "边分类账目一致")
    check("先修" in kinds, "存在硬先修边")


def demo_closure(g):
    show("第二段：闭包查询 —— 直接先修 vs 间接先修 vs 解锁")
    print("    B9 操作系统原理：")
    print(f"      直接先修: {sorted(g.direct_prereqs('B9'))}")
    print(f"      全部先修（含间接）: {sorted(g.ancestors('B9'))}")
    check(g.ancestors("B9") == {"B1", "B2", "B5", "B6", "B8"},
          "B9 的先修闭包 = B1/B2/B5/B6/B8（PLAN §3 明文链）")
    des = g.descendants("B11")
    print(f"    B11 计算机网络解锁 {len(des)} 个任务: {sorted(des)}")
    check({"B31", "B30", "B35", "B38", "B37"} <= des,
          "B11 解锁 B31/B30/B35/B38 及其下游 B37")


def demo_missing(g):
    show("第三段：缺先修模拟 —— “想做 B18，还缺什么？”")
    scenarios = [
        ("刚做完批次 2", {"B1", "B2", "B5", "B6", "B7", "B8"}),
        ("做完批次 3", {"B1", "B2", "B5", "B6", "B7", "B8", "B9", "B10",
                        "B11", "B12", "B13"}),
    ]
    for name, done in scenarios:
        missing = g.missing_prereqs("B18", done)
        print(f"    [{name}] 做 B18 还缺 {len(missing)} 项: {sorted(missing)}")
    missing = g.missing_prereqs("B18", {"B1", "B2", "B5", "B6", "B7", "B8"})
    # 手工整理的期望缺口：B9(系统)、B10/B11(库与网络)、B14(Java)、
    # B31(Web) 与批次 5 链上的 B15/B16/B17——恰好等于 B18 的先修闭包
    # 去掉已完成集合。
    expect = {"B9", "B10", "B11", "B14", "B31", "B15", "B16", "B17"}
    check(missing == expect,
          f"第一批模拟缺口 8 项与先修闭包完全一致（{sorted(missing)}）")
    path = g.learning_path("B18")
    print(f"    通往 B18 的学习路径（{len(path)} 步）: {' -> '.join(path)}")
    pos = {t: i for i, t in enumerate(path)}
    ok = all(pos[e["src"]] < pos[e["dst"]] for e in g.edges
             if e["src"] in pos and e["dst"] in pos)
    check(ok, "路径是合法拓扑序")


def demo_viz(g, tmp):
    show("第四段：可视化 —— 自包含 HTML（点击节点高亮先修闭包）")
    html = render_html(g)
    out = Path(tmp) / "kg_graph.html"
    out.write_text(html, encoding="utf-8")
    print(f"    已生成: {out}")
    check(all(f'data-id="{t}"' in html for t in g.nodes), "41 个节点全部出现")
    check(html.count('class="edge"') == len(g.edges), "边全部绘制")
    check("http://" not in html.replace("http://www.w3.org", "")
          and "https://" not in html, "自包含：无任何外部请求")
    print("    用浏览器打开后，点击任意节点即可高亮其全部先修与解锁后继")


def main() -> int:
    print("B27-course-kg 演示（纯标准库，零依赖）")
    g = load_default()
    g.validate()
    tmp = tempfile.mkdtemp(prefix="b27-kg-")
    try:
        demo_data(g)
        demo_closure(g)
        demo_missing(g)
        demo_viz(g, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'=' * 62}")
    if FAILS:
        print(f"演示存在 {len(FAILS)} 处失败：")
        for f in FAILS:
            print(f"  [fail] {f}")
        return 1
    print("四段演示全部通过 [ok]（临时 HTML 已清理）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
