"""tools/export_gate.py —— 把 `docs/12-qa.md` 的两张 QA 表导成 `contracts/gate.json`（B21）。

沿用这一套代码从 B17 起就有的做法：**规范表写在文档里，机器读的那份是生成物**，
所以"文档改了没重生成"必须能被 `--check` 抓到，而不是靠人记得。

导出时做三件校验，每件都对应一种真实事故：
1. 门禁表的层集合必须与 `tools/pipeline.py` 的层**完全相等**——
   流水线加了一层而门禁表忘了写，那层就处在"没人规定它拦不拦"的状态，等于默认放行。
2. 分诊表的类别必须**全部有真实样本**（样本 = `tools/mutation_check.py` 的登记变异），
   每条变异的类别必须在分诊表里——两边互相收口，删规则或写个没样本的类别都会红。
3. `mutation` 层必须 blocking（这条是门禁的地基，写在代码里而不是只写在文档里，
   因为"把最关键的层降成 advisory"正是门禁最容易被悄悄虚化的方式）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks import check_docs                            # noqa: E402
from tools import pipeline                               # noqa: E402

GATE_DOC = ROOT / "docs" / "12-qa.md"
OUT = ROOT / "contracts" / "gate.json"
SCHEMA_VERSION = 1

GATE_HEADER = ["层 id", "拦不拦", "这层拦下的是", "红了先做什么"]
TRIAGE_HEADER = ["类别", "触发特征（输出里出现）", "含义", "该跑什么来确认"]
FALLBACK = "behavior-regression"
#: 不许被降级的层：它管"验证机制自己还可不可信"
MUST_BLOCK = ("mutation",)


def tables():
    found, problems = check_docs.tables_in(GATE_DOC.read_text(encoding="utf-8"))
    if problems:
        raise SystemExit(f"docs/12 的表格本身不合格：{problems}")
    return found


def strip_ticks(text: str) -> list:
    """触发特征写成 `A`、`B` 的形式；剥掉反引号后按顿号或逗号切。

    兜底那一格写的是"（兜底，不命中以上任何特征）"，它**不是特征**。
    只要整格里出现"兜底"就整格算空特征——早先按分段过滤会把后半句
    "不命中以上任何特征）"留下当成一个模式，于是兜底规则带着伪模式；
    这条是 tests/test_gate.py 的分隔符测试抓出来的。
    """
    if "兜底" in text:
        return []
    parts = [piece.strip().strip("`").strip() for piece in re.split(r"、|，", text)]
    return [piece for piece in parts if piece]


def build() -> dict:
    found = tables()
    gate_rows = check_docs.one(found, GATE_HEADER, "第 1 节门禁表")
    triage_rows = check_docs.one(found, TRIAGE_HEADER, "第 2 节分诊表")
    layers = [{"id": r[0].strip().strip("`"), "blocking": r[1].strip() == "blocking",
               "catches": r[2].strip(), "next": r[3].strip()} for r in gate_rows]
    triage = [{"category": r[0].strip().strip("`"), "patterns": strip_ticks(r[1]),
               "meaning": r[2].strip(), "confirm": r[3].strip()} for r in triage_rows]
    return {"schema_version": SCHEMA_VERSION,
            "source": "docs/12-qa.md 第 1、2 节（由 tools/export_gate.py 生成，勿手改）",
            "layers": layers, "triage": triage}


def problems(data: dict) -> list:
    """这里的每一条都必须能被某次改动弄红，否则它就是装饰。"""
    out = []
    ids = [row["id"] for row in data["layers"]]
    if len(ids) != len(set(ids)):
        out.append(f"门禁表有重复层：{[x for x in ids if ids.count(x) > 1]}")
    pipeline_ids = [layer.id for layer in pipeline.LAYERS]
    if set(ids) != set(pipeline_ids):
        out.append(f"门禁表与流水线的层集合不等：只有文档有 {sorted(set(ids) - set(pipeline_ids))}，"
                   f"只有流水线有 {sorted(set(pipeline_ids) - set(ids))}")
    for row in data["layers"]:
        if row["blocking"] not in (True, False):
            out.append(f"层 {row['id']} 的『拦不拦』不是 blocking/advisory")
    for id_ in MUST_BLOCK:
        row = next((r for r in data["layers"] if r["id"] == id_), None)
        if row is None:
            out.append(f"门禁表缺了必须被管的层 {id_}")
        elif not row["blocking"]:
            out.append(f"层 {id_} 被降级成 advisory：它管的是核对器还有没有牙齿，"
                       f"这条一松整套门禁就变成装饰")

    cats = [rule["category"] for rule in data["triage"]]
    if len(cats) != len(set(cats)):
        out.append(f"分诊表有重复类别：{[c for c in cats if cats.count(c) > 1]}")
    if not cats or cats[-1] != FALLBACK:
        out.append(f"分诊表最后一类必须是兜底的 {FALLBACK}，实际是 {cats[-1:]}")
    for rule in data["triage"][:-1]:
        if not rule["patterns"]:
            out.append(f"分诊类别 {rule['category']} 没有触发特征，永远不会命中")

    from tools import mutation_check                      # noqa: E402
    samples = [m for m in mutation_check.MUTATIONS if m.get("kind") != "control"]
    for m in samples:
        bucket = m.get("bucket")
        if bucket is None:
            out.append(f"变异 {m['id']} 没登记分诊类别 bucket")
        elif bucket not in cats:
            out.append(f"变异 {m['id']} 的类别 {bucket} 不在分诊表里")
    covered = {m.get("bucket") for m in samples}
    for cat in cats:
        if cat not in covered:
            out.append(f"分诊类别 {cat} 没有任何真实样本（登记变异里没人落到这一类）——"
                       f"这条规则没被验证过")
    return out


def to_text(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="导出 QA 门禁契约")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv[1:])
    data = build()
    bad = problems(data)
    if bad:
        print(f"QA 门禁表发现 {len(bad)} 处问题：")
        for p in bad:
            print("  -", p)
        return 1
    if args.write:
        OUT.write_text(to_text(data), encoding="utf-8")
        print(f"已写出 {OUT.name}：{len(data['layers'])} 层"
              f"（blocking {sum(1 for r in data['layers'] if r['blocking'])}）"
              f"、{len(data['triage'])} 类分诊")
        return 0
    if not OUT.is_file():
        print(f"{OUT.relative_to(ROOT)} 不存在，跑：python tools/export_gate.py --write")
        return 1
    saved = json.loads(OUT.read_text(encoding="utf-8"))
    if saved != data:
        print("门禁契约与文档不一致：docs/12 改了没重生成，或有人手改了 JSON")
        for key in ("layers", "triage"):
            if saved.get(key) != data.get(key):
                doc = json.dumps(saved.get(key), ensure_ascii=False).split("},")
                now = json.dumps(data.get(key), ensure_ascii=False).split("},")
                for a, b in zip(doc + [""] * len(now), now + [""] * len(doc)):
                    if a != b:
                        print(f"  - {key} 首个差异：已存 {a[:90]} vs 现在 {b[:90]}")
                        break
        return 1
    print(f"门禁契约与文档、流水线三方一致：{len(data['layers'])} 层、"
          f"{sum(1 for r in data['layers'] if r['blocking'])} 层 blocking、"
          f"{len(data['triage'])} 类分诊（每类都有真实样本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
