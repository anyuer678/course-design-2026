"""check_exits.py —— 四个"错误样例"的退出码检查（run.bat 第 2 步用）。

为什么放在 Python 里：批处理要做"跑一个程序、断言它的退出码是 2"这种判断，
就得用 label/goto + 括号块，而本仓库实测过那类结构会让 cmd 按字节偏移回读脚本、
从一行中间开始执行（PLAN §6 记的两次事故）。所以批处理只负责调用，
判断与中文提示都在这里做，退出码照旧回传给 run.bat。

四个样例的期望退出码（出处：`tiny.py` 的约定，README 第 2 节）：
    error_syntax   词法/语法错误       → 2
    error_types    语义错误           → 2
    error_runtime  运行期错误（除零）  → 1
    error_depth    运行期错误（无限递归，调用深度上限）→ 1
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
EXPECTED = {"error_syntax": 2, "error_types": 2, "error_runtime": 1, "error_depth": 1}


def main() -> int:
    failures = []
    for name, want in EXPECTED.items():
        proc = subprocess.run([sys.executable, "tiny.py", f"programs/{name}.tiny"],
                              cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        got = proc.returncode
        ok = got == want
        print(f"  {name + '.tiny':<22}期望退出码 {want}，实得 {got}"
              f"{'  √' if ok else '  ×（这是真缺陷或期望写错了）'}")
        if not ok:
            failures.append(f"{name}: 期望 {want} 实得 {got}")
    if failures:
        print("错误样例的退出码不符合约定：", "; ".join(failures))
        return 1
    print("  四个错误样例的退出码都符合约定（2/2/1/1）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
