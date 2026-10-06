"""board/compile_support.py —— 引擎与产品层的编译（测试与启动器共用这一个实现）。

编译口径沿用 B14 的构建纪律：
    `javac --release 17 -encoding UTF-8`，产物进 board/build/（根 .gitignore 的
    build/ 规则已覆盖）——JDK 17 与 21 都实测能跑（B14 README 的实测记录）。
    脏检查：任何 .java 比 stamp.txt 新就重编；B14 主源 + board 产品源一起进
    classes/，B14 的 PaintTests 进 test-classes/（引擎自检测试要跑它）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BOARD = Path(__file__).resolve().parent
REPO = BOARD.parent
B14 = REPO / "projects" / "B14-java-paint"
BUILD = BOARD / "build"
CLASSES = BUILD / "classes"
TEST_CLASSES = BUILD / "test-classes"
STAMP = BUILD / "stamp.txt"


def source_files() -> tuple[list[Path], list[Path]]:
    """(主源码, 测试源码)：B14 引擎全量 + board 产品层；测试只有 B14 的 PaintTests。"""
    main = sorted((B14 / "src" / "main" / "java").rglob("*.java")) \
        + sorted((BOARD / "src").rglob("*.java"))
    test = sorted((B14 / "src" / "test" / "java").rglob("*.java"))
    return main, test


def is_stale() -> bool:
    if not STAMP.exists():
        return True
    stamp = STAMP.stat().st_mtime
    main, test = source_files()
    return any(path.stat().st_mtime > stamp for path in main + test)


def ensure_classes(force: bool = False) -> tuple[Path, Path]:
    """保证 classes/ 与 test-classes/ 新鲜；返回 (classes, test_classes)。"""
    main, test = source_files()
    if not force and not is_stale() and CLASSES.is_dir() and TEST_CLASSES.is_dir():
        return CLASSES, TEST_CLASSES
    if not (B14 / "src" / "main" / "java").is_dir():
        raise FileNotFoundError(f"找不到 B14 引擎源码：{B14}")
    for directory in (CLASSES, TEST_CLASSES):
        directory.mkdir(parents=True, exist_ok=True)
    _javac(main, CLASSES, extra_classpath=None)
    _javac(test, TEST_CLASSES, extra_classpath=CLASSES)
    STAMP.write_text("ok", encoding="ascii")
    return CLASSES, TEST_CLASSES


def _javac(sources: list[Path], out_dir: Path, *, extra_classpath: Path | None) -> None:
    argfile = BUILD / (out_dir.name + "-sources.txt")
    argfile.write_text("\n".join(str(p) for p in sources), encoding="utf-8")
    cmd = ["javac", "--release", "17", "-encoding", "UTF-8",
           "-d", str(out_dir), f"@{argfile}"]
    if extra_classpath is not None:
        cmd[3:3] = ["-cp", str(extra_classpath)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    if proc.returncode != 0:
        raise RuntimeError("javac 失败：\n" + (proc.stdout or "") + (proc.stderr or ""))


if __name__ == "__main__":
    ensure_classes(force="--force" in sys.argv)
    print(f"classes={CLASSES}")
    print(f"test-classes={TEST_CLASSES}")
