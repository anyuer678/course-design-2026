"""boardweb/tests/test_ws_board.py —— 协同白板 /ws/board 集成测试：真套接字走
WebSocket 升级（netlab 手写 RFC 6455），验证 握手→peers 计数→增量广播（不回显）
→全量 sync→断开回收 五段链路。

客户端帧按规范掩码（浏览器由内核代劳，测试里自己实现）。
跑法：pytest boardweb/tests/test_ws_board.py -q
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webframe import MicroServer          # noqa: E402
from boardweb.server import build_app     # noqa: E402


def _mask_frame(opcode, payload, *, fin=True):
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    head = bytearray([(0x80 if fin else 0) | opcode])
    n = len(payload)
    if n < 126:
        head.append(0x80 | n)
    elif n < 65536:
        head.append(0x80 | 126)
        head += struct.pack(">H", n)
    else:
        head.append(0x80 | 127)
        head += struct.pack(">Q", n)
    return bytes(head) + mask + masked


class WsClient:
    def __init__(self, port, path="/ws/board"):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self.buf += self.sock.recv(4096)
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        assert b"101" in head.split(b"\r\n")[0], head

    def send_json(self, obj):
        self.sock.sendall(_mask_frame(0x1, json.dumps(obj).encode()))

    def recv_json(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self._pop_frame()
            if msg is not None:
                return msg
            self.sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                return None
            self.buf += chunk
        return None

    def recv_none(self, window=0.5):
        """窗口期内不应有消息（验证"不回显发送方"）。"""
        self.sock.settimeout(window)
        try:
            chunk = self.sock.recv(65536)
        except socket.timeout:
            return True
        if not chunk:
            return True
        self.buf += chunk
        return self._pop_frame() is None

    def _pop_frame(self):
        if len(self.buf) < 2:
            return None
        b1 = self.buf[0]
        if not (b1 & 0x80) or (b1 & 0x0F) != 0x1:
            return None
        b2 = self.buf[1]
        assert not (b2 & 0x80), "服务器帧不许掩码"
        length, pos = b2 & 0x7F, 2
        if length == 126:
            if len(self.buf) < 4:
                return None
            length = struct.unpack(">H", self.buf[2:4])[0]
            pos = 4
        elif length == 127:
            if len(self.buf) < 10:
                return None
            length = struct.unpack(">Q", self.buf[2:10])[0]
            pos = 10
        if len(self.buf) < pos + length:
            return None
        payload = self.buf[pos:pos + length]
        self.buf = self.buf[pos + length:]
        return json.loads(payload.decode("utf-8"))

    def close(self):
        try:
            self.sock.sendall(_mask_frame(0x8, struct.pack(">H", 1000)))
        except OSError:
            pass
        self.sock.close()


class TestWsBoard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.server = MicroServer(build_app(data_dir=Path(self._tmp.name)),
                                  host="127.0.0.1", port=0)
        port = self.server.start()
        self.addCleanup(self.server.stop)
        self.port = port

    def _connect(self):
        client = WsClient(self.port)
        self.addCleanup(client.close)
        return client

    def test_hello_and_peers_broadcast(self):
        a = self._connect()
        self.assertEqual(a.recv_json(), {"type": "hello", "peers": 1})
        b = self._connect()
        self.assertEqual(b.recv_json(), {"type": "hello", "peers": 2})
        self.assertEqual(a.recv_json(), {"type": "peers", "peers": 2})  # b 进场推给 a
        b.close()
        self.assertEqual(a.recv_json(), {"type": "peers", "peers": 1})  # b 退场回收

    def test_add_broadcasts_without_echo(self):
        a, b = self._connect(), self._connect()
        a.recv_json()                                    # hello
        b.recv_json()                                    # hello(peers=2)
        a.recv_json()                                    # peers=2
        shape = {"type": "rect", "x": 1, "y": 2, "w": 3, "h": 4,
                 "color": "#171717", "width": 4}
        a.send_json({"type": "add", "shape": shape})
        got = b.recv_json()
        self.assertEqual(got, {"type": "add", "shape": shape})
        self.assertTrue(a.recv_none())                   # 不回显发送方

    def test_sync_and_clear(self):
        a, b = self._connect(), self._connect()
        a.recv_json(); b.recv_json()                     # 两份 hello
        a.recv_json()                                    # peers=2
        shapes = [{"type": "pen", "pts": [[0, 0], [5, 5]],
                   "color": "#f00", "width": 2}]
        a.send_json({"type": "sync", "shapes": shapes})
        self.assertEqual(b.recv_json(), {"type": "sync", "shapes": shapes})
        a.send_json({"type": "clear"})
        self.assertEqual(b.recv_json(), {"type": "clear"})

    def test_bad_messages_report_error_not_crash(self):
        a = self._connect()
        a.recv_json(); a.recv_json()
        a.send_json({"type": "add"})                     # 缺 shape
        self.assertIn("error", a.recv_json())
        a.send_json({"type": "sync", "shapes": "nope"})  # shapes 非数组
        self.assertIn("error", a.recv_json())
        a.send_json({"type": "mystery"})                 # 未知类型
        self.assertIn("error", a.recv_json())
        a.sock.sendall(_mask_frame(0x1, b"not json"))    # 坏 JSON
        self.assertIn("error", a.recv_json())
        # 连接仍活着
        a.send_json({"type": "ping"})
        self.assertEqual(a.recv_json(), {"type": "pong"})

    def test_oversized_sync_rejected_cleanly(self):
        a, b = self._connect(), self._connect()
        a.recv_json(); b.recv_json()                     # 两份 hello
        a.recv_json()                                    # peers=2
        # 载荷须落在 (56KiB, 64KiB) 窗口：过 netlab 入站帧上限、触发服务端守护；
        # 更大的帧在协议层就被断连（netlab 的 64KiB 纪律），轮不到 handler。
        pts = [[i % 800, i % 600] for i in range(5300)]
        big = [{"type": "pen", "pts": pts, "color": "#000", "width": 2}]
        raw = json.dumps({"type": "sync", "shapes": big})
        self.assertGreater(len(raw), 56 * 1024)
        self.assertLess(len(raw), 64 * 1024)
        a.send_json({"type": "sync", "shapes": big})
        err = a.recv_json()
        self.assertEqual(err["type"], "error")
        self.assertIn("过大", err["error"])
        self.assertTrue(b.recv_none())                   # 超限不外播


if __name__ == "__main__":
    unittest.main()
