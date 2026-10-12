"""check_runbat_claims.py —— run.bat 测试数声明 × pytest 实况收集数对拍。

背景（轮二十五）：boardweb 加了协同白板测试后 run.bat 还写着 "8 tests"，
同类漂移一查 5 处（boardweb/datascope/linkbox/sensorhub/studio）。
run.bat 是每次跑都在读的活文档，数字必须与实况一致；README/PRODUCTS 是
历史收官叙事，写的是当时事实，不在对拍范围。

对拍口径：
- 只认 run.bat 里 "N tests" 的第一个总数（"104 tests: product + QR" 取 104）；
- 实况 = pytest --collect-only 的 collected 数（与 check_all 同一收集口径）；
- tests/ 目录收集不到用例而 run.bat 有声明 → 违例（声明指向了空套件）；
- 没有 tests/ 目录或无声明 → 跳过（courselab 走自己的 154 项端到端 runner）。
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

# 参与对拍的目录：managed 产品 + webframe（与 check_all 产品层同一批）
PRODUCTS = ["webframe", "studio", "linkbox", "simlab", "datascope", "cachekv",
            "sensorhub", "boardweb", "board"]

CLAIM_RE = re.compile(r"(\d+)\s+tests", re.IGNORECASE)


def collect_count(directory: Path) -> int | None:
    """pytest --collect-only 的用例数；套件本身坏了返回 None。"""
    r = subprocess.run([PY, "-m", "pytest", str(directory),
                        "--collect-only", "-q", "-p", "no:cacheprovider"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(ROOT), timeout=120)
    m = re.search(r"(\d+) tests? collected", r.stdout)
    if m:
        return int(m.group(1))
    # pytest 收集 0 条时措辞是 "no tests ran"/"no tests collected"
    if "no tests" in r.stdout.lower():
        return 0
    return None


def main() -> int:
    violations: list[str] = []
    checked = 0
    for product in PRODUCTS:
        bat = ROOT / product / "run.bat"
        tests = ROOT / product / "tests"
        if not bat.is_file() or not tests.is_dir():
            continue
        text = bat.read_text(encoding="utf-8", errors="replace")
        claim = CLAIM_RE.search(text)
        if claim is None:
            continue
        claimed = int(claim.group(1))
        checked += 1
        actual = collect_count(tests)
        if actual is None:
            violations.append(
                f"{product}: pytest 收集失败（run.bat 声明 {claimed}）——"
                "多为同目录并发收集的缓存竞态，单独重跑确认")
        elif actual != claimed:
            violations.append(
                f"{product}: run.bat 声明 {claimed} tests，pytest 实况收集 {actual}"
                f"（加/删测试后忘了改 run.bat）")
    if violations:
        print(f"run.bat 测试数声明对账：{len(violations)} 处漂移")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"run.bat 测试数声明对账：{checked} 个产品声明与 pytest 收集数一致")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    code = main()
    print(f"（{time.time() - t0:.1f}s）")
    sys.exit(code)
