"""tools/shrink.py —— 失败输入收缩（B20 测试工程）。

为什么报修系统需要它：模型里一个坏行为往往要**一长串动作**才能复现
（"退回—改派—再开工—再退回…"）。这种序列给人看没意义，给回归测试用又太脆。
所以这里做两件事：

1. `ddmin`：对一个只依赖序列的判定（谓词），反复删 chunk / 删单步，缩到**单步不可再删**；
2. `shortest_by_bfs`：同一批动作字母表上做广度优先，给出**真正最短**的见证序列。

两者对拍。注意 ddmin 只会删、不会重排，所以它可能达不到全局最短——
那不是一个 bug，是算法的边界；我把实测差距写进测试而不是假装相等（B15 起就吃过
"把实现当定义"的亏，这里换成"把算法能力当上限"同样会骗人）。

用法：

```
python tools/shrink.py                 # 打印七个状态的最短见证 + ddmin 对比
python tools/shrink.py --json          # 机器可读结果（供 pipeline / 后果测量复用）
python -m unittest tests.test_shrink   # 收缩器自己的测试
```
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec import workorder as W                          # noqa: E402

#: 动作字母表：(角色, 身份, 动作, 该动作固定带的输入)。身份覆盖了报修人/两个维修员/管理员，
#: 输入固定成合法值——收缩关心的是"哪几步不可省"，不是"哪次填错"。
ACTORS = {"STUDENT": "stu-1", "WORKER": "w-1", "ADMIN": "adm-1"}
ALPHABET = tuple(
    (role, actor, action)
    for role, actor in sorted(ACTORS.items())
    for action in sorted(a.value for a in W.Action)
)
STEP = tuple                      # (role, actor_id, action)


@dataclass
class Trace:
    ok_steps: tuple               # 真正被接受的动作（顺序）
    codes: tuple                  # 每一步的结果：目标状态 或 错误码
    final: W.Order | None


def replay(seq, *, start: W.Order | None = None) -> Trace:
    """从头执行一个序列，逐步记录"到了哪个状态 / 被哪个码挡住"。

    谓词只准看这份轨迹：收缩器换步、删步之后语义必须一致，否则对拍无意义。
    """
    order = start if start is not None else _draft()
    ok_steps, codes = [], []
    for role, actor, action in seq:
        try:
            order = W.apply_transition(order, W.Role(role), actor, W.Action(action),
                                       now=_now_for(len(codes)), **_inputs_for(action))
            ok_steps.append((role, actor, action))
            codes.append("->" + order.state)
        except W.TransitionError as e:
            codes.append("!" + e.code)
    return Trace(tuple(ok_steps), tuple(codes), order)


def _draft() -> W.Order:
    return W.create_order(id="S1", reporter="stu-1", room="A01-101", category="WATER_ELEC",
                          priority="NORMAL", description="水管漏水", contact="13800000000",
                          created_at=100.0)


def _now_for(step_index: int) -> float:
    return 1000.0 + step_index * 1000.0


def _inputs_for(action: str) -> dict:
    return {"assignee": "w-1", "note": "换了垫圈", "reason": "理由"}


def ddmin(seq, predicate: Callable) -> tuple:
    """标准 delta debugging：先删 chunk，再删单步；两者都删不动才收窄粒度。

    保证的是**单步不可再删**（1-minimal），不保证全局最短——它只会删，不会重排。
    循环在长度降到 1 时就退出，所以收尾必须单独试一次"删到空"：
    第一版漏了这步，实测 `DRAFT` 一栏 `单步不可删=False`——因为空序列本来就满足"到达 DRAFT"
    （新草稿就是 DRAFT），而 ddmin 返回了 1 步的序列并自称最小。**"我认为它保证了"和"它保证了"是两件事。**
    """
    current = list(seq)
    if not predicate(current):
        raise ValueError("原序列就不满足谓词，收缩无从谈起")
    n = 2
    while len(current) >= 2:
        size = max(1, len(current) // n)
        chunks = [current[i:i + size] for i in range(0, len(current), size)]
        if len(chunks) < 2:
            break
        progressed = False
        for i in range(len(chunks)):            # ① 删掉一整块
            candidate = [x for j, part in enumerate(chunks) if j != i for x in part]
            if predicate(candidate):
                current, progressed, n = candidate, True, max(n - 1, 2)
                break
        if not progressed:
            for i in range(len(current)):       # ② 只删一步
                candidate = current[:i] + current[i + 1:]
                if predicate(candidate):
                    current, progressed, n = candidate, True, max(n - 1, 2)
                    break
        if not progressed:
            if n >= len(current):
                break
            n = min(2 * n, len(current))
    # 收尾：循环在长度 1 时就退出，"删到空"这步得自己试一次
    if predicate([]):
        return ()
    return tuple(current)


def is_one_minimal(seq, predicate: Callable) -> bool:
    """形式上的"不可再小"：删任何一步谓词都不成立。ddmin 保证这个，不保证全局最短。"""
    return all(not predicate(list(seq[:i]) + list(seq[i + 1:])) for i in range(len(seq)))


def shortest_by_bfs(predicate: Callable, *, max_depth: int = 6, key=lambda order: order.state):
    """广度优先找**最短**见证序列，按 `key(工单)` 去重，所以是真正的搜索而不是 36^6 的树。

    限制要写明白：`key` 必须是谓词**唯一依赖**的东西。这里用最终状态，谓词是"到达某状态"，
    成立；如果哪天谓词还看历史条数，就得把条数并进 key，否则"最短"会变成假的。
    （第一版我没去重，跑到超时才暴露——注释里写着"状态空间小"，代码却没利用它。）
    """
    frontier = [()]
    best_key = key(replay(()).final)
    visited = {best_key}
    if predicate([]):        # 深度 0 也是一个答案；漏了它，"最短"对空序列成立的问题就是错的
        return ()
    for _ in range(max_depth):
        nxt = []
        for seq in frontier:
            for step in ALPHABET:
                candidate = seq + (step,)
                trace = replay(candidate)
                if trace.final is None:
                    continue
                if predicate(list(candidate)):
                    return candidate
                k = key(trace.final)
                if k in visited:
                    continue
                visited.add(k)
                nxt.append(candidate)
        frontier = nxt
        if not frontier:
            break
    return None


def reaches(state: str):
    return lambda seq: (lambda t: t.final is not None and t.final.state == state)(replay(seq))


def find_witnesses():
    """给每个状态找一条见证序列，并量出 ddmin 与全局最短的差距。"""
    out = {}
    for state in [s.value for s in W.State]:
        seed = _seed_sequence(state)
        if seed is None:
            out[state] = {"reachable": False}
            continue
        minimal = ddmin(seed, reaches(state))
        best = shortest_by_bfs(reaches(state), max_depth=6)
        # 注意：空序列是合法答案（DRAFT 就在起点），所以判"没找到"必须用 is None，
        # 不能用 `if best` —— 空元组是假值，会被误判成 None。
        out[state] = {
            "reachable": True,
            "seed_len": len(seed),
            "ddmin_len": len(minimal),
            "bfs_len": None if best is None else len(best),
            "one_minimal": is_one_minimal(minimal, reaches(state)),
            "matched_optimum": best is not None and len(minimal) == len(best),
            "witness": [f"{r}/{a}/{act}" for r, a, act in minimal],
            "codes": list(replay(minimal).codes),
        }
    return out


def _seed_sequence(state: str):
    """一条"明显能到该状态"的长序列：先走完整链路，再按状态截断/追加。"""
    full = [("STUDENT", "stu-1", "submit"), ("ADMIN", "adm-1", "assign"),
            ("WORKER", "w-1", "accept"), ("WORKER", "w-1", "resolve"),
            ("STUDENT", "stu-1", "confirm")]
    want = {"DRAFT": [], "SUBMITTED": full[:1], "ASSIGNED": full[:2],
            "IN_PROGRESS": full[:3], "RESOLVED": full[:4], "CLOSED": full[:5],
            "CANCELLED": [full[0], ("STUDENT", "stu-1", "cancel")]}
    seq = [tuple(s) for s in want[state]]
    # 故意加冗余：先塞几步注定被拒的动作，看收缩器能不能删干净
    noise = [("WORKER", "w-1", "resolve"), ("ADMIN", "adm-1", "escalate"),
             ("STUDENT", "stu-1", "reassign")]
    padded = (noise[:2] + seq + noise[:1]) if seq else (noise + seq)
    return tuple(padded) if reaches(state)(list(padded)) else (tuple(seq) if reaches(state)(list(seq)) else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="序列收缩与最短见证对拍")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = ap.parse_args(argv[1:] if argv else None)
    data = find_witnesses()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    print("状态        种子长  ddmin  BFS最短  单步不可删  达到最优")
    for state, row in data.items():
        if not row.get("reachable"):
            print(f"{state:<12} 不可达")
            continue
        print(f"{state:<12} {row['seed_len']:>6} {row['ddmin_len']:>6} "
              f"{row['bfs_len']:>7} {str(row['one_minimal']):>10} {str(row['matched_optimum']):>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
