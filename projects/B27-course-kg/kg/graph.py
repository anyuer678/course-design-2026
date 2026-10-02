"""kg/graph.py —— 有向图 + 先修闭包 + 缺先修检测 + 拓扑排序

课程要点（知识图谱与知识工程）：
    - 三元组 (头实体, 关系, 尾实体) 是知识图谱的最小表达——本项目里即
      (B_prev, 先修/概念支撑/迭代阶段, B_next)，数据在 data/*.csv，
      代码只负责加载与计算，不硬编码任何一条边。
    - 图算法落在"先修闭包"上：直接先修 vs 间接先修（传递闭包），
      "学过 A 之后解锁什么"是闭包的反向查询。
    - 缺先修检测 = 用图回答业务问题："想做 B18，以我已完成的集合，
      还缺哪些（含间接）先修？"——这是知识图谱相对散装表格的核心价值。

约定：边方向 src -> dst 表示 "src 是 dst 的先修"。
"""
from __future__ import annotations

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class KnowledgeGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}          # id -> {batch, courses}
        self.edges: list[dict] = []               # [{src, dst, kind, source}]
        self._succ: dict[str, set[str]] = {}      # 后继（解锁）
        self._pred: dict[str, set[str]] = {}      # 前驱（直接先修）

    # ------------------------------------------------ 加载
    def load(self, courses_csv: Path, prereqs_csv: Path) -> "KnowledgeGraph":
        with open(courses_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.add_task(row["task_id"], int(row["batch"]),
                              row["courses"])
        with open(prereqs_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.add_edge(row["src_id"], row["dst_id"], row["kind"],
                              row["source"])
        return self

    def add_task(self, task_id: str, batch: int, courses: str) -> None:
        if task_id in self.nodes:
            raise ValueError(f"任务重复: {task_id}")
        self.nodes[task_id] = {"batch": batch, "courses": courses}
        self._succ.setdefault(task_id, set())
        self._pred.setdefault(task_id, set())

    def add_edge(self, src: str, dst: str, kind: str, source: str = "") -> None:
        for node in (src, dst):
            if node not in self.nodes:
                raise ValueError(f"边引用了不存在的任务: {node}")
        self.edges.append({"src": src, "dst": dst, "kind": kind,
                           "source": source})
        self._succ[src].add(dst)
        self._pred[dst].add(src)

    # ------------------------------------------------ 直接关系
    def direct_prereqs(self, task_id: str) -> set[str]:
        return set(self._pred[task_id])

    def unlocks(self, task_id: str) -> set[str]:
        """学完 task_id 直接触及的后继任务。"""
        return set(self._succ[task_id])

    # ------------------------------------------------ 传递闭包
    def ancestors(self, task_id: str) -> set[str]:
        """全部（含间接）先修——沿前驱 BFS。"""
        seen: set[str] = set()
        frontier = [task_id]
        while frontier:
            cur = frontier.pop()
            for p in self._pred[cur]:
                if p not in seen:
                    seen.add(p)
                    frontier.append(p)
        return seen

    def descendants(self, task_id: str) -> set[str]:
        seen: set[str] = set()
        frontier = [task_id]
        while frontier:
            cur = frontier.pop()
            for s in self._succ[cur]:
                if s not in seen:
                    seen.add(s)
                    frontier.append(s)
        return seen

    # ------------------------------------------------ 业务查询
    def missing_prereqs(self, task_id: str, completed: set[str]) -> set[str]:
        """做 task_id 还缺哪些先修（含间接）。task_id 本身不计入。"""
        return self.ancestors(task_id) - completed

    def ready_tasks(self, completed: set[str]) -> list[str]:
        """已完成任务集合下，此刻"可以先做"的任务（先修全满足，且未完成）。
        只统计有先修边或被先修边指向的任务——独立任务（如 B4）不参与。"""
        out = []
        involved = {e["src"] for e in self.edges} | {e["dst"] for e in self.edges}
        for task_id in sorted(involved):
            if task_id in completed:
                continue
            if self.ancestors(task_id) <= completed:
                out.append(task_id)
        return out

    def learning_path(self, task_id: str) -> list[str]:
        """通往 task_id 的学习路径：其先修闭包子图的拓扑序（含 task_id）。"""
        sub = self.ancestors(task_id) | {task_id}
        indeg = {t: 0 for t in sub}
        for e in self.edges:
            if e["src"] in sub and e["dst"] in sub:
                indeg[e["dst"]] += 1
        # Kahn：入度 0 的按批次与编号排序，保证确定性与"尽早学基础"
        ready = sorted([t for t in sub if indeg[t] == 0],
                       key=lambda t: (self.nodes[t]["batch"], t))
        order = []
        while ready:
            cur = ready.pop(0)
            order.append(cur)
            for e in self.edges:
                if e["src"] == cur and e["dst"] in sub:
                    indeg[e["dst"]] -= 1
                    if indeg[e["dst"]] == 0:
                        ready.append(e["dst"])
            ready.sort(key=lambda t: (self.nodes[t]["batch"], t))
        if len(order) != len(sub):
            raise ValueError("图中存在环，无法给出学习路径")
        return order

    # ------------------------------------------------ 拓扑与校验
    def topological_order(self) -> list[str]:
        """全图拓扑序（Kahn）；有环抛异常。"""
        indeg = {t: 0 for t in self.nodes}
        for e in self.edges:
            indeg[e["dst"]] += 1
        ready = sorted([t for t in self.nodes if indeg[t] == 0],
                       key=lambda t: (self.nodes[t]["batch"], t))
        order = []
        while ready:
            cur = ready.pop(0)
            order.append(cur)
            for e in self.edges:
                if e["src"] == cur:
                    indeg[e["dst"]] -= 1
                    if indeg[e["dst"]] == 0:
                        ready.append(e["dst"])
            ready.sort(key=lambda t: (self.nodes[t]["batch"], t))
        if len(order) != len(self.nodes):
            raise ValueError("图中存在环")
        return order

    def validate(self) -> None:
        """图的结构校验：边端点存在（add_edge 已查）、无环、任务数完整。"""
        self.topological_order()                      # 有环即抛
        if len(self.nodes) != 41:
            raise ValueError(f"任务数应为 41，实际 {len(self.nodes)}")


def load_default() -> KnowledgeGraph:
    """加载仓库自带的两份 CSV（41 任务 + PLAN§3 依赖边）。"""
    return KnowledgeGraph().load(DATA_DIR / "courses.csv",
                                 DATA_DIR / "prereqs.csv")
