"""demo.py —— B40 四段演示：证据核验 → 负面对照（改坏必须红）→ 示例 JD 映射 → 使用与边界。

确定性：全部输入是仓库里的文件与固定 fixture，无计时输出——
run.bat 两次日志除 unittest 计时行外逐字相同（tools/logdiff.py 只允许那一类规范化）。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))

import check_evidence                                     # noqa: E402
import map_jd                                             # noqa: E402

REPO_ROOT = ROOT.parents[1]


def section(no: int, title: str) -> None:
    print("\n" + "=" * 78 + f"\n  {no}) {title}\n" + "=" * 78)


def show(label: str, value: object) -> None:
    print(f"  {label:<30}{value}")


def _mutated_problems(override: dict) -> list[str]:
    """在临时目录里改坏一条真实证据，交给核验器（不改动仓库文件）。"""
    ev = json.loads((ROOT / "data" / "evidence.json").read_text(encoding="utf-8"))
    entry = dict(ev["evidence"][0])
    entry.update(override)
    ev["evidence"][0] = entry
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="b40-demo-"))
    try:
        path = tmp / "evidence.json"
        path.write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
        return check_evidence.check_evidence_data(path, REPO_ROOT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("B40-career-map 演示：求职证据的可核验化 + JD 差距矩阵（专业实习）")

    # ------------------------------------------------------------------ 1
    section(1, "证据索引：31 条声明的指针/提交/锚点逐条核验")
    ev = json.loads((ROOT / "data" / "evidence.json").read_text(encoding="utf-8"))["evidence"]
    skills = json.loads((ROOT / "data" / "skills.json").read_text(encoding="utf-8"))["skills"]
    problems = check_evidence.check_evidence_data(ROOT / "data" / "evidence.json", REPO_ROOT)
    problems += check_evidence.check_skills_data(ROOT / "data" / "skills.json",
                                                 {e["id"] for e in ev})
    show("核验结果", "PASS（0 个问题）" if not problems else f"RED：{problems}")
    for entry in ev[0:1] + ev[13:14] + ev[27:28]:
        show(f"抽样 {entry['id']}", f"{entry['claim'][:34]}… → {entry['pointers'][0]} @{entry['commit']}")

    # ------------------------------------------------------------------ 2
    section(2, "负面对照：改坏一处，核验器必须报红（否则它就是装饰）")
    cases = [("指针指向不存在的文件", {"pointers": ["projects/NOPE/README.md"]}),
             ("锚点字符串不在文件里", {"anchor": "这段字符串绝不可能出现在文档里xq9"}),
             ("引用一个假提交号", {"commit": "deadbeef0"})]
    for label, override in cases:
        got = _mutated_problems(override)
        first = got[0] if got else "（没有报红——BUG）"
        show(label, f"RED，首条：{first}")

    # ------------------------------------------------------------------ 3
    section(3, "示例 JD 映射：命中→证据 / 缺口→练习（合成示例，非真实岗位）")
    jd_path, example = map_jd.collect_jds(ROOT / "jd")[0]
    report = map_jd.render_matrix(jd_path.name, jd_path.read_text(encoding="utf-8"),
                                  skills, map_jd.load_evidence(ROOT / "data" / "evidence.json"),
                                  example)
    print(report)

    # ------------------------------------------------------------------ 4
    section(4, "怎么用：把岗位换成真的，方向仍由你定")
    print("  1. 把 1-3 个真实岗位 JD 存成 jd/岗位名.txt（不要改 EXAMPLE 那个文件）；")
    print("  2. 跑 python tools/map_jd.py --write —— 差距矩阵写到 build/jd_matrix.md；")
    print("  3. 缺口逐条对照 skill 的 practice 排期；证据条目随时用")
    print("     python tools/check_evidence.py 复核（改坏一条必须红）。")
    print("  边界：本工具只做映射与核验，**不替你选岗位/方向**（PLAN §5），")
    print("        也不替代真实实习——团队协作与业务上下文只能在实习里学。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
