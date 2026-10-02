"""checks/check_arch.py —— 架构核对器（B17）。

架构文档最大的谎言是那张依赖图：**画的人很认真，代码早就变了。**
所以这里不"看图"，而是用 `ast` 把真实 import 扫出来，和 `docs/08-architecture.md`
里声明的边集做**双向相等**比较——多一条边是越界，少一条边是文档在吹。

四组检查：

1. **依赖方向**：组件级 import 边 = 文档声明的边；并且 `spec`（领域）必须零内部依赖、
   不 import netlab/界面/时钟。这条一破，"状态机只有一份"就开始漏。
2. **契约三方一致**：`contracts/workflow.json` = 由 SRS 现算的契约 = `spec`；
   `docs/08` 里的三种风格指标表 = `arch/style_probe.py` 实测值。
3. **ADR 完整性**：每个 ADR 五节齐全（背景/决定/备选/后果/验证方式），被 08 引用，且没有孤儿 ADR。
4. **新文档不引用不存在的 ID**：06/07/08/ADR 里出现的 FR/BR/NFR/IF/UC/US/AC/AQ 必须真实存在。

用法：`python checks/check_arch.py`（有问题打印并返回非 0）。
"""
from __future__ import annotations

import ast
import fnmatch
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arch import style_probe                                 # noqa: E402
from checks import check_docs                                # noqa: E402
from tools import export_contract                            # noqa: E402

DOC = ROOT / "docs" / "08-architecture.md"
JAVA_DOC = ROOT / "docs" / "09-platform.md"
PACKAGE_ROOT = "course.dormrepair"
JAVA_SRC = ROOT / "java" / "src" / "main" / "java" / "course" / "dormrepair"
JAVA_DOC = ROOT / "docs" / "09-platform.md"
PACKAGE_ROOT = "course.dormrepair"
JAVA_SRC = ROOT / "java" / "src" / "main" / "java" / "course" / "dormrepair"
ADR_DIR = ROOT / "docs" / "adr"
ADR_SECTIONS = ("背景", "决定", "备选", "后果", "验证方式")
COMPONENTS = ("spec", "prototype", "checks", "tools", "arch", "tests", "demo", "say")
EXTERNAL_ALLOWED = {"netlab"}
REF_RE = re.compile(r"\b(?:FR|BR|NFR|IF|UC|US|AC|AQ)-\d{2}\b")


def cells(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def table(doc_text: str, first_header: str):
    """按表头第一格抓表格正文（跳过表头与分隔行）。"""
    rows, started = [], False
    for line in doc_text.splitlines():
        if line.startswith("|") and first_header in line:
            started = True
            continue
        if started and re.match(r"^\|[\s:|-]+\|$", line.strip()):
            continue
        if started and line.startswith("|"):
            rows.append(cells(line))
        elif started:
            break
    return rows


def strip_ticks(text: str) -> str:
    return text.replace("`", "").strip()


# ------------------------------------------------------------------ 真实 import 图

def actual_edges():
    """组件 → 它真实依赖的组件集合（只看内部组件与 netlab，stdlib 不算）。"""
    graph = {c: set() for c in COMPONENTS}
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "__pycache__" in str(path) or ".pytest_cache" in str(path):
            continue
        rel = path.relative_to(ROOT)
        here = rel.parts[0] if rel.parts[:-1] else rel.stem      # 目录名或顶层脚本名
        if here not in graph:
            continue
        for node in ast.walk(ast.parse(text)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
                # `from . import x` 这种相对导入：module 为 None，靠 level 判断同包
            elif isinstance(node, ast.ImportFrom) and node.level:
                names = [here]
            for dep in names:
                if dep in graph and dep != here:
                    graph[here].add(dep)
                elif dep in EXTERNAL_ALLOWED:
                    graph[here].add(dep)
    return graph


def declared_edges(doc_text: str):
    graph = {}
    rows = table(doc_text, "组件")
    if not rows:
        raise ValueError("08 文档里找不到 `| 组件 | 允许依赖 |` 那张表")
    for row in rows:
        if len(row) < 2:
            continue
        name = strip_ticks(row[0])
        if name not in COMPONENTS:
            continue
        deps = set()
        body = strip_ticks(row[1])
        if body and body not in ("—", "-", "无", "（无）"):
            deps = {strip_ticks(p) for p in re.split(r"[,，、/]+", body) if strip_ticks(p)}
        graph[name] = deps
    return graph


# ------------------------------------------------------------------ 检查

def check_domain_purity(problems):
    """领域层必须干净：不碰界面、不碰 HTTP、不自己读时钟。"""
    spec_dir = ROOT / "spec"
    for path in sorted(spec_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for banned in ("netlab", "prototype", "import time", "datetime", "http"):
            if banned in text:
                problems.append(f"spec/{path.name} 里出现了 {banned!r}：领域层不该知道界面、时钟或传输")


def check_contract(problems):
    if not export_contract.CONTRACT.is_file():
        problems.append("contracts/workflow.json 不存在（跑 python tools/export_contract.py --write）")
        return
    try:
        saved = json.loads(export_contract.CONTRACT.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        problems.append(f"契约不是合法 JSON：{exc}")
        return
    fresh = export_contract.build()
    if saved != fresh:
        problems.append("契约与 SRS 文档不一致（文档改了没重生成，或有人手改了 JSON）")
    problems.extend(f"契约与模型不一致：{p}" for p in export_contract.against_spec(fresh))


def check_style_table(doc_text: str, problems):
    measured = style_probe.metrics()
    rows = {strip_ticks(r[0]): r for r in table(doc_text, "风格") if r}
    if not rows:
        problems.append("08 文档里没有三种风格的指标表")
        return
    same, calls = style_probe.same_outcome()
    if not same:
        problems.append("三种风格跑完终态不一致，比较本身不成立")
    if len(rows) != len(STYLE_ORDER):
        problems.append(f"指标表应有 {len(STYLE_ORDER)} 个风格，实到 {len(rows)}")
    for name in STYLE_ORDER:
        row = rows.get(name)
        got = measured[name]
        if row is None:
            problems.append(f"指标表缺了风格 {name}")
            continue
        want = [str(got["参与者"]), str(got["事务边界"]), "1", str(got["总线消息"]),
                str(got["重复状态点"])]
        have = [strip_ticks(x) for x in row[1:6]]
        if have != want:
            problems.append(f"风格 {name} 的指标表与实测不符：文档 {have} vs 实测 {want}")
    owners = measured["_共享判定源"]
    if owners != ["spec/workorder.py"]:
        problems.append(f"判定源不止一份：{owners}（这正是 PLAN 禁止的'状态机写三遍'）")
    if len(calls) != 1:
        problems.append("三种风格调用判定源的次数不同，比较口径不一致")


STYLE_ORDER = ("A 分层单体", "B 端口-适配器", "C 两服务+事件总线")


def check_adrs(doc_text: str, problems):
    files = sorted(ADR_DIR.glob("ADR-*.md")) if ADR_DIR.is_dir() else []
    if not files:
        problems.append("docs/adr/ 下一条 ADR 都没有")
        return []
    ids = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        adr_id = path.name.split("_")[0].replace(".md", "")
        ids.add(adr_id)
        for section in ADR_SECTIONS:
            if f"## {section}" not in text:
                problems.append(f"{path.name} 缺少 `## {section}`")
        if len(text) < 500:
            problems.append(f"{path.name} 太短，ADR 不是标题党")
        for line in text.splitlines():
            if "状态：" in line and not re.search(r"状态：(accepted|已采纳|superseded|proposed)", line):
                problems.append(f"{path.name} 的状态写法不认识：{line.strip()[:40]}")
    referenced = set(re.findall(r"ADR-\d{2}", doc_text))
    for missing in sorted(referenced - ids):
        problems.append(f"08 引用了 {missing}，但没有这个 ADR 文件")
    for orphan in sorted(ids - referenced):
        problems.append(f"{orphan} 存在却没被 08 引用（孤儿文档）")
    return ids


def check_new_doc_refs(problems):
    parsed = check_docs.parse(check_docs.load())
    known = (set(parsed["frs"]) | set(parsed["brs"]) | set(parsed["nfrs"]) | set(parsed["ifs"])
             | set(parsed["ucs"]) | set(parsed["uss"])
             | {a["ac"] for items in parsed["acs"].values() for a in items} | parsed["aqs"])
    # 两件事分开做，别互相顶替：
    #   ① REQUIRED 管"该有的文档不许少"——glob 只会看见存在的文件，缺一篇就少核对一篇；
    #   ② glob 管"每篇文档里的 ID 引用都得存在"——手写白名单漏加新文档＝那篇没人核对。
    required = [DOC, JAVA_DOC, ROOT / "docs" / "06-wireframes.md",
                ROOT / "docs" / "07-walkthrough.md", ROOT / "docs" / "10-soa.md",
                ROOT / "docs" / "11-testing.md"]
    for path in required:
        if not path.is_file():
            problems.append(f"应有的文档缺失：{path.relative_to(ROOT)}")
    extra = sorted(set((ROOT / "docs").glob("*.md")) | set(ADR_DIR.glob("*.md")))
    for path in extra:
        for ref in sorted(set(REF_RE.findall(path.read_text(encoding="utf-8")))):
            if ref not in known:
                problems.append(f"{path.name} 引用了不存在的 ID {ref}")


def java_layer_table(text):
    """按**整行表头精确匹配**抓分层表。

    不能复用 `table(doc_text, "层")`：那个函数按"这一行含有'层'"来认表头，
    而 config 行的允许依赖写着"所有层"——它自己就被当成了表头，整行被跳过。
    这类"解析器被内容骗到"的错，只有把匹配收紧到整格相等才会消失。
    """
    header = ["层", "包", "允许依赖"]
    rows, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        if cells(line) == header:
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                rows.append(cells(row))
    return rows


def java_edge_problems(declared, measured):
    """把"文档声明的分层"与"扫出来的 import"对撞。纯函数，方便喂假数据测牙齿。"""
    problems = []
    if set(measured) != set(declared):
        problems.append(f"docs/09 声明的包与实际扫到的包不一致：只在文档 "
                        f"{sorted(set(declared) - set(measured))}，只在代码 "
                        f"{sorted(set(measured) - set(declared))}")
    for package, imports in sorted(measured.items()):
        allowed = declared.get(package)
        if allowed is None:
            continue
        allow_all = any("所有层" in a for a in allowed)
        observed_internal = set()
        for imp in sorted(imports):
            target = imp.rsplit(".", 1)[0]
            internal = target.startswith(PACKAGE_ROOT + ".") or target == PACKAGE_ROOT
            if internal and target != package:
                observed_internal.add(target)
            matched = allow_all or any(fnmatch.fnmatch(imp, _to_glob(a)) for a in allowed)
            if not matched:
                problems.append(f"依赖越界：{package} 里 import 了 {imp}"
                                f"（docs/09 允许的只有 {allowed}）")
        declared_internal = {a for a in allowed if a.startswith(PACKAGE_ROOT + ".")} - {package}
        unused = sorted(declared_internal - observed_internal)
        if unused:
            problems.append(f"文档声明但未使用：{package} → {unused}"
                            f"（要么代码真的用到，要么把这条边从表里删掉）")
    domain = PACKAGE_ROOT + ".domain"
    for imp in sorted(measured.get(domain, set())):
        for banned in ("org.springframework", "java.sql", "javax.sql", "com.fasterxml",
                       "jakarta.annotation"):
            if imp.startswith(banned):
                problems.append(f"领域层不纯：{domain} import 了 {imp}")
    return problems


def java_measured_imports():
    """扫 java/src/main/java 下每个包的真实 import。"""
    measured = {}
    if not JAVA_SRC.is_dir():
        return measured
    for path in sorted(JAVA_SRC.rglob("*.java")):
        # JAVA_SRC.parents[1] 才是 src/main/java：[0] 是 .../java/course，[2] 会多算出一层 "java."
        package = ".".join(path.relative_to(JAVA_SRC.parents[1]).parts[:-1])
        for imp in re.findall(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;",
                              path.read_text(encoding="utf-8"), re.M):
            measured.setdefault(package, set()).add(imp)
    return measured


def check_java(problems):
    """B18 的 Java 分层：文档表 ↔ 真实 import，双向。与 Python 侧同一套规矩。

    做的事和 `actual_edges()` 对 Python 做的一样：**不信任图，只信扫出来的边**。
    外加三条 Java 特有的红线：领域层不许认识 Spring/SQL/Jackson、
    `java/` 下不许有契约副本、`pom.xml` 必须从 `../contracts` 复制而不是自己存一份。
    """
    if not JAVA_SRC.is_dir():
        problems.append(f"Java 源码目录不存在：{JAVA_SRC}")
        return
    text = JAVA_DOC.read_text(encoding="utf-8")
    declared = {}
    for row in java_layer_table(text):
        if len(row) < 3:
            continue
        package = strip_ticks(row[1])
        if not package.startswith(PACKAGE_ROOT):
            continue
        declared[package] = [strip_ticks(p) for p in re.split(r"[,，]", row[2]) if p.strip()]
    if not declared:
        problems.append("docs/09 的分层表没解析出任何包（表头必须精确是 层 | 包 | 允许依赖）")
        return

    measured = java_measured_imports()
    problems.extend(java_edge_problems(declared, measured))

    # 契约只有一份：java/ 的**源码**里不许出现副本。
    # target/ 下那份是构建时从 ../contracts 复制出来的产物，算它就成了"自己抄自己"的假阳性。
    copies = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "java").rglob("workflow.json")
                    if "target" not in p.parts)
    if copies:
        problems.append(f"java/ 下出现契约副本（第二份状态表）：{copies}")
    pom = ROOT / "java" / "pom.xml"
    if pom.is_file():
        pom_text = pom.read_text(encoding="utf-8")
        if "../contracts" not in pom_text:
            problems.append("java/pom.xml 没有从 ../contracts 复制契约，说明 Java 侧在读别处的表")
    elif (ROOT / "java").is_dir():
        problems.append("缺少 java/pom.xml")


def _to_glob(pattern: str) -> str:
    """把文档里的 `java.*` / `course.dormrepair.domain` 变成 fnmatch 模式；
    裸包名（不带通配）匹配该包下的所有类。"""
    p = pattern.strip()
    if p.endswith(".*") or "*" in p:
        return p
    return p + ".*"


def strip_java_comments(text):
    """剥掉 // 行注释与 /* */ 块注释（含 Java 的 /// 与文本块里的引号不特别处理）。

    为什么必须剥：我在 SOAP 文件的注释里写了 `state.equals("SUBMITTED")` 作为反例说明，
    扫描器把它当成代码，就会报"这里出现了一条自己的规则"——散文冒充代码的假阳性。
    """
    out = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = re.sub(r"^\s*//.*$", "", out, flags=re.M)
    out = re.sub(r"//[^\"']*$", "", out)             # 行尾注释（不跨引号，够用）
    return out


def java_state_literals():
    """扫每个 Java 源文件里出现的**状态字面量**（字符串常量里的状态名）。"""
    states = set(json.loads((ROOT / "contracts" / "workflow.json")
                            .read_text(encoding="utf-8"))["states"])
    found = {}
    for path in sorted(JAVA_SRC.rglob("*.java")):
        body = strip_java_comments(path.read_text(encoding="utf-8"))
        hits = {s for s in states if re.search(r"['\"]" + re.escape(s) + r"['\"]", body)}
        rel = path.relative_to(ROOT).as_posix()
        if hits:
            found[rel] = hits
    return found


def state_literal_problems(declared, found):
    """白名单 ↔ 实测，双向。这是 ADR-02「判定源唯一」在 Java 侧的等价物。

    `declared`：{相对路径: 允许出现的状态字面量集合}，出处 docs/10。
    多一处 = 那个文件可能自己写了一套状态判断（第二份状态表的征兆）；
    少一处 = 文档在虚报，下一轮会照着它加代码。
    """
    problems = []
    for rel, hits in sorted(found.items()):
        allowed = declared.get(rel, set())
        extra = sorted(hits - allowed)
        if extra:
            problems.append(f"疑似第二份状态表：{rel} 里出现了未申报的状态字面量 {extra}"
                            f"（判定只应在 domain/StateMachine 与 SQL 谓词里发生）")
    for rel, allowed in sorted(declared.items()):
        got = found.get(rel, set())
        unused = sorted(allowed - got)
        if unused:
            problems.append(f"docs/10 声明了 {rel} 可以出现 {unused}，但代码里已经没有了"
                            f"（白名单过期，请删行）")
        if allowed and not (ROOT / rel).is_file():
            problems.append(f"docs/10 白名单指向不存在的文件：{rel}")
    return problems


def state_literal_allow_list(doc_text):
    """docs/10 白名单 → {相对路径: 状态字面量集合}。核对器与测试都用这一个实现，
    免得像本轮第一次那样：测试自己重写一遍解析、忘了剥反引号，于是测试红而实现绿。"""
    declared = {}
    for row in state_literal_table(doc_text):
        rel = strip_ticks(row[0])
        if not rel:
            continue
        declared[rel] = {strip_ticks(x) for x in re.split(r"[,，]", row[1]) if x.strip()}
    return declared


def check_java_state_literals(problems):
    doc = ROOT / "docs" / "10-soa.md"
    if not doc.is_file():
        problems.append(f"缺少 {doc.relative_to(ROOT)}（状态字面量白名单的出处）")
        return
    problems.extend(state_literal_problems(state_literal_allow_list(doc.read_text(encoding="utf-8")),
                                           java_state_literals()))


def state_literal_table(text):
    """解析 docs/10 里那张白名单表（表头精确匹配，理由同 java_layer_table）。"""
    header = ["Java 文件（相对 dorm-repair）", "允许出现的状态字面量", "为什么必须在代码里"]
    rows, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("|") and cells(line) == header:
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                rows.append(cells(row))
    return rows


def check():
    if not DOC.is_file():
        return [f"缺少 {DOC.relative_to(ROOT)}"]
    doc_text = DOC.read_text(encoding="utf-8")
    problems = []
    try:
        declared = declared_edges(doc_text)
    except ValueError as exc:
        declared = None
        problems.append(str(exc))
    actual = actual_edges()
    if declared is not None:
        for comp in COMPONENTS:
            want = declared.get(comp, set())
            got = actual.get(comp, set())
            for extra in sorted(got - want):
                problems.append(f"依赖越界：{comp} → {extra}（文档没允许这条边）")
            for unused in sorted(want - got):
                problems.append(f"文档声明了 {comp} → {unused}，但代码里没有这条 import")
    check_domain_purity(problems)
    check_contract(problems)
    check_style_table(doc_text, problems)
    check_adrs(doc_text, problems)
    check_new_doc_refs(problems)
    check_java(problems)
    check_java_state_literals(problems)
    return problems


def main() -> int:
    problems = check()
    if problems:
        print(f"架构核对发现 {len(problems)} 处问题：")
        for p in problems:
            print("  -", p)
        return 1
    edges = actual_edges()
    print(f"架构核对通过：{len(COMPONENTS)} 个组件、"
          f"{sum(len(v) for v in edges.values())} 条真实依赖边与文档一致；"
          "判定源仅 spec 一份；契约与文档、模型三方一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
