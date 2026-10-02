"""B11-net-lab 演示：HTTP 子集 → keep-alive/多路复用 → 边界拒绝 → UDP → GBN。

只绑 127.0.0.1，端口由系统分配，跑完全部关掉。
    python demo.py
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from netlab import gbn, udp                                              # noqa: E402
from netlab.client import Connection, encode_request, one_shot           # noqa: E402
from netlab.http1 import HttpError, parse_request                       # noqa: E402
from netlab.server import Server                                         # noqa: E402

BAR = "=" * 72


def title(index: int, text: str) -> None:
    print(f"\n{BAR}\n[{index}/5] {text}\n{BAR}")


def show_bytes(label: str, data: bytes, limit: int = 260) -> None:
    text = data.decode("utf-8", "replace")
    if len(text) > limit:
        text = text[:limit] + f"…（共 {len(data)} 字节）"
    print(f"  {label}:")
    for line in text.splitlines() or [""]:
        print(f"    | {line}" if line else "    |")


def show_request(request) -> None:
    print(f"  解析结论: {request.method} {request.path!r} 版本={request.version} "
          f"keep-alive={request.keep_alive} 体={len(request.body)} 字节")
    print(f"  头部: {request.headers}")
    print(f"  查询: {request.query}")


def show_response(response) -> None:
    print(f"  响应: HTTP/{response.version} {response.status} {response.reason} "
          f"体={response.body[:60]!r}")


def main() -> int:
    server = Server(port=0)
    server.start()
    print(f"netlab 演示：服务器已在 127.0.0.1:{server.port} 启动（单线程 + select）")

    try:
        # -------------------------------------------------------- 1 一条请求的旅程
        title(1, "一条请求的完整旅程：字节 → 解析 → 路由 → 响应字节")
        wire = encode_request("PUT", "/kv/repair", body="水管漏水".encode("utf-8"))
        show_bytes("客户端发出的请求字节", wire)
        parsed, used = parse_request(wire)
        print(f"  消耗字节: {used}")
        show_request(parsed)
        response = one_shot(server.port, "PUT", "/kv/repair", body="水管漏水".encode("utf-8"))
        show_response(response)
        with Connection(port=server.port) as conn:
            conn.send(encode_request("GET", "/kv/repair", close=True))
            raw = b""
            while True:
                chunk = conn.sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
            show_bytes("同一请求的原始响应字节", raw)

        # -------------------------------------------------------- 2 CRUD 与路由
        title(2, "应用路由：键值表的增删改查 + 查询串")
        for method, target, body in [
            ("GET", "/", b""),
            ("PUT", "/kv/name", b"anyuer"),
            ("PUT", "/kv/city", b"hangzhou"),
            ("GET", "/kv", b""),
            ("GET", "/kv/name", b""),
            ("POST", "/kv/name", b"renamed"),
            ("GET", "/sum?a=1.5&b=27", b""),
            ("GET", "/echo?text=hello+world%21", b""),
            ("DELETE", "/kv/city", b""),
            ("GET", "/kv/city", b""),
        ]:
            r = one_shot(server.port, method, target, body=body)
            text = r.text().strip().replace("\r\n", " / ").replace("\n", " / ")
            print(f"  {method:6s} {target:26s} -> {r.status} "
                  f"{text[:56] + '…' if len(text) > 57 else text!r}")
        print("  说明：204 没体所以不带 Content-Length；HEAD 带长度但不带体；"
              "405 会附 Allow；`..` 上跳在解析层就被拒。")

        # -------------------------------------------------------- 3 复用、并发与拒绝
        title(3, "keep-alive、多路复用，以及每一种越界被拒的样子")
        with Connection(port=server.port) as conn:
            for target in ("/", "/kv", "/stats"):
                show_response(conn.request("GET", target))
            print(f"  一条连接上跑了 3 个请求：连接数="
                  f"{server.stats.connections} 请求数={server.stats.requests}")

        clients = []
        gate = threading.Event()

        def chatter(i: int) -> None:
            with Connection(port=server.port) as c:
                c.request("GET", "/")
                gate.wait(5)                       # 大家都在此挂着，逼出并发
                c.request("GET", f"/echo?text=c{i}")
            clients.append(i)

        threads = [threading.Thread(target=chatter, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        time.sleep(0.2)
        peak_now = server.stats.open_now
        gate.set()
        for t in threads:
            t.join(10)
        print(f"  8 个客户端同时挂着时服务端同时持有 {peak_now} 条连接，"
              f"历史峰值 {server.stats.peak_open}（始终只有一条线程）")

        print("\n  越界请求的响应码：")
        bad_cases = [
            ("请求目标超长", b"GET /" + b"a" * 3000 + b" HTTP/1.1\r\n\r\n"),
            ("头部条数超限", b"GET / HTTP/1.1\r\n" + b"X: 1\r\n" * 200 + b"\r\n"),
            ("裸 LF 换行", b"GET / HTTP/1.1\n\n"),
            ("chunked（不支持也不忽略）",
             b"POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n"),
            ("两个不一致的 Content-Length",
             b"POST / HTTP/1.1\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\nab"),
            ("声明巨体", b"POST / HTTP/1.1\r\nContent-Length: 99999999\r\n\r\n"),
            ("不认识的版本", b"GET / HTTP/2.0\r\n\r\n"),
            ("路径上跳", b"GET /a/../b HTTP/1.1\r\n\r\n"),
        ]
        for name, payload in bad_cases:
            with socket.create_connection(("127.0.0.1", server.port), timeout=3) as s:
                s.sendall(payload)
                s.settimeout(3)
                head = s.recv(4096).split(b"\r\n")[0]
            print(f"    {name:28s} -> {head.decode('latin-1')}")

        print("\n  解析层直接抛出的错误（同一条规则在客户端也能挡住）：")
        for sample in (b"GET / HTTP/1.1\n\n",
                       b"POST / HTTP/1.1\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\nab",
                       b"GET /a/%2e%2e/b HTTP/1.1\r\n\r\n"):
            try:
                parse_request(sample)
            except HttpError as exc:
                print(f"    {sample[:38]!r}… -> {exc}")
        print(f"  目前统计：{server.stats.as_dict()}")

        # -------------------------------------------------------- 4 UDP 的裸脾气
        title(4, "UDP：有边界、没顺序、没可靠性")
        a, b = udp.make_pair()
        a.send(b"first-datagram")
        a.send(b"second-datagram")
        print(f"  发两次、收两次，边界原样保留：{b.recv()!r} + {b.recv()!r}")
        print(f"  没人发的时候 recv 只能等到超时返回 None：{b.recv()!r}"
              "  ← 包丢了还是对方根本没说？UDP 不区分，也不告诉你")
        a.close()
        b.close()

        # -------------------------------------------------------- 5 GBN 可靠传输
        title(5, "GBN 滑动窗口：把上面那个不可靠的通道变成按序字节流")
        payload = os.urandom(4096)
        print("  丢包率扫描（窗口=8，seed=7，同一段 4096 字节随机数据）：")
        print("    丢包率  时隙  发送包数  重传  超时  有效载荷比")
        for drop in (0.0, 0.1, 0.2, 0.3, 0.4):
            channel = udp.SimChannel(seed=7, drop=drop)
            result = gbn.run_simulation(payload, channel, mss=256, window=8)
            assert result.received == payload, result.summary()
            print(f"    {drop:5.0%} {result.slots:6d} {result.sender.transmitted:8d}"
                  f" {result.sender.retransmitted:6d} {result.sender.timeouts:5d}"
                  f" {result.efficiency:11.1%}")

        first = gbn.run_simulation(payload, udp.SimChannel(seed=7, drop=0.3), mss=256)
        again = gbn.run_simulation(payload, udp.SimChannel(seed=7, drop=0.3), mss=256)
        print(f"  可复现：同 seed 两次轨迹 {first.slots}=={again.slots} 且 "
              f"发送数 {first.sender.transmitted}=={again.sender.transmitted} "
              f"→ {first.slots == again.slots and first.sender.transmitted == again.sender.transmitted}")

        print("  窗口大小的意义（丢包 20%，同 seed）：")
        for window in (1, 2, 4, 8):
            result = gbn.run_simulation(payload, udp.SimChannel(seed=42, drop=0.2),
                                        mss=256, window=window)
            print(f"    window={window}: 时隙={result.slots} 发送={result.sender.transmitted}")

        wrapped = gbn.run_simulation(os.urandom(200),
                                     udp.SimChannel(seed=17, drop=0.2),
                                     mss=8, window=4, seq_space=8)
        print(f"  序号回绕：space=8、25 个包绕 3 圈，结果仍逐字节一致 → {wrapped.finished}")

        print("  同一套代码跑在真 127.0.0.1 UDP 上：")
        link_a, link_b = udp.make_pair()
        big = os.urandom(30000)
        box = {}
        receiver = threading.Thread(
            target=lambda: box.update(r=gbn.run_real_receiver(link_b, deadline=20)))
        receiver.start()
        started = time.monotonic()
        sender = gbn.run_real_sender(link_a, big, timeout=0.4, window=8, mss=1024,
                                     deadline=20)
        receiver.join(25)
        print(f"    30000 字节：发送完成={sender.done()} 收完={box['r'].finished} "
              f"字节一致={bytes(box['r'].received) == big} "
              f"耗时={time.monotonic() - started:.2f}s 发送包数={sender.transmitted}")
        link_a.close()
        link_b.close()
        return 0
    finally:
        server.stop()
        print("\n服务器与所有连接已关闭。")


if __name__ == "__main__":
    sys.exit(main())
