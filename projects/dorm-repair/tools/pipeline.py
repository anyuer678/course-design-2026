"""tools/pipeline.py —— 分层本地流水线（B20）。

这一轮前面造的东西都是"点"：一个核对器、一个收缩器、一个变异自检台。
课程里把它们串起来的那条东西叫流水线，而流水线的关键不在"能跑"，在这三件事：

1. **每层说清自己在管什么**，以及"什么样的改动会让这层红"。
   答不出后者的层就是在烧时间——它跑过了不代表它有牙齿（B18 的 `BUILD SUCCESS 但 0 个测试`、
   B19 的"XXE 加固其实没生效"都是这一类）。
2. **读数失败＝这层红**。命令退出码 0 但输出里解析不到我要的那个数字，
   就等于"没跑"。这条是本流水线唯一自带的规则，也是前面所有轮次的教训固化。
3. **不 fail-fast**。第一层红就退出，后面六层的状况这轮就拿不到了；
   全跑完再汇总，一次看全。代价是慢，好处是报告是真的。

前提：**全程本地、离线、不装任何东西**（Java 层用 `~/.m2` 里已缓存的 Maven 与依赖，
`mvn -o`）。它不覆盖浏览器人工走查（B16 的 20 步清单）——那部分只有你眼睛能验。

用法：

```
python tools/pipeline.py                 # 全跑并出分层报告
python tools/pipeline.py --json          # 同一份报告的机器可读版
python tools/pipeline.py --only docs     # 只跑某一层（id 见 --list）
python tools/pipeline.py --list
```
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]


class CannotRead(Exception):
    """读数读不到：这层的输出形状变了，或者它压根没跑成。"""


def _num(pattern: str, text: str, label: str) -> int:
    m = re.search(pattern, text)
    if not m:
        raise CannotRead(f"输出里找不到 {label}（模式 {pattern!r}）")
    return int(m.group(1))


def _doc(path: str) -> dict:
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CannotRead(f"{path} 读不出来：{exc}") from exc


def _both(proc) -> str:
    return (proc.stdout or "") + (proc.stderr or "")


# ------------------------------------------------------------------ 各层读数

def read_docs(out: str) -> dict:
    m = re.search(r"FR (\d+) / BR (\d+) / NFR (\d+) / IF (\d+) / UC (\d+) / US (\d+) / "
                  r"AC (\d+) / 转换 (\d+) / 待决 (\d+)", out)
    if not m:
        raise CannotRead("文档计数行没匹配上，check_docs 的输出形状变了")
    keys = ("FR", "BR", "NFR", "IF", "UC", "US", "AC", "转换", "待决")
    return dict(zip(keys, (int(x) for x in m.groups())))


def read_contract(out: str) -> dict:
    if "三方一致" not in out:
        raise CannotRead("没看到『三方一致』这句结论")
    data = _doc("contracts/workflow.json")
    return {"schema_version": int(data["schema_version"]),
            "转换": len(data["transitions"]),
            "角色": len(data["permissions"]),
            "前置条件": len(data["preconditions"])}


def read_verdict(out: str) -> dict:
    return {"格子": _num(r"判定表与模型一致：(\d+) 格", out, "判定表格子数")}


def read_arch(out: str) -> dict:
    return {"组件": _num(r"(\d+) 个组件", out, "组件数"),
            "依赖边": _num(r"(\d+) 条真实依赖边", out, "依赖边数")}


def read_python_tests(out: str) -> dict:
    ran = _num(r"Ran (\d+) tests", out, "unittest 的 Ran 行")
    if not re.search(r"^OK", out, re.M):
        raise CannotRead("没有 OK 汇总行（有失败或根本没跑成）")
    m = re.search(r"OK \(skipped=(\d+)\)", out)
    return {"测试": ran, "跳过": int(m.group(1)) if m else 0}


def read_java(out: str) -> dict:
    # java_build 自己已经判过"BUILD SUCCESS 但 0 个测试"和"逐类相加≠mvn 总计"，
    # 那两条各有变异盯着；这里只把它报的数字取出来，不重复实现一遍判定。
    ran = _num(r"Tests run=(\d+)", out, "java_build 的 Tests run")
    if ran == 0:
        raise CannotRead("Tests run=0：这层不许当绿")
    return {"测试": ran,
            "失败": _num(r"failures=(\d+)", out, "failures"),
            "错误": _num(r"errors=(\d+)", out, "errors"),
            "跳过": _num(r"skipped=(\d+) BUILD SUCCESS", out, "skipped")}


def read_shrink(out: str) -> dict:
    data = _json_from(out)
    optimum = sum(1 for v in data.values() if v.get("matched_optimum"))
    minimal = sum(1 for v in data.values() if v.get("one_minimal"))
    if optimum != len(data):
        raise CannotRead(f"有状态收缩得比暴力最短还长：{optimum}/{len(data)}")
    return {"状态": len(data), "达到暴力最短": optimum, "单步不可删": minimal}


def read_consequences(out: str) -> dict:
    data = _json_from(out)
    grid = data["aq11"]["grid"]
    scenarios = ("all_normal", "all_urgent", "assumed_mix")
    cells = sum(1 for row in grid.values() for key in scenarios if key in row)
    if cells != 3 * len(grid):
        raise CannotRead(f"AQ-11 每档应有 {len(scenarios)} 种配比，实测 {cells}")
    aq10 = data["aq10"]
    if not aq10["sla_frozen"]:
        raise CannotRead("AQ-10 的测量里时限竟然动了——测量对象变了")
    return {"AQ-10 循环长度": int(aq10["loop_len"]),
            "AQ-10 时限冻结": bool(aq10["sla_frozen"]),
            "AQ-11 配置": len(grid),
            "AQ-11 格子": cells}


def read_qa(out: str) -> dict:
    m = re.search(r"走查 (\d+) 步＝纯自动 (\d+) \+ 自动且仍需人工 (\d+) \+ 只能人工 (\d+)", out)
    if not m:
        raise CannotRead("没读到走查对齐的四个数")
    gate = re.search(r"(\d+) 层，blocking (\d+) 层", out)
    if not gate:
        raise CannotRead("没读到门禁层数")
    return {"层": int(gate.group(1)), "blocking": int(gate.group(2)),
            "走查步数": int(m.group(1)), "纯自动": int(m.group(2)),
            "自动且仍需人工": int(m.group(3)), "只能人工": int(m.group(4))}


def read_pm(out: str) -> dict:
    m = re.search(r"台账 (\d+) 个键.*未决 (\d+) 条.*坑 1\.\.(\d+)", out)
    if not m:
        raise CannotRead("PM 层没报出键数、未决条数与复盘覆盖上限")
    return {"台账键": int(m.group(1)), "未决AQ": int(m.group(2)), "复盘覆盖到": int(m.group(3))}


def read_mutation(out: str) -> dict:
    m = re.search(r"变异自检：(\d+)/(\d+) 条", out)
    if not m:
        raise CannotRead("没有变异自检的汇总行")
    red, total = int(m.group(1)), int(m.group(2))
    if red != total:
        raise CannotRead(f"{total - red} 条变异没能把核对器弄红")
    return {"变异": total, "按预期变红": red}


def _json_from(out: str) -> dict:
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise CannotRead(f"--json 输出不是合法 JSON：{exc}") from exc


# ------------------------------------------------------------------ 层定义

@dataclass
class Layer:
    id: str
    title: str
    argv: list
    read: Callable[[str], dict]
    turns_red: str          # 这层存在的理由：什么改动必须把它弄红
    why: str                # 这层在管什么，一句话说清

    def run(self) -> dict:
        started = time.perf_counter()
        env = dict(os.environ, PYTHONUTF8="1")
        proc = subprocess.run([sys.executable] + self.argv, cwd=str(ROOT), env=env,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        out = _both(proc)
        duration = round(time.perf_counter() - started, 2)
        row = {"id": self.id, "title": self.title, "cmd": " ".join(self.argv),
               "code": proc.returncode, "duration_s": duration,
               "output_tail": out.strip().splitlines()[-3:],
               # 完整输出留给分诊器：分诊看的是"到底报了什么"，只看尾三行会把类别猜错
               "output": out}
        if proc.returncode != 0:
            row.update(status="红", metrics={},
                       note=f"命令退出码 {proc.returncode}")
        else:
            try:
                row.update(status="绿", metrics=self.read(out), note="")
            except CannotRead as exc:
                row.update(status="红", metrics={}, note=f"退出码 0 但读不到数：{exc}")
        return row


LAYERS = [
    Layer("docs", "需求文档 ↔ 模型 ↔ 追踪矩阵", ["checks/check_docs.py"], read_docs,
          "改 SRS 的规范表不同步 spec，或改 spec 不重生成 traceability.csv，或把 T: 指向"
          "一个不存在的测试",
          "文档说的数、模型用的数、矩阵引的数必须是同一个数"),
    Layer("contract", "契约文件与它的两个来源", ["tools/export_contract.py", "--check"],
          read_contract,
          "只改 spec（比如把 LOW 时限 72→71）而不重生成 workflow.json——Java 就会读旧表",
          "契约是从文档现算的生成物，不是人手维护的第三份规则"),
    Layer("verdict", "跨语言判定表（Python 逐格复算）",
          ["tools/export_verdict_table.py", "--check"], read_verdict,
          "放宽某条转换的前置条件却不重生成判定表，Java 对拍就失去参照",
          "1680 个格子的期望判定必须有据可查，不能『我以为通过』"),
    Layer("arch", "架构核对（含 Java 分层与状态字面量）", ["checks/check_arch.py"], read_arch,
          "领域层 import Spring、app 里塞 instanceof、Java 里自造一条状态判断、"
          "ADR 少一节『验证方式』",
          "依赖图是实测的：文档画的边必须和源码里的 import 一致"),
    Layer("qa", "质量门禁口径与走查清单对齐", ["checks/check_qa.py"], read_qa,
          "门禁表与文档不一致、把 mutation 层降成 advisory、走查某步声称有自动证据但那条测试并不存在、"
          "或结果列被检查器代填",
          "门禁定义的是『什么算不合格』，它自己过期了整套判定就失去意义"),
    Layer("pm", "管理文档与台账一致（计划/风险/复盘）", ["checks/check_pm.py"], read_pm,
          "改了事实源没重生成 ledger、把风险登记册里一条未决 AQ 删掉、复盘漏归类或重号、"
          "台账留了没人引用的装饰键",
          "计划、风险、复盘里的数字必须是现算的，抄来的数字过期时没人会响"),
    Layer("pytests", "Python 需求模型测试", ["-m", "unittest", "discover", "-s", "tests"],
          read_python_tests,
          "任何一条状态机/权限/校验/时限规则被改坏——包括被『顺手优化』改掉的那条",
          "可执行需求模型的回归网；期望值都写明了出处"),
    Layer("javatests", "Java 平台离线构建与测试", ["tools/java_build.py", "--require"],
          read_java,
          "契约版本不符导致启动失败、乐观锁失效、REST/SOAP 判定与 Python 不一致；"
          "以及最阴的一种：BUILD SUCCESS 但 0 个测试",
          "同一份契约在第二种语言里落地；--require 让『没装 Maven』算失败而不算跳过"),
    Layer("shrink", "反例序列收缩器（与暴力最短对拍）", ["tools/shrink.py", "--json"],
          read_shrink,
          "收缩器给出的见证比 BFS 算出的最短还长，或见证里有可删的一步",
          "调试用的最小反例：短到能读，且证明它确实最短"),
    Layer("consequences", "未裁决需求的后果测量", ["tools/consequences.py", "--json"],
          read_consequences,
          "测量失去响应：把 URGENT 时限放宽而逾期率不降，或循环重复而时限/痕迹没变",
          "AQ-10/AQ-11 不是嘴上说有风险，要能报出数字"),
    Layer("mutation", "变异自检台（核对器有没有牙齿）", ["tools/mutation_check.py"],
          read_mutation,
          "任何一条登记变异没能把对应核对器弄红——那这层的绿就是假的",
          "把『证明它会失败』变成一条可反复跑的命令"),
]

BY_ID = {layer.id: layer for layer in LAYERS}


def run(layer_ids: list, quiet: bool = False) -> list:
    rows = []
    for layer in LAYERS:
        if layer.id not in layer_ids:
            continue
        row = layer.run()
        row["turns_red"] = layer.turns_red
        row["why"] = layer.why
        rows.append(row)
        if not quiet:
            print(f"  [{row['status']}] {row['id']:<12} {row['duration_s']:>6.2f}s  "
                  + (f"{row['note']}" if row["status"] == "红"
                     else " ".join(f"{k}={v}" for k, v in row["metrics"].items())))
    return rows


def report(rows: list) -> int:
    print("\n分层说明（这层管什么 / 什么改动必须让它红）")
    for row in rows:
        print(f"  {row['id']:<12} 管：{row['why']}")
        print(f"  {'':<12} 红：{row['turns_red']}")

    print("\n分层报告（本轮实测，不是文档里抄的）")
    print(f"  {'层':<12} {'状态':<4} {'耗时':>7}  {'读数':<52} 命令")
    for row in rows:
        metrics = " ".join(f"{k}={v}" for k, v in row["metrics"].items()) or "—"
        print(f"  {row['id']:<12} {row['status']:<4} {row['duration_s']:>6.2f}s  "
              f"{metrics:<52} python {' '.join(row['cmd'].split())}")

    failed = [r for r in rows if r["status"] == "红"]
    total = round(sum(r["duration_s"] for r in rows), 2)
    print(f"\n共 {len(rows)} 层、{total}s；本地离线跑完，未安装或下载任何东西")
    print("不覆盖：浏览器里的人工走查（B16 的 20 步清单）、真实用户满意度、并发压测。")
    for row in failed:
        print(f"[红] {row['id']}：{row['note'] or '命令失败'}")
        for line in row["output_tail"]:
            print(f"      {line[:150]}")
    if not failed:
        print("全部层绿：每层的读数都取到了，没有任何一层是『退出码 0 但读不到数』。")
    return 1 if failed else 0


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="分层本地流水线")
    ap.add_argument("--only", action="append", metavar="ID", help="只跑指定层，可重复")
    ap.add_argument("--list", action="store_true", help="列出层")
    ap.add_argument("--json", action="store_true", help="输出机器可读报告")
    args = ap.parse_args(argv[1:])
    if args.list:
        for layer in LAYERS:
            print(f"{layer.id:<12} {layer.title}")
        return 0
    ids = [layer.id for layer in LAYERS]
    if args.only:
        unknown = [x for x in args.only if x not in BY_ID]
        if unknown:
            print(f"未知的层：{unknown}；可选：{ids}", file=sys.stderr)
            return 1
    if args.json and not args.only:
        print("整套报告的分层说明在 --json 里被压掉了（stdout 只能是纯 JSON），"
              "给人看就省略 --json。", file=sys.stderr)
    if args.only:
        selected = args.only
    else:
        selected = [layer.id for layer in LAYERS]
    if not args.json:
        print(f"分层流水线（{len(selected)} 层，顺序执行，不 fail-fast）")
    rows = run(selected, quiet=args.json)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 1 if any(r["status"] == "红" for r in rows) else 0
    return report(rows)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
