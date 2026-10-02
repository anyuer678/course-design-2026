"""demo.py —— B41 四段演示：事实核验 → 负面对照（改坏必须红）→ 三维比较表 → fsync 基准。

确定性：核验与比较表全部由文件现算；唯一【实测】是末段的本机写盘基准（两行 ms），
logdiff 负责规范化那两行 + unittest 计时。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))

import bench_io                                            # noqa: E402
import check_seeds                                         # noqa: E402
import report_seeds                                        # noqa: E402

REPO_ROOT = ROOT.parents[1]
SEEDS_PATH = ROOT / "data" / "seeds.json"


def section(no: int, title: str) -> None:
    print("\n" + "=" * 78 + f"\n  {no}) {title}\n" + "=" * 78)


def show(label: str, value: object) -> None:
    print(f"  {label:<30}{value}")


def _mutated_problems(mutate) -> list[str]:
    data = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    mutate(data["seeds"])
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="b41-demo-"))
    try:
        path = tmp / "seeds.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return check_seeds.check_seeds_data(path, REPO_ROOT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("B41-thesis-seeds 演示：毕设候选的三维可行性（数字现算；④①②③已选定实施，选定由你）")

    # ------------------------------------------------------------------ 1
    section(1, "事实核验：行数重算 + 缺口探针重跑（过期即红）")
    data = report_seeds._load()
    seeds = data["seeds"]
    problems = check_seeds.check_seeds_data(SEEDS_PATH, REPO_ROOT)
    show("核验结果", "PASS（0 个问题）" if not problems else f"RED：{problems}")
    n_files = sum(len(s["files"]) for s in seeds)
    n_probes = sum(len(s["probes"]) for s in seeds)
    show("规模", f"{len(seeds)} 个未选候选、{n_files} 处文件行数、{n_probes} 个探针")
    chosen = data.get("chosen") or []
    if isinstance(chosen, dict):
        chosen = [chosen]
    if chosen:
        show("已选定并实施", "；".join(f"{c['title']}（{c['date']}）" for c in chosen))
    sample = seeds[0]["probes"][0]
    show(f"抽样：{seeds[0]['id']} 缺口探针",
         f"{sample['name']}（期望计数 {sample['expected']}）")
    b23 = [p for p in seeds[-1]["probes"]]
    show("抽样：B23 环境探针", "；".join(
        f"{p['module']} {'在' if p['expected'] else '缺'}" for p in b23))

    # ------------------------------------------------------------------ 2
    section(2, "负面对照：改坏一处，核验器必须报红（否则数字就是装饰）")
    cases = [("改错一行行数", lambda s: s[0]["files"][0].__setitem__(
                  "lines", s[0]["files"][0]["lines"] + 1)),
             ("改错探针期望值", lambda s: s[0]["probes"][0].__setitem__("expected", 1)),
             ("锚点指向不存在的短语", lambda s: s[0]["evidence"].__setitem__(
                  "anchor", "这段字符串绝不可能出现xq9"))]
    for label, mutate in cases:
        got = _mutated_problems(mutate)
        first = got[0] if got else "（没有报红——BUG）"
        show(label, f"RED，首条：{first}")

    # ------------------------------------------------------------------ 3
    section(3, "三维比较表（数据/资源/评价 + 风险；现算自 data/seeds.json）")
    print(report_seeds.render_report(data))

    # ------------------------------------------------------------------ 4
    section(4, "候选①的资源基准【实测】与本机读数 + 选定指引")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="b41-bench-"))
    try:
        result = bench_io.write_bench(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    show("写 8KB 记录（60 次中位数）", f"plain {result['plain_ms']:>8.3f} ms")
    show("写 8KB + fsync（60 次中位数）", f"fsync {result['fsync_ms']:>8.3f} ms")
    print(f"  {'解读':<30}「提交即持久」的边际成本 ≈ "
          f"{result['fsync_ms'] - result['plain_ms']:.3f} ms/条（本机介质相关，仅供参考）")
    print()
    print("  选定哪一个是你的决定：把候选 id（或'都不选'）告诉我，下一轮按它开题。")
    print("  候选题清单不等于开题；任何一条候选开工前，先跑 run.bat 把基线与本基准过一遍。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
