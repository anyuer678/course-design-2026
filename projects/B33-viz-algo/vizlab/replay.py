"""vizlab/replay.py —— 独立回放/参照实现：把"操作记录"翻译成可核对的状态机

课程要点（可视化技术的"底层是数据结构"）：
    - 动画不是凭空画的：每一帧都来自一条**可回放的操作记录**。回放器只有三种台词：
      排序侧（swap / pop / build）、图侧（visit + 前沿快照）——页面与测试共用同一份回放语义；
    - 本模块同时也是**独立参照**：BFS/DFS 用 Python 从头写一遍，与 B2（C++）导出的记录
      逐步比对——"看得见的动画"和"跑得对的结构"必须是一回事（对拍纪律）。
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path


def load_trace(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 排序侧

def replay_sort(trace: dict) -> list[dict]:
    """回放排序记录：按 C++ 侧的真实协议重建数组，逐步核对每条快照。

    关键协议（读 B2 的 Heap::pop 源码得来，**不是猜的**）：一次取出 =
      [未记录] 根<->尾交换 + 丢掉尾元素 → sift 交换若干（有记录）→ "pop" 事件。
    收缩发生在**每次 build 或 pop 事件之后、下一个事件处理之前**（即下一轮取出的开头），
    所以见到 build/pop 事件就把 pending_strip 立起来；pop 事件里刚取出的值 =
    收缩前那个"旧根"（用 waiting 携带）。
    """
    n = len(trace["input"])
    heap = list(trace["input"])
    extracted: list[int] = []
    pending_strip = False
    waiting: int | None = None
    checks: list[dict] = []

    def fail(info: dict, why: str) -> None:
        info["ok"] = False
        info["why"] = why

    for index, step in enumerate(trace["steps"]):
        info = {"index": index, "op": step["op"], "ok": True, "out": int(step["out"])}
        if pending_strip:                      # 补上上一轮取出/建堆收尾的未记录收缩
            waiting = heap[0]
            heap[0], heap[-1] = heap[-1], heap[0]
            heap.pop()
            pending_strip = False
        if step["op"] == "swap":
            a, b = int(step["a"]), int(step["b"])
            if not (0 <= a < len(heap) and 0 <= b < len(heap)):
                fail(info, f"swap 下标越界 {a},{b}（堆长 {len(heap)}）")
            else:
                heap[a], heap[b] = heap[b], heap[a]
            if int(step["out"]) != len(extracted):
                fail(info, "swap 步的 out 与已取出数不符")
        elif step["op"] == "pop":
            if int(step["out"]) != len(extracted) + 1:
                fail(info, "pop 步的 out 没有 +1")
            if step["state"][int(step["out"]) - 1] != waiting:
                fail(info, "取出的不是当时的堆顶")
            extracted.append(waiting)          # type: ignore[arg-type]
        elif step["op"] == "build":
            for i in range(1, len(heap)):
                if heap[i] < heap[(i - 1) // 2]:
                    fail(info, "build 后堆序不成立")
                    break
        else:
            fail(info, f"未知 op {step['op']!r}")
        if step["op"] in ("build", "pop"):     # 下一轮取出的收缩，从这里开始计数
            pending_strip = True

        combined = extracted + heap                 # 注意：取出的"在途帧"长度为 n-1（少一个尾巴）
        if combined != list(step["state"]):
            fail(info, "快照与回放不符")
        if not 0 <= len(combined) <= n:
            fail(info, f"回放长度异常 {len(combined)}")
        checks.append(info)
    return checks


def sort_final_state(trace: dict) -> list[int]:
    return list(trace["steps"][-1]["state"]) if trace["steps"] else list(trace["input"])


# ---------------------------------------------------------------- 图侧

def _adjacency(trace: dict) -> dict[int, list[int]]:
    adj: dict[int, list[int]] = {i: [] for i in range(trace["nodes"])}
    for u, v in trace["edges"]:
        adj[u].append(v)
        adj[v].append(u)
    return adj


def reference_bfs(trace: dict) -> list[dict]:
    """Python 版 BFS：产出与 C++ 侧**同一口径**的逐步记录（visit + 队列快照）。"""
    adj = _adjacency(trace)
    start = trace["from"]
    seen = {start}
    queue = deque([start])
    steps = []
    while queue:
        u = queue.popleft()
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                queue.append(v)
        steps.append({"op": "visit", "a": u, "state": list(queue)})
    return steps


def reference_dfs(trace: dict) -> list[dict]:
    """Python 版 DFS（显式栈 + 逆序压栈，与 B2 的迭代版同构）：visit + 栈快照。"""
    adj = _adjacency(trace)
    start = trace["from"]
    seen: set[int] = set()
    stack = [start]
    steps = []
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        for v in reversed(adj[u]):                            # 逆序压栈 → 弹出按邻接序
            if v not in seen:
                stack.append(v)
        steps.append({"op": "visit", "a": u, "state": list(stack)})
    return steps


def bfs_distances(trace: dict) -> dict[int, int]:
    """BFS 距离（独立算一遍，核对 trace 里的 b 字段）。"""
    adj = _adjacency(trace)
    start = trace["from"]
    dist = {start: 0}
    queue = deque([start])
    while queue:
        u = queue.popleft()
        for v in adj[u]:
            if v not in dist:
                dist[v] = dist[u] + 1
                queue.append(v)
    return dist
