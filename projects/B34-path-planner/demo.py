"""demo.py —— B34 六段演示：手算基准 → 三算法对拍表 → 可采约性 → 反例 → 无解 → 动画页。

数字全部运行时现算；唯一含实时测量的是第 3 段的耗时列（【实测】，两次运行有波动），
其余由固定种子驱动、逐字可复现（tools/logdiff.py 可核对两次 run.bat 日志）。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from planner import grid as G           # noqa: E402
from planner import heuristics as H     # noqa: E402
from planner import search as S         # noqa: E402
from planner import viz                 # noqa: E402


def section(no: int, title: str) -> None:
    print("\n" + "=" * 78 + f"\n  {no}) {title}\n" + "=" * 78)


def show(label: str, value: object) -> None:
    print(f"  {label:<26}{value}")


def draw_grid(grid: G.Grid, path: list, start, goal, width: int = 24) -> None:
    path_set = set(path)
    for y in range(grid.height):
        row = []
        for x in range(grid.width):
            cell = (x, y)
            if cell == start:
                row.append("S")
            elif cell == goal:
                row.append("G")
            elif cell in grid.obstacles:
                row.append("#")
            elif cell in path_set:
                row.append("*")
            else:
                row.append(".")
        print("   " + "".join(row))


def main() -> int:
    print("B34-path-planner 演示：栅格 A* / Dijkstra / BFS 同源对拍（无人系统）")

    # ------------------------------------------------------------------ 1
    section(1, "手算基准：小地图与直走廊")
    corridor = G.corridor(4)
    r = S.dijkstra(corridor, (0, 0), (3, 0))
    show("1×4 走廊代价（手算 3）", r.cost)
    g = G.Grid(width=8, height=6, obstacles={(2, 1), (2, 2), (2, 3), (5, 3), (5, 4)})
    r2 = S.astar(g, (0, 0), (7, 5), H.manhattan)
    print("   地图（# 障碍，* 路径，S/G 起终点）：")
    draw_grid(g, r2.path, (0, 0), (7, 5))
    show("A* 代价 / 路径长度", f"{r2.cost} / {len(r2.path)} 格")
    show("路径合法性检查", S.validate_path(g, r2.path, (0, 0), (7, 5)) or "通过")

    # ------------------------------------------------------------------ 2
    section(2, "对拍摘要：A* == Dijkstra 的代价，且扩展更少")
    same4 = sum(
        S.dijkstra(g4, (0, 0), (23, 17)).cost == S.astar(g4, (0, 0), (23, 17), H.manhattan).cost
        for g4 in (G.random_grid(24, 18, 0.28, seed=s) for s in range(1, 31)))
    dijk_exp = sum(S.dijkstra(g4, (0, 0), (23, 17)).expanded_count
                   for g4 in (G.random_grid(24, 18, 0.28, seed=s) for s in range(1, 11)))
    astar_exp = sum(S.astar(g4, (0, 0), (23, 17), H.manhattan).expanded_count
                    for g4 in (G.random_grid(24, 18, 0.28, seed=s) for s in range(1, 11)))
    show("4 邻域 30 图代价一致", f"{same4}/30")
    show("10 图扩展数（Dijkstra → A*）", f"{dijk_exp} → {astar_exp}")
    same8 = sum(
        S.dijkstra(g8, (0, 0), (23, 17)).cost == S.astar(g8, (0, 0), (23, 17), H.octile).cost
        for g8 in (G.random_grid(24, 18, 0.28, seed=s, allow_diagonal=True) for s in range(1, 31)))
    show("8 邻域 30 图代价一致（octile）", f"{same8}/30")
    bfs_ok = all(S.dijkstra(g4, (0, 0), (15, 11)).cost == S.bfs(g4, (0, 0), (15, 11)).cost
                 for g4 in (G.random_grid(16, 12, 0.25, seed=s) for s in range(1, 21)))
    show("无权图上 BFS 等价", f"{bfs_ok}/20 图")

    # ------------------------------------------------------------------ 3
    section(3, "对比表：代价 / 扩展数 / 耗时【实测】（一张 32×24 种子图）")
    big = G.random_grid(32, 24, 0.28, seed=9)
    bigd = G.random_grid(32, 24, 0.28, seed=9, allow_diagonal=True)
    configs = [
        ("Dijkstra（4 邻域）", big, H.zero),
        ("A* 曼哈顿（4 邻域）", big, H.manhattan),
        ("Dijkstra（8 邻域）", bigd, H.zero),
        ("A* 对角（8 邻域）", bigd, H.octile),
        ("A* 欧氏（8 邻域）", bigd, H.euclidean),
    ]
    print(f"   {'配置':<22}{'代价':>9}{'扩展':>7}{'耗时[实测]':>12}")
    for name, gx, heur in configs:
        t0 = time.perf_counter()
        res = S.best_first(gx, (0, 0), (31, 23), heur, name=name)
        ms = (time.perf_counter() - t0) * 1000
        print(f"   {name:<22}{res.cost:>9.3f}{res.expanded_count:>7}{ms:>10.1f} ms")

    # ------------------------------------------------------------------ 4
    section(4, "可采纳性是量出来的：max(h - 真实距离) ≤ 0")
    g16 = G.random_grid(16, 12, 0.25, seed=5)
    g16d = G.random_grid(16, 12, 0.25, seed=5, allow_diagonal=True)
    show("4 邻域 × 曼哈顿", f"slack = {S.max_admissibility_slack(g16, (15, 11), H.manhattan):+.3f}")
    show("8 邻域 × 对角(octile)", f"slack = {S.max_admissibility_slack(g16d, (15, 11), H.octile):+.3f}")
    show("8 邻域 × 欧氏", f"slack = {S.max_admissibility_slack(g16d, (15, 11), H.euclidean):+.3f}")
    show("8 邻域 × 曼哈顿（故意撒谎）", f"slack = {S.max_admissibility_slack(g16d, (15, 11), H.manhattan):+.3f}")

    # ------------------------------------------------------------------ 5
    section(5, "反例：不可采纳的启发式给出次优路径（种子图 seed=3）")
    gce = G.random_grid(10, 8, 0.25, seed=3, allow_diagonal=True)
    d = S.dijkstra(gce, (0, 0), (9, 7))
    a = S.astar(gce, (0, 0), (9, 7), H.manhattan)
    show("Dijkstra 最优代价", f"{d.cost:.6f}（= 10 + 3√2）")
    show("A* 曼哈顿×8邻域 代价", f"{a.cost:.6f}（= 10 + 4√2，多贪一步直路）")
    show("差值", f"{a.cost - d.cost:.6f}（恰好 2-√2）")
    show("结论", "启发式一撒谎，A* 的最优性保证就没了——这是它的前提条件")

    # ------------------------------------------------------------------ 6
    section(6, "无解与退化 + 搜索展开动画（自包含 HTML）")
    gwall, ws, wg = G.walled_scene()
    rw = S.dijkstra(gwall, ws, wg)
    show("目标被围死", f"found={rw.found}；原因：{rw.reason}")
    r0 = S.dijkstra(gwall, ws, ws)
    show("起点=终点", f"found={r0.found}；代价 {r0.cost}；路径 {r0.path}")

    trace = viz.export_trace(bigd, (0, 0), (31, 23), S.astar(bigd, (0, 0), (31, 23), H.octile), "octile")
    (ROOT / "build").mkdir(parents=True, exist_ok=True)
    out = ROOT / "build" / "plan.html"
    size = viz.build_page(trace, out)
    show("动画页产物", f"build/{out.name}（{size} 字节，展开 {trace['meta']['expanded']} 步）")
    node = shutil.which("node")
    if node:
        script = re.search(r"<script>\n(.*)</script>", out.read_text(encoding="utf-8"), re.S).group(1)
        js_path = ROOT / "build" / "extracted.js"
        js_path.write_text(script, encoding="utf-8")
        try:
            r = subprocess.run([node, "--check", str(js_path)], capture_output=True, text=True)
            show("node --check", f"退出码 {r.returncode}")
        except OSError as err:
            show("node 执行失败（跳过）", str(err))
    else:
        show("node 不可用", "跳过语法体检")

    print("\n" + "=" * 78)
    print("用户验收（我不代勾）：打开 build\\plan.html，点「播放」看搜索怎么展开——")
    print("冷色越深展开越晚、红色是当前格、到终点后绿色高亮最终路径；切换速度看节奏。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
