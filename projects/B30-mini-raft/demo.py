"""projects/B30-mini-raft/demo.py —— 八段演示（分布式与云计算 / mini-Raft）

每段的数字都是**这一趟跑出来的**，没有一处写死；跑两遍输出逐字一致
（真套接字只连本机、端口用 0 由系统分配且不打印，所以线程时序不影响输出）。

看什么：
① mini-RPC 的消息边界与 id 关联 ② 一致性哈希 vs 朴素取模的搬移比例
③ 一次正常选举与日志复制的终态 ④ 分区下的可用性 + Raft §5.4.2 的"未提交条目被覆盖"
⑤ 随机事件流（提交/分区/重启/成员变更）里四条安全性不变式逐事件成立
⑥ leader 重启后持久状态不回退
⑦ 快照与追赶：日志压缩 + InstallSnapshot（B41 候选③）
⑧ 成员变更：单步 3→5→4，配置进日志、提交后生效（B41 候选③）

红线：这是**单进程事件驱动模拟 + 真套接字 RPC 教学件**，不是一套跑完就等价于
生产级 Raft 的东西；快照/成员变更是教学实现（无 Joint Consensus、无 Pre-Vote），
完整边界见 README「明确不做」。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from raft30.hashing import ConsistentHash, NaiveShard, moved_fraction   # noqa: E402
from raft30.rpc import FrameDecoder, RpcClient, RpcServer, encode_msg   # noqa: E402
from raft30.sim import Simulation                                       # noqa: E402

WIDTH = 78


def section(index: int, title: str) -> None:
    print()
    print("=" * WIDTH)
    print(f"{index}) {title}")
    print("=" * WIDTH)


def show(label: str, value) -> None:
    print(f"  {label:<26} {value}")


def wait_leader(sim: Simulation, limit: int = 600) -> int | None:
    while sim.now < limit:
        sim.advance(1)
        leader = sim.leader_id()
        if leader is not None:
            return leader
    return None


# ------------------------------------------------------------------ ① RPC
def demo_rpc() -> None:
    section(1, "mini-RPC：TCP 上的消息边界、id 关联与坏帧")
    calls = [{"op": "set", "k": "名称", "v": "值一"}, {"op": "get", "k": "名称"},
             {"op": "sum", "xs": [1, 2, 3]}]

    def handler(body: dict) -> dict:
        if body.get("op") == "sum":
            return {"sum": sum(body["xs"])}
        return {"echo": body, "node": "srv"}

    server = RpcServer("127.0.0.1", 0, handler)
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = RpcClient("127.0.0.1", server.port)
    for body in calls:
        show(f"call {body['op']}", client.call(body))
    client.close()
    server.stop()

    d = FrameDecoder()
    a, b = encode_msg({"id": 1, "body": {"op": "ping"}}), encode_msg({"id": 2, "body": {"op": "pong"}})
    glued = d.feed(a + b)
    show("两帧一次到达", f"解出 {len(glued)} 条（不能把一次 recv 当成一条消息）")
    half = FrameDecoder()
    stream = a + b
    first = half.feed(stream[:len(a) + 5])          # 第一帧完整 + 第二帧只到一半
    rest = half.feed(stream[len(a) + 5:])
    show("半帧停在边界", f"第一次解出 {len(first)} 条，补完再解出 {len(rest)} 条")
    noisy = FrameDecoder().feed(b"\nnot-json\n" + a)
    show("坏帧（空行/非 JSON）", f"跳过并只回 {len(noisy)} 条合法消息——把坏帧与请求分开")


# ------------------------------------------------------------------ ② 分片
def demo_sharding() -> None:
    section(2, "分片：朴素取模 vs 一致性哈希的搬移比例（4→5 扩容、5→4 缩容）")
    keys = [f"key:{i}" for i in range(2000)]
    four = ["n1", "n2", "n3", "n4"]
    cons_old = ConsistentHash(four, vnodes=100)
    cons_new = ConsistentHash(four + ["n5"], vnodes=100)
    ideal_add = 1 / (len(four) + 1)
    show("朴素取模 4→5 搬移", f"{moved_fraction(NaiveShard(4), NaiveShard(5), keys):.1%}"
                              f"（理论 ≈ {1 - 1 / 5:.0%}：节点数一变，归属几乎全变）")
    show("一致性哈希 4→5 搬移", f"{moved_fraction(cons_old, cons_new, keys):.1%}"
                                f"（理想 = 1/(n+1) = {ideal_add:.1%}，新节点只接管自己那一段）")
    cons_down = ConsistentHash(four, vnodes=100)
    show("一致性哈希 5→4 缩容", f"{moved_fraction(cons_new, cons_down, keys):.1%}"
                                f"（只有被摘掉节点的键需要搬家）")
    only = [k for k in keys if cons_new.shard(k) == "n5" and cons_down.shard(k) != "n5"]
    others = [k for k in keys if cons_new.shard(k) != "n5" and cons_down.shard(k) != "n5"
              and cons_new.shard(k) != cons_down.shard(k)]
    show("搬移是否只涉及 n5", f"n5 的键搬了 {len(only)} 个；不属 n5 却搬家的键 {len(others)} 个")
    ch = ConsistentHash(["a", "b", "c"], vnodes=10)
    loads = {n: sum(1 for k in keys if ch.shard(k) == n) for n in ("a", "b", "c")}
    show("vnodes=10 的负载分布", f"{loads}（虚拟副本越多越平，代价是环更长）")


# ------------------------------------------------------------------ ③ 选举与复制
def demo_election() -> None:
    section(3, "一次正常选举与日志复制（5 节点，seed=0，无故障）")
    sim = Simulation(n=5, seed=0)
    leader = wait_leader(sim)
    show("选出的 leader", f"节点 {leader}，term={sim.nodes[leader].term}，耗时 t={sim.now}")
    for i, (k, v) in enumerate((("x", "1"), ("y", "2"), ("z", "3")), start=1):
        sim.submit(k, v)
        sim.advance(12)
    sim.advance(200)
    show("各节点 (role,term,快照,末索引,commit,applied)",
         " ".join(f"[{n.role[0]}{n.term},{n.snapshot_index},{n.last_log_index()},"
                  f"{n.commit_index},{n.last_applied}]" for n in sim.nodes.values()))
    show("状态机是否全员一致", f"{len({tuple(sorted(n.sm.items())) for n in sim.nodes.values()}) == 1}")
    sim.check_election_safety()
    sim.check_log_matching()
    sim.check_applied_consistency()
    show("三条不变式", "全部通过（每个任期至多一个 leader / 日志前缀一致 / 已应用前缀一致）")
    show("leader 更替史", f"{sim.leader_history}")


# ------------------------------------------------------------------ ④ 分区与 §5.4.2
def demo_partition() -> None:
    section(4, "分区：多数派继续服务，少数派旧 leader 的未提交条目被覆盖（Raft §5.4.2）")
    for seed in range(50):
        sim = Simulation(n=5, seed=seed)
        old = wait_leader(sim)
        if old is None:
            continue
        sim.partition({i: (0 if i == old else 1) for i in range(5)})
        sim.advance(150)
        new = sim.leader_id()
        if new is None or new == old or sim.nodes[new].term <= sim.nodes[old].term:
            continue
        old_term, new_term = sim.nodes[old].term, sim.nodes[new].term
        sim.submit_to(old, "ghost", "c")           # 少数派旧 leader 收到但提交不了
        sim.submit_to(new, "real", "r")            # 多数派正常提交
        sim.heal()
        sim.advance(400)
        ghosts = [n.id for n in sim.nodes.values() if "ghost" in n.sm]
        values = {n.sm.get("real") for n in sim.nodes.values()}
        show("构造用的 seed", f"seed={seed}：分裂当时 旧 leader=节点{old}(term={old_term})，"
                             f"新 leader=节点{new}(term={new_term})")
        show("为什么必须比任期", f"新 leader 任期更大（{new_term} > {old_term}）才算换了届；"
                              f"愈合后两者会收敛到同一任期，所以读数要在分裂那一刻取")
        show("多数派是否继续服务", f"real 在全员状态机里的取值集合 = {values}")
        show("ghost 有没有被应用", f"出现在节点 {ghosts}（空 = 从未提交，被新任期覆盖）")
        sim.check_election_safety()
        sim.check_log_matching()
        sim.check_applied_consistency()
        show("愈合后三条不变式", "全部通过")
        return


# ------------------------------------------------------------------ ⑤ 随机事件流
def demo_soak() -> None:
    section(5, "随机事件流：提交/分区/重启/成员变更混在一起，4 条不变式逐事件检查"
               "（10 seed × 60 步）")
    checks = elections = dropped = configs = compactions = installs = 0
    for seed in range(10):
        sim = Simulation(n=3, seed=seed, snapshot_threshold=4)
        rng = random.Random(seed)
        wait_leader(sim)
        for step in range(60):
            roll = rng.random()
            if roll < 0.30:
                sim.submit(f"k{rng.randint(0, 5)}", f"v{step}")
            elif roll < 0.55:
                sim.advance(rng.randint(4, 15))
            elif roll < 0.65:
                sim.partition({i: (i % 2 if rng.random() < 0.5 else 0) for i in sim.nodes})
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
            checks += 4
        sim.heal()
        sim.advance(600)
        for node in sim.nodes.values():
            sim.verify_node_replay(node)
        elections += len(sim.leader_history)
        dropped += sim.net.dropped
        configs += len(sim.config_history)
        compactions += sim.compactions
        installs += sim.snapshot_installs
    show("逐事件不变式检查", f"{checks} 次，0 失败（含配置交叠；有失败会直接抛断言）")
    show("期间选举 / 丢包", f"选举 {elections} 次；分区丢包 {dropped} 次（都是设计行为）")
    show("快照与成员活动", f"配置变更 {configs} 次、压缩 {compactions} 次、"
                          f"快照安装 {installs} 次")
    show("回放校验", "10 个 seed 的全部节点：状态机 == 快照+日志重放")


# ------------------------------------------------------------------ ⑥ 重启
def demo_restart() -> None:
    section(6, "leader 重启：持久状态保留，已应用前缀不回退")
    sim = Simulation(n=5, seed=3)
    leader = wait_leader(sim)
    for k, v in (("a", "1"), ("b", "2")):
        sim.submit(k, v)
        sim.advance(12)
    sim.advance(150)
    node = sim.nodes[leader]
    applied_before = node.last_applied
    digest_before = node.digest_at(applied_before)
    before = (node.term, node.last_log_index(), node.commit_index,
              tuple(sorted(node.sm.items())))
    sim.restart(leader)
    after = sim.nodes[leader]
    now = (after.term, after.last_log_index(), after.commit_index,
           tuple(sorted(after.sm.items())))
    show("重启前 (term,末索引,commit,sm)", before)
    show("重启后 (term,末索引,commit,sm)", now)
    show("持久状态是否保住", "是" if before == now else "否（那就是 bug）")
    show("易失角色是否清零", f"{after.role}（重启瞬间它不再是 leader）")
    new_leader = wait_leader(sim, limit=sim.now + 800)
    show("是否重新选出 leader", f"节点 {new_leader}，t={sim.now}")
    sim.advance(400)
    current = sim.nodes[leader]
    show("已应用前缀是否只前进", f"applied {applied_before} -> {current.last_applied}；"
                                  f"旧前缀的哈希链 digest 不变："
                                  f"{current.digest_at(applied_before) == digest_before}")
    sim.check_election_safety()
    sim.check_log_matching()
    sim.check_applied_consistency()
    show("三条不变式", "全部通过")


# ------------------------------------------------------------------ ⑦ 快照与追赶
def demo_snapshot() -> None:
    section(7, "快照与追赶：日志压缩 + InstallSnapshot（快照只含已提交）")
    sim = Simulation(n=3, seed=2, snapshot_threshold=3)
    leader = wait_leader(sim)
    victim = next(i for i in sim.nodes if i != leader)
    sim.partition({i: (0 if i == victim else 1) for i in sim.nodes})
    for i in range(12):
        sim.submit(f"k{i}", f"v{i}")
        sim.advance(12)
    node = sim.nodes[leader]
    show("多数派（2 节点）压缩读数",
         f"压缩 {sim.compactions} 次；leader 快照到 index={node.snapshot_index}，"
         f"日志只剩 {len(node.log)} 条")
    show("被隔离节点进度",
         f"节点{victim}：快照 index={sim.nodes[victim].snapshot_index}，"
         f"日志 {len(sim.nodes[victim].log)} 条（落后于多数派日志起点）")
    installs_before = sim.snapshot_installs
    sim.heal()
    sim.advance(400)
    show("愈合后 InstallSnapshot",
         f"安装次数 {installs_before} -> {sim.snapshot_installs}"
         f"（计数证明走了快照路径，不是碰巧还能全量 append）")
    converged = all(n.sm.get("k11") == "v11" for n in sim.nodes.values())
    show("追平结果", f"k11=v11 全员一致：{converged}")
    for n in sim.nodes.values():
        sim.verify_node_replay(n)
    show("回放校验", "每个节点的状态机都等于'快照+日志重放'（有反例会直接抛断言）")
    sim.check_election_safety()
    sim.check_log_matching()
    sim.check_applied_consistency()
    show("安全不变式", "全部通过（含哈希链账本的已应用前缀比较）")


# ------------------------------------------------------------------ ⑧ 成员变更
def demo_membership() -> None:
    section(8, "成员变更：单步 3 → 5 → 4（配置进日志、提交后生效、被移除者学会后安静）")
    sim = Simulation(n=3, seed=0, snapshot_threshold=4)
    wait_leader(sim)
    for i in range(4):
        sim.submit(f"k{i}", f"v{i}")
        sim.advance(10)
    first, second = sim.add_server(), sim.add_server()
    ok1 = sim.change_membership(add=first)
    sim.advance(250)
    ok2 = sim.change_membership(add=second)
    sim.advance(300)
    current = sim.leader_id()
    members = sorted(sim.nodes[current].effective_members())
    show("扩容两次（一次一个）", f"{ok1}/{ok2}；当前成员 {members}")
    show("新节点是否追平",
         f"节点{first} sm[k3]={sim.nodes[first].sm.get('k3')}；"
         f"节点{second} sm[k3]={sim.nodes[second].sm.get('k3')}")
    victim = next(i for i in members if i != current and i < 3)
    ok3 = sim.change_membership(remove=victim)
    sim.advance(300)
    current = sim.leader_id()
    show("缩容一次", f"{ok3}；移除节点{victim} 后的成员 "
                     f"{sorted(sim.nodes[current].effective_members())}")
    show("被移除者学会后安静",
         f"节点{victim} 还认为自己在配置里吗："
         f"{victim in sim.nodes[victim].effective_members()}（期望 False；是则它会搅动选举）")
    show("配置史（已提交，按序）",
         str([sorted(c) for _, c in sorted(sim.config_history.items())]))
    submitted = sim.submit("after", "ok")
    sim.advance(200)
    survivors = [n for n in sim.nodes.values() if n.id != victim]
    show("缩容后服务未断",
         f"再提交一条：{submitted}；剩余成员状态机一致："
         f"{len({n.sm.get('after') for n in survivors}) == 1}")
    sim.check_election_safety()
    sim.check_log_matching()
    sim.check_applied_consistency()
    sim.check_config_overlap()
    show("四条不变式", "全部通过（含相邻配置的单步与多数派交叠检查）")


def main() -> int:
    print("B30 mini-raft 八段演示 —— 数字全部现算；单进程模拟 + 真套接字 RPC")
    demo_rpc()
    demo_sharding()
    demo_election()
    demo_partition()
    demo_soak()
    demo_restart()
    demo_snapshot()
    demo_membership()
    print("\n" + "=" * WIDTH)
    print("本轮没做的（别把模拟当生产）：无 Joint Consensus、无 Pre-Vote/CheckQuorum、")
    print("无多进程真集群与磁盘持久化、无乱序/重复投递的完整处理；快照安装整发不分块。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
