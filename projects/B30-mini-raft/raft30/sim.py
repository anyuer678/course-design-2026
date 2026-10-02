"""raft30/sim.py —— 事件驱动的确定性 Raft 模拟（选举/复制/提交/分区/重启 + 快照/成员变更）

课程要点（Raft 论文的两条安全性约束是本实现的验收核心）：
    - Election Safety：一个任期至多一个 leader（投票只投给"日志不落后于自己"
      的候选人 + 每任期一人一票）。
    - Log Matching + Leader Completeness：同索引同任期的日志条目必然相同；
      leader 只提交**本任期**的条目（Raft §5.4.2），旧任期的条目随新任期条目
      被间接提交——不实现这条就会出现"已提交条目被覆盖"的经典事故。

B41 候选③ 的增量（口径先写死在 docs/snapshot-membership-spec.md，本文件只做翻译）：
    - **快照（日志压缩）**：节点持久字段带 snapshot（last_index/last_term/sm 副本/
      members/digest）；应用超过 SNAPSHOT_THRESHOLD 就压缩一次，日志只剩快照之后的段；
      日志访问一律走 entry_term()/first_log_index()/last_log_index() 抽象。
      **只压缩已提交条目**（压缩点取 last_applied）——快照永远不含未提交内容。
    - **InstallSnapshot**：leader 发现 next_index < first_log_index 就整发快照；
      follower 有"进度只许前进"的守卫（last_index <= last_applied 时不改状态）。
    - **成员变更（单步）**：配置就是一条普通日志条目 ("config", 排序元组)，提交后生效；
      决策用"日志里最新的配置"；一次一个（未提交 config 存在时拒绝再改）；
      发送集 = committed ∪ effective 的并集（可达性工程，安全口径不变）。
    - **已应用前缀比较**：压缩让旧条目不可见，改用**哈希链诊断账本**（digests）——
      任何索引处的值都是"条目 1..i 的折叠"，两节点在共同拥有的最大索引处比一个点即可。
      账本是检查器专用的诊断设施，不进快照、不参与恢复语义。

教学简化（README 有完整声明）：
    - 单进程事件驱动模拟（不是多进程真网络）：时间/延迟/分区全部由种子化事件堆驱动，
      因此**同一 seed 的轨迹逐次一致**，不变式可在每个事件后检查。
    - 日志与状态机视为持久（重启后保留）；快照安装全弃后缀（论文允许保留匹配后缀，简化在案）。
    - 不做 Joint Consensus / Pre-Vote；被移除节点的 disruption 按未修复形态如实登记。
"""
from __future__ import annotations

import hashlib
import heapq
import itertools
import random
from collections import defaultdict

TICK = 1                    # 全局心跳检查节拍
ELECTION_MIN, ELECTION_MAX = 15, 35
HEARTBEAT = 8
LATENCY_MAX = 3
SNAPSHOT_THRESHOLD = 8      # 已应用但未进快照的条目到多少条就压缩一次

GENESIS_DIGEST = hashlib.sha256(b"raft30/genesis").digest()


def fold_digest(prev: bytes, entry: dict) -> bytes:
    """哈希链：digest(i) = H(digest(i-1) ‖ term ‖ cmd)。确定性、与压缩无关。"""
    return hashlib.sha256(prev + repr((entry["term"], entry["cmd"])).encode("utf-8")).digest()


def majority(members) -> int:
    return len(members) // 2 + 1


def configs_have_disjoint_majorities(c1, c2) -> bool:
    """能否在两份配置里各选出一个互不相交的多数派？
    单步变更（差一个成员）的代数事实：不能。差两个及以上就可能。"""
    m1, m2 = majority(c1), majority(c2)
    return any(len(c2 - set(q1)) >= m2
               for q1 in itertools.combinations(sorted(c1), m1))


class Node:
    """一个 Raft 节点。持久状态：term/voted_for/log/sm/last_applied + 快照字段 + 诊断账本；
    易失状态：role/commit 的运行期字段/next_index/match_index。"""

    def __init__(self, node_id: int, base_members):
        self.id = node_id
        self.base_members = set(base_members)   # 自举配置（新节点为空，等教会）
        self.term = 0
        self.voted_for = None
        self.log: list[dict] = []               # 只装 index > snapshot_index 的条目
        self.snapshot_index = 0
        self.snapshot_term = 0
        self.snapshot_sm: dict[str, str] = {}   # 快照处的状态机副本
        self.snapshot_members: set[int] = set()  # 快照处的成员（空 = 尚未知）
        self.snapshot_digest = GENESIS_DIGEST
        self.commit_index = 0
        self.last_applied = 0
        self.sm: dict[str, str] = {}            # 状态机（教学键值存储）
        self.digests: dict[int, bytes] = {0: GENESIS_DIGEST}   # 诊断账本（见模块 docstring）
        self.role = "follower"
        self.leader_id = None
        self.votes: set[int] = set()
        self.next_index: dict[int, int] = {}
        self.match_index: dict[int, int] = {}
        self.alive_ts = 0                       # 上次"听到有效 leader/投出票"
        self.election_timeout = 0

    # ------------------------------------------------ 日志索引抽象（快照 + 相对段）
    def first_log_index(self) -> int:
        return self.snapshot_index + 1

    def last_log_index(self) -> int:
        return self.snapshot_index + len(self.log)

    def entry_term(self, index: int) -> int:
        if index == 0:
            return 0
        if index <= self.snapshot_index:
            return self.snapshot_term
        return self.log[index - self.snapshot_index - 1]["term"]

    def entry_cmd(self, index: int):
        if index <= self.snapshot_index:
            raise IndexError(f"index {index} 已被压缩进快照，没有命令可读")
        return self.log[index - self.snapshot_index - 1]["cmd"]

    def last_log_term(self) -> int:
        return self.entry_term(self.last_log_index())

    # ------------------------------------------------ 成员配置口径
    def _config_at(self, index: int):
        """index 处生效的配置：日志里 <= index 的最新 config；否则快照；否则自举。"""
        best = None
        for offset, entry in enumerate(self.log):
            entry_index = self.snapshot_index + offset + 1
            if entry_index > index:
                break
            if entry["cmd"][0] == "config":
                best = set(entry["cmd"][1])
        if best is not None:
            return best
        if self.snapshot_members:
            return set(self.snapshot_members)
        return set(self.base_members)

    def effective_members(self) -> set:
        """决策用配置：日志里最新的 config（**即使未提交**），否则快照/自举。"""
        for entry in reversed(self.log):
            if entry["cmd"][0] == "config":
                return set(entry["cmd"][1])
        if self.snapshot_members:
            return set(self.snapshot_members)
        return set(self.base_members)

    def committed_members(self) -> set:
        return self._config_at(self.commit_index)

    # ------------------------------------------------ 运行期小工具
    def digest_at(self, index: int):
        return self.digests.get(index)


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
    elif kind == "install_snapshot":
        sim.on_install_snapshot(node, msg)
    elif kind == "snapshot_resp":
        sim.on_snapshot_resp(node, msg)


def sim_tick(sim) -> None:
    """全局节拍（模块级函数：事件堆里存的是函数引用，必须能独立解析）。"""
    for node in sim.nodes.values():
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

    def __init__(self, n: int = 5, seed: int = 0, snapshot_threshold: int = SNAPSHOT_THRESHOLD):
        self.rng = random.Random(seed)
        self.now = 0
        self._seq = itertools.count()
        self.events: list = []
        self.net = Network(self)
        self.snapshot_threshold = snapshot_threshold
        self.nodes: dict[int, Node] = {i: Node(i, range(n)) for i in range(n)}
        self.leader_history: list[tuple[int, int]] = []
        self.timeline: list[str] = []
        self.config_history: dict[tuple[int, int], frozenset] = {}   # (index, term) -> 配置
        self.base_config = frozenset(range(n))                       # 自举配置（检查器的链首）
        self.compactions = 0
        self.snapshot_installs = 0
        for i in self.nodes:
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

    def _send_targets(self, node: Node) -> list[int]:
        """发送集 = committed ∪ effective 的并集（可达性工程；安全口径只看多数派）。
        并集让新增节点在配置提交前就开始追赶、被移除节点在提交前仍能学会自己被移除。"""
        targets = node.committed_members() | node.effective_members()
        targets.discard(node.id)
        return sorted(targets)

    # ------------------------------------------------ 选举
    def start_election(self, i: int) -> None:
        node = self.nodes[i]
        if node.id not in node.effective_members():
            return                                # 已学会"我不在配置里"：不搅动
        node.term += 1
        node.role = "candidate"
        node.voted_for = i
        node.votes = {i}
        node.leader_id = None
        self._reset_election_timer(i)
        self.timeline.append(f"t={self.now} 节点{i} 发起选举 (term={node.term})")
        for j in self._send_targets(node):
            self.net.send({"kind": "request_vote", "src": i, "dst": j,
                           "term": node.term,
                           "last_log_index": node.last_log_index(),
                           "last_log_term": node.last_log_term()})

    def on_request_vote(self, node: Node, msg: dict) -> None:
        if msg["term"] > node.term:
            node.term = msg["term"]
            node.role = "follower"
            node.voted_for = None
        grant = False
        if msg["term"] == node.term and node.voted_for in (None, msg["src"]):
            my_last = (node.last_log_index(), node.last_log_term())
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
        if msg["granted"] and msg["src"] in node.effective_members():
            node.votes.add(msg["src"])            # 非成员的票不数
            self._reset_election_timer(node.id)
            if len(node.votes) >= majority(node.effective_members()):
                self._become_leader(node)

    def _become_leader(self, node: Node) -> None:
        node.role = "leader"
        node.leader_id = node.id
        node.next_hb = self.now
        self.leader_history.append((node.term, node.id))
        self.timeline.append(f"t={self.now} 节点{node.id} 当选 leader "
                             f"(term={node.term})")
        for j in self._send_targets(node):
            node.next_index[j] = node.last_log_index() + 1
            node.match_index[j] = 0
        self.broadcast_append(node)
        node.next_hb = self.now + HEARTBEAT

    # ------------------------------------------------ 日志复制
    def broadcast_append(self, leader: Node) -> None:
        for j in self._send_targets(leader):
            self.send_append(leader, j)

    def send_append(self, leader: Node, j: int) -> None:
        ni = leader.next_index.get(j, leader.last_log_index() + 1)
        if ni < leader.first_log_index():
            self.send_snapshot(leader, j)         # follower 需要的段已被压缩
            return
        prev_index = ni - 1
        prev_term = leader.entry_term(prev_index)
        entries = leader.log[prev_index - leader.snapshot_index:]
        self.net.send({"kind": "append", "src": leader.id, "dst": j,
                       "term": leader.term, "prev_index": prev_index,
                       "prev_term": prev_term, "entries": entries,
                       "commit_index": leader.commit_index})

    def send_snapshot(self, leader: Node, j: int) -> None:
        self.net.send({"kind": "install_snapshot", "src": leader.id, "dst": j,
                       "term": leader.term,
                       "last_index": leader.snapshot_index,
                       "last_term": leader.snapshot_term,
                       "sm": dict(leader.snapshot_sm),
                       "members": sorted(leader.snapshot_members),
                       "digest": leader.snapshot_digest.hex(),
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
        prev_index = msg["prev_index"]
        if prev_index < node.snapshot_index:
            # 防御：leader 的段落后于我们的快照点（合法路径不该出现）——
            # 回成功并带上快照点，让 leader 从快照之后继续（进度只许前进）
            self.net.send({"kind": "append_resp", "src": node.id, "dst": msg["src"],
                           "term": node.term, "success": True,
                           "match": node.snapshot_index})
            return
        # 日志匹配检查：prev 处的任期必须一致
        prev_ok = (prev_index == 0 or
                   (prev_index <= node.last_log_index() and
                    node.entry_term(prev_index) == msg["prev_term"]))
        if not prev_ok:
            self.net.send({"kind": "append_resp", "src": node.id,
                           "dst": msg["src"], "term": node.term,
                           "success": False})
            return
        # 追加：按 1 起的日志下标逐条对齐；任一条目任期冲突则截断后缀。
        # （第一版在这里用了 0 基下标：prev=0 时 idx=0 走 log[-1] 负索引，
        #   空日志直接 IndexError——Raft 实现的经典翻车点。）
        for k, entry in enumerate(msg["entries"]):
            idx = prev_index + k + 1
            if idx <= node.last_log_index():
                if node.entry_term(idx) != entry["term"]:
                    node.log = node.log[:idx - node.snapshot_index - 1]
                    node.log.append(entry)
                # 相同条目已存在：幂等跳过
            else:
                node.log.append(entry)
        if msg["commit_index"] > node.commit_index:
            node.commit_index = min(msg["commit_index"], node.last_log_index())
            self._apply(node)
        self.net.send({"kind": "append_resp", "src": node.id, "dst": msg["src"],
                       "term": node.term, "success": True,
                       "match": node.last_log_index()})

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
            # 钳制：follower 的日志可能比 leader 长（多出一段未提交尾巴），
            # 它回执的 match 是"它的总长度"。不钳制会让 next_index 超过 leader 自己的
            # 日志长度，下一次 send_append 的 prev 查询直接越界——本实现实测抓到的缺陷。
            node.match_index[j] = min(msg["match"], node.last_log_index())
            node.next_index[j] = node.match_index[j] + 1
            self._advance_commit(node)
            if node.commit_index >= node.next_index[j]:
                self.send_append(node, j)        # 有新提交待传播
        else:
            node.next_index[j] = max(1, node.next_index.get(j, 1) - 1)
            self.send_append(node, j)            # 退避重试（简化：逐条回退；走到压缩段会改发快照）

    # ------------------------------------------------ 快照安装
    def on_install_snapshot(self, node: Node, msg: dict) -> None:
        if msg["term"] < node.term:
            self.net.send({"kind": "snapshot_resp", "src": node.id, "dst": msg["src"],
                           "term": node.term, "success": False,
                           "match": node.last_applied})
            return
        if msg["term"] > node.term:
            node.term = msg["term"]
            node.role = "follower"
            node.voted_for = None
        if msg["last_index"] <= node.last_applied:
            # 陈旧/不落后：进度只许前进，连角色与选举计时都不碰；
            # 回执带上我们的进度让 leader 续传（下一次会更新的快照或日志段）
            self.net.send({"kind": "snapshot_resp", "src": node.id, "dst": msg["src"],
                           "term": node.term, "success": True,
                           "match": node.last_applied})
            return
        node.role = "follower"
        node.leader_id = msg["src"]
        self._reset_election_timer(node.id)
        node.snapshot_index = msg["last_index"]
        node.snapshot_term = msg["last_term"]
        node.snapshot_sm = dict(msg["sm"])
        node.snapshot_members = set(msg["members"])
        node.snapshot_digest = bytes.fromhex(msg["digest"])
        node.sm = dict(msg["sm"])
        node.log = []                            # 简化：全弃后缀（论文允许保留匹配段，登记在案）
        node.commit_index = max(node.commit_index, msg["last_index"])
        node.last_applied = msg["last_index"]
        node.digests[msg["last_index"]] = node.snapshot_digest   # 账本补一个点，缺口跳过
        self.snapshot_installs += 1
        self.timeline.append(f"t={self.now} 节点{node.id} 安装快照 "
                             f"(index={msg['last_index']}, term={msg['last_term']})")
        self.net.send({"kind": "snapshot_resp", "src": node.id, "dst": msg["src"],
                       "term": node.term, "success": True,
                       "match": msg["last_index"]})

    def on_snapshot_resp(self, node: Node, msg: dict) -> None:
        if msg["term"] > node.term:
            node.term = msg["term"]
            node.role = "follower"
            node.voted_for = None
            self._reset_election_timer(node.id)
            return
        if node.role != "leader" or msg["term"] != node.term:
            return
        j = msg["src"]
        if msg["success"]:
            node.match_index[j] = max(node.match_index.get(j, 0), msg["match"])
            node.next_index[j] = node.match_index[j] + 1
            self._advance_commit(node)
            self.send_append(node, j)            # 快照之后的条目续传
        else:
            self.send_snapshot(node, j)          # 防御路径：重发

    # ------------------------------------------------ 提交与状态机
    def _advance_commit(self, leader: Node) -> None:
        """多数派（按 effective_members）复制且**条目属于当前任期**才推进
        commitIndex（§5.4.2）。一旦当前任期有条目提交，此前的旧任期条目被间接提交。"""
        members = leader.effective_members()
        replicas = sorted(
            [leader.last_log_index()] +
            [leader.match_index.get(j, 0) for j in members if j != leader.id],
            reverse=True)
        candidate = replicas[majority(members) - 1]
        if (candidate > leader.commit_index
                and leader.entry_term(candidate) == leader.term):
            leader.commit_index = candidate
            self._apply(leader)
            self.timeline.append(f"t={self.now} leader 节点{leader.id} "
                                 f"提交至 index={leader.commit_index}")

    def _apply(self, node: Node) -> None:
        while node.last_applied < node.commit_index:
            idx = node.last_applied + 1
            node.last_applied = idx
            entry = node.log[idx - node.snapshot_index - 1]
            node.digests[idx] = fold_digest(node.digests[idx - 1], entry)
            cmd = entry["cmd"]
            if cmd[0] == "set":
                node.sm[cmd[1]] = cmd[2]
            elif cmd[0] == "config":
                members = frozenset(cmd[1])
                self.config_history[(idx, entry["term"])] = members
                self.timeline.append(f"t={self.now} 节点{node.id} 应用配置 "
                                     f"{sorted(members)} (index={idx})")
                if node.role == "leader" and node.id not in members:
                    node.role = "follower"       # 自移除：立刻退位
                    node.leader_id = None
                    self.timeline.append(f"t={self.now} leader 节点{node.id} "
                                         f"按新配置自移除，退位")
            self._maybe_compact(node)

    def _maybe_compact(self, node: Node) -> None:
        """压缩点取 last_applied（≤ commit）：快照永远只含**已提交**内容。"""
        if node.last_applied - node.snapshot_index < self.snapshot_threshold:
            return
        members_at = node._config_at(node.last_applied)      # 都要在改基点之前读
        term_at = node.entry_term(node.last_applied)
        digest_at = node.digests[node.last_applied]
        keep_from = node.last_applied - node.snapshot_index  # 旧基点下的偏移
        node.snapshot_index = node.last_applied
        node.snapshot_term = term_at
        node.snapshot_sm = dict(node.sm)
        node.snapshot_members = members_at
        node.snapshot_digest = digest_at
        node.log = node.log[keep_from:]
        self.compactions += 1
        self.timeline.append(f"t={self.now} 节点{node.id} 压缩日志到 "
                             f"index={node.last_applied}")

    # ------------------------------------------------ 客户端与场景
    def leader_id(self) -> int | None:
        for node in self.nodes.values():
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
        node.match_index[node_id] = node.last_log_index()
        node.next_index[node_id] = node.last_log_index() + 1
        self.broadcast_append(node)
        self._advance_commit(node)
        return True

    # ------------------------------------------------ 成员变更（单步）
    def add_server(self) -> int:
        """新节点：空日志、空配置集（不知道集群）→ 不竞选，等被教会。"""
        new_id = max(self.nodes) + 1
        self.nodes[new_id] = Node(new_id, set())
        self._reset_election_timer(new_id)
        self.timeline.append(f"t={self.now} 新节点{new_id} 加入（空状态，待追赶）")
        return new_id

    def change_membership(self, add: int | None = None, remove: int | None = None) -> bool:
        """单步成员变更：恰好一个 add 或 remove；一次一个（有未提交 config 就拒绝）。"""
        if (add is None) == (remove is None):
            return False
        lid = self.leader_id()
        if lid is None:
            return False
        leader = self.nodes[lid]
        for offset, entry in enumerate(leader.log):
            idx = leader.snapshot_index + offset + 1
            if idx > leader.commit_index and entry["cmd"][0] == "config":
                return False                      # 一次一个
        members = leader.effective_members()
        target = add if add is not None else remove
        if add is not None and (target in members or target not in self.nodes):
            return False
        if remove is not None and target not in members:
            return False
        new_members = (members | {target}) if add is not None else (members - {target})
        leader.log.append({"term": leader.term,
                           "cmd": ("config", tuple(sorted(new_members)))})
        leader.match_index[leader.id] = leader.last_log_index()
        leader.next_index[leader.id] = leader.last_log_index() + 1
        self.timeline.append(f"t={self.now} leader 节点{leader.id} 发起配置变更 → "
                             f"{sorted(new_members)}")
        self.broadcast_append(leader)
        self._advance_commit(leader)
        return True

    def restart(self, node_id: int) -> None:
        """重启：持久状态（term/voted_for/log/sm/commit/applied + 快照字段 + 账本）
        保留，易失状态（role/votes/next_index/match_index）清零。"""
        old = self.nodes[node_id]
        fresh = Node(node_id, old.base_members)
        fresh.term = old.term
        fresh.voted_for = old.voted_for
        fresh.log = old.log
        fresh.snapshot_index = old.snapshot_index
        fresh.snapshot_term = old.snapshot_term
        fresh.snapshot_sm = old.snapshot_sm
        fresh.snapshot_members = old.snapshot_members
        fresh.snapshot_digest = old.snapshot_digest
        fresh.digests = old.digests
        fresh.sm = old.sm
        fresh.last_applied = old.last_applied
        fresh.commit_index = old.commit_index
        fresh.alive_ts = self.now
        fresh.election_timeout = self.rng.randint(ELECTION_MIN, ELECTION_MAX)
        self.nodes[node_id] = fresh
        self.timeline.append(f"t={self.now} 节点{node_id} 重启 "
                             f"(term={fresh.term}, 日志到 index={fresh.last_log_index()})")

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
        真正的安全性由两条守住：本方法（同任期 → 前缀一致）与
        `check_applied_consistency`（已应用前缀一致 → 已提交条目不会被改写）。

        快照版口径：只在**双方日志段都覆盖**的索引区间里比较（压缩掉的段没有条目可读；
        那部分历史由 `check_applied_consistency` 的哈希链账本兜底）。
        """
        nodes = list(self.nodes.values())
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                lo = max(a.snapshot_index, b.snapshot_index) + 1
                hi = min(a.last_log_index(), b.last_log_index())
                for idx in range(lo, hi + 1):
                    if a.entry_term(idx) != b.entry_term(idx):
                        continue                    # 任期不同 → 该位置允许不同（未提交才允许）
                    for k in range(lo, idx + 1):
                        if (a.entry_term(k) != b.entry_term(k)
                                or a.entry_cmd(k) != b.entry_cmd(k)):
                            raise AssertionError(
                                f"节点{a.id}/{b.id} 在 index {idx} 任期相同"
                                f"（{a.entry_term(idx)}）但前缀在 index {k} 分叉："
                                f"{a.entry_cmd(k)} vs {b.entry_cmd(k)}")

    def check_applied_consistency(self) -> None:
        """状态机安全（快照版）：两节点在**共同拥有的最大账本索引**（≤ 双方 applied）
        处比哈希链 digest。链值 = 条目 1..i 的折叠，所以任意更早的分叉都会改变该值——
        比一个点就够。账本缺口（快照安装跳过的索引）自动跳过，取下一个公共点。"""
        nodes = list(self.nodes.values())
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                common = [idx for idx in a.digests
                          if idx <= min(a.last_applied, b.last_applied) and idx in b.digests]
                assert common, f"节点{a.id}/{b.id} 没有公共账本点（索引 0 恒在，不该发生）"
                idx = max(common)
                assert a.digests[idx] == b.digests[idx], \
                    (f"节点{a.id}/{b.id} 的已应用前缀在 index {idx} 处分叉"
                     f"（哈希链 digest 不同）")

    def verify_node_replay(self, node: Node) -> None:
        """验收①：状态机必须等于"快照 + 日志重放"；账本链也要接得上。

        负面对照（测试里做）：故意改坏一条日志条目，这个校验器必须红。"""
        replay = dict(node.snapshot_sm)
        for offset, entry in enumerate(node.log):
            idx = node.snapshot_index + offset + 1
            if idx > node.last_applied:
                break
            if entry["cmd"][0] == "set":
                replay[entry["cmd"][1]] = entry["cmd"][2]
        assert replay == node.sm, \
            f"节点{node.id} 的状态机与'快照+日志重放'不一致"
        if node.last_applied in node.digests:
            chain = node.snapshot_digest
            for offset, entry in enumerate(node.log):
                idx = node.snapshot_index + offset + 1
                if idx > node.last_applied:
                    break
                chain = fold_digest(chain, entry)
            assert chain == node.digests[node.last_applied], \
                f"节点{node.id} 的账本链与重放不一致"

    def check_config_overlap(self) -> None:
        """单步成员变更的两条**可检查前提**：

        1. 相邻两份配置（含自举配置到第一次变更）只差一个成员——"一次一个"；
        2. 相邻两份的任意多数派必相交——单步变更的代数事实（|Δ|=1 → 必相交）。

        **全对全的"任意两份已提交配置的多数派都相交"是过强断言**：隔了几步的配置本来
        就不保证（本实现实测：churn seed=5 撞出 {0,1,2,3} 与 {0,1,3,4,6}——那是合法的
        链式演化，不是缺陷）。跨配置的安全性由每个事件的 applied-consistency（哈希链账本）
        与 election-safety 实测兜底；形式化的链式安全证明超出本项目范围
        （Joint Consensus 才是通用解，明确没做）。
        """
        ordered = [self.base_config] + [c for _, c in sorted(self.config_history.items())]
        for c1, c2 in zip(ordered, ordered[1:]):
            assert len(c1 ^ c2) == 1, \
                f"相邻配置 {sorted(c1)} → {sorted(c2)} 差多于一个成员（违反'一次一个'）"
            assert not configs_have_disjoint_majorities(c1, c2), \
                f"相邻配置 {sorted(c1)} 与 {sorted(c2)} 存在不相交的多数派"
