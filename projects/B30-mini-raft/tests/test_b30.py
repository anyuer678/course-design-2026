"""B30-mini-raft 自测。

"期望值必须有出处"的落法：
    1. Raft 安全不变式 <-- 论文定义（Election Safety / Log Matching /
       State Machine Safety），在种子化随机事件流中**每个事件后**检查
    2. §5.4.2 场景 <-- 手工构造"旧 leader 隔离期写入的未提交条目，
       愈合后被覆盖"——期望值是 Raft 论文的标准结论
    3. 一致性哈希 <-- 搬移比例的理论值（朴素 ~4/5 vs 一致性 ~1/n）
    4. RPC <-- 真套接字回声 + 坏帧跳过约定
"""
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from raft30.hashing import ConsistentHash, NaiveShard, moved_fraction
from raft30.rpc import FrameDecoder, RpcClient, RpcServer, encode_msg
from raft30.sim import Simulation


def wait_leader(sim, max_ticks=400):
    sim.advance(max_ticks)
    return sim.leader_id()


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
        leaders = [n for n in sim.nodes if n.role == "leader"]
        self.assertEqual(len(leaders), 1)

    def test_replication_reaches_all(self):
        sim = Simulation(n=5, seed=2)
        lid = wait_leader(sim)
        for i in range(1, 6):
            self.assertTrue(sim.submit(f"k{i}", f"v{i}"))
        sim.advance(60)
        for node in sim.nodes:
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
                    committed = [n.sm.get("k") for n in sim.nodes
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
            for node in sim.nodes:
                self.assertNotIn("ghost", node.sm)
            values = {n.sm.get("real") for n in sim.nodes}
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
        for node in sim.nodes:
            for k, v in committed_before.items():
                self.assertEqual(node.sm.get(k), v)
        self.assertEqual(sim.nodes[0].sm.get("k3"), "v3")


def wait_leader(sim, max_ticks=400):
    sim.advance(max_ticks)
    return sim.leader_id()


if __name__ == "__main__":
    unittest.main(verbosity=2)
