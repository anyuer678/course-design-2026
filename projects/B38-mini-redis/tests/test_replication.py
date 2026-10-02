"""tests/test_replication.py —— B38 主从复制扩展自测（13 项，case-study §8 语义表）

纪律（与 B38 其它测试一致）：
  1. 期望值来自语义表：握手格式/READONLY 文本/偏移=规范化帧字节数/被动过期，
     逐条写成断言；
  2. **两库对账器**（reconcile）逐键逐值+逐到期时刻比对，并且它自己有"牙齿"
     （负面自证：人为分叉必须被抓）；
  3. 断链/重连/过期传播这些异步过程用"等状态成立"封装（有超时、失败即红），
     不靠 sleep 猜时间。
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from redislite import Client, Server, resp                                 # noqa: E402
from redislite.server import READONLY_ERROR, REPLID                        # noqa: E402


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b38rep-{name}-"))
    if str(base.resolve()).lower().startswith(str(ROOT.parent.parent.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


def wait_until(cond, timeout: float = 8.0, step: float = 0.02) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return False


def reconcile(master: Server, replica: Server) -> list[str]:
    """两库对账器：逐键逐值 + 逐到期时刻。返回问题列表（空=一致）。"""
    problems = []
    m_data, r_data = master.store.data, replica.store.data
    for key in sorted(set(m_data) | set(r_data)):
        if key not in r_data:
            problems.append(f"从库缺键：{key!r}")
        elif key not in m_data:
            problems.append(f"从库多键：{key!r}")
        elif m_data[key] != r_data[key]:
            problems.append(f"值不一致：{key!r}: {m_data[key]!r} != {r_data[key]!r}")
    if dict(master.store.expires) != dict(replica.store.expires):
        problems.append(f"到期时刻不一致：{master.store.expires} != {replica.store.expires}")
    return problems


def linked_and_synced(master: Server, replica: Server) -> bool:
    link = replica.master_link
    return (link is not None and link.state == "streaming"
            and master.repl_offset == replica.applied_offset
            and not reconcile(master, replica))


class ReplicationCase(unittest.TestCase):
    """一套主从 + 客户端，测试内共享；重连间隔调小让测试快。"""

    def setUp(self):
        self.clock = FakeClock()
        self.master = Server(port=0, clock=self.clock).start()
        self.replica = Server(port=0, clock=self.clock, repl_retry=0.05).start()
        self.addCleanup(self.master.stop)
        self.addCleanup(self.replica.stop)
        self.m = Client("127.0.0.1", self.master.port)
        self.r = Client("127.0.0.1", self.replica.port)
        self.addCleanup(self.m.close)
        self.addCleanup(self.r.close)

    def link_replica(self):
        assert self.r.cmd("REPLICAOF", "127.0.0.1", self.master.port) == b"OK"
        self.assertTrue(wait_until(lambda: linked_and_synced(self.master, self.replica)),
                        "从库未在超时内完成全量同步并追平")


class TestReplication(ReplicationCase):
    def test_handshake_fullresync_format(self):
        """PSYNC 原始握手（不经封装）：FULLRESYNC 行格式与 offset=当前流位置。"""
        self.m.cmd("SET", "k", "v")                        # 让偏移量非 0
        raw = Client("127.0.0.1", self.master.port)
        self.addCleanup(raw.close)
        raw.send("PSYNC", "?", "-1")
        banner = raw.read_reply()
        self.assertEqual(banner, f"FULLRESYNC {REPLID} {self.master.repl_offset}".encode())
        snapshot = raw.read_reply()
        self.assertIsInstance(snapshot, bytes)
        self.assertTrue(snapshot.startswith(b"REDISLITE1"))
        # 偏移量语义：= 规范化帧字节数之和
        self.assertEqual(self.master.repl_offset, len(resp.encode_command("SET", "k", "v")))

    def test_full_sync_carries_data_and_ttl(self):
        self.m.cmd("SET", "plain", "1")
        self.m.cmd("SET", "ttlkey", "x" * 40)
        self.m.cmd("EXPIRE", "ttlkey", 60)
        self.link_replica()
        self.assertEqual(reconcile(self.master, self.replica), [])
        self.assertEqual(self.r.cmd("GET", "plain"), b"1")
        self.assertEqual(self.r.cmd("TTL", "ttlkey"), 60)

    def test_incremental_and_offsets_exact(self):
        self.link_replica()
        before = self.master.repl_offset
        commands = [("SET", "a", "1"), ("INCR", "n"), ("EXPIRE", "a", "5"), ("DEL", "nope")]
        for command in commands:
            self.m.cmd(*command)
        self.assertTrue(wait_until(lambda: linked_and_synced(self.master, self.replica)))
        delta = sum(len(resp.encode_command(*c)) for c in commands)
        self.assertEqual(self.master.repl_offset - before, delta)   # 偏移=帧字节数（精确钉）
        self.assertEqual(self.replica.applied_offset, self.master.repl_offset)
        self.assertEqual(self.r.cmd("GET", "a"), b"1")

    def test_readonly_exact_text(self):
        self.link_replica()
        for command in (("SET", "z", "9"), ("DEL", "z"), ("INCR", "z"), ("EXPIRE", "z", 5)):
            self.assertEqual(self.r.cmd(*command), resp.RespError(READONLY_ERROR),
                             msg=command)
        self.assertEqual(self.r.cmd("PING"), b"PONG")       # 读侧不受影响
        self.assertIsNone(self.r.cmd("GET", "z"))

    def test_replicaof_no_one_detach(self):
        self.link_replica()
        self.m.cmd("SET", "keep", "1")
        self.assertTrue(wait_until(lambda: self.replica.store.data.get(b"keep") == b"1"))
        self.assertEqual(self.r.cmd("REPLICAOF", "NO", "ONE"), b"OK")
        self.assertFalse(self.replica.is_replica)
        self.assertIsNone(self.replica.master_link)
        self.assertEqual(self.r.cmd("GET", "keep"), b"1")   # 数据保留
        self.assertEqual(self.r.cmd("SET", "local", "ok"), b"OK")  # 恢复可写

    def test_disconnect_reconnect_catch_up(self):
        self.link_replica()
        self.master._drop_replica_links()                    # 模拟链路故障
        self.m.cmd("SET", "during", "gap")                   # 断链窗口里的写入
        self.m.cmd("INCR", "gaptt")
        self.assertTrue(wait_until(lambda: linked_and_synced(self.master, self.replica)),
                        "重连后未追平")
        self.assertEqual(self.r.cmd("GET", "during"), b"gap")
        self.assertEqual(self.r.cmd("GET", "gaptt"), b"1")

    def test_active_expiry_propagates_to_replica(self):
        for i in range(30):
            self.m.cmd("SET", f"e{i}", "v")
            self.m.cmd("EXPIRE", f"e{i}", 5)
        self.link_replica()
        self.clock.advance(6)
        for _ in range(64):                                  # 触发主库主动周期
            self.m.cmd("PING")
        # 等"终态"而不是等"某条件首次成立"：主库清空 + 两库逐键对账干净
        ok = wait_until(lambda: len(self.master.store.data) == 0
                        and not reconcile(self.master, self.replica))
        self.assertTrue(ok, "过期删除未传播到从库")
        self.assertEqual(len(self.replica.store.data), len(self.master.store.data))
        self.assertEqual(self.replica.store.stats["expired_lazy"], 0)     # 从库自己从不删
        self.assertEqual(self.replica.store.stats["expired_active"], 0)

    def test_replica_passive_expire_reads_missing_keeps_keys(self):
        """从库语义（case-study §8.1）：过期键读作'不存在'但不删，等主库 DEL。"""
        self.m.cmd("SET", "gone", "v")
        self.m.cmd("EXPIRE", "gone", 2)
        self.link_replica()
        self.clock.advance(3)
        self.assertIsNone(self.r.cmd("GET", "gone"))          # 读表现为不存在
        self.assertEqual(self.r.cmd("TTL", "gone"), -2)
        self.assertIn(b"gone", self.replica.store.data)       # 但内存里还在（被动）
        self.assertEqual(self.replica.store.stats["expired_lazy"], 0)
        self.assertEqual(self.m.cmd("GET", "gone"), None)     # 主库一读：惰性删除+传播 DEL
        self.assertTrue(wait_until(lambda: b"gone" not in self.replica.store.data))

    def test_expire_verbatim_shared_clock(self):
        """共享假时钟下，EXPIRE 原样传播 → 两侧到期时刻逐值相等（偏差已归零）。"""
        self.link_replica()
        self.m.cmd("SET", "t", "v")
        self.m.cmd("EXPIRE", "t", 10)
        self.assertTrue(wait_until(
            lambda: self.replica.store.expires.get(b"t") == self.master.store.expires.get(b"t")))
        self.assertEqual(self.r.cmd("TTL", "t"), 10)

    def test_expired_key_not_resurrected_on_resync(self):
        """重连=全量重同步：主库快照不含已过期键，从库内存里的陈旧键被覆盖掉。"""
        self.m.cmd("SET", "old", "v")
        self.m.cmd("EXPIRE", "old", 60)
        self.link_replica()
        self.clock.advance(61)                               # 两侧逻辑上都过期
        self.assertIn(b"old", self.replica.store.data)       # 从库没删（被动）
        self.master._drop_replica_links()
        # 等终态（旧键在从库消失），避免"断链尚未被察觉"时旧条件提前通过
        self.assertTrue(wait_until(lambda: b"old" not in self.replica.store.data),
                        "全量重同步后从库仍持有过期键")
        self.assertTrue(wait_until(lambda: linked_and_synced(self.master, self.replica)))
        self.assertNotIn(b"old", self.master.store.data)     # 主库快照取数时已顺手清理

    def test_del_and_expire_clean_expires_on_both(self):
        """回归：DEL 必须连 expires 一起清（对账器抓出的残留——主库同样中招）。"""
        self.link_replica()
        self.m.cmd("SET", "t1", "v")
        self.m.cmd("EXPIRE", "t1", 50)
        self.m.cmd("SET", "t2", "v")
        self.m.cmd("EXPIRE", "t2", 50)
        self.m.cmd("DEL", "t1")
        self.m.cmd("EXPIRE", "t2", 0)                        # 非正数：删除路径
        self.assertTrue(wait_until(lambda: linked_and_synced(self.master, self.replica)))
        self.assertEqual(self.master.store.expires, {})
        self.assertEqual(self.replica.store.expires, {})

    def test_reconcile_helper_has_teeth(self):
        """负面自证：对账器必须能抓到人为分叉（否则上面所有 reconcile 都是装饰）。"""
        self.link_replica()
        self.m.cmd("SET", "k", "v")
        self.assertTrue(wait_until(lambda: not reconcile(self.master, self.replica)))
        self.replica.store.data[b"ghost"] = b"1"             # 人为塞一个多键
        problems = reconcile(self.master, self.replica)
        self.assertTrue(any("多键" in p and "ghost" in p for p in problems), problems)
        del self.replica.store.data[b"ghost"]
        self.replica.store.data[b"k"] = b"tampered"          # 人为改值
        problems = reconcile(self.master, self.replica)
        self.assertTrue(any("值不一致" in p for p in problems), problems)

    def test_snapshot_module_reused_for_transfer(self):
        """全量同步载荷就是 dbsnap 格式：从主库手工 PSYNC 下来的字节可直接 decode。"""
        from redislite import dbsnap
        self.m.cmd("SET", "bin", b"\x00\x01\xff")
        raw = Client("127.0.0.1", self.master.port)
        self.addCleanup(raw.close)
        raw.send("PSYNC", "?", "-1")
        raw.read_reply()                                     # FULLRESYNC 行
        entries = dbsnap.decode_snapshot(raw.read_reply())
        self.assertEqual(entries, [(b"bin", b"\x00\x01\xff", None)])


if __name__ == "__main__":
    unittest.main()
