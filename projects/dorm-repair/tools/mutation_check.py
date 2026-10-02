"""tools/mutation_check.py —— 变异自检台：证明核对器**会失败**（B20）。

前面每一轮我都写过"故意改坏看它抓不抓"的反向测试，但那都是**测试文件里的几条断言**：
它证明的是当时那一版有牙齿。代码一直改，牙齿会掉——掉的时候没有任何东西会响。
这里把"证明它会红"变成一条可以反复跑的命令：

* 每个变异**独享一份新副本**（绝不碰工作树），在副本上施加变异；
* 跑对应的核对器，要求它 ① 退出码非 0 ② 输出里出现预期的原因；
* 每个变异跑之前先对**未变异的副本**跑一遍同一条核对器（阴性对照）——
  否则"它红了"可能只是我的拷贝或环境坏了。
* 变异的锚点文本必须**唯一命中一次**；命中 0 次或多次都算失败。
  这一条专治"重构之后变异静默不再生效，于是一片绿"。

副本为什么要一份一个（B20 实测踩到的坑）：第一版所有变异共用一份副本、改完再还原，
结果 `stale-contract` 单独跑变红、全套连着跑就绿。机制要说准：核对器 `import spec.workorder`
时把 `.pyc` 写进了**副本**里，而 CPython 的 pyc 头部（前 16 字节）只存源码 mtime 的
**整数秒**与源码**字节数**这两个字段——命中判定比的就是这两个数，**源码内容从不参与比较**
（本机实测：头部 mtime 字段 1790845298 = `int(st_mtime)`；把源码改成同长度的另一份内容、
mtime 复原，`import` 仍读到旧值 1）。`copytree` 保留原 mtime、还原后字节数复原、
两次写又落在同一整秒内，三个条件同时成立，于是变异改了源码却没改行为。
共用副本让"变异之间"互相污染，这样的绿是假的；一份一个副本 + 子进程不写字节码，
才是"每个变异都从零开始"。副本 947 KB，代价可以忽略。

用法：

```
python tools/mutation_check.py                    # 跑全部登记项
python tools/mutation_check.py --list             # 只看登记了什么
python tools/mutation_check.py --only stale-contract --verbose
```

`--verbose` 逐条印出：这条想改坏什么、施加的 unified diff、副本内文件的前后指纹、
变异后真正落在盘上的那一行，以及核对器的**完整**输出（默认只印首行和尾部）。
临时目录退出即删，所以要手工进副本复现，就用 `--only <id> --verbose` 重跑。
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 复制时排除的东西：构建产物与缓存既大又与核对无关
SKIP_DIRS = {"target", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}

#: 登记表：每条都写清"改坏哪里 / 期望哪个核对器红 / 红的原因里必须出现什么"。
MUTATIONS = [
    {"id": "sla-hours-model",
     "bucket": "doc-model-divergence",
     "what": "只把模型里的 URGENT 时限从 2 小时改成 3 小时（文档不改）",
     "file": "spec/workorder.py", "count": 1,
     "find": 'Priority.URGENT: 2}', "replace": 'Priority.URGENT: 3}',
     "check": ["checks/check_docs.py"], "expect": "SLA URGENT"},

    {"id": "visibility-doc-only",
     "bucket": "doc-model-divergence",
     "what": "只改文档：维修员可见范围退回旧代码 OWN_OR_POOL",
     "file": "docs/02-srs.md", "count": 1,
     "find": "| WORKER | OWN_OR_POOL_OR_RESOLVED |", "replace": "| WORKER | OWN_OR_POOL |",
     "check": ["checks/check_docs.py"], "expect": "可见性矩阵 WORKER"},

    {"id": "grace-model-only",
     "bucket": "doc-model-divergence",
     "what": "只改模型的验收宽限期（文档仍是 168）",
     "file": "spec/workorder.py", "count": 1,
     "find": "ACCEPTANCE_GRACE_HOURS = 168", "replace": "ACCEPTANCE_GRACE_HOURS = 24",
     "check": ["checks/check_docs.py"], "expect": "ACCEPTANCE_GRACE_HOURS"},

    {"id": "field-limits-doc",
     "bucket": "doc-model-divergence",
     "what": "只改文档里的描述长度上限 500 → 400",
     "file": "docs/02-srs.md", "count": 1,
     "find": "| `description` | 1 | 500 | NONE |", "replace": "| `description` | 1 | 400 | NONE |",
     "check": ["checks/check_docs.py"], "expect": "description"},

    {"id": "stale-contract",
     "bucket": "artifact-stale",
     "what": "改模型但不重生成契约",
     "file": "spec/workorder.py", "count": 1,
     "find": 'Priority.LOW: 72', "replace": 'Priority.LOW: 71',
     # 注意：`export_contract --check` 只比"已存契约 = 文档现算的契约"，
     # 模型单方面改动要靠 check_arch 的三方比对才看得见（第一版我选错了核对器）。
     "check": ["checks/check_arch.py"], "expect": "契约与模型不一致"},

    {"id": "stale-verdict-table",
     "bucket": "artifact-stale",
     "what": "放宽 TR-10 的前置条件但不重生成判定表",
     "file": "spec/workorder.py", "count": 1,
     "find": '_tr("TR-10", "force_close", "RESOLVED", "CLOSED", "ADMIN", "acceptance_timeout")',
     "replace": '_tr("TR-10", "force_close", "RESOLVED", "CLOSED", "ADMIN", "none")',
     "check": ["tools/export_verdict_table.py", "--check"],
     "expect": "判定表与当前模型不一致"},

    {"id": "java-second-rule",
     "bucket": "architecture-violation",
     "what": "往 SOAP 层塞一条自造状态判断（绕过契约）",
     "file": "java/src/main/java/course/dormrepair/soap/SoapQueryService.java", "count": 1,
     "find": "        for (WorkOrder order : orders) {",
     "replace": '        for (WorkOrder order : orders) {\n            if (order.state().equals("SUBMITTED")) { continue; }',
     "check": ["checks/check_arch.py"], "expect": "疑似第二份状态表"},

    {"id": "java-layer-violation",
     "bucket": "architecture-violation",
     "what": "让领域层 import Spring（分层表没这条边）",
     "file": "java/src/main/java/course/dormrepair/domain/WorkOrder.java", "count": 1,
     "find": "import java.util.ArrayList;",
     "replace": "import java.util.ArrayList;\nimport org.springframework.jdbc.core.JdbcTemplate;",
     "check": ["checks/check_arch.py"], "expect": "依赖越界：course.dormrepair.domain"},

    {"id": "adr-section-dropped",
     "bucket": "architecture-violation",
     "what": "删掉一份 ADR 的“验证方式”一节",
     "file": "docs/adr/ADR-02_判定源唯一.md", "count": 1,
     "find": "## 验证方式", "replace": "## 验证办法",
     "check": ["checks/check_arch.py"], "expect": "ADR"},

    {"id": "matrix-stale",
     "bucket": "artifact-stale",
     "what": "改了 FR-01 的验证入口（指向另一个真实存在的测试）但没重生成追踪矩阵",
     # 这条必须**只**违反"矩阵是生成物"一项：换个不存在的测试名会被 T: 存在性检查先拦下，
     # 加一条占位 AC 会被"没测试引用"拦下——那样红了也算不上证据，因为不是矩阵抓的。
     "file": "docs/02-srs.md", "count": 1,
     "find": "`T:tests/test_workorder_spec.py::test_valid_order_accepts_minimal_fixture`",
     "replace": "`T:tests/test_workorder_spec.py::test_transition_table_matches_srs`",
     "check": ["checks/check_docs.py"], "expect": "traceability.csv"},

    {"id": "shrink-alphabet-cut",
     "bucket": "harness-broken",
     "what": "把收缩字母表里的维修员身份删掉（见证就该走不通）",
     "file": "tools/shrink.py", "count": 1,
     "find": 'ACTORS = {"STUDENT": "stu-1", "WORKER": "w-1", "ADMIN": "adm-1"}',
     "replace": 'ACTORS = {"STUDENT": "stu-1", "ADMIN": "adm-1"}',
     "check": ["-m", "pytest", "tests/test_shrink.py", "-q"], "expect": "不可达"},

    {"id": "pm-stale-ledger",
     "what": "改了 docs/13 指标表里一个数字但没重算台账（管理文档开始撒谎）",
     "bucket": "artifact-stale",
     "file": "docs/13-project-plan.md", "count": 1,
     "find": "| `verdict_cells` | `L:verdict_cells=1680` |",
     "replace": "| `verdict_cells` | `L:verdict_cells=1681` |",
     "check": ["checks/check_pm.py"], "expect": "写 L:verdict_cells=1681"},

    {"id": "pm-risk-row-dropped",
     "what": "从风险登记册里删掉一条未裁决 AQ 的登记行",
     "bucket": "register-incomplete",
     "file": "docs/14-risk-register.md", "count": 1,
     "find": "| AQ-06 |", "replace": "| AQ-66 |",
     "check": ["checks/check_pm.py"], "expect": "没有登记进风险登记册"},

    {"id": "java-build-zero-tests",
     "bucket": "toolchain",
     "what": "喂一段“BUILD SUCCESS 但 0 个测试”的输出给 java_build 的解析器",
     "kind": "inline",
     "check": ["-c", "inline"], "expect": "0"},
    # --- B21 追加：门禁口径本身也要能被证明会红 -------------------------------
    {"id": "gate-downgrade",
     "what": "把 mutation 层从 blocking 偷偷降成 advisory（门禁最容易被虚化的方式）",
     "bucket": "policy-tampering",
     "file": "docs/12-qa.md", "count": 1,
     "find": "| `mutation` | blocking |", "replace": "| `mutation` | advisory |",
     "check": ["tools/export_gate.py", "--check"], "expect": "被降级成 advisory"},

    {"id": "triage-rule-dropped",
     "what": "把分诊表里的 toolchain 类别改名（规则表与登记变异不再互相收口）",
     "bucket": "policy-tampering",
     "file": "docs/12-qa.md", "count": 1,
     "find": "| `toolchain` | `BUILD SUCCESS`", "replace": "| `toolchain-x` | `BUILD SUCCESS`",
     "check": ["tools/export_gate.py", "--check"], "expect": "不在分诊表里"},

    {"id": "prototype-overdue-sort",
     "what": "让逾期单不再排最前（真实行为回归，不是文档也不是生成物）",
     "bucket": "behavior-regression",
     "file": "prototype/server.py", "count": 1,
     "find": "key=lambda o: (-1 if W.is_overdue(o, now) else 0, o.id)",
     "replace": "key=lambda o: (o.id,)",
     "check": ["-m", "unittest", "tests.test_prototype.TestApiContract.test_overdue_orders_sort_first"],
     "expect": "逾期排最前"},
]


def _copy_tree(dest: Path) -> None:
    def ignore(_dir, names):
        return [n for n in names if n in SKIP_DIRS]
    shutil.copytree(ROOT, dest, ignore=ignore)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def run_check(copy_root: Path, argv: list) -> tuple:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable] + argv, cwd=str(copy_root), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _apply(copy_root: Path, mutation) -> dict:
    """在副本上施加变异，并返回**可核对的证据**（改了哪里、指纹前后、unified diff）。

    为什么要回读、要指纹：`stale-contract` 第一次连跑变绿时，我分不清是
    "变异没落到那个副本上"还是"落了但核对器看不见"。这两个的修法完全相反。
    """
    path = copy_root / mutation["file"]
    text = path.read_text(encoding="utf-8")
    hits = text.count(mutation["find"])
    if hits != mutation.get("count", 1):
        raise RuntimeError(f"变异锚点命中 {hits} 次（要求 {mutation.get('count', 1)} 次）："
                           f"{mutation['id']} → {mutation['file']}。"
                           f"重构之后变异已失效，绝不能让它静默跳过")
    mutated = text.replace(mutation["find"], mutation["replace"])
    path.write_text(mutated, encoding="utf-8")
    if path.read_text(encoding="utf-8") != mutated:
        raise RuntimeError(f"{mutation['id']}：写入副本后回读不一致，副本不可信")
    return {
        "file": mutation["file"],
        "before": _sha(text),
        "after": _sha(mutated),
        "hits": hits,
        "diff": "".join(difflib.unified_diff(text.splitlines(keepends=True),
                                             mutated.splitlines(keepends=True),
                                             fromfile=mutation["file"],
                                             tofile=mutation["file"] + "（变异后）")),
        "lines": [ln.strip() for ln in mutated.splitlines()
                  if mutation["replace"].splitlines()[0] in ln][:3],
    }


def inline_probe() -> tuple:
    """`java_build` 的两条守卫：不复制树，但走的是**生产代码路径**。

    只 stub 掉两个外部边界（`find_maven` 这台机器上"没装 Maven"、`run` 那段 mvn 输出），
    消息文本由 `java_build.main()` 自己打印——分诊器要拿它当 `toolchain` 类的样本，
    编一条"看起来像"的日志就等于没验（B21 立的规矩：规则必须有真实样本）。
    """
    import contextlib
    import io
    sys.path.insert(0, str(ROOT))
    from tools import java_build
    buffer = io.StringIO()
    real_find, real_run = java_build.find_maven, java_build.run
    java_build.find_maven = lambda: None
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        java_build.main(["--require"])
        java_build.find_maven = real_find
        java_build.run = lambda *a: (0, "[INFO] BUILD SUCCESS")
        java_build.main(["test"])
    java_build.find_maven, java_build.run = real_find, real_run
    text = buffer.getvalue()
    ok = "找不到 Maven" in text and "0 个测试" in text
    return ok, text


#: 阴性对照要跑的核对器：未变异的副本必须全绿，否则后面所有的"红了"都不算证据
CONTROL_CHECKS = (["checks/check_docs.py"], ["checks/check_arch.py"],
                  ["tools/export_contract.py", "--check"],
                  ["tools/export_verdict_table.py", "--check"],
                  ["tools/export_gate.py", "--check"])

#: 本项目之外唯一的真实依赖：B16 原型跑在 B11 的 netlab 上。
#: 副本必须把这份依赖也带进它在临时目录里的**同级位置**，
#: 否则 prototype 相关的变异会因为"找不到 netlab"而红——那是拷贝的缺陷，不是核对器的缺口。
#: 注意：这是拷贝不是链接，B11 若被改动，这里用的仍是拷贝时的版本（本表只对 dorm-repair 施变异）。
EXTERNAL_DEPS = (("../B11-net-lab/netlab", "B11-net-lab/netlab"),)
#: 台账的另一位事实源在**仓库根**（副本祖父目录那一层），不带过来 `pm` 层的变异就会红在 traceback 上
EXTERNAL_FILES = (("../../PLAN.md", "PLAN.md"),)


def _stage_external_deps(copy_parent: Path, grandparent: Path) -> None:
    for rel_src, rel_dst in EXTERNAL_DEPS:
        src = (ROOT / rel_src).resolve()
        dst = copy_parent / Path(rel_dst)
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, ignore=lambda _d, names: [n for n in names if n in SKIP_DIRS])
    for rel_src, rel_dst in EXTERNAL_FILES:
        src = (ROOT / rel_src).resolve()
        dst = grandparent / Path(rel_dst)
        if dst.exists() or not src.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def run(only: str | None = None, verbose: bool = False) -> list:
    rows = []
    ids = {m["id"] for m in MUTATIONS}
    if only is not None and only not in ids:
        # 打错 id 会让待跑列表为空 → "0 条失败" → 退出码 0。这种绿必须当场算失败。
        return [{"id": f"unknown:{only}", "passed": False, "verbose": {},
                 "detail": f"未知的变异 id，已登记：{', '.join(sorted(ids))}"}]
    todo = [m for m in MUTATIONS if only is None or m["id"] == only]
    with tempfile.TemporaryDirectory(prefix="b20-mutation-") as tmpdir:
        tmp = Path(tmpdir) / "outer" / "projects"
        tmp.mkdir(parents=True)
        # 副本一律放在 outer/projects/<名字>，这样：
        #   副本.parent == projects/（B11-net-lab 放这儿，对应 server.py 的 PROJECTS）
        #   副本.parent.parent == outer/（仓库根的 PLAN.md 放这儿，对应台账的 ROOT.parent.parent）
        _stage_external_deps(tmp, tmp.parent)   # tmp=.../outer/projects → 副本的祖父目录是 outer/
        control = tmp / "control"
        _copy_tree(control)
        for probe in CONTROL_CHECKS:
            code, out = run_check(control, probe)
            if code != 0:
                rows.append({"id": f"control:{probe[0]}", "passed": False, "verbose": {},
                             "detail": "未变异的副本就红了，自检台本身有问题：" + out[-400:]})
                return rows
        rows.append({"id": "negative-control", "passed": True, "verbose": {},
                     "detail": f"{len(CONTROL_CHECKS)} 个核对器在未变异副本上全绿"})

        for n, mutation in enumerate(todo, start=1):
            if mutation.get("kind") == "inline":
                ok, detail = inline_probe()
                rows.append({"id": mutation["id"], "passed": ok,
                             "verbose": {"output": detail},
                             "detail": (f"两条守卫的文本都出现了：{detail[:70]!r}…" if ok
                                        else f"守卫文本没同时出现两条：{detail!r}"),
                             "what": mutation["what"]})
                continue
            copy_root = tmp / f"{n:02d}-{mutation['id']}"
            _copy_tree(copy_root)
            cmd = " ".join([Path(sys.executable).name, *mutation["check"]])
            try:
                evidence = _apply(copy_root, mutation)
                code, out = run_check(copy_root, mutation["check"])
            except RuntimeError as e:
                rows.append({"id": mutation["id"], "passed": False, "verbose": {},
                             "detail": str(e), "what": mutation["what"]})
                continue
            red = code != 0 and mutation["expect"] in out
            if red:
                detail = f"退出码 {code}，输出含 {mutation['expect']!r}"
            else:
                detail = (f"没有按要求变红：exit={code}，期望输出含 {mutation['expect']!r}；"
                          f"副本内变异确实已生效（指纹 {evidence['before']}→{evidence['after']}，"
                          f"锚点命中 {evidence['hits']} 处），所以这是核对器的真实缺口。"
                          f"复现：python tools/mutation_check.py --only {mutation['id']} --verbose"
                          f"\n--- {cmd} 输出尾部 ---\n{out[-800:]}")
            rows.append({"id": mutation["id"], "passed": red, "what": mutation["what"],
                         "detail": detail,
                         "verbose": {"cmd": cmd, "code": code, "expect": mutation["expect"],
                                     **evidence, "output": out}})
    return rows


def print_verbose(row) -> None:
    ev = row.get("verbose") or {}
    print(f"\n=== {row['id']} —— {'红得对' if row['passed'] else '有问题'} ===")
    print(f"意图：{row.get('what', '（阴性对照/内联探针，不改文件）')}")
    if ev.get("file"):
        print(f"命令：在副本根目录执行  {ev['cmd']}   → 退出码 {ev['code']}")
        print(f"文件：{ev['file']}  指纹 {ev['before']} → {ev['after']}"
              f"  锚点命中 {ev['hits']} 处")
        print("--- 施加的 diff ---")
        print(ev["diff"].rstrip("\n"))
        print("--- 变异后含新文本的行（证明副本里确实是它） ---")
        for line in ev["lines"]:
            print(f"  {line[:200]}")
        print(f"--- 核对器完整输出（预期原因：{ev['expect']!r}） ---")
    else:
        print("--- 输出 ---")
    for line in (ev.get("output") or row["detail"]).rstrip("\n").splitlines():
        print(f"  {line}")


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="变异自检台")
    ap.add_argument("--list", action="store_true", help="列出登记的变异")
    ap.add_argument("--only", help="只跑某个 id")
    ap.add_argument("--verbose", action="store_true",
                    help="逐条输出施加的 diff、副本指纹与核对器完整输出（临时目录退出即删，"
                         "要手工进副本请用 --only 复现）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    if args.list:
        for m in MUTATIONS:
            print(f"{m['id']:<24} {m['what']}")
        return 0
    rows = run(only=args.only, verbose=args.verbose)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        for row in rows:
            if args.verbose:
                print_verbose(row)
            else:
                print(f"[{'红得对' if row['passed'] else '有问题'}] "
                      f"{row['id']:<24} {row['detail'].splitlines()[0]}")
    failed = [r for r in rows if not r["passed"]]
    controls = [r for r in rows if r["id"] == "negative-control"]
    mutations = [r for r in rows if r not in controls]
    hit = sum(1 for r in mutations if r["passed"])
    print(f"\n变异自检：{hit}/{len(mutations)} 条变异把对应核对器弄红了；"
          f"阴性对照 {len(controls)} 条{'通过' if controls and controls[0]['passed'] else '缺失/未通过'}"
          f"（对照要求的是**不**变红）")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
