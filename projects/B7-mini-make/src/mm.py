"""src/mm.py —— Makefile 子集 + 依赖图 + 环检测 + 增量构建（并发可选）。

课程要点（软件开发技术基础）：
    - make 的核心不是"跑命令"，而是**依赖图上的偏序**：目标只有在全部前置就绪后才执行；
    - 环检测必须发生在执行之前：`a: b` 与 `b: a` 在没检查时表现为"跑到一半互相等待"；
    - 增量的判据是 **mtime**：目标比任一前置旧才重建（"up to date" 就是这么来的）；
    - 失败要**传播**：一个目标失败，依赖它的目标一律不执行，并且进程以非 0 退出；
    - `-j N` 是"能并行的就并行"：同一层里互不依赖的目标可以同时跑，结果仍须与串行一致。

与真 make 的差别（明确声明，不冒充）：不支持变量展开、模式规则、隐式规则与 `.PHONY`
之外的伪目标语义；recipe 逐行交给 shell 执行；`-j` 用线程池（命令仍是子进程）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class MakeError(RuntimeError):
    pass


class Target:
    __slots__ = ("name", "deps", "recipe")

    def __init__(self, name: str, deps: list[str], recipe: list[str]):
        self.name = name
        self.deps = deps
        self.recipe = recipe


class Makefile:
    """解析后的 Makefile：目标表 + 依赖图。"""

    PHONY_PREFIX = ".PHONY:"

    def __init__(self, targets: dict[str, Target], phony: set[str],
                 base: Path | None = None):
        self.targets = targets
        self.phony = phony
        # 所有相对路径都相对 **Makefile 所在目录**，不是进程的 cwd。
        # 第一版按 cwd 解析：在临时目录里跑测试时前置文件一个个"不存在"，
        # recipe 还会把产物写到仓库里——真 make 的 -C/-f 语义就是这条，必须照做。
        self.base = base or Path(".")

    @classmethod
    def load(cls, path: Path) -> "Makefile":
        targets: dict[str, Target] = {}
        phony: set[str] = set()
        current: Target | None = None
        if not path.is_file():
            raise MakeError(f"找不到 Makefile：{path}")
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            if raw.startswith(cls.PHONY_PREFIX):
                phony.update(raw[len(cls.PHONY_PREFIX):].split())
                current = None
                continue
            if raw[0] in ("\t", " "):
                if current is None:
                    raise MakeError(f"第 {lineno} 行：recipe 出现在目标之前")
                current.recipe.append(raw.strip())
                continue
            if ":" not in raw:
                raise MakeError(f"第 {lineno} 行：既不是目标也不是 recipe：{raw!r}")
            name, _, rest = raw.partition(":")
            name = name.strip()
            if name in targets:
                raise MakeError(f"第 {lineno} 行：目标 {name} 重复定义")
            current = Target(name, rest.split(), [])
            targets[name] = current
        if not targets:
            raise MakeError("Makefile 里没有任何目标")
        return cls(targets, phony, base=path.resolve().parent)

    # ---------------------------------------------------------------- 图算法
    def order(self, goal: str) -> list[str]:
        """返回一个合法的执行顺序（拓扑序，DFS 后序）；有环就报出环上的名字。"""
        visiting: list[str] = []
        done: set[str] = set()
        result: list[str] = []

        def visit(node: str) -> None:
            if node in done:
                return
            if node in visiting:
                cycle = visiting[visiting.index(node):] + [node]
                raise MakeError("依赖成环：" + " -> ".join(cycle))
            if node not in self.targets:
                if self.path_of(node).exists():
                    done.add(node)               # 文件前置：存在即满足
                    return
                raise MakeError(f"目标 {node} 的前置 {node!r} 既不是规则也不是已存在的文件")
            visiting.append(node)
            for dep in self.targets[node].deps:
                visit(dep)
            visiting.pop()
            done.add(node)
            result.append(node)

        visit(goal)
        return result

    def path_of(self, name: str) -> Path:
        return (self.base / name) if not Path(name).is_absolute() else Path(name)

    def mtime(self, name: str) -> float:
        try:
            return os.path.getmtime(self.path_of(name))
        except OSError:
            return -1.0                          # 不存在 ⇒ 一定过期

    def needs_build(self, name: str) -> bool:
        if name in self.phony or name not in self.targets:
            return True
        target = self.targets[name]
        if not self.path_of(name).exists():
            return True
        newest_dep = max((self.mtime(d) for d in target.deps), default=-1.0)
        return newest_dep > self.mtime(name)


class Builder:
    def __init__(self, makefile: Makefile, jobs: int = 1, verbose: bool = True):
        self.mf = makefile
        self.jobs = max(1, jobs)
        self.verbose = verbose
        self.built: list[str] = []
        self.skipped: list[str] = []
        self.failed: str | None = None
        self._lock = threading.Lock()

    def _run_recipe(self, name: str) -> None:
        target = self.mf.targets[name]
        if not target.recipe:
            return
        for line in target.recipe:
            if self.verbose:
                print(f"  $ [{name}] {line}", flush=True)
            proc = subprocess.run(line, shell=True, cwd=self.mf.base)
            if proc.returncode != 0:
                raise MakeError(f"目标 {name} 的命令失败（退出码 {proc.returncode}）：{line}")

    def build(self, goal: str) -> int:
        """按拓扑序构建；并发时只在**互不依赖**的目标间并行。

        实现取巧但诚实：把拓扑序切成"依赖已全部完成"的批次，同批并行。
        这样既不改判定语义，也让 -j4 与串行的结果一致（测试里对拍）。
        """
        order = self.mf.order(goal)
        remaining = {name: set(self.mf.targets[name].deps) & set(order) for name in order}
        while remaining:
            batch = [n for n, deps in remaining.items() if not deps]
            if not batch:
                raise MakeError("依赖图里仍有未满足的前置——拓扑序被破坏")
            # 失败**不抛出**、只登记：调用方拿到非 0 返回码，依赖失败目标的后续目标一律跳过。
            # （测试要求 build() 返回 1 而不是抛异常——"失败传播"是流程，不是崩溃。）
            if self.jobs == 1:
                for name in batch:
                    self._safe_build(name)
            else:
                with ThreadPoolExecutor(max_workers=self.jobs) as pool:
                    futures = {pool.submit(self._safe_build, name): name for name in batch}
                    for future in futures:
                        future.result()
            for name in batch:
                remaining.pop(name, None)
                for other in remaining.values():
                    other.discard(name)
        if self.failed:
            print(f"构建失败：{self.failed}", flush=True)
            return 1
        print(f"完成：构建 {len(self.built)} 个，跳过 {len(self.skipped)} 个", flush=True)
        return 0

    def _safe_build(self, name: str) -> None:
        try:
            self._build_one(name)
        except MakeError:
            pass                                  # 原因已在 _build_one 里记账

    def _build_one(self, name: str) -> None:
        with self._lock:
            if self.failed is not None:
                raise MakeError(f"上游已失败，跳过 {name}")   # 失败传播
        if not self.mf.needs_build(name):
            with self._lock:
                self.skipped.append(name)
            if self.verbose:
                print(f"  = {name} 已是最新（up to date）", flush=True)
            return
        try:
            self._run_recipe(name)
        except MakeError:
            with self._lock:
                if self.failed is None:
                    self.failed = name
            raise
        with self._lock:
            self.built.append(name)


def _default_makefile(directory: Path) -> Path:
    for name in ("Makefile", "makefile"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    raise MakeError(f"{directory} 下没有 Makefile")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mini-make：Makefile 子集")
    parser.add_argument("-f", dest="makefile", default=None)
    parser.add_argument("-j", dest="jobs", type=int, default=1)
    parser.add_argument("-C", dest="directory", default=".")
    parser.add_argument("-q", dest="quiet", action="store_true")
    parser.add_argument("goals", nargs="*", default=[])
    args = parser.parse_args(argv)

    directory = Path(args.directory)
    path = Path(args.makefile) if args.makefile else _default_makefile(directory)
    try:
        makefile = Makefile.load(path)
        builder = Builder(makefile, jobs=args.jobs, verbose=not args.quiet)
        goals = args.goals or ["all"]
        for goal in goals:
            code = builder.build(goal)
            if code:
                return code
        return 0
    except MakeError as exc:
        print(f"mini-make: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
