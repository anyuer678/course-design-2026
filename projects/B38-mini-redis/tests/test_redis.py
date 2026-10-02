"""tests/test_redis.py —— B38 自测：解析边界 / 语义表 / 双策略过期 / 交叉对拍 / fuzz / 快照

纪律（和本仓库其它项目一致）：
  1. 语义期望值来自 docs/case-study.md §6 语义表（逐条），错误文本逐字断言；
  2. 协议对拍 = 独立第二解析器（tools/reference_resp.py）交叉读 + 改坏主语料必须两边一致地红；
  3. 过期用**可注入假时钟**做确定性边界（不 sleep）；
  4. fuzz 的验收是"不崩 + 错误必须是定义好的那几种"，随机流种子化。
"""
from __future__ import annotations

import pathlib
import random
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from redislite import (Client, CommandError, ConnectionClosed, Server,          # noqa: E402
                       SnapshotError, Store, load_snapshot, resp, save_snapshot)
import reference_resp as ref                                                    # noqa: E402


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b38-{name}-"))
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


CMD = resp.encode_command


class TestRespParser(unittest.TestCase):
    def test_reply_types_roundtrip(self):
        stream = (resp.encode_simple("OK") + resp.encode_error("ERR x") +
                  resp.encode_int(-42) + resp.encode_bulk(b"bin\r\n\x00ary") +
                  resp.encode_bulk(None) + resp.encode_array([1, b"a", None]))
        values = resp.decode_replies(stream)
        self.assertEqual(values[0], b"OK")
        self.assertEqual(values[1], resp.RespError("ERR x"))
        self.assertEqual(values[2], -42)
        self.assertEqual(values[3], b"bin\r\n\x00ary")
        self.assertIsNone(values[4])
        self.assertEqual(values[5], [1, b"a", None])

    def test_streaming_chunking_equivalence(self):
        stream = CMD("SET", "k", "v\r\n\x00bin") + b"PING\r\n" + CMD("GET", "k")
        whole = resp.decode_commands(stream)
        rng = random.Random(7)
        for _ in range(20):
            dec = resp.FrameDecoder()
            got = []
            pos = 0
            while pos < len(stream):
                n = rng.randint(1, 9)
                dec.feed(stream[pos:pos + n])
                pos += n
                while True:
                    frame = dec.next_command()
                    if frame is resp.INCOMPLETE:
                        break
                    if frame:
                        got.append(frame)
            self.assertEqual(got, whole)

    def test_inline_and_array_mixed(self):
        stream = (b"PING\r\n" + CMD("SET", "k", "v") + b'set q "a b"\r\n' +
                  b"\r\n" + CMD("GET") + b"del x\r\n")
        self.assertEqual(resp.decode_commands(stream),
                         [[b"PING"], [b"SET", b"k", b"v"], [b"set", b"q", b"a b"],
                          [b"GET"], [b"del", b"x"]])
        # *0 / *-1 / 空内联行都是"无命令"，且与随后的命令并存
        self.assertEqual(resp.decode_commands(b"*0\r\n*-1\r\n\r\nPING\r\n"),
                         [[b"PING"]])

    def test_inline_quote_spec(self):
        self.assertEqual(resp.decode_commands(b'"a b" c\r\n'), [[b"a b", b"c"]])
        self.assertEqual(resp.decode_commands(b'""\r\n'), [[b""]])          # 空参数保留
        self.assertEqual(resp.decode_commands(b'a"b"\r\n'), [[b'a"b"']])    # token 内引号是字面量
        with self.assertRaises(resp.ProtocolError) as ctx:
            resp.decode_commands(b'"a"b\r\n')                                # 引号后必须空白/行尾
        self.assertEqual(str(ctx.exception), "unbalanced quotes in request")
        with self.assertRaises(resp.ProtocolError):
            resp.decode_commands(b'"open\r\n')

    def test_strict_headers(self):
        # $01 前导零 → invalid bulk length（string2ll 口径）
        with self.assertRaises(resp.ProtocolError) as ctx:
            resp.decode_commands(b"*1\r\n$01\r\nx\r\n")
        self.assertEqual(str(ctx.exception), "invalid bulk length")
        with self.assertRaises(resp.ProtocolError) as ctx:
            resp.decode_commands(b"*1e2\r\n")
        self.assertEqual(str(ctx.exception), "invalid multibulk length")

    def test_protocol_error_taxonomy(self):
        cases = [
            (b"*x\r\n", "invalid multibulk length"),
            (b"*-2\r\n", "invalid multibulk length"),
            (b"*1\r\n+PING\r\n", "expected '$', got '+'"),
            (b"*1\r\n$-1\r\n", "invalid bulk length"),
            (b"*1\r\n$99999999999999999999\r\n", "invalid bulk length"),
            (b"x" * (resp.MAX_INLINE + 10), "too big inline request"),
        ]
        for wire, message in cases:
            with self.assertRaises(resp.ProtocolError, msg=wire[:30]) as ctx:
                resp.decode_commands(wire)
            self.assertEqual(str(ctx.exception), message, msg=wire[:30])

    def test_encode_command_coerces_numbers(self):
        """踩过的坑钉住：int 参数必须编成 bulk（`10` 不是整数帧 `:10`）。"""
        wire = resp.encode_command("EXPIRE", "k", 10)
        self.assertNotIn(b":", wire)
        self.assertEqual(resp.decode_commands(wire), [[b"EXPIRE", b"k", b"10"]])
        with self.assertRaises(resp.ProtocolError):
            resp.decode_commands(b"*2\r\n$3\r\nGET\r\n:1\r\n")   # 手写整数帧：非法请求


class TestCrossCheck(unittest.TestCase):
    def _request_corpus(self) -> bytes:
        cases = [b"PING\r\n", b"ping\r\n", b'set k "a b"\r\n', b"\r\n", b"*0\r\n",
                 CMD("SET", b"k\x00y", b"v\r\nbin"), CMD("GET", "k"), CMD("DEL", "a", "b"),
                 b'del "x y" z\r\n', b"*-1\r\n", CMD("INCR", "n"),
                 b"PING\r\n" + CMD("GET") + b"FOO bar\r\n"]
        return b"".join(cases)

    def _reply_corpus(self) -> bytes:
        return (resp.encode_simple("OK") + resp.encode_error("ERR nope") +
                resp.encode_int(0) + resp.encode_int(-9223372036854775808) +
                resp.encode_bulk(b"") + resp.encode_bulk(b"\r\n\x00") +
                resp.encode_bulk(None) +
                resp.encode_array([b"a", 1, None, [b"n", -7]]) +
                resp.encode_array([]) + resp.encode_array(None))

    def test_requests_agree(self):
        corpus = self._request_corpus()
        self.assertEqual(resp.decode_commands(corpus), ref.parse_requests(corpus))

    def test_replies_agree(self):
        corpus = self._reply_corpus()
        mine = resp.decode_replies(corpus)
        theirs = ref.decode_replies(corpus)
        normalized = [("-", v.message) if isinstance(v, resp.RespError) else v for v in mine]
        self.assertEqual(normalized, theirs)

    def test_bad_streams_rejected_with_same_message(self):
        bad = [b"*x\r\n", b"*-2\r\n", b"*1\r\n+PING\r\n", b"*1\r\n$-1\r\n",
               b"*1\r\n$03\r\nx\r\n", b'"open\r\n', b'"a"b\r\n']
        for wire in bad:
            with self.assertRaises(resp.ProtocolError, msg=wire) as mine:
                resp.decode_commands(wire)
            with self.assertRaises(ref.RefProtocolError, msg=wire) as theirs:
                ref.parse_requests(wire)
            self.assertEqual(str(mine.exception), str(theirs.exception), msg=wire)

    def test_corrupted_corpus_never_disagrees(self):
        """改坏一处字节：两器要么都拒、要么都收——不允许一个收一个拒。"""
        corpus = self._request_corpus()
        rng = random.Random(11)
        checked = 0
        for pos in range(len(corpus)):
            if rng.random() > 0.35:
                continue
            mutated = bytearray(corpus)
            mutated[pos] ^= 0x20                      # 只翻一个字母位
            wire = bytes(mutated)
            mine = theirs = None
            try:
                mine = resp.decode_commands(wire)
            except resp.ProtocolError:
                mine = None
            try:
                theirs = ref.parse_requests(wire)
            except ref.RefProtocolError:
                theirs = None
            same = (mine is None) == (theirs is None)
            self.assertTrue(same, msg=f"pos={pos} wire={wire[:40]!r}")
            if mine is not None:
                self.assertEqual(mine, theirs, msg=f"pos={pos}")
            checked += 1
        self.assertGreaterEqual(checked, 15)          # 抽样不许太小


class TestStoreSemantics(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = Store(clock=self.clock)

    def d(self, *args):
        return self.store.dispatch([a.encode() if isinstance(a, str) else a for a in args])

    def test_set_get_del(self):
        self.d("SET", "k", "v")
        self.assertEqual(self.d("GET", "k"), b"v")
        self.assertIsNone(self.d("GET", "missing"))
        self.assertEqual(self.d("DEL", "k"), 1)
        self.assertEqual(self.d("DEL", "k"), 0)

    def test_set_clears_ttl(self):
        self.d("SET", "k", "v")
        self.d("EXPIRE", "k", "10")
        self.assertEqual(self.d("TTL", "k"), 10)
        self.d("SET", "k", "v2")
        self.assertEqual(self.d("TTL", "k"), -1)

    def test_expire_ttl_boundaries(self):
        self.d("SET", "k", "v")
        self.assertEqual(self.d("EXPIRE", "k", "10"), 1)
        self.assertEqual(self.d("TTL", "k"), 10)
        self.clock.advance(0.5)
        self.assertEqual(self.d("TTL", "k"), 9)            # 向下取整
        self.clock.advance(9.0)                            # 剩 0.5s
        self.assertEqual(self.d("TTL", "k"), 0)
        self.assertEqual(self.d("GET", "k"), b"v")         # 还没到期
        self.clock.advance(0.5)                            # 恰好到 deadline
        self.assertIsNone(self.d("GET", "k"))              # deadline ≤ now 即过期
        self.assertEqual(self.d("TTL", "k"), -2)
        self.assertEqual(self.d("EXPIRE", "missing", "5"), 0)

    def test_expire_nonpositive_deletes(self):
        for seconds in ("0", "-1"):
            self.d("SET", "k", "v")
            self.assertEqual(self.d("EXPIRE", "k", seconds), 1)
            self.assertIsNone(self.d("GET", "k"))
            self.assertEqual(self.d("TTL", "k"), -2)

    def test_expire_override_and_ttl_codes(self):
        self.d("SET", "k", "v")
        self.assertEqual(self.d("TTL", "k"), -1)           # 无过期
        self.d("EXPIRE", "k", "100")
        self.d("EXPIRE", "k", "5")
        self.assertEqual(self.d("TTL", "k"), 5)            # 覆盖旧时间

    def test_lazy_expiry_counts(self):
        self.d("SET", "k", "v")
        self.d("EXPIRE", "k", "1")
        self.clock.advance(2)
        self.assertIsNone(self.d("GET", "k"))
        self.assertEqual(self.store.stats["expired_lazy"], 1)
        self.assertEqual(self.store.stats["expired_active"], 0)

    def test_incr_semantics(self):
        self.assertEqual(self.d("INCR", "n"), 1)
        self.assertEqual(self.d("INCR", "n"), 2)
        self.d("SET", "k", "-5")
        self.assertEqual(self.d("INCR", "k"), -4)
        self.d("SET", "z", "0")
        self.assertEqual(self.d("INCR", "z"), 1)
        self.d("SET", "t", "1")
        self.d("EXPIRE", "t", "10")
        self.d("INCR", "t")
        self.assertEqual(self.d("TTL", "t"), 10)           # INCR 保留 TTL

    def test_incr_strict_grammar_and_errors(self):
        for bad in ("1.0", " 1", "+1", "01", "-0", ""):
            self.d("SET", "k", bad)
            with self.assertRaises(CommandError, msg=repr(bad)) as ctx:
                self.d("INCR", "k")
            self.assertEqual(str(ctx.exception),
                             "ERR value is not an integer or out of range", msg=repr(bad))
        self.d("SET", "big", "9223372036854775807")
        with self.assertRaises(CommandError) as ctx:
            self.d("INCR", "big")
        self.assertEqual(str(ctx.exception), "ERR increment or decrement would overflow")
        self.d("SET", "huge", "9223372036854775808")       # 超出 int64：文法错误
        with self.assertRaises(CommandError) as ctx:
            self.d("INCR", "huge")
        self.assertEqual(str(ctx.exception), "ERR value is not an integer or out of range")
        self.d("SET", "low", "-9223372036854775808")
        self.assertEqual(self.d("INCR", "low"), -9223372036854775807)

    def test_command_errors_text(self):
        with self.assertRaises(CommandError) as ctx:
            self.d("FOO", "bar")
        self.assertEqual(str(ctx.exception), "ERR unknown command 'FOO'")
        with self.assertRaises(CommandError) as ctx:
            self.d("GET")
        self.assertEqual(str(ctx.exception), "ERR wrong number of arguments for 'get' command")
        with self.assertRaises(CommandError) as ctx:
            self.d("PING", "a", "b")
        self.assertEqual(str(ctx.exception), "ERR wrong number of arguments for 'ping' command")

    def test_active_expire_cycles(self):
        # 全过期：一轮采样 4×20=80 个（过期率 100% 一直触发），再来一轮清空
        for i in range(100):
            self.d("SET", f"k{i}", "v")
            self.d("EXPIRE", f"k{i}", "5")
        self.clock.advance(6)
        first = self.store.active_expire_cycle()
        self.assertEqual(first, 80)                        # 采样确定性（全过期）
        second = self.store.active_expire_cycle()
        self.assertEqual(second, 20)
        self.assertEqual(self.store.expires, {})
        self.assertEqual(self.store.stats["expired_active"], 100)
        self.assertEqual(self.store.stats["expired_lazy"], 0)   # 一个都没被访问过

    def test_active_expire_noop_when_fresh(self):
        for i in range(30):
            self.d("SET", f"k{i}", "v")
            self.d("EXPIRE", f"k{i}", "100")
        self.assertEqual(self.store.active_expire_cycle(), 0)   # 过期率 0 → 首轮即收工
        self.assertEqual(len(self.store.expires), 30)


class TestServer(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.server = Server(port=0, clock=self.clock, active_every=64).start()
        self.addCleanup(self.server.stop)

    def client(self) -> Client:
        client = Client("127.0.0.1", self.server.port)
        self.addCleanup(client.close)
        return client

    def test_roundtrip(self):
        c = self.client()
        self.assertEqual(c.cmd("PING"), b"PONG")
        self.assertEqual(c.cmd("PING", "hi"), b"hi")
        self.assertEqual(c.cmd("SET", "k", "v"), b"OK")
        self.assertEqual(c.cmd("GET", "k"), b"v")
        self.assertEqual(c.cmd("INCR", "n"), 1)
        self.assertEqual(c.cmd("EXPIRE", "k", 10), 1)
        self.assertEqual(c.cmd("TTL", "k"), 10)
        self.assertEqual(c.cmd("DEL", "k"), 1)

    def test_pipelining(self):
        c = self.client()
        c.send_raw(CMD("PING") + CMD("SET", "p", "1") + CMD("GET", "p") + CMD("INCR", "p"))
        self.assertEqual(c.read_replies(4), [b"PONG", b"OK", b"1", 2])   # p="1" → INCR 后 2
    def test_partial_command_across_packets(self):
        import time
        c = self.client()
        wire = CMD("SET", "slow", "ok")
        c.send_raw(wire[:7])
        time.sleep(0.05)
        c.send_raw(wire[7:])
        self.assertEqual(c.read_reply(), b"OK")
        self.assertEqual(c.cmd("GET", "slow"), b"ok")

    def test_multi_client_shared_and_isolated(self):
        a, b = self.client(), self.client()
        self.assertEqual(a.cmd("SET", "shared", "1"), b"OK")
        self.assertEqual(b.cmd("GET", "shared"), b"1")
        self.assertEqual(a.cmd("INCR", "cnt"), 1)
        self.assertEqual(b.cmd("INCR", "cnt"), 2)          # 单线程串行：天然原子
        self.assertEqual(self.server.stats["connections"], 2)

    def test_protocol_error_isolated(self):
        good = self.client()
        bad = self.client()
        bad.send_raw(b"*2\r\n$3\r\nGET\r\n:1\r\n")          # 整数帧当元素：非法请求
        reply = bad.read_reply()
        self.assertEqual(reply, resp.RespError("ERR Protocol error: expected '$', got ':'"))
        with self.assertRaises(ConnectionClosed):
            bad.cmd("PING")                                 # 错误帧之后连接被关
        self.assertEqual(good.cmd("PING"), b"PONG")         # 好连接毫发无损
        self.assertEqual(self.server.stats["protocol_errors"], 1)

    def test_expiry_over_network(self):
        c = self.client()
        self.assertEqual(c.cmd("SET", "k", "v"), b"OK")
        self.assertEqual(c.cmd("EXPIRE", "k", 10), 1)
        self.clock.advance(11)
        self.assertIsNone(c.cmd("GET", "k"))
        self.assertEqual(c.cmd("TTL", "k"), -2)

    def test_active_expiry_triggered_by_commands(self):
        server = Server(port=0, clock=self.clock, active_every=8).start()
        self.addCleanup(server.stop)
        c = Client("127.0.0.1", server.port)
        self.addCleanup(c.close)
        for i in range(30):
            c.cmd("SET", f"k{i}", "v")
            c.cmd("EXPIRE", f"k{i}", 5)
        self.clock.advance(6)
        for _ in range(8):                                  # 触发一次主动周期
            c.cmd("PING")
        self.assertGreater(server.store.stats["expired_active"], 0)
        self.assertEqual(server.store.stats["expired_lazy"], 0)   # 没人 GET 过任何键

    def test_reconnect_keeps_data(self):
        c1 = self.client()
        c1.cmd("SET", "persist", "yes")
        c1.close()
        c2 = self.client()
        self.assertEqual(c2.cmd("GET", "persist"), b"yes")

    def test_save_and_reload_on_restart(self):
        tmp = make_tmp("db")
        self.addCleanup(shutil.rmtree, tmp, True)
        dbfile = tmp / "dump.rl"
        server = Server(port=0, clock=self.clock, dbfile=dbfile).start()
        self.addCleanup(server.stop)
        c = Client("127.0.0.1", server.port)
        self.addCleanup(c.close)
        c.cmd("SET", "a", "1")
        c.cmd("SET", "b", "x" * 50)
        c.cmd("EXPIRE", "b", 60)
        self.assertEqual(c.cmd("SAVE"), b"OK")
        self.assertTrue(dbfile.exists())
        server.stop()
        clock2 = FakeClock(start=self.clock.t)              # 重启：墙钟继续
        server2 = Server(port=0, clock=clock2, dbfile=dbfile).start()
        self.addCleanup(server2.stop)
        c2 = Client("127.0.0.1", server2.port)
        self.addCleanup(c2.close)
        self.assertEqual(c2.cmd("GET", "a"), b"1")
        self.assertEqual(c2.cmd("GET", "b"), b"x" * 50)
        self.assertEqual(c2.cmd("TTL", "b"), 60)            # 绝对到期时刻被保留

    def test_corrupt_dbfile_refuses_start(self):
        tmp = make_tmp("bad")
        self.addCleanup(shutil.rmtree, tmp, True)
        dbfile = tmp / "dump.rl"
        save_snapshot(dbfile, [(b"k", b"v", None)])
        raw = dbfile.read_bytes()
        dbfile.write_bytes(raw[:15] + bytes([raw[15] ^ 0xFF]) + raw[16:])
        with self.assertRaises(SnapshotError):
            Server(port=0, clock=self.clock, dbfile=dbfile)


class TestFuzz(unittest.TestCase):
    def test_parser_fuzz_never_crashes(self):
        rng = random.Random(2026)
        for _ in range(400):
            length = rng.randint(0, 64)
            blob = bytes(rng.randrange(256) for _ in range(length))
            dec = resp.FrameDecoder()
            dec.feed(blob)
            try:
                while True:
                    frame = dec.next_command()
                    if frame is resp.INCOMPLETE:
                        break
            except resp.ProtocolError:
                pass                                        # 只允许定义好的协议错误
            # 回复方向同理
            dec2 = resp.FrameDecoder()
            dec2.feed(blob)
            try:
                while True:
                    frame = dec2.next_frame()
                    if frame is resp.INCOMPLETE or frame is resp.ProtocolError:
                        break
            except resp.ProtocolError:
                pass

    def test_server_fuzz_survives(self):
        server = Server(port=0).start()
        self.addCleanup(server.stop)
        # 保底结构化坏包：必须收到"协议化错误"并断开（确定性的那部分）
        guaranteed = [b"*x\r\n", b"*2\r\n$3\r\nGET\r\n:1\r\n", b"*1\r\n+oops\r\n"]
        for blob in guaranteed:
            c = Client("127.0.0.1", server.port, timeout=0.5)
            c.send_raw(blob)
            reply = c.read_reply()
            self.assertIsInstance(reply, resp.RespError, msg=blob)
            self.assertIn("Protocol error", reply.message, msg=blob)
            with self.assertRaises(ConnectionClosed):
                c.cmd("PING")
            c.close()
        # 随机字节流：不崩即可（允许超时——没 CRLF 的行会让服务器等下去）
        rng = random.Random(7)
        for _ in range(25):
            c = Client("127.0.0.1", server.port, timeout=0.2)
            c.send_raw(bytes(rng.randrange(256) for _ in range(rng.randint(1, 48))))
            try:
                c.read_reply()
            except OSError:
                pass
            c.close()
        with Client("127.0.0.1", server.port) as c:         # 服务器必须还活着且能干活
            self.assertEqual(c.cmd("PING"), b"PONG")
            self.assertEqual(c.cmd("SET", "k", "v"), b"OK")
            self.assertEqual(c.cmd("GET", "k"), b"v")
        self.assertGreaterEqual(server.stats["protocol_errors"], 3)


class TestSnapshot(unittest.TestCase):
    def test_roundtrip_and_atomic(self):
        tmp = make_tmp("snap")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "dump.rl"
        entries = [(b"a", b"1", None), (b"bin\x00\r\n", b"\xff\x00val", 12345.5)]
        size = save_snapshot(path, entries)
        self.assertGreater(size, 0)
        self.assertFalse((tmp / "dump.rl.tmp").exists())    # 原子写：临时文件不残留
        self.assertEqual(load_snapshot(path), entries)

    def test_corrupt_and_version_errors(self):
        tmp = make_tmp("snap2")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "dump.rl"
        save_snapshot(path, [(b"k", b"v", None)])
        raw = path.read_bytes()
        path.write_bytes(b"OTHERMAGIC" + raw[10:])
        with self.assertRaises(SnapshotError):
            load_snapshot(path)
        path.write_bytes(raw)
        bad = bytearray(raw)
        bad[-3] ^= 0xFF                                     # 校验行前改一个字节
        path.write_bytes(bytes(bad))
        with self.assertRaises(SnapshotError):
            load_snapshot(path)


if __name__ == "__main__":
    unittest.main()
