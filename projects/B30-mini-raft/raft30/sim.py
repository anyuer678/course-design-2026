"""raft30/sim.py —— 事件驱动的确定性 Raft 模拟（选举/复制/提交/分区/重启）

课程要点（Raft 论文的两条安全性约束是本实现的验收核心）：
    - Election Safety：一个任期至多一个 leader（投票只投给"日志不落后
      于自己"的候选人 + 每任期一人一票）。
    - Log Matching + Leader Completeness：同索引同任期的日志条目必然
      相同；leader 只提交**本任期**的条目（Raft §5.4.2），旧任期的
      条目随新任期条目被间接提交——不实现这条就会出现"已提交条目
      被覆盖"的经典事故。

教学简化（README 有完整声明）：
    - 单进程事件驱动模拟（不是多进程真网络）：时间/延迟/分区全部由
      种子化事件堆驱动，因此**同一 seed 的轨迹逐次一致**，不变式可在
      每个事件后检查——这是模拟器相对真系统的最大好处。
    - 日志与状态机视为持久（重启后保留）；真实系统靠快照+日志重放恢复。
    - 消息不压缩、无快照、无成员变更；命令只有 ("set", k, v)。
"""
from __future__ import annotations

import heapq
import itertools
import random
from collections import defaultdict

TICK = 1                    # 全局心跳检查节拍
ELECTION_MIN, ELECTION_MAX = 15, 35
HEARTBEAT = 8
LATENCY_MAX = 3


class Node:
    """一个 Raft 节点。持久状态：term/voted_for/log/sm/last_applied；
    易失状态：role/commit 的运行期字段/next_index/match_index。"""

    def __init__(self, node_id: int, n: int):
        self.id = node_id
        self.n = n
        self.term = 0
        self.voted_for = None
        self.log: list[dict] = []            # log[i] 是第 i+1 条（下标 1 起）
        self.commit_index = 0
        self.last_applied = 0
        self.sm: dict[str, str] = {}         # 状态机（教学键值存储）
        self.role = "follower"
        self.leader_id = None
        self.votes: set[int] = set()
        self.next_index: dict[int, int] = {}
        self.match_index: dict[int, int] = {}
        self.alive_ts = 0                    # 上次"听到有效 leader/投出票"
        self.election_timeout = 0

    def last_log_term(self) -> int:
        return self.log[-1]["term"] if self.log else 0

    def applied_prefix(self) -> tuple:
        """已应用条目的指纹（用于状态机一致性检查）。"""
        return tuple((e["term"], tuple(e["cmd"]))
                     for e in self.log[:self.last_applied])


class Network:
    """模拟网络：投递延迟 + 分区丢弃。分区 = 节点到组号的映射。"""

    def __init__(self, sim):
        self.sim = sim
        self.groups: dict[int, int] = {}
        self.dropped = 0

    def set_partition(self, groups: dict[int, int] | None) -> None:
        self.groups = dict(groups) if groups else {}

    def partitioned(self, a: int, b: int) -> bool:
        if not self.groups:
            return False
        ga = self.groups.get(a, 0)
        gb = self.groups.get(b, 0)
        return ga != gb

    def send(self, msg: dict) -> None:
        if self.partitioned(msg["src"], msg["dst"]):
            self.dropped += 1
            return                            # 分区：静默丢弃（接收方无感知）
        self.sim.schedule(self.sim.rng.randint(0, LATENCY_MAX),
                          sim_deliver, msg)


def sim_deliver(sim, msg: dict) -> None:
    node = sim.nodes[msg["dst"]]
    kind = msg["kind"]
    if kind == "request_vote":
        sim.on_request_vote(node, msg)
    elif kind == "vote_resp":
        sim.on_vote_resp(node, msg)
    elif kind == "append":
        sim.on_append(node, msg)
    elif kind == "append_resp":
        sim.on_append_resp(node, msg)


def sim_tick(sim) -> None:
    """全局节拍（模块级函数：事件堆里存的是函数引用，必须能独立解析）。"""
    for node in sim.nodes:
        if node.role == "leader":
            if sim.now >= getattr(node, "next_hb", 0):
                sim.broadcast_append(node)
                node.next_hb = sim.now + HEARTBEAT
        else:
            if sim.now - node.alive_ts > node.election_timeout:
                sim.start_election(node.id)
    sim.schedule(TICK, sim_tick)


class Simulation:
    """事件驱动 Raft 模拟。tick(1) 一次驱动选举超时与心跳；消息按随机
    延迟投递。同一 seed 的事件序列与结果逐次一致（确定性核心）。"""

    def __init__(self, n: int = 5, seed: int = 0):
        self.n = n
        self.rng = random.Random(seed)
        self.now = 0
        self._seq = itertools.count()
        self.events: list = []
        self.net = Network(self)
        self.nodes = [Node(i, n) for i in range(n)]
        self.leader_history: list[tuple[int, int]] = []
        self.timeline: list[str] = []
        self.client_msgs: list[dict] = []
        for i in range(n):
            self._reset_election_timer(i)
        self.schedule(TICK, sim_tick)

    # ------------------------------------------------ 事件堆
    def schedule(self, delay: int, fn, *args) -> None:
        heapq.heappush(self.events, (self.now + delay, next(self._seq),
                                     fn, args))

    def run_until(self, deadline: int) -> None:
        while self.events and self.events[0][0] <= deadline:
            now, _, fn, args = heapq.heappop(self.events)
            self.now = now
            fn(self, *args)

    def advance(self, ticks: int) -> None:
        self.run_until(self.now + ticks)

    # ------------------------------------------------ 驱动
    def _reset_election_timer(self, i: int) -> None:
        node = self.nodes[i]
        node.alive_ts = self.now
        node.election_timeout = self.rng.randint(ELECTION_MIN, ELECTION_MAX)

    # ------------------------------------------------ 选举
    def start_election(self, i: int) -> None:
        node = self.nodes[i]
        node.term += 1
        node.role = "candidate"
        node.voted_for = i
        node.votes = {i}
        node.leader_id = None
        self._reset_election_timer(i)
        self.timeline.append(f"t={self.now} 节点{i} 发起选举 (term={node.term})")
        for j in range(self.n):
            if j == i:
                continue
            self.net.send({"kind": "request_vote", "src": i, "dst": j,
                           "term": node.term,
                           "last_log_index": len(node.log),
                           "last_log_term": node.last_log_term()})

    def on_request_vote(self, node: Node, msg: dict) -> None:
        if msg["term"] > node.term:
            node.term = msg["term"]
            node.role = "follower"
            node.voted_for = None
        grant = False
        if msg["term"] == node.term and node.voted_for in (None, msg["src"]):
            my_last = (len(node.log), node.last_log_term())
            cand_last = (msg["last_log_index"], msg["last_log_term"])
            if cand_last >= my_last:              # 日志至少不落后才给票
                grant = True
                node.voted_for = msg["src"]
                self._reset_election_timer(node.id)
        self.net.send({"kind": "vote_resp", "src": node.id, "dst": msg["src"],
                       "term": node.term, "granted": grant})

    def on_vote_resp(self, node: Node, msg: dict) -> None:
        if msg["term"] > node.term:
            node.term = msg["term"]
            node.role = "follower"
            node.voted_for = None
            self._reset_election_timer(node.id)
            return
        if node.role != "candidate" or msg["term"] != node.term:
            return
        if msg["granted"]:
            node.votes.add(msg["src"])
            self._reset_election_timer(node.id)
            if len(node.votes) > node.n // 2:
                self._become_leader(node)

    def _become_leader(self, node: Node) -> None:
        node.role = "leader"
        node.leader_id = node.id
        node.next_hb = self.now
        self.leader_history.append((node.term, node.id))
        self.timeline.append(f"t={self.now} 节点{node.id} 当选 leader "
                             f"(term={node.term})")
        for j in range(node.n):
            if j != node.id:
                node.next_index[j] = len(node.log) + 1
                node.match_index[j] = 0
        self.broadcast_append(node)
        node.next_hb = self.now + HEARTBEAT

    # ------------------------------------------------ 日志复制
    def broadcast_append(self, leader: Node) -> None:
        for j in range(leader.n):
            if j != leader.id:
                self.send_append(leader, j)

    def send_append(self, leader: Node, j: int) -> None:
        ni = leader.next_index.get(j, len(leader.log) + 1)
        prev_index = ni - 1
        prev_term = leader.log[prev_index - 1]["term"] if prev_index >= 1 else 0
        entries = leader.log[ni - 1:]
        self.net.send({"kind": "append", "src": leader.id, "dst": j,
                       "term": leader.term, "prev_index": prev_index,
                       "prev_term": prev_term, "entries": entries,
                       "commit_index": leader.commit_index})

    def on_append(self, node: Node, msg: dict) -> None:
        if msg["term"] > node.term:
            node.term = msg["term"]
            node.role = "follower"
            node.voted_for = None
        if msg["term"] < node.term:
            self.net.send({"kind": "append_resp", "src": node.id,
                           "dst": msg["src"], "term": node.term,
                           "success": False})
            return
        # 合法 leader 的心跳/复制：确认 leader，重置选举计时
        node.role = "follower"
        node.leader_id = msg["src"]
        self._reset_election_timer(node.id)
        self.timeline.append(f"t={self.now} 节点{node.id} 承认 leader "
                             f"节点{msg['src']} (term={msg['term']})")
        # 日志匹配检查：prev 处的任期必须一致
        prev_ok = (msg["prev_index"] == 0 or
                   (len(node.log) >= msg["prev_index"] and
                    node.log[msg["prev_index"] - 1]["term"] == msg["prev_term"]))
        if not prev_ok:
            self.net.send({"kind": "append_resp", "src": node.id,
                           "dst": msg["src"], "term": node.term,
                           "success": False})
            return
        # 追加：按 1 起的日志下标逐条对齐；任一条目任期冲突则截断后缀。
        # （第一版在这里用了 0 基下标：prev=0 时 idx=0 走 log[-1] 负索引，
        #   空日志直接 IndexError——Raft 实现的经典翻车点。）
        for k, entry in enumerate(msg["entries"]):
            idx = msg["prev_index"] + k + 1
            if idx <= len(node.log):
                if node.log[idx - 1]["term"] != entry["term"]:
                    del node.log[idx - 1:]
                    node.log.append(entry)
                # 相同条目已存在：幂等跳过
            else:
                node.log.append(entry)
        if msg["commit_index"] > node.commit_index:
            node.commit_index = min(msg["commit_index"], len(node.log))
            self._apply(node)
        self.net.send({"kind": "append_resp", "src": node.id, "dst": msg["src"],
                       "term": node.term, "success": True,
                       "match": len(node.log)})

    def on_append_resp(self, node: Node, msg: dict) -> None:
        if msg["term"] > node.term:              # 落后于对方：退位
            node.term = msg["term"]
            node.role = "follower"
            node.voted_for = None
            self._reset_election_timer(node.id)
            return
        if node.role != "leader" or msg["term"] != node.term:
            return
        j = msg["src"]
        if msg["success"]:
            node.match_index[j] = msg["match"]
            node.next_index[j] = msg["match"] + 1
            self._advance_commit(node)
            if node.commit_index >= node.next_index[j]:
                self.send_append(node, j)        # 有新提交待传播
        else:
            node.next_index[j] = max(1, node.next_index.get(j, 1) - 1)
            self.send_append(node, j)            # 退避重试（简化：逐条回退）

    # ------------------------------------------------ 提交与状态机
    def _advance_commit(self, leader: Node) -> None:
        """多数派复制且**条目属于当前任期**才推进 commitIndex（§5.4.2）。
        一旦当前任期有条目提交，此前的旧任期条目被间接提交。"""
        replicas = [len(leader.log)] + sorted(
            (m for j, m in leader.match_index.items() if j != leader.id),
            reverse=True)
        candidate = replicas[leader.n // 2]
        if (candidate > leader.commit_index
                and leader.log[candidate - 1]["term"] == leader.term):
            leader.commit_index = candidate
            self._apply(leader)
            self.timeline.append(f"t={self.now} leader 节点{leader.id} "
                                 f"提交至 index={leader.commit_index}")

    def _apply(self, node: Node) -> None:
        while node.last_applied < node.commit_index:
            node.last_applied += 1
            cmd = node.log[node.last_applied - 1]["cmd"]
            if cmd[0] == "set":
                node.sm[cmd[1]] = cmd[2]

    # ------------------------------------------------ 客户端与场景
    def leader_id(self) -> int | None:
        for node in self.nodes:
            if node.role == "leader":
                return node.id
        return None

    def submit(self, key: str, value: str) -> bool:
        """向当前 leader 提交命令；无 leader 或 leader 被分区隔离则失败。"""
        lid = self.leader_id()
        if lid is None:
            return False
        return self.submit_to(lid, key, value)

    def submit_to(self, node_id: int, key: str, value: str) -> bool:
        node = self.nodes[node_id]
        if node.role != "leader":
            return False
        node.log.append({"term": node.term, "cmd": ("set", key, value)})
        node.match_index[node_id] = len(node.log)
        node.next_index[node_id] = len(node.log) + 1
        self.broadcast_append(node)
        self._advance_commit(node)
        return True

    def restart(self, node_id: int) -> None:
        """重启：持久状态（term/voted_for/log/sm/last_applied/commit_index）
        保留，易失状态（role/votes/next_index/match_index）清零。"""
        old = self.nodes[node_id]
        fresh = Node(node_id, self.n)
        fresh.term = old.term
        fresh.voted_for = old.voted_for
        fresh.log = old.log
        fresh.sm = old.sm
        fresh.last_applied = old.last_applied
        fresh.commit_index = old.commit_index
        fresh.alive_ts = self.now
        fresh.election_timeout = self.rng.randint(ELECTION_MIN, ELECTION_MAX)
        self.nodes[node_id] = fresh
        self.timeline.append(f"t={self.now} 节点{node_id} 重启 "
                             f"(term={fresh.term}, 日志 {len(fresh.log)} 条)")

    def partition(self, groups: dict[int, int]) -> None:
        self.net.set_partition(groups)
        self.timeline.append(f"t={self.now} 网络分区: {groups}")

    def heal(self) -> None:
        self.net.set_partition(None)
        self.timeline.append(f"t={self.now} 网络愈合")

    # ------------------------------------------------ 不变式
    def check_election_safety(self) -> None:
        per_term: dict[int, set[int]] = defaultdict(set)
        for term, node_id in self.leader_history:
            per_term[term].add(node_id)
        for term, ids in per_term.items():
            assert len(ids) <= 1, f"term {term} 出现多个 leader: {ids}"

    def check_log_matching(self) -> None:
        """Log Matching 的**论文原话**：两节点若在某个 index 上的条目任期相同，
        则两节点日志在该 index 及其之前逐条相同。

        第一版这里写成了"任意两节点日志的公共前缀必须逐条相同"——那是**过强的断言**，
        把合法中间态当成违规：新 leader 刚选出（本任期还没有任何已提交条目）时，
        follower 在 index 1 上可能还留着**上一任期的未提交条目**，与 leader 的条目任期不同，
        要等下一条 AppendEntries 去覆盖它。2026-10-02 demo 第 5 段在 seed=5 撞出来：
        当时 `分区表={}`、`commit=0`，两节点 index 1 分别是 term 1 与 term 2 ——合法，不是 bug。
        真正的安全性由两条守住：本方法（同任期 ⇒ 前缀一致）与
        `check_applied_consistency`（已应用前缀一致 ⇒ 已提交条目不会被改写）。
        """
        nodes = self.nodes
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a_log, b_log = nodes[i].log, nodes[j].log
                for idx in range(min(len(a_log), len(b_log))):
                    if a_log[idx]["term"] != b_log[idx]["term"]:
                        continue                    # 任期不同 ⇒ 该位置允许不同（未提交才允许）
                    for k in range(idx + 1):
                        a, b = a_log[k], b_log[k]
                        assert a["term"] == b["term"] and a["cmd"] == b["cmd"], \
                            (f"节点{i}/{j} 在 index {idx + 1} 任期相同（{a_log[idx]['term']}）"
                             f"但前缀在 index {k + 1} 分叉：{a} vs {b}")

    def check_applied_consistency(self) -> None:
        """状态机安全（论文版）：任意两节点**已应用前缀**逐条相同——
        注意不是"当前值一致"：follower 落后几个提交是正常的，
        比较当前值会把正常的复制延迟误判成分歧。"""
        prefixes = [node.applied_prefix() for node in self.nodes]
        for i in range(len(prefixes)):
            for j in range(i + 1, len(prefixes)):
                common = min(len(prefixes[i]), len(prefixes[j]))
                assert prefixes[i][:common] == prefixes[j][:common], \
                    f"节点{i}/{j} 的已应用前缀在 index {common + 1} 附近分叉"
