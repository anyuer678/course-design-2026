"""tools/triage.py —— 失败分诊：一层红了，先归到 docs/12 分诊表的某一类（B21）。

QA 里最贵的不是失败，是**失败之后没人知道该动哪一侧**。
所以分诊规则写在文档里（规范表），代码只是执行它，规则本身是生成物 `contracts/gate.json` 的一部分——
和契约、判定表同一套做法：文档改了没重生成，`--check` 就会红。

三条硬约束（每条都能被某次改动弄红，见 tests/test_triage.py 与登记变异）：
* 规则**按顺序**取第一条命中，最后一条必须是兜底类，否则一个没匹配上的失败会被静默丢掉；
* 每个类别必须有**真实样本**（样本 = `tools/mutation_check.py` 的登记变异产生的输出），
  没有样本的规则等于没写过——导出器会拒绝；
* 分诊只回答"这类问题通常动哪一侧"，不假装能替人判定"这次到底是谁改的"。
  文档与模型不一致时，光看输出文本分不出需求变了还是实现漂了，所以它们合成一类
  `doc-model-divergence`，把归属判断留给 `git diff`（本轮不提交，所以确认动作写成第二条命令）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))            # 没有这行，脚本模式下的 sys.path[0] 是 tools/，自测导入不到 tools 包
GATE = ROOT / "contracts" / "gate.json"


def load_rules(path: Path = GATE) -> list:
    if not path.is_file():
        raise SystemExit(f"{path.name} 不存在，先跑：python tools/export_gate.py --write")
    return json.loads(path.read_text(encoding="utf-8"))["triage"]


def classify(text: str, rules: list | None = None) -> dict:
    """按顺序找第一条命中的规则；命中不了就落到最后一类（兜底必须是它，导出器盯着）。"""
    rules = rules or load_rules()
    for rule in rules[:-1]:
        for pattern in rule["patterns"]:
            if pattern in text:
                return {"category": rule["category"], "matched": pattern,
                        "meaning": rule["meaning"], "confirm": rule["confirm"]}
    last = rules[-1]
    return {"category": last["category"], "matched": None,
            "meaning": last["meaning"], "confirm": last["confirm"]}


def selftest() -> int:
    """用 15 条登记变异的**真实失败输出**验分诊规则：每条必须落进它自己声明的类别。

    这里不写任何"看起来像"的假日志——样本就是 `tools/mutation_check.py` 跑出来的那段输出。
    它慢（要复制 15 份树 + 起子进程，约 10 秒），所以不进 pytest，而是 `--selftest` 显式跑；
    规则表与样本的**互相收口**（每类都有样本、每个样本都有类）则由 `export_gate.problems()`
    在每次导出与流水线 qa 层里免费检查。
    """
    from tools import mutation_check
    rows = {row["id"]: row for row in mutation_check.run()}
    problems = []
    for mutation in mutation_check.MUTATIONS:
        row = rows.get(mutation["id"])
        if row is None:
            problems.append(f"{mutation['id']}：自检台没跑出这一行")
            continue
        if not row["passed"]:
            problems.append(f"{mutation['id']}：没能把核对器弄红，这条样本不成立")
            continue
        text = (row.get("verbose") or {}).get("output") or row["detail"]
        got = classify(text)
        if got["category"] != mutation["bucket"]:
            problems.append(f"{mutation['id']}：声明 {mutation['bucket']}，实际分诊到 "
                            f"{got['category']}（命中 {got['matched']!r}）；输出尾部 "
                            f"{text[-160:]!r}")
    total = len(mutation_check.MUTATIONS)
    for problem in problems:
        print("  -", problem)
    print(f"分诊自测：{total - len(problems)}/{total} 条真实失败样本落到声明的类别")
    return 1 if problems else 0


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="失败分诊：读一段失败输出，给出类别与下一步")
    ap.add_argument("--text", help="直接给一段失败输出；不给就从标准输入读")
    ap.add_argument("--selftest", action="store_true",
                    help="用登记变异的真实失败输出逐条验分诊规则")
    args = ap.parse_args(argv[1:])
    if args.selftest:
        return selftest()
    text = args.text if args.text is not None else sys.stdin.read()
    if not text.strip():
        print("没有输入文本，无从分诊", file=sys.stderr)
        return 1
    result = classify(text)
    print(f"类别：{result['category']}"
          + (f"（命中特征 {result['matched']!r}）" if result["matched"] else "（兜底：没有命中任何特征）"))
    print(f"含义：{result['meaning']}")
    print(f"下一步：{result['confirm']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
