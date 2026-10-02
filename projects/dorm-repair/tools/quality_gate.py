"""tools/quality_gate.py —— 按 `docs/12-qa.md` 的口径判定"这一版能不能放行"（B21）。

流水线（B20）说的是"每一层跑过了没有"；门禁要说的是另一句话：
**哪些层红了必须拦，哪些层红了照样放行但要点名**。
所以这个脚本自己不发明规则，它读 `contracts/gate.json`——那份由 QA 表现算来的口径。

三件它坚持做的事，每件都是本轮真实踩过的失效方式：

* **口径过期就先拒判**。门禁表与文档不一致时，"哪层拦、哪层不拦"这件事本身就不可信，
  此时跑完九层给出的 PASS 是在骗人。所以第一步先核对口径，不通过就 **不跑各层**、直接 BLOCKED。
  （这不是流水线的 fail-fast：那八层是并列证据，口径是判据本身。）
* **advisory 层红了要点名，不许静默**。放行的定义是"blocking 全绿"，不是"全绿"；
  把 advisory 藏起来，下次它坏了没人记得它管过什么。
* **每个红层都给分诊类别 + 下一步命令**，用 `tools/triage.py` 的规则（规则也在门禁契约里），
  这样"红了以后先做什么"不用靠人记。

用法：

```
python tools/quality_gate.py          # 跑全部层并判定 PASS / BLOCKED
python tools/quality_gate.py --json   # 同一结论的机器可读版
```

退出码：0 = 放行（blocking 层全绿）；1 = 拦下。**没有第三种"跳过"**——那正是 B18 那次
`BUILD SUCCESS 但 0 个测试` 的形态。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks import check_qa                             # noqa: E402
from tools import export_gate, pipeline, triage         # noqa: E402


def policy() -> dict:
    if not export_gate.OUT.is_file():
        raise SystemExit(f"缺 {export_gate.OUT.name}：先跑 python tools/export_gate.py --write")
    return json.loads(export_gate.OUT.read_text(encoding="utf-8"))


def decide() -> dict:
    started = time.perf_counter()
    gate = policy()
    blocking = {row["id"]: row for row in gate["layers"] if row["blocking"]}
    advisory = {row["id"]: row for row in gate["layers"] if not row["blocking"]}

    stale = check_qa.gate_problems()
    if stale:
        # 判据本身不可信，跑多少层都不构成放行证据
        return {"verdict": "BLOCKED", "reason": "门禁口径本身过期或有矛盾，先修它",
                "policy_problems": stale, "layers": [],
                "duration_s": round(time.perf_counter() - started, 2)}

    rows = pipeline.run([row["id"] for row in gate["layers"]], quiet=True)
    for row in rows:                      # 拦不拦是**口径**的属性，绿层也要带着，否则报告会写成"放"
        row["blocking"] = row["id"] in blocking
        row["policy_next"] = (blocking.get(row["id"]) or advisory.get(row["id"]) or {}).get("next", "")
    reds = [row for row in rows if row["status"] == "红"]
    blocked_by = [row for row in reds if row["id"] in blocking]
    warned = [row for row in reds if row["id"] in advisory]
    for row in reds:
        row["triage"] = triage.classify(row.get("output", ""))
        row["next_step"] = row["policy_next"]
    stats = check_qa.walk_stats(check_qa.walk_rows()[0])
    return {"verdict": "BLOCKED" if blocked_by else "PASS",
            "reason": (f"{len(blocked_by)} 个 blocking 层红" if blocked_by
                       else f"{len(blocking)} 个 blocking 层全绿"
                            + (f"，另有 {len(warned)} 个 advisory 层红（放行但点名）" if warned else "")),
            "blocking_total": len(blocking), "advisory_total": len(advisory),
            "blocked_by": [row["id"] for row in blocked_by],
            "advisory_red": [row["id"] for row in warned],
            "walkthrough": stats, "layers": rows,
            "duration_s": round(time.perf_counter() - started, 2)}


def report(result: dict) -> None:
    print(f"质量门禁判定：{result['verdict']} —— {result['reason']}")
    for problem in result.get("policy_problems", []):
        print(f"  [口径] {problem}")
    for row in result.get("layers", []):
        flag = "拦" if row["blocking"] else "放"
        detail = (" ".join(f"{k}={v}" for k, v in row["metrics"].items())
                  if row["status"] == "绿"
                  else f"分诊 {row['triage']['category']}：{row['policy_next']}")
        print(f"  [{row['status']}]({flag}) {row['id']:<12} {row['duration_s']:>6.2f}s  {detail}")
    for row in result.get("layers", []):
        if row["status"] == "红":
            t = row["triage"]
            print(f"  分诊 {row['id']}：{t['category']}"
                  + (f"（命中 {t['matched']!r}）" if t["matched"] else "（兜底）")
                  + f"；确认动作：{t['confirm']}")
    walk = result.get("walkthrough")
    if walk:
        print(f"  人工走查仍有 {walk['只能人工']} 步只能由你判、"
              f"{walk['自动+人工']} 步虽有自动证据但仍要看观感（清单 docs/07，结果列我不代填）")
    print(f"  本轮耗时 {result['duration_s']} s；这是**本地判定**，不是服务端强制的分支保护")


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="质量门禁：按口径决定放不放行")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    result = decide()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        report(result)
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
