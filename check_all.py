"""check_all.py —— 全仓一键体检：把"整仓现在健康吗"收成一条命令（2026-10-03）。

跑什么（全部只读；每步子进程、强制 PYTHONUTF8=1、超时 600 秒）：
  1. 展示层：showcase/check.py（33 页结构/自包含/新鲜度 + 总入口 + lab.js 语法）
  2. G2 练习册：g2/render.py --check（40 卡锚点逐字 + 渲染新鲜度）
  3. B40 证据核验：31 条证据的指针/提交/锚点三层核验
  4. B41 种子核验：行数重算 / 缺口探针 / 证据锚点
  5. dorm 事实台账：27 键现算（PLAN 改动的联动哨兵）
  6. dorm 管理文档核对：check_pm（台账引用/风险登记/复盘分类）
  7. 交付齐全性：scan_refs.py projects（README + run.bat 引用扫描）
--deep 追加：33 个项目的展示页测试套件（各项目 tests/test_showcase.py）。

不覆盖（如实声明）：各项目核心测试套件（Python/C++/Java，见各项目 run.bat）、
WSL/Java/Spark 的运行环境、以及所有"人工验收项"（真窗口/浏览器观感/走查）。

行为：打印每步 [PASS]/[FAIL] 与耗时；任一失败 → 退出码 1 并打印该步输出尾部。
--selftest：用一对"必过/必红"的假步骤证明体检器本身会红、也会绿。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def steps(deep: bool) -> list:
    out = [
        ("展示层校验（33 页 + 总入口 + lab.js）", [PY, "showcase/check.py"]),
        ("G2 练习册（40 卡锚点 + 渲染新鲜度）", [PY, "g2/render.py", "--check"]),
        ("B40 证据核验（指针/提交/锚点三层）", [PY, "projects/B40-career-map/tools/check_evidence.py"]),
        ("B41 种子核验（行数/探针/锚点）", [PY, "projects/B41-thesis-seeds/tools/check_seeds.py"]),
        ("dorm 事实台账（27 键现算）", [PY, "projects/dorm-repair/tools/project_ledger.py", "--check"]),
        ("dorm 管理文档核对（check_pm）", [PY, "projects/dorm-repair/checks/check_pm.py"]),
        ("交付齐全性（README+run.bat 引用扫描）", [PY, "scan_refs.py", "projects"]),
    ]
    if deep:
        for g in sorted((ROOT / "projects").glob("*/")):
            f = g / "tests" / "test_showcase.py"
            if not f.is_file():
                f = g / "tests" / "showcase_check.py"
            if f.is_file():
                out.append((f"展示页套件 {g.name}", [PY, str(f)]))
    return out


def run_step(label: str, cmd: list) -> bool:
    env = dict(os.environ, PYTHONUTF8="1")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=600)
    dt = time.time() - t0
    ok = proc.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {label}（{dt:.1f}s）")
    if not ok:
        merged = (proc.stdout or "") + "\n" + (proc.stderr or "")
        tail = [ln for ln in merged.strip().splitlines() if ln][-8:]
        for ln in tail:
            print("      |", ln)
    return ok


def selftest() -> int:
    ok_run = run_step("自检：必过步骤", [PY, "-c", "print('ok')"])
    red_run = run_step("自检：必红步骤（预期 FAIL）", [PY, "-c", "import sys; print('boom'); sys.exit(3)"])
    good = ok_run and not red_run
    print("体检器自检：" + ("PASS" if good else "FAIL"))
    return 0 if good else 1


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="全仓一键体检（口径见文件头与根 README）")
    ap.add_argument("--deep", action="store_true", help="追加 33 个项目的展示页测试套件")
    ap.add_argument("--selftest", action="store_true", help="用假步骤自检体检器会红会绿")
    args = ap.parse_args(argv[1:])
    if args.selftest:
        return selftest()
    plan = steps(args.deep)
    t0 = time.time()
    results = [run_step(label, cmd) for label, cmd in plan]
    dt = time.time() - t0
    bad = [label for (label, _), ok in zip(plan, results) if not ok]
    if bad:
        print(f"\n全仓体检：{len(plan) - len(bad)} 项通过 / {len(bad)} 项失败（总耗时 {dt:.1f}s）")
        print("失败项：" + "；".join(bad))
        return 1
    mode = "--deep" if args.deep else "默认"
    print(f"\n全仓体检（{mode}）：{len(plan)} 项全部通过（总耗时 {dt:.1f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
