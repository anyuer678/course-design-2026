"""demo.py —— B38 六段演示：基础命令 → 协议边界 → 过期双策略 → 语义表 → 对拍与 fuzz → 快照。

确定性说明：过期/快照用**假墙钟**（时间由脚本推进），fuzz 用固定种子，
整条演示除标注【实测】的一行吞吐外两次运行逐字一致（tools/logdiff.py 可核对）。
"""
from __future__ import annotations

import pathlib
import random
import shutil
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from redislite import (Client, ConnectionClosed, RespError, Server,              # noqa: E402
                       SnapshotError, Store, load_snapshot, resp, save_snapshot)
import reference_resp as ref                                                     # noqa: E402


def section(no: int, title: str) -> None:
    print("\n" + "=" * 78 + f"\n  {no}) {title}\n" + "=" * 78)


def show(label: str, value: object) -> None:
    print(f"  {label:<30}{value}")


class Clock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


def main() -> int:
    print("B38-mini-redis 演示：RESP2 + 单线程事件循环 + 惰性/主动双策略过期（软件工程案例）")
    clock = Clock()
    server = Server(port=0, clock=clock, active_every=64).start()
    try:
        # -------------------------------------------------------------- 1
        section(1, "启动与基础命令（真实套接字，单线程 selectors 服务）")
        c = Client("127.0.0.1", server.port)
        show("PING / PING msg", f"{c.cmd('PING')!r} / {c.cmd('PING', 'hello')!r}")
        show("SET / GET / INCR", f"{c.cmd('SET', 'k', 'v')!r} / {c.cmd('GET', 'k')!r} / {c.cmd('INCR', 'n')!r}")
        show("GET 不存在 / DEL", f"{c.cmd('GET', 'nope')!r} / {c.cmd('DEL', 'k')!r}")
        show("TTL 三态（无过期/不存在）", f"{c.cmd('SET', 'k2', 'v')!r} → TTL={c.cmd('TTL', 'k2')!r}；"
                                          f"missing → TTL={c.cmd('TTL', 'xx')!r}")

        # -------------------------------------------------------------- 2
        section(2, "协议边界：内联×数组混合、管线、二进制安全（同一份解码器两端共用）")
        mixed = (b'PING\r\n' + resp.encode_command("SET", "bin", b"a\r\n\x00b") +
                 b'set q "x y"\r\n' + resp.encode_command("GET", "bin"))
        show("一段混合字节流解出命令数", len(resp.decode_commands(mixed)))
        c.send_raw(mixed)
        replies = c.read_replies(4)
        show("四次回复（含二进制值）", replies)
        show("管线：一次写 3 条", f"发送 {resp.encode_command('SET','p','1')!r} + GET + INCR → "
                                  f"{_pipeline(c)}")

        # -------------------------------------------------------------- 3
        section(3, "过期双策略：惰性保障读不到，主动采样保障不占内存（假时钟推进）")
        c.cmd("SET", "lazy", "v")
        c.cmd("EXPIRE", "lazy", 10)
        clock.advance(11)
        show("到期后 GET（惰性）", f"{c.cmd('GET', 'lazy')!r}；lazy 计数="
                                   f"{server.store.stats['expired_lazy']}")
        for i in range(100):
            c.cmd("SET", f"e{i}", "v")
            c.cmd("EXPIRE", f"e{i}", 5)
        clock.advance(6)
        for _ in range(64):                                  # 触发主动周期（每 64 条命令一次）
            c.cmd("PING")
        show("100 键到期后（从未 GET）", f"active 删除={server.store.stats['expired_active']}，"
                                         f"剩余 expires={len(server.store.expires)}")
        show("EXPIRE 0 / 负数（立即删除）", f"{c.cmd('SET', 'z', 'v')!r} → {c.cmd('EXPIRE', 'z', 0)!r} → "
                                            f"GET={c.cmd('GET', 'z')!r}")

        # -------------------------------------------------------------- 4
        section(4, "语义表抽查：INCR 严格整数文法与溢出、命令错误文本逐字")
        for bad in ("01", "1.0", "+1", "-0"):
            c.cmd("SET", "bad", bad)
            show(f"INCR 值 {bad!r}", c.cmd("INCR", "bad"))
        c.cmd("SET", "big", "9223372036854775807")
        show("INCR 溢出", c.cmd("INCR", "big"))
        show("未知命令 / 参数个数", f"{c.cmd('FOO', 'bar')} / {c.cmd('GET')}")

        # -------------------------------------------------------------- 5
        section(5, "对拍与 fuzz：第二解析器交叉读；坏包必须协议化 + 服务器不倒")
        corpus = mixed
        mine = resp.decode_commands(corpus)
        theirs = ref.parse_requests(corpus)
        show("交叉读（命令与参照实现）", f"逐条相等：{mine == theirs}（{len(mine)} 条命令）")
        reply_corpus = (resp.encode_simple("OK") + resp.encode_error("ERR x") +
                        resp.encode_int(-7) + resp.encode_array([1, b"a", None]))
        norm = [("-", v.message) if isinstance(v, RespError) else v
                for v in resp.decode_replies(reply_corpus)]
        show("回复流交叉读", f"逐条相等：{norm == ref.decode_replies(reply_corpus)}")
        rng = random.Random(2026)
        proto_hits = 0
        others = 0
        for _ in range(200):
            dec = resp.FrameDecoder()
            dec.feed(bytes(rng.randrange(256) for _ in range(rng.randint(0, 64))))
            try:
                while dec.next_command() is not resp.INCOMPLETE:
                    pass
            except resp.ProtocolError:
                proto_hits += 1
            except Exception:                                 # noqa: BLE001 - fuzz：除协议错误外都不允许
                others += 1
        crafted = [b"*x\r\n", b"*1\r\n+PING\r\n", b"*1\r\n$01\r\nx\r\n", b"*1\r\n$-1\r\n",
                   b'"open\r\n', b'"a"b\r\n']
        crafted_rejected = 0
        for wire in crafted:
            try:
                resp.decode_commands(wire)
            except resp.ProtocolError:
                crafted_rejected += 1
        show("解析器 fuzz 200 条随机流", f"协议错误 {proto_hits} 次、非协议异常 {others} 次"
                                         f"（后者必须为 0）")
        show("构造坏帧 6 条", f"全部报协议错误：{crafted_rejected == len(crafted)}"
                              f"（{'、'.join(str(len(w)) + 'B' for w in crafted)}）")
        bombs = [b"*x\r\n", b"*2\r\n$3\r\nGET\r\n:1\r\n", b"*1\r\n+oops\r\n"]
        for blob in bombs:
            bad = Client("127.0.0.1", server.port, timeout=1.0)
            bad.send_raw(blob)
            bad.read_reply()                                  # 协议化错误
            try:
                bad.cmd("PING")
            except ConnectionClosed:
                pass
            bad.close()
        for _ in range(20):                                   # 随机字节：只发不读，服务器统计为准
            bad = Client("127.0.0.1", server.port, timeout=0.5)
            bad.send_raw(bytes(rng.randrange(256) for _ in range(rng.randint(1, 48))))
            bad.close()
        show("服务器 fuzz（3 结构化 + 20 随机）", f"protocol_errors 累计={server.stats['protocol_errors']}；"
                                                  f"新连接 PING={c.cmd('PING')!r}")

        # -------------------------------------------------------------- 6
        section(6, "快照：原子写 + 校验和；重启加载；坏文件拒启 + 吞吐【实测】")
        tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="b38-demo-"))
        db = tmpdir / "dump.rl"
        s2 = Server(port=0, clock=clock, dbfile=db).start()
        try:
            c2 = Client("127.0.0.1", s2.port)
            c2.cmd("SET", "snapkey", "snapvalue")
            c2.cmd("EXPIRE", "snapkey", 60)
            show("SAVE", c2.cmd("SAVE"))
            size = db.stat().st_size
            entries = load_snapshot(db)
            show("快照文件", f"dump.rl（{size} 字节，{len(entries)} 条目，含 SHA256 校验和）")
            raw = db.read_bytes()
            db.write_bytes(raw[:20] + bytes([raw[20] ^ 0xFF]) + raw[21:])
            try:
                load_snapshot(db)
                show("坏文件检测", "没有抓住（BUG）")
            except SnapshotError:
                show("坏文件检测", "改坏一字节 → SnapshotError（拒绝带病加载）")
            try:
                Server(port=0, clock=clock, dbfile=db)
                show("坏文件拒启", "没有抓住（BUG）")
            except SnapshotError:
                show("坏文件拒启", "服务器构造即拒绝（不带病启动）")
            db.write_bytes(raw)
            c2.close()
            s2.stop()
            s3 = Server(port=0, clock=clock, dbfile=db).start()   # 重启：从快照恢复
            try:
                c3 = Client("127.0.0.1", s3.port)
                show("重启后 GET / TTL", f"{c3.cmd('GET', 'snapkey')!r} / "
                                         f"TTL={c3.cmd('TTL', 'snapkey')!r}（绝对到期时刻保留）")
                c3.close()
            finally:
                s3.stop()
        finally:
            s2.stop()
            shutil.rmtree(tmpdir, ignore_errors=True)
        t0 = time.perf_counter()
        for _ in range(2000):
            c.cmd("INCR", "bench")
        elapsed = (time.perf_counter() - t0) * 1000
        show("吞吐：2000 次 INCR 往返", f"{elapsed:>10.1f} ms【实测】（本机回环，单线程）")
        c.close()

        print("\n" + "=" * 78)
        print(f"  服务器统计：{server.stats}；过期统计：{server.store.stats}")
        print("  明确不是完整 Redis：只有字符串类型与 8 条命令，无事务/订阅/复制/集群；")
        print("  设计要点、子集与偏离表见 docs/case-study.md。")
        return 0
    finally:
        server.stop()


def _pipeline(c: Client):
    c.send_raw(resp.encode_command("SET", "p", "1") + resp.encode_command("GET", "p") +
               resp.encode_command("INCR", "p"))
    return c.read_replies(3)


if __name__ == "__main__":
    raise SystemExit(main())
