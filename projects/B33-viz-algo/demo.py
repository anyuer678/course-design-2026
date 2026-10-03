"""demo.py —— B33 演示：导出 → 回放核对 → 生成动画页 → 语法体检（数字全部现算）

 1) 调 export_trace.exe 重新导出 sort/bfs/dfs 三份操作记录（数据来自 B2 的结构库）
 2) 回放保真：排序逐步重建 + BFS/DFS 对独立 Python 参照——把"演的就是真算法"量化
 3) 生成自包含 HTML（内嵌数据 + 手写 JS 动画器），打印体积与构成
 4) node --check 做 JS 语法体检（没有 node 就跳过，如实标注）
 5) 打印用户验收指引（打开 HTML → 播放/暂停/单步）

本演示无耗时输出、无随机数，两遍运行应逐字相同。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from vizlab import page, replay   # noqa: E402

TRACES = ROOT / "build" / "traces"
EXPORTER = ROOT / "build" / "export_trace.exe"


def section(no: int, title: str) -> None:
    print("\n" + "=" * 78 + f"\n  {no}) {title}\n" + "=" * 78)


def show(label: str, value: object) -> None:
    print(f"  {label:<26}{value}")


def main() -> int:
    print("B33-viz-algo 演示：B2 导出操作记录 → 回放核对 → 自包含动画页")

    section(1, "导出操作记录（B2 的只读 trace 观察口）")
    if not EXPORTER.exists():
        print(f"  缺 {EXPORTER} —— 先跑 run.bat 的编译步")
        return 1
    TRACES.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(EXPORTER), str(TRACES)], capture_output=True, text=True)
    if result.returncode != 0:
        print("  导出失败：", result.stdout, result.stderr)
        return 1
    print("  " + result.stdout.strip())
    sizes = {name: (TRACES / f"{name}.json").stat().st_size for name in ("sort", "bfs", "dfs")}
    show("三份 JSON 字节数", sizes)

    section(2, "回放保真：演的是不是真算法，逐步对")
    sort_t = replay.load_trace(TRACES / "sort.json")
    checks = replay.replay_sort(sort_t)
    bad = [c for c in checks if not c["ok"]]
    show("堆排序事件数", len(checks))
    show("  逐步回放失败步数（应为 0）", len(bad))
    show("  最终状态 == 升序排序", replay.sort_final_state(sort_t) == sorted(sort_t["input"]))
    for algo, ref in (("bfs", replay.reference_bfs), ("dfs", replay.reference_dfs)):
        trace = replay.load_trace(TRACES / f"{algo}.json")
        got = [{"op": s["op"], "a": s["a"], "state": s["state"]} for s in trace["steps"]]
        show(f"{algo.upper()} 步数 / 与独立参照一致",
             f"{len(trace['steps'])} / {got == ref(trace)}")

    section(3, "生成自包含动画页（内嵌数据，双击即开）")
    out = ROOT / "build" / "viz.html"
    size = page.build_page(TRACES, out)
    html = out.read_text(encoding="utf-8")
    embedded = len(re.search(r"const TRACES = (\{.*?\});\n", html, re.S).group(1))
    show("产物", "build/viz.html")
    show("HTML 字节数", size)
    show("其中内嵌数据字节数", embedded)
    show("页面构成", "堆排序条形图 + 图遍历 SVG + 播放/暂停/单步/速度")

    section(4, "JS 语法体检（node --check；无 node 则如实跳过）")
    node = shutil.which("node")
    if node:
        script = re.search(r"<script>\n(.*)</script>", html, re.S).group(1)
        js_path = ROOT / "build" / "extracted.js"
        js_path.write_text(script, encoding="utf-8")
        try:
            r = subprocess.run([node, "--check", str(js_path)], capture_output=True, text=True)
        except OSError as err:
            show("node 执行失败（跳过）", f"{err}")     # 例如 PATH 上的 shim/伪文件
            r = None
        if r is not None:
            show("node --check 退出码", r.returncode)
            if r.returncode != 0:
                print(r.stderr[:400])
                return 1
    else:
        show("node 不可用", "跳过（不影响页面本身）")

    section(5, "用户验收指引（动画观感由你实跑确认）")
    print("  1. 打开 build\\viz.html（双击即可，数据已内嵌，无需服务器）")
    print("  2. 左卡片：点「播放」看建堆与取顶；用「下一步/上一步」单步，选速度换节奏")
    print("  3. 右卡片：BFS / DFS 单选切换，观察队列与栈的前沿（橙色）怎么变")
    print("  4. 动画观感（动没动、卡不卡、讲不讲得清）请如实反馈——这一步我不代勾")

    print("\n" + "=" * 78)
    print("完成：演示跑通。本演示无耗时输出，两遍运行应逐字相同。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
