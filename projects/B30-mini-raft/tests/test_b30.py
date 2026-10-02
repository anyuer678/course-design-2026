"""B30-mini-raft 自测。

"期望值必须有出处"的落法：
    1. Raft 安全不变式 <-- 论文定义（Election Safety / Log Matching /
       State Machine Safety），在种子化随机事件流中**每个事件后**检查
    2. §5.4.2 场景 <-- 手工构造"旧 leader 隔离期写入的未提交条目，
       愈合后被覆盖"——期望值是 Raft 论文的标准结论
    3. 一致性哈希 <-- 搬移比例的理论值（朴素 ~4/5 vs 一致性 ~1/n）
    4. RPC <-- 真套接字回声 + 坏帧跳过约定
    5. 快照/成员变更（B41 候选③）<-- docs/snapshot-membership-spec.md 的口径：
       快照只含已提交、进度只许前进、一次一个变更、单步配置的多数派交叠
"""
import random
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from raft30.hashing import ConsistentHash, NaiveShard, moved_fraction
from raft30.rpc import FrameDecoder, RpcClient, RpcServer, encode_msg
from raft30.sim import Simulation, configs_have_disjoint_majorities


def wait_leader(sim, max_ticks=400):
    sim.advance(max_ticks)
    return sim.leader_id()


def drive_until_leader(sim, limit=600):
    """逐拍推进直到选出 leader（模拟旧场景的 while 版；返回 id 或 None）。"""
    while sim.now < limit:
        sim.advance(1)
        leader = sim.leader_id()
        if leader is not None:
            return leader
    return None


# ---------------------------------------------------------------- 哈希
class TestHashing(unittest.TestCase):
    def keys(self, n=2000):
        return [f"key:{i}" for i in range(n)]

    def test_determinism(self):
        ks = self.keys()
        ch = ConsistentHash(["n1", "n2", "n3"], vnodes=50)
        self.assertEqual([ch.shard(k) for k in ks],
                         [ch.shard(k) for k in ks])

    def test_consistent_hash_moves_minimally(self):
        """4 -> 5 节点扩容：理想搬移比例 = 1/(n+1) = 0.2（新节点接管环上
        1/5 区段）；朴素取模理论上只留 1/5 不动（搬 4/5）。"""
        keys = self.keys()
        cons_old = ConsistentHash(["n1", "n2", "n3", "n4"], vnodes=100)
        cons_new = ConsistentHash(["n1", "n2", "n3", "n4", "n5"], vnodes=100)
        moved_cons = moved_fraction(cons_old, cons_new, keys)
        naive_old, naive_new = NaiveShard(4), NaiveShard(5)
        moved_naive = moved_fraction(naive_old, naive_new, keys)
        self.assertLess(moved_cons, 0.25)       # 理想 0.2，虚拟节点有波动
        self.assertGreater(moved_naive, 0.7)    # 理想 0.8
        print(f"      扩容 4->5：一致性搬移 {moved_cons:.1%}（理想 20%），"
              f"朴素取模搬移 {moved_naive:.1%}（理想 80%）")

    def test_removal_only_moves_removed_node_keys(self):
        keys = self.keys()
        ch = ConsistentHash(["n1", "n2", "n3"], vnodes=100)
        before = {k: ch.shard(k) for k in keys}
        ch.remove("n2")
        after = {k: ch.shard(k) for k in keys}
        for k in keys:
            if before[k] != "n2":
                self.assertEqual(before[k], after[k], msg=k)

    def test_balance_with_vnodes(self):
        keys = self.keys(5000)
        ch = ConsistentHash([f"n{i}" for i in range(5)], vnodes=200)
        counts: dict = {}
        for k in keys:
            s = ch.shard(k)
            counts[s] = counts.get(s, 0) + 1
        expected = 5000 / 5
        for node, cnt in counts.items():
            self.assertTrue(0.7 * expected <= cnt <= 1.3 * expected,
                            msg=f"{node} 承载 {cnt}")


# ---------------------------------------------------------------- RPC
class TestRpc(unittest.TestCase):
    def test_frame_decoder(self):
        d = FrameDecoder()
        self.assertEqual(d.feed(encode_msg({"id": 1, "body": {"a": 1}})),
                         [{"id": 1, "body": {"a": 1}}])
        # 半包：先给一半再给另一半
        full = encode_msg({"id": 2, "body": {}})
        d.feed(full[:5])
        self.assertEqual(d.feed(full[5:]), [{"id": 2, "body": {}}])
        # 粘包：两条一次到
        self.assertEqual(len(d.feed(full + full)), 2)
        # 坏帧跳过
        self.assertEqual(d.feed(b"not-json\n" + full), [{"id": 2, "body": {}}])

    def test_echo_over_real_socket(self):
        server = RpcServer("127.0.0.1", 0,
                           handler=lambda body: {"echo": body, "len": len(body)})
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        client = RpcClient("127.0.0.1", server.port)
        resp = client.call({"msg": "hello"})
        self.assertEqual(resp["echo"], {"msg": "hello"})
        self.assertEqual(resp["len"], 1)        # handler 定义 len(body)=键数
        client.close()
        server.stop()


# ---------------------------------------------------------------- Raft 基础
class TestRaftBasics(unittest.TestCase):
    def test_elects_single_leader(self):
        sim = Simulation(n=5, seed=1)
        lid = wait_leader(sim)
        self.assertIsNotNone(lid)
        leaders = [n for n in sim.nodes.values() if n.role == "leader"]
        self.assertEqual(len(leaders), 1)

    def test_replication_reaches_all(self):
        sim = Simulation(n=5, seed=2)
        wait_leader(sim)
        for i in range(1, 6):
            self.assertTrue(sim.submit(f"k{i}", f"v{i}"))
        sim.advance(60)
        for node in sim.nodes.values():
            self.assertEqual(node.sm,
                             {f"k{i}": f"v{i}" for i in range(1, 6)})

    def test_invariants_hold_after_random_events(self):
        """随机事件流（提交/分区/愈合/重启）中，论文安全性在每个事件后成立。"""
        for seed in range(10):
            sim = Simulation(n=5, seed=seed)
            rng = __import__("random").Random(seed)
            sim.advance(100)                       # 先选出 leader
            for step in range(60):
                choice = rng.random()
                if choice < 0.35:
                    key = f"k{rng.randint(0, 5)}"
                    sim.submit(key, f"v{step}")
                elif choice < 0.7:
                    sim.advance(rng.randint(5, 20))
                elif choice < 0.8:
                    groups = {i: i % 2 for i in range(5)}
                    if rng.random() < 0.5:
                        groups = {i: 0 for i in range(5)}
                    sim.partition(groups)
                elif choice < 0.9:
                    sim.heal()
                else:
                    sim.restart(rng.randrange(5))
                sim.check_election_safety()
                sim.check_log_matching()
                sim.check_applied_consistency()
            sim.heal()
            sim.advance(300)
            sim.check_election_safety()
            sim.check_log_matching()
            sim.check_applied_consistency()


# ---------------------------------------------------------------- 分区实验
class TestPartitionScenarios(unittest.TestCase):
    def test_majority_side_keeps_serving(self):
        """leader 在多数派一侧：提交照常工作。"""
        for seed in range(20):
            sim = Simulation(n=5, seed=seed)
            lid = wait_leader(sim)
            if lid is None:
                continue
            majority = {0, 1, 2}
            if lid in majority:
                sim.partition({i: (0 if i in majority else 1)
                               for i in range(5)})
                sim.advance(50)
                ok = sim.submit("k", "v")          # leader 在多数派
                sim.advance(80)
                if ok:
                    committed = [n.sm.get("k") for n in sim.nodes.values()
                                 if n.commit_index >= 1]
                    check_values = {v for v in committed if v is not None}
                    self.assertLessEqual(len(check_values), 1)
                    break                          # 一个成功场景就够

    def test_minority_old_leader_entries_get_overwritten(self):
        """Raft §5.4.2 经典场景（论文标准结论，也是本实现的核心考点）：
        1) 旧 leader 被隔离在少数派，隔离期收到的未提交条目 "c"；
        2) 多数派选出新高任期 leader 并提交新条目；
        3) 愈合后旧 leader 的未提交条目被覆盖——**任何节点都不应用 "c"**。"""
        for seed in range(50):
            sim = Simulation(n=5, seed=seed)
            lid = wait_leader(sim)
            if lid is None:
                continue
            # 构造：旧 leader 单独成组（少数派）
            sim.partition({i: (0 if i == lid else 1) for i in range(5)})
            sim.advance(150)                       # 多数派选出新 leader
            new_leader = sim.leader_id()
            if new_leader is None or new_leader == lid:
                continue
            old_term = sim.nodes[lid].term
            new_term = sim.nodes[new_leader].term
            if new_term <= old_term:
                continue
            # 旧 leader 隔离期"自说自话"收到的条目（未提交）
            self.assertTrue(sim.submit_to(lid, "ghost", "c"))
            # 多数派一侧正常提交
            self.assertTrue(sim.submit_to(new_leader, "real", "r"))
            sim.heal()
            sim.advance(400)
            # 断言：ghost 从未出现在任何节点的状态机里；real 全员一致
            for node in sim.nodes.values():
                self.assertNotIn("ghost", node.sm)
            values = {n.sm.get("real") for n in sim.nodes.values()}
            self.assertEqual(values, {"r"})
            # 日志匹配： healing 后所有节点的日志公共前缀逐条一致
            sim.check_log_matching()
            return                                  # 一个走通的场景即通过
        self.fail("50 个 seed 里没构造出 §5.4.2 场景（应调参重试）")

    def test_restart_preserves_committed_state(self):
        """重启：已提交条目保留（日志/状态机持久），重新选出 leader 后继续服务。"""
        sim = Simulation(n=5, seed=9)
        lid = wait_leader(sim)
        for i in range(3):
            self.assertTrue(sim.submit(f"k{i}", f"v{i}"))
        sim.advance(60)
        committed_before = dict(sim.nodes[0].sm)
        sim.restart(lid)
        sim.advance(200)
        new_lid = wait_leader(sim)
        self.assertIsNotNone(new_lid)
        self.assertTrue(sim.submit("k3", "v3"))
        sim.advance(100)
        for node in sim.nodes.values():
            for k, v in committed_before.items():
                self.assertEqual(node.sm.get(k), v)
        self.assertEqual(sim.nodes[0].sm.get("k3"), "v3")


# ---------------------------------------------------------------- 不变式的两侧边界
class TestLogMatchingIsNotOverStrong(unittest.TestCase):
    """不变式写强了会把**合法中间态**判成 bug，写松了会把真分叉放过——两侧都要钉住。

    出处：2026-10-02 demo 第 5 段在 seed=5 撞出的现场。当时 `分区表={}`、两节点 `commit=0`、
    index 1 分别是 term 1 与 term 2：新 leader 还没用自己的条目覆盖 follower 那条**未提交**的
    旧任期条目。按论文原话（同 index 同任期 → 该处及之前逐条相同）这是合法的中间态，
    而第一版 `check_log_matching` 写的是"公共前缀逐条相同"，于是把正确实现判成了 bug。
    """

    def soak(self, seed: int, steps: int = 60) -> None:
        """和 demo 第 5 段同一套事件脚本：提交/推进/分区/愈合/重启，每个事件后查三条不变式。"""
        import random as _random
        sim = Simulation(n=5, seed=seed)
        rng = _random.Random(seed)
        sim.advance(100)
        for step in range(steps):
            roll = rng.random()
            if roll < 0.35:
                sim.submit(f"k{rng.randint(0, 5)}", f"v{step}")
            elif roll < 0.7:
                sim.advance(rng.randint(5, 20))
            elif roll < 0.8:
                groups = {i: (i % 2 if rng.random() < 0.5 else 0) for i in range(5)}
                sim.partition(groups)
            elif roll < 0.9:
                sim.heal()
            else:
                sim.restart(rng.randrange(5))
            sim.check_election_safety()
            sim.check_log_matching()
            sim.check_applied_consistency()
        sim.heal()
        sim.advance(300)
        sim.check_log_matching()

    def test_historical_seed5_soak_no_longer_trips(self):
        """seed=5 是当年当场抛红的那一个；再加两个 seed 防止"只给一个种子打补丁"。"""
        for seed in (5, 41, 77):
            with self.subTest(seed=seed):
                self.soak(seed)

    def test_uncommitted_divergence_is_legal(self):
        """构造合法中间态：同 index 不同 term、两边都没提交 → 必须**不**抛。"""
        sim = Simulation(n=3, seed=0)
        sim.nodes[0].log = [{"term": 1, "cmd": ("set", "a", "1")}]
        sim.nodes[1].log = [{"term": 2, "cmd": ("set", "b", "2")}]
        sim.nodes[2].log = []
        for node in sim.nodes.values():
            node.commit_index = 0
            node.last_applied = 0
        sim.check_log_matching()

    def test_same_term_divergence_is_still_caught(self):
        """反向：同 index **同 term** 却分叉，必须抛，而且理由要是"任期相同 → 前缀应一致"。

        没有这一条，"把断言改宽"和"把牙齿拔掉"就分不出来。
        """
        sim = Simulation(n=3, seed=0)
        sim.nodes[0].log = [{"term": 1, "cmd": ("set", "a", "1")},
                            {"term": 2, "cmd": ("set", "x", "1")}]
        sim.nodes[1].log = [{"term": 1, "cmd": ("set", "a", "1")},
                            {"term": 2, "cmd": ("set", "y", "2")}]
        sim.nodes[2].log = []
        with self.assertRaises(AssertionError) as caught:
            sim.check_log_matching()
        self.assertIn("任期相同", str(caught.exception))


# ---------------------------------------------------------------- 快照与日志压缩（B41 候选③）
class TestSnapshotAndCompaction(unittest.TestCase):
    def test_compaction_bounds_log_and_replay_matches(self):
        """压缩确实发生、日志被压住、每条状态机都等于'快照+日志重放'（验收①）。"""
        sim = Simulation(n=3, seed=0, snapshot_threshold=4)
        self.assertIsNotNone(drive_until_leader(sim))
        for i in range(16):
            self.assertTrue(sim.submit(f"k{i}", f"v{i}"))
            sim.advance(10)
        sim.advance(120)
        self.assertGreater(sim.compactions, 0)
        for node in sim.nodes.values():
            self.assertGreaterEqual(node.snapshot_index, 4)     # 确实压缩过
            self.assertLessEqual(len(node.log), sim.snapshot_threshold + 4)   # 日志有界
            sim.verify_node_replay(node)                        # 负面对照见 TestNewCheckers

    def test_snapshot_boundary_does_not_leak_uncommitted(self):
        """快照边界上的 §5.4.2（验收③）：新 leader 压缩**跨过** ghost 的索引，
        ghost 不进任何快照/状态机；旧 leader 走 InstallSnapshot 追平。"""
        for seed in range(80):
            sim = Simulation(n=5, seed=seed, snapshot_threshold=3)
            old = drive_until_leader(sim)
            if old is None:
                continue
            sim.partition({i: (0 if i == old else 1) for i in range(5)})
            sim.advance(150)
            new = sim.leader_id()
            if new is None or new == old or sim.nodes[new].term <= sim.nodes[old].term:
                continue
            sim.submit_to(old, "ghost", "c")
            ghost_index = sim.nodes[old].last_log_index()
            for i in range(8):
                sim.submit_to(new, f"real{i}", f"r{i}")
                sim.advance(15)
            if sim.nodes[new].snapshot_index < ghost_index:
                sim.advance(150)                       # 再压一会儿
            if sim.nodes[new].snapshot_index < ghost_index:
                continue                                # 没压过 ghost 索引，换种子
            for node in sim.nodes.values():             # 压缩点之前：ghost 不在任何快照里
                self.assertNotIn("ghost", node.snapshot_sm)
            installs_before = sim.snapshot_installs
            sim.heal()
            sim.advance(500)
            for node in sim.nodes.values():
                self.assertNotIn("ghost", node.sm)
                self.assertNotIn("ghost", node.snapshot_sm)
                self.assertEqual(node.sm.get("real7"), "r7")
                sim.verify_node_replay(node)
            self.assertGreater(sim.snapshot_installs, installs_before,
                               "旧 leader 应当经 InstallSnapshot 追平（计数器证明走了这条路）")
            sim.check_election_safety()
            sim.check_log_matching()
            sim.check_applied_consistency()
            return
        self.fail("80 个 seed 里没构造出快照边界场景（应调参重试）")

    def test_isolated_compacted_node_catches_up_via_snapshot(self):
        """落后于日志起点的节点：append 退避到压缩段后必须改走快照并追平。"""
        for seed in range(30):
            sim = Simulation(n=3, seed=seed, snapshot_threshold=3)
            leader = drive_until_leader(sim)
            victim = next(i for i in sim.nodes if i != leader)
            sim.partition({i: (0 if i == victim else 1) for i in sim.nodes})
            for i in range(12):
                sim.submit(f"k{i}", f"v{i}")
                sim.advance(12)
            if sim.nodes[leader].snapshot_index <= sim.nodes[victim].last_log_index():
                continue                                # 没压过 victim 的日志起点，换种子
            before = sim.snapshot_installs
            sim.heal()
            sim.advance(400)
            self.assertGreater(sim.snapshot_installs, before)
            for node in sim.nodes.values():
                self.assertEqual(node.sm.get("k11"), "v11")
                sim.verify_node_replay(node)
            return
        self.fail("30 个 seed 里没构造出'落后于压缩段'的场景")

    def test_stale_snapshot_is_ignored(self):
        """守卫：last_index <= last_applied 的快照不碰任何状态（进度只许前进）。"""
        sim = Simulation(n=3, seed=0, snapshot_threshold=4)
        drive_until_leader(sim)
        for i in range(10):
            sim.submit(f"k{i}", f"v{i}")
            sim.advance(12)
        sim.advance(120)
        node = sim.nodes[0]
        before = (node.snapshot_index, dict(node.sm), node.commit_index, node.last_applied)
        msg = {"kind": "install_snapshot", "src": 1, "dst": 0, "term": node.term,
               "last_index": 1, "last_term": 1,
               "sm": {"hacked": "x"}, "members": [0, 1, 2],
               "digest": "00" * 32, "commit_index": 1}
        sim.on_install_snapshot(node, msg)
        self.assertEqual((node.snapshot_index, dict(node.sm), node.commit_index,
                          node.last_applied), before)
        self.assertNotIn("hacked", node.sm)

    def test_restart_preserves_snapshot_and_replay(self):
        """重启保留快照字段与账本；重启后的状态机仍通过回放校验（验收①）。"""
        sim = Simulation(n=3, seed=0, snapshot_threshold=4)
        drive_until_leader(sim)
        for i in range(12):
            sim.submit(f"k{i}", f"v{i}")
            sim.advance(12)
        sim.advance(120)
        target = 1
        node = sim.nodes[target]
        self.assertGreater(node.snapshot_index, 0)
        before = (node.snapshot_index, node.snapshot_term,
                  dict(node.snapshot_sm), node.last_applied)
        sim.restart(target)
        fresh = sim.nodes[target]
        self.assertEqual((fresh.snapshot_index, fresh.snapshot_term,
                          dict(fresh.snapshot_sm), fresh.last_applied), before)
        sim.verify_node_replay(fresh)
        sim.advance(200)
        sim.verify_node_replay(fresh)
        self.assertEqual(fresh.sm.get("k11"), "v11")


# ---------------------------------------------------------------- 成员变更（B41 候选③）
class TestMembershipChange(unittest.TestCase):
    def test_grow_and_shrink_with_service(self):
        """3 → 5 → 4：新节点追平、缩容后服务不断、配置史与交叠检查都对。"""
        sim = Simulation(n=3, seed=0, snapshot_threshold=4)
        drive_until_leader(sim)
        for i in range(6):
            self.assertTrue(sim.submit(f"k{i}", f"v{i}"))
            sim.advance(10)
        first, second = sim.add_server(), sim.add_server()
        self.assertTrue(sim.change_membership(add=first))
        sim.advance(250)
        self.assertTrue(sim.change_membership(add=second))
        sim.advance(300)
        for node in sim.nodes.values():
            self.assertEqual(sorted(node.effective_members()), [0, 1, 2, first, second])
            self.assertEqual(node.sm.get("k5"), "v5")
            sim.verify_node_replay(node)
        victim = 0
        self.assertTrue(sim.change_membership(remove=victim))
        sim.advance(300)
        for node in sim.nodes.values():
            if node.id == victim:
                continue
            self.assertEqual(sorted(node.effective_members()),
                             sorted({1, 2, first, second}))
        self.assertNotIn(victim, sim.nodes[victim].effective_members())
        self.assertTrue(sim.submit("after", "ok"))          # 缩容后服务未断
        sim.advance(150)
        for node in sim.nodes.values():
            if node.id == victim:
                continue
            self.assertEqual(node.sm.get("after"), "ok")
        sim.check_config_overlap()
        self.assertEqual(len(sim.config_history), 3)

    def test_one_at_a_time_rejected_while_uncommitted(self):
        """一次一个：leader 日志里有未提交 config 时，第二次变更被拒绝。"""
        sim = Simulation(n=3, seed=0, snapshot_threshold=4)
        leader = drive_until_leader(sim)
        sim.partition({i: (0 if i == leader else 1) for i in sim.nodes})
        sim.advance(50)
        self.assertTrue(sim.change_membership(add=sim.add_server()))
        self.assertFalse(sim.change_membership(add=sim.add_server()))
        node = sim.nodes[leader]
        pending = [entry for offset, entry in enumerate(node.log)
                   if node.snapshot_index + offset + 1 > node.commit_index
                   and entry["cmd"][0] == "config"]
        self.assertEqual(len(pending), 1)

    def test_removed_node_learns_and_stops_campaigning(self):
        """被移除节点收到（即使未提交的）config 条目后就安静下来，不再搅动选举。"""
        sim = Simulation(n=3, seed=0, snapshot_threshold=4)
        leader = drive_until_leader(sim)
        for i in range(5):
            sim.submit(f"k{i}", f"v{i}")
            sim.advance(10)
        victim = next(i for i in sim.nodes if i != leader)
        self.assertTrue(sim.change_membership(remove=victim))
        sim.advance(300)
        self.assertNotIn(victim, sim.nodes[victim].effective_members())
        term_at_learning = sim.nodes[victim].term
        sim.advance(600)
        later = [t for (t, i) in sim.leader_history if i == victim and t > term_at_learning]
        self.assertEqual(later, [], "学会自己已被移除之后仍发起选举")

    def test_new_node_not_elected_before_joining(self):
        """空配置的新节点在学会配置之前不自荐。"""
        sim = Simulation(n=3, seed=0, snapshot_threshold=4)
        drive_until_leader(sim)
        new_id = sim.add_server()
        sim.advance(400)
        self.assertNotIn(new_id, sim.nodes[new_id].effective_members())
        self.assertEqual([t for t, i in sim.leader_history if i == new_id], [])

    def test_leader_self_removal_steps_down(self):
        """leader 把自己移出配置：提交后退位，剩余成员选出新 leader 继续服务。"""
        sim = Simulation(n=3, seed=0, snapshot_threshold=4)
        leader = drive_until_leader(sim)
        for i in range(4):
            sim.submit(f"k{i}", f"v{i}")
            sim.advance(12)
        self.assertTrue(sim.change_membership(remove=leader))
        sim.advance(300)
        self.assertNotEqual(sim.nodes[leader].role, "leader")
        self.assertTrue(sim.submit("after", "ok"))
        sim.advance(150)
        for node in sim.nodes.values():
            if node.id == leader:
                continue
            self.assertEqual(node.sm.get("after"), "ok")


# ---------------------------------------------------------------- 新检查器的两侧
class TestNewCheckersAreNotToothless(unittest.TestCase):
    def test_replay_checker_catches_tampered_log(self):
        """负面对照：改坏一条日志条目，'快照+日志重放'校验器必须红。"""
        sim = Simulation(n=3, seed=0, snapshot_threshold=4)
        drive_until_leader(sim)
        for i in range(6):
            sim.submit(f"k{i}", f"v{i}")
            sim.advance(10)
        sim.advance(100)
        target = sim.nodes[0]
        sim.verify_node_replay(target)
        tampered = False
        for entry in target.log:
            if entry["cmd"][0] == "set":
                entry["cmd"] = ("set", entry["cmd"][1], "tampered")
                tampered = True
                break
        self.assertTrue(tampered, "目标节点日志里没有可改的 set 条目")
        with self.assertRaises(AssertionError) as caught:
            sim.verify_node_replay(target)
        self.assertIn("快照+日志重放", str(caught.exception))

    def test_config_overlap_checker_catches_bad_history(self):
        """负面对照：相邻配置差两个成员必须红；"单步必相交"用代数事实单独钉。

        注意这里**不**断言"任意两份配置的多数派都相交"——那是过强口径，本实现自己的
        churn 已用实测反例证伪（sim.check_config_overlap 注释里记着那对配置）。
        """
        sim = Simulation(n=3, seed=0)
        sim.config_history = {(1, 1): frozenset({0, 1, 2, 3}),
                              (2, 1): frozenset({0, 1, 2, 4, 5})}
        with self.assertRaises(AssertionError) as caught:
            sim.check_config_overlap()
        self.assertIn("差多于一个成员", str(caught.exception))
        # 代数事实：单步变更（差一个成员）的两份配置，任何多数派必相交
        self.assertFalse(configs_have_disjoint_majorities({0, 1, 2}, {0, 1, 2, 3}))
        self.assertFalse(configs_have_disjoint_majorities({0, 1, 2, 3}, {0, 1, 2}))
        # 反面存在性：换人（差两个）就可能选出不相交的多数派——这正是"一次一个"要拦的
        self.assertTrue(configs_have_disjoint_majorities({0, 1, 2}, {0, 1, 3}))
        # 隔了多步的配置也不保证相交（全对全检查过强的证据，churn 实测的那一对）
        self.assertTrue(configs_have_disjoint_majorities({0, 1, 2}, {3, 4, 5}))
        self.assertTrue(configs_have_disjoint_majorities({0, 1, 2, 3}, {0, 1, 3, 4, 6}))


# ---------------------------------------------------------------- 成员变更 × 快照的随机 churn
class TestMembershipSnapshotSoak(unittest.TestCase):
    def churn(self, seed: int, steps: int = 60) -> Simulation:
        """提交/分区/愈合/重启/成员变更混在一起；四条不变式每个事件后都查。"""
        sim = Simulation(n=3, seed=seed, snapshot_threshold=4)
        rng = random.Random(seed)
        drive_until_leader(sim)
        for step in range(steps):
            roll = rng.random()
            if roll < 0.30:
                sim.submit(f"k{rng.randint(0, 5)}", f"v{step}")
            elif roll < 0.55:
                sim.advance(rng.randint(4, 15))
            elif roll < 0.65:
                sim.partition({i: (i % 2 if rng.random() < 0.5 else 0)
                               for i in sim.nodes})
            elif roll < 0.72:
                sim.heal()
            elif roll < 0.82:
                sim.restart(rng.choice(sorted(sim.nodes)))
            elif roll < 0.94:
                lid = sim.leader_id()
                members = sim.nodes[lid].effective_members() if lid is not None else None
                if members is None:
                    sim.advance(8)
                elif len(members) < 6 and rng.random() < 0.55:
                    sim.change_membership(add=sim.add_server())
                elif len(members) > 3:
                    sim.change_membership(remove=rng.choice(sorted(members)))
            else:
                sim.advance(rng.randint(4, 10))
            sim.check_election_safety()
            sim.check_log_matching()
            sim.check_applied_consistency()
            sim.check_config_overlap()
        sim.heal()
        sim.advance(600)
        sim.check_election_safety()
        sim.check_log_matching()
        sim.check_applied_consistency()
        sim.check_config_overlap()
        for node in sim.nodes.values():
            sim.verify_node_replay(node)
        return sim

    def test_random_membership_churn_invariants(self):
        configs = installs = compactions = 0
        for seed in range(8):
            with self.subTest(seed=seed):
                sim = self.churn(seed)
                configs += len(sim.config_history)
                installs += sim.snapshot_installs
                compactions += sim.compactions
        self.assertGreater(configs, 4, "churn 里几乎没发生成员变更（脚本问题，不是实现问题）")
        self.assertGreater(compactions, 0, "churn 里一次压缩都没发生")
        self.assertGreater(installs, 0, "churn 里一次快照追赶都没发生（成员变更+压缩的组合没走到）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
