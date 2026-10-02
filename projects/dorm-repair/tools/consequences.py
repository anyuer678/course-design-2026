"""tools/consequences.py —— 把两条**未裁决**的 AQ 从"文档里的风险"变成"看得见的数字"（B20）。

为什么值得做：AQ-10（循环无上界）和 AQ-11（优先级自选且没人能降级）在需求文档里
挂了三轮，每次都只写"这是风险"。风险如果永远只是一句话，就没有人需要为它做决定。
这里把它们量化：

* **AQ-10**：用 `shrink` 找"回到 `IN_PROGRESS` 且换了维修员"的**最短循环**，
  再把它重复若干遍，看时限、留痕、负责人各发生什么变化。
* **AQ-11**：一个**闭式**（无随机数）的排队小模型：固定到达间隔、固定单维修员工时，
  比较"全都选 NORMAL"与"全都选 URGENT"下的逾期比例。

必须说清楚的边界：AQ-11 的参数是**我拟的假设**，不是调研结果（01 节的来源声明同样适用于这里）。
它能支持的结论只有"在其他条件相同下，把 SLA 从 24 小时压到 2 小时会怎样"，
不能支持"真实校园的逾期率是 X%"。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec import workorder as W                       # noqa: E402
from tools import shrink as S                         # noqa: E402

STEP = tuple


def _interleaved(distribution: dict, total: int):
    """按占比**均匀穿插**排单，而不是同类挤在一起。

    这不是美化：按组排列时占比 10% 的 URGENT 全落在队列最前面、最先被做完，
    逾期率被排成 0%，那是排序造成的假象而不是结论。
    每轮从"还剩最多"的那档取一张，天然把各档摊平。
    """
    want = {prio: int(total * share) for prio, share in distribution.items()}
    for prio in sorted(want, key=lambda x: -distribution[x]):     # 余数给占比大的档
        if sum(want.values()) < total:
            want[prio] += 1
    slots, remaining = [], dict(want)
    while len(slots) < total and any(remaining.values()):
        for prio in sorted(remaining, key=lambda x: (-remaining[x], x)):
            if remaining[prio] > 0 and len(slots) < total:
                slots.append(prio)
                remaining[prio] -= 1
    return slots


def _loop_predicate(seq):
    """回到 `IN_PROGRESS`、**开工动作已发生第二次**、且 SLA 起算点没被重置。

    第一版这里写的是"负责人必须变成 w-2"，于是搜索永远返回 None——
    因为 `shrink.ALPHABET` 里的维修员身份只有 w-1，谓词要求的东西根本不在搜索空间里。
    **写谓词之前先看字母表**：一个不可能成立的判据不会测出风险，只会测出沉默。
    """
    trace = S.replay(list(seq))
    order = trace.final
    if order is None or order.state != "IN_PROGRESS":
        return False
    if order.submitted_at != 1000.0:                  # BR-08：时限起算点不许被推诿重置
        return False
    accepts = sum(1 for c in order.history if c.action == "accept")
    return accepts >= 2


def loop_witness():
    """最短的"换人循环"。字母表里 w-1 是固定身份，所以换到 w-2 需要显式 reassign。"""
    # 最短的真实循环是 escalate→assign→accept（不是 reject_check→accept：
    # accept 只存在于 ASSIGNED 状态，从 IN_PROGRESS 再 accept 会被拒，谓词永远不成立）。
    seed = [
        ("STUDENT", "stu-1", "submit"), ("ADMIN", "adm-1", "assign"),
        ("WORKER", "w-1", "accept"), ("ADMIN", "adm-1", "escalate"),
        ("ADMIN", "adm-1", "assign"), ("WORKER", "w-1", "accept"),
    ]
    if not _loop_predicate(seed):
        # 上面这条走不通（reject_check 之后需要再 accept 才能回到 IN_PROGRESS），
        # 退一步用搜索：从"已开工"出发扫一遍，取第一个满足谓词的短序列
        for depth in range(1, 7):
            found = _search_loop(depth)
            if found:
                return S.ddmin(found, _loop_predicate)
        return None
    return S.ddmin(seed, _loop_predicate)


def _search_loop(depth):
    """按 ALPHABET 顺序扫定长序列。字母表小，深度 4 已够找到循环。"""
    if depth <= 0:
        return None
    stack = [()]
    for _ in range(depth):
        nxt = []
        for prefix in stack:
            for step in S.ALPHABET:
                cand = prefix + (step,)
                if _loop_predicate(list(cand)):
                    return list(cand)
                nxt.append(cand)
            if len(nxt) > 200000:                     # 防爆：够用就行，不做全量
                return None
        stack = nxt
    return None


def loop_repeated(times: int) -> dict:
    """把循环体重复 `times` 遍，看哪些量在动、哪些量不动。"""
    body = [("ADMIN", "adm-1", "escalate"), ("ADMIN", "adm-1", "assign"),
            ("WORKER", "w-2", "accept")]
    order = S.replay([("STUDENT", "stu-1", "submit"), ("ADMIN", "adm-1", "assign"),
                      ("WORKER", "w-1", "accept")]).final
    assignees, errors = [order.assignee], []
    for _ in range(times):
        for role, actor, action in body:
            try:
                order = W.apply_transition(order, W.Role(role), actor, W.Action(action),
                                           now=order.created_at + 1e6, **_inputs(action))
            except W.TransitionError as e:
                errors.append(e.code)
        assignees.append(order.assignee)
    return {"state": order.state, "sla_due_at": order.sla_due_at,
            "submitted_at": order.submitted_at, "history_len": len(order.history),
            "assignees_after_each_round": assignees, "rejected": sorted(set(errors))}


def _inputs(action: str) -> dict:
    return {"assignee": "w-2" if action in ("assign", "reassign") else None,
            "note": "换好了" if action == "resolve" else None,
            "reason": "推回公共池" if action in ("escalate", "return_pool", "reject_check") else None}


#: AQ-11 的假设参数。**这些都是我拟的**，真实分布要靠运营数据（AQ-06/AQ-11 未裁决）。
#: 故意跑**网格**而不是挑一组好看的数字：第一版只报了一组（到达 60 分、工时 40 分，利用率 0.67），
#: 三档逾期率全是 0%——那种配置下一天内积压根本追不上 SLA，差点让我得出"没有后果"的结论。
GRID = (("轻松·一天", 60, 40, 24), ("紧·一天", 45, 60, 24),
        ("挤·一天", 30, 60, 24), ("紧·一周", 45, 60, 168))   # (名称, 到达间隔, 工时, 单数)
ORDERS = 24                     # 观察 24 张单 ≈ 一天
MIX = {"URGENT": 0.10, "HIGH": 0.20, "NORMAL": 0.50, "LOW": 0.20}


def priority_inflation(distribution: dict, *, arrival_min: int, service_min: int,
                          total: int = ORDERS) -> dict:
    """闭式模拟：第 i 张单在 i×arrival_min 到达，完工时刻 = (i+1)×service_min（串行、无空闲优化）。

    逾期定义沿用 SRS 第 8 节：完工时刻 ≥ 到期时刻。这里比的是"交付 vs 承诺"，
    不含抢单、并联、加班等真实运营因素——所以它只说明**方向**，不说明幅度。
    """
    labels = _interleaved(distribution, total)
    overdue, late_minutes, worst = 0, 0, 0.0
    for i, priority in enumerate(labels):
        submitted = i * arrival_min * 60.0
        due = submitted + W.SLA_HOURS[W.Priority(priority)] * 3600
        done = (i + 1) * service_min * 60.0
        if done >= due:
            overdue += 1
            late_minutes += (done - due) / 60
            worst = max(worst, (done - due) / 60)
    if len(labels) != total:
        raise AssertionError(f"穿插后单数不对：{len(labels)} != {total}")
    return {"orders": len(labels), "overdue": overdue,
            "overdue_rate": round(overdue / len(labels), 3),
            "mean_late_minutes_when_overdue": round(late_minutes / overdue, 1) if overdue else 0.0,
            "worst_late_minutes": round(worst, 1),
            "utilisation": round(service_min / arrival_min, 2)}


def measure() -> dict:
    witness = loop_witness()
    rounds = {str(n): loop_repeated(n) for n in (1, 3, 6)}
    grid = {}
    for name, arrival, service, total in GRID:
        grid[name] = {
            "arrival_every_min": arrival, "service_min": service, "orders": total,
            "utilisation": round(service / arrival, 2),
            "all_normal": priority_inflation({"NORMAL": 1.0}, arrival_min=arrival,
                                             service_min=service, total=total),
            "all_urgent": priority_inflation({"URGENT": 1.0}, arrival_min=arrival,
                                             service_min=service, total=total),
            "assumed_mix": priority_inflation(MIX, arrival_min=arrival, service_min=service,
                                               total=total)}
    return {
        "aq10": {
            "shortest_loop": [f"{r}/{a}/{act}" for r, a, act in (witness or [])],
            "loop_len": len(witness) if witness else None,
            "after_rounds": rounds,
            "sla_frozen": len({row["sla_due_at"] for row in rounds.values()}) == 1,
            "history_grows": [rounds[k]["history_len"] for k in ("1", "3", "6")],
            "any_rejection": sorted({code for row in rounds.values()
                                     for code in row["rejected"]}),
        },
        "aq11": {
            "assumptions": {"default_orders": ORDERS, "mix_assumed": MIX,
                            "source": "AI 拟的假设，非调研（docs/01 来源声明同样约束这里）"},
            "grid": grid,
        },
    }


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="AQ-10 / AQ-11 后果测量")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    data = measure()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    aq10 = data["aq10"]
    print(f"AQ-10 最短循环：{aq10['loop_len']} 步  {aq10['shortest_loop']}")
    for rounds, row in aq10["after_rounds"].items():
        print(f"  重复 {rounds} 遍 → 状态 {row['state']}、submitted_at={row['submitted_at']}、"
              f"到期={row['sla_due_at']}、留痕 {row['history_len']} 条、负责人轨迹 {row['assignees_after_each_round']}")
    print(f"  时限是否全程不动：{aq10['sla_frozen']}")
    aq11 = data["aq11"]
    print("AQ-11 参数（AI 假设，非调研）：" + json.dumps(aq11["assumptions"], ensure_ascii=False))
    for name, row in aq11["grid"].items():
        print(f"  [{name}] 到达 {row['arrival_every_min']} 分 / 工时 {row['service_min']} 分 "
              f"→ 利用率 {row['utilisation']}，观察 {row['orders']} 张")
        for label in ("all_normal", "all_urgent", "assumed_mix"):
            cell = row[label]
            print(f"     {label:<12} 逾期 {cell['overdue']}/{cell['orders']} = {cell['overdue_rate']:.1%}"
                  f"，逾期时平均晚 {cell['mean_late_minutes_when_overdue']} 分，"
                  f"最晚 {cell['worst_late_minutes']} 分")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
