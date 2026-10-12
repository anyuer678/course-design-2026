"""check_docker_layout.py —— 容器布局对拍：Dockerfile COPY × .dockerignore × 代码实际读取。

背景（2026-10-12 轮二十二）：compose 全家桶从未实测（本机 Docker 引擎没启动过），
人工静态核对一次性抓出 7 处"容器必炸"：
  - 6 个 Dockerfile 没拷 webframe/（server.py 全部 from webframe import，import 即崩）；
  - courselab 缺 g2/cards.json（.dockerignore 整目录排除，而 courses.py 运行时读它）。
本检查把这类核对固化，原理：
  1. 镜像里真有什么 = 每个产品的 COPY 清单，套 .dockerignore 过滤（gitignore 式
     末条命中优先，支持 ! 重新放行——g2/* 与 !g2/cards.json 就是靠它协作）；
  2. 代码实际要什么 = REPO 级路径字面量（REPO / "g2" / "cards.json" 这类）
     + 非 stdlib 顶层 import + CMD 启动脚本；
  3. 对拍：每一条"要什么"都必须在"有什么"里解析得到。
只对拍、不构建：本机 Docker 引擎不可用也能跑（真构建/起容器归 compose 实测）。

已知边界（如实声明）：
  - studio 的一键启停 cwd 指向兄弟产品目录，是文档写明的 local-mode 特性
    （容器里 TCP 面板如实报离线），studio 的路径字面量不参与对拍；
  - 函数体内的缩进 import 不扫（零依赖文化下不存在第三方包，顶层对拍已够）；
  - .dockerignore 匹配器按本仓自己的方言实现（名字 / dir/ / **/x/ / **/*.ext /
    带斜杠路径 / ! 放行），不追求通用。
退出码：0 全对拍通过；1 有违例（逐条打印产品 × 违例）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ["studio", "linkbox", "simlab", "datascope",
            "cachekv", "sensorhub", "courselab", "boardweb"]

# 顶层 import 对拍时按"产品自己的包名"优先解析的目录
STDLIB = sys.stdlib_module_names


# ---------------------------------------------------------------- dockerignore
def parse_ignore(text: str) -> list[tuple[bool, str]]:
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        rules.append((neg, line[1:] if neg else line))
    return rules


def _rule_match(rule: str, path: str, is_dir: bool) -> bool:
    """单条规则是否命中 path（posix 相对路径）。本仓方言，见模块 docstring。"""
    if rule.endswith("/"):
        d = rule.rstrip("/")
        return path == d or path.startswith(d + "/")
    if "**/" in rule:
        base = rule.split("**/")[-1].rstrip("/")
        if base.startswith("*."):
            return path.endswith(base) or path.split("/")[-1].endswith(base)
        return path == base or path.endswith("/" + base) or path.startswith(base + "/")
    if "/" in rule:
        return path == rule or path.startswith(rule + "/")
    if "*" in rule:                       # g2/* 这类：仅直系子级
        parent, _, pat = rule.partition("/")
        if not path.startswith(parent + "/"):
            return False
        rest = path[len(parent) + 1:]
        return "/" not in rest and Path(rest).match(pat)
    # 纯名字：任何一层命中（.git / build 这类）
    return path == rule or f"/{rule}/" in f"/{path}/" or path.split("/")[-1] == rule


def excluded(rel: str, rules: list[tuple[bool, str]], is_dir: bool = False) -> bool:
    """gitignore 式：末条命中优先（! 重新放行靠它）；祖先目录被排除则整体不可达。

    hit 存的是每条命中规则的 neg 位：neg=True 表示放行。
    被排除 ⇔ 末条命中规则的 neg=False。"""
    parts = rel.split("/")
    for i in range(1, len(parts)):        # 祖先目录：一旦排除即不可达
        anc = "/".join(parts[:i])
        hit = [neg for neg, rule in rules if _rule_match(rule, anc, True)]
        if hit and not hit[-1]:
            return True
    hit = [neg for neg, rule in rules if _rule_match(rule, rel, is_dir)]
    return bool(hit and not hit[-1])


# ---------------------------------------------------------------- Dockerfile
def parse_dockerfile(text: str) -> tuple[list[tuple[str, str]], str | None]:
    copies, script = [], None
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^COPY\s+(\S+)\s+(\S+)$", line)
        if m:
            copies.append((m.group(1), m.group(2)))
            continue
        m = re.match(r'^CMD\s+\["python",\s*"([^"]+)"', line)
        if m:
            script = m.group(1)
    return copies, script


def image_paths(product: str, copies: list[tuple[str, str]],
                rules: list[tuple[bool, str]]) -> set[str]:
    """镜像内文件路径全集（posix，相对 /app）。"""
    out: set[str] = set()
    for src, dst in copies:
        src_p = ROOT / src
        if not src_p.exists():
            continue
        if src_p.is_file():
            if not excluded(src, rules):
                out.add(dst)
            continue
        for f in src_p.rglob("*"):
            if f.is_dir():
                continue
            rel = f.relative_to(ROOT).as_posix()
            if excluded(rel, rules):
                continue
            tail = f.relative_to(src_p).as_posix()
            out.add(f"{dst.rstrip('/')}/{tail}")
    return out


# ---------------------------------------------------------------- 代码读取
RE_PATHLIT = re.compile(
    r"(?:REPO|_REPO|ROOT\.parent)\s*((?:/\s*\"[^\"]+\"\s*)+)")
RE_IMPORT = re.compile(r"^(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)

# studio 一键启停 cwd 指兄弟产品是文档写明的 local-mode 特性（见模块 docstring）
PATHLIT_SKIP = {("studio", "linkbox"), ("studio", "simlab"), ("studio", "datascope"),
                ("studio", "cachekv"), ("studio", "sensorhub"), ("studio", "courselab"),
                ("studio", "boardweb"), ("studio", "board"), ("studio", "showcase")}


def code_wants(product: str) -> tuple[list[str], list[str]]:
    """返回（REPO 级路径字面量, 顶层 import 模块名）。"""
    paths, mods = [], set()
    pdir = ROOT / product
    for f in sorted(pdir.rglob("*.py")):
        rel = f.relative_to(ROOT).as_posix()
        if "/__pycache__/" in rel or "/tests/" in rel or "/data/" in rel:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in RE_PATHLIT.finditer(text):
            segs = re.findall(r"\"([^\"]+)\"", m.group(1))
            if segs:
                paths.append("/".join(segs))
        for m in RE_IMPORT.finditer(text):
            mods.add(m.group(1))
    return paths, sorted(mods)


def resolve_mod(mod: str, image: set[str]) -> bool:
    if mod in STDLIB or mod.startswith("_"):
        return True
    hits = [p for p in image if p == f"{mod}/__init__.py" or p == f"{mod}.py"
            or p.endswith(f"/{mod}/__init__.py") or p.endswith(f"/{mod}.py")]
    return bool(hits)


# ---------------------------------------------------------------- 主流程
def main() -> int:
    rules = parse_ignore((ROOT / ".dockerignore").read_text(encoding="utf-8"))
    violations: list[str] = []
    for product in PRODUCTS:
        df = ROOT / product / "Dockerfile"
        if not df.is_file():
            violations.append(f"{product}: 无 Dockerfile（compose 引用了它）")
            continue
        copies, script = parse_dockerfile(df.read_text(encoding="utf-8"))
        image = image_paths(product, copies, rules)
        if script and script not in image:
            violations.append(f"{product}: CMD 启动脚本 {script} 不在镜像里（COPY 清单 × dockerignore 后缺失）")
        paths, mods = code_wants(product)
        for rel in paths:
            if (product, rel.split("/")[0]) in PATHLIT_SKIP:
                continue
            in_img = rel in image or any(p.startswith(rel + "/") for p in image)
            if not in_img:
                violations.append(f"{product}: 代码读取 {rel} 不在镜像里（COPY 缺失或被 dockerignore 排除）")
        for mod in mods:
            if not resolve_mod(mod, image):
                violations.append(f"{product}: 顶层 import {mod} 在镜像里解析不到（既非 stdlib 也无对应包目录）")
    if violations:
        print(f"容器布局对拍：{len(violations)} 处违例")
        for v in violations:
            print("  -", v)
        return 1
    n = len(PRODUCTS)
    print(f"容器布局对拍：{n} 个产品 × （COPY×dockerignore 镜像集 × 代码路径/imports/CMD）全对拍通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
