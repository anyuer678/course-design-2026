"""check_all.py —— 全仓一键体检：把"整仓现在健康吗"收成一条命令（2026-10-03）。

跑什么（全部只读；每步子进程、强制 PYTHONUTF8=1、超时 600 秒）：
  1. 展示层：showcase/check.py（33 页结构/自包含/新鲜度 + 总入口 + lab.js 语法）
  2. G2 练习册：g2/render.py --check（40 卡锚点逐字 + 渲染新鲜度）
  3. B40 证据核验：31 条证据的指针/提交/锚点三层核验
  4. B41 种子核验：行数重算 / 缺口探针 / 证据锚点
  5. dorm 事实台账：27 键现算（PLAN 改动的联动哨兵）
  6. dorm 管理文档核对：check_pm（台账引用/风险登记/复盘分类）
  7. 交付齐全性：scan_refs.py projects（README + run.bat 引用扫描）
  7.4 共享资产新鲜度：sync_assets.py --check（webkit/kb.css+echarts → 8 产品 16 份副本）
  7.5 容器布局对拍：check_docker_layout.py（Dockerfile COPY × .dockerignore × 代码读取 × compose 端口，
      8 产品；compose 全家桶没实测过的替代哨兵，轮二十二 7 处容器 bug 的固化）
  7.6 新鲜空数据起服：check_fresh_boot.py（8 产品 staged 空卷真启动探活，
      轮二十四新增——compose 命名卷首挂是空目录，此前从未验证过）
  7.7 run.bat 测试数声明对账：check_runbat_claims.py（活文档里的 "N tests"
      × pytest 实况收集，轮二十五新增——boardweb 加测试后 run.bat 还写 8 的漂移固化）
  8. 产品层：webframe（36，含静态路径安全专项）/ studio（26，八产品真启停+审计+探活历史+WS 状态推送）/ linkbox（76）/ simlab（37）
     / datascope（45）/ cachekv（19）/ sensorhub（28）/ board（12）
     / courselab（154 项端到端自检）/ boardweb（15，含图形库五形状）
--deep 追加：33 个项目的展示页测试套件（各项目 tests/test_showcase.py）。

不覆盖（如实声明）：各项目核心测试套件（Python/C++/Java，见各项目 run.bat）、
WSL/Java/Spark 的运行环境、以及所有"人工验收项"（真窗口/浏览器观感/走查）。

行为：打印每步 [PASS]/[FAIL] 与耗时；任一失败 → 退出码 1 并打印该步输出尾部。
--selftest：用一对"必过/必红"的假步骤证明体检器本身会红、也会绿。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # scripts/ 的上一级 = 仓库根
PY = sys.executable


def steps(deep: bool) -> list:
    out = [
        ("展示层校验（33 页 + 总入口 + lab.js）", [PY, "showcase/check.py"]),
        ("G2 练习册（40 卡锚点 + 渲染新鲜度）", [PY, "g2/render.py", "--check"]),
        ("B40 证据核验（指针/提交/锚点三层）", [PY, "projects/B40-career-map/tools/check_evidence.py"]),
        ("B41 种子核验（行数/探针/锚点）", [PY, "projects/B41-thesis-seeds/tools/check_seeds.py"]),
        ("dorm 事实台账（27 键现算）", [PY, "projects/dorm-repair/tools/project_ledger.py", "--check"]),
        ("dorm 管理文档核对（check_pm）", [PY, "projects/dorm-repair/checks/check_pm.py"]),
        ("交付齐全性（README+run.bat 引用扫描）", [PY, "scripts/scan_refs.py", "projects"]),
        ("共享资产新鲜度（webkit/ → 8 产品 16 份副本逐字节）", [PY, "scripts/sync_assets.py", "--check"]),
        ("容器布局对拍（Dockerfile×dockerignore×代码读取×compose 端口，8 产品）", [PY, "scripts/check_docker_layout.py"]),
        ("新鲜空数据起服（8 产品：容器空卷/新克隆等价冒烟）", [PY, "scripts/check_fresh_boot.py"]),
        ("产品层：webframe 微框架（36 项双入口，含静态路径安全专项）", [PY, "-m", "pytest", "webframe/tests", "-q"]),
        ("run.bat 测试数声明对账（声明 × pytest 收集，8 产品）", [PY, "scripts/check_runbat_claims.py"]),
        ("产品层：Studio 门户（26 项：认证+矩阵+探活历史+WS 状态推送+八产品真启停+操作审计）", [PY, "-m", "pytest", "studio/tests", "-q"]),
        ("产品层：LinkBox（76 项双入口）", [PY, "-m", "pytest", "linkbox/tests", "-q"]),
        ("产品层：SimLab 仿真馆（37 项：记录+引擎+播放器+实时重算）", [PY, "-m", "pytest", "simlab/tests", "-q"]),
        ("产品层：DataScope 工作台（45 项：清洗+挖掘+报告+配方+xlsx 导入+服务）", [PY, "-m", "pytest", "datascope/tests", "-q"]),
        ("产品层：CacheKV 缓存（19 项：TTL+快照+HTTP+概览演示+导入导出）", [PY, "-m", "pytest", "cachekv/tests", "-q"]),
        ("产品层：SensorHub 物联网监测（28 项：MQTT 链路+对账+告警确认+阈值页面化+曲线限流+WS 实时）", [PY, "-m", "pytest", "sensorhub/tests", "-q"]),
        ("产品层：board 画板（12 项：B14 自检 7106+备份+守护+启动器契约+画笔微调）", [PY, "-m", "pytest", "board/tests", "-q"]),
        ("产品层：CourseLab 课程工坊（154 项端到端自检）", [PY, "courselab/server.py", "--selftest"]),
        ("产品层：画板 Web 版（15 项：文档+备份轮转+贴图+安全+图形库五形状+WS 协同）", [PY, "-m", "pytest", "boardweb/tests", "-q"]),
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
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=600)
    except subprocess.TimeoutExpired as exc:
        # 单步卡死只红本步，不吞后续步骤（2026-10-07 审查收口）
        dt = time.time() - t0
        print(f"[FAIL] {label}（{dt:.1f}s）")
        print("      | 超时 600s 强制终止")
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        tail = [ln for ln in out.strip().splitlines() if ln][-5:]
        for ln in tail:
            print("      |", ln)
        return False
    dt = time.time() - t0
    ok = proc.returncode == 0
    # 标签钉值对拍：标签里声明"（N 项"的 pytest 步骤，实跑 passed 数必须相等。
    # 标签是写给人看的数字，加测试后最容易忘改（webframe 30→31 / cachekv 15→17
    # 都实测漂移过）——让"改了代码不改文档就红"的纪律也覆盖标签本身。
    m = re.search(r"（(\d+) 项", label)
    if m and "-m" in cmd and "pytest" in cmd:
        claimed = int(m.group(1))
        ran = sum(int(x) for x in re.findall(r"(\d+) passed", proc.stdout or ""))
        if ok and ran != claimed:
            ok = False
            print(f"      | 标签对拍失败：标签声明 {claimed} 项，pytest 实跑 {ran} 项——改标签或改套件，二者必须一致")
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
