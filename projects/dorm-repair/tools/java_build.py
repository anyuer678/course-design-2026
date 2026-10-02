"""tools/java_build.py —— 由 Python 负责找 Maven、跑离线构建，并**拒绝把空绿当通过**。

为什么不让 `run.bat` 直接调 Maven：批处理里 `%VAR%` 的展开时机坑过我们
（本轮 `for /d %%D` 取到的路径没生效，脚本照样退出 0）。把这件事挪到 Python 里，
就只需要相信一个已经跑了很多轮的东西。

更要紧的是第二条：PLAN 第 6 节 B18 新写的规矩——**构建工具报 SUCCESS 不等于测试跑了**。
开工前的探针里，测试类命名不匹配 surefire 约定，`mvn -o test` 返回 BUILD SUCCESS 而实际 0 个测试。
所以这里强制解析 `Tests run:` 的条数，为 0 就判定失败。

用法：

```
python tools/java_build.py            # 跑测试；找不到 Maven 就打印说明并返回 0（跳过，但会明说）
python tools/java_build.py --require  # 找不到 Maven 直接返回 1（CI 用）
python tools/java_build.py --package  # 离线打包（跳过测试），打印 jar 路径
```
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "java"
POM = JAVA / "pom.xml"
#: 本机实测：PATH 上没有 mvn，但 ~/.m2/wrapper/dists 里有解压好的 3.9.12（B18 订正的那条旧事实）
MVN_GLOBS = [
    os.path.expanduser("~/.m2/wrapper/dists/apache-maven-*/**/bin/mvn.cmd"),
    os.path.expanduser("~/.m2/wrapper/dists/apache-maven-*/**/bin/mvn"),
]
#: 每个测试类那一行带 "-- in <class>"；最后的总计行不带。之前我把两种都相加，
#: 23 个测试报成 46——自己造的指标自己先信了，这是同一类错。
PER_CLASS = re.compile(r"Tests run:\s*(\d+), Failures:\s*(\d+), Errors:\s*(\d+), Skipped:\s*(\d+).*-- in ")
SUMMARY = re.compile(r"^\[INFO\] Tests run:\s*(\d+), Failures:\s*(\d+), Errors:\s*(\d+), Skipped:\s*(\d+)\s*$",
                     re.M)


def _version_of(path: str):
    m = re.search(r"apache-maven-(\d+)\.(\d+)(?:\.(\d+))?", path)
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def find_maven() -> Path | None:
    """取版本号最大的那个，而不是 sorted()[0]（那会给你 3.8.5）。"""
    candidates = []
    for pattern in MVN_GLOBS:
        candidates += [Path(p) for p in glob.glob(pattern, recursive=True) if Path(p).exists()]
    if candidates:
        return max(candidates, key=lambda p: _version_of(str(p)))
    which = subprocess.run(["where", "mvn"], capture_output=True, text=True)
    line = (which.stdout or "").splitlines()
    return Path(line[0]) if line else None


def run(mvn: Path, goals: list) -> tuple:
    cmd = [str(mvn), "-o", "-B"] + goals          # -o：离线。下载依赖必须先经用户同意（PLAN 第 8 节）
    proc = subprocess.run(cmd, cwd=str(JAVA), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout + proc.stderr


def summarize(output: str) -> dict:
    """解析 mvn 输出。两条独立来源必须相等：逐类相加 = 最后那行总计。

    只取其一的话，我的解析器出错也照样"看起来通过"——B17 抄错 subTest 数、
    本轮把 23 报成 46，都是同一个形状的错。
    """
    per_class = [(int(a), int(b), int(c), int(d)) for a, b, c, d in PER_CLASS.findall(output)]
    ran = sum(t[0] for t in per_class)
    failed = sum(t[1] for t in per_class)
    errors = sum(t[2] for t in per_class)
    skipped = sum(t[3] for t in per_class)
    totals = SUMMARY.findall(output)
    declared = (int(totals[-1][0]), int(totals[-1][1]), int(totals[-1][2]), int(totals[-1][3])) \
        if totals else None
    return {"ran": ran, "failed": failed, "errors": errors, "skipped": skipped,
            "declared": declared, "consistent": (declared is None or declared == (ran, failed, errors, skipped)),
            "success": "BUILD SUCCESS" in output}


def main(argv: list) -> int:
    require = "--require" in argv
    package = "--package" in argv
    mvn = find_maven()
    if mvn is None or not mvn.exists():
        if require:
            print("[x] 找不到 Maven，且本次要求必须跑（--require）", file=sys.stderr)
            return 1
        print("[!] 没找到本机 Maven（找过 ~/.m2/wrapper/dists 与 PATH）。")
        print("    Java 这一步**没有跑**，不是跑过了；手动跑法见 docs/09-platform.md 第 9 节。")
        return 0
    goals = ["-DskipTests", "package"] if package else ["test"]
    print(f"[java] {mvn}")
    print(f"[java] 离线执行：mvn -o -B {' '.join(goals)}")
    code, output = run(mvn, goals)
    stats = summarize(output)
    print(f"[java] Tests run={stats['ran']} failures={stats['failed']} "
          f"errors={stats['errors']} skipped={stats['skipped']} BUILD SUCCESS={stats['success']}"
          f"（mvn 自己报的总计 = {stats['declared']}）")
    if code != 0:
        tail = [line for line in output.splitlines() if "ERROR" in line or ".java:[" in line]
        print("\n".join(tail[:12]) or output[-800:])
        return 1
    if not stats["consistent"]:
        print("[x] 逐类相加与 mvn 的总计行不一致：解析器不可信，判失败。", file=sys.stderr)
        return 1
    if not stats["success"]:
        print("[x] 退出码 0 但输出里没有 BUILD SUCCESS——不猜测，判失败。", file=sys.stderr)
        return 1
    if not package and stats["ran"] == 0:
        # 这正是开工前那次假绿：类名不匹配 surefire 的 *Test.java，一个测试都没跑还报 SUCCESS
        print("[x] BUILD SUCCESS 但 0 个测试运行。检查类名是否匹配 surefire 约定（*Test.java）。",
              file=sys.stderr)
        return 1
    if package:
        jars = sorted(JAVA.glob("target/*.jar"))
        print(f"[java] 产物：{jars[0].name if jars else '（没找到 jar）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
