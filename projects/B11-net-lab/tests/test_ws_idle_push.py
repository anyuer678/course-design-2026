"""回归：空闲超 idle_timeout 的 WS 连接收到补推帧，必须能送达——不许被
"ws stuck output" 误杀。2026-10-11 boardweb 协同实测抓出：广播帧入队与
_tick 的超时清扫同 tick 竞速，旧逻辑用 last_active（读活动）判滞留，
把"空闲 25s 后的第一帧"当成了"滞留 25s 的死帧"。修后滞留判定看
outbuf_since（outbuf 从空变非空的时刻）。
"""
import base64
import json
import os
import socket
import struct
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from netlab.server import Server                          # noqa: E402


def _mask_frame(opcode, payload):
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    head = bytearray([0x80 | opcode]); n = len(payload)
    if n < 126:
        head.append(0x80 | n)
    else:
        head.append(0x80 | 126); head += struct.pack(">H", n)
    return bytes(head) + mask + masked


class _HubApp:
    """最小 WS 应用：/ws 上收到 push 指令后，向所有会话补推一帧。"""

    def __init__(self):
        self.sessions = []

    def ws_routes_factory(self, server):
        self.sessions = []
        server.ws_routes.append(("/ws", self._handler))
        return server.ws_routes

    def _handler(self, session):
        self.sessions.append(session)


class TestIdleWsStillReceivable(unittest.TestCase):
    def test_push_after_idle_window_arrives(self):
        app = _HubApp()
        server = Server("127.0.0.1", 0, idle_timeout=0.5, verbose=False)
        server.ws_routes.append(("/ws", app._handler))
        port = server.start()
        self.addCleanup(server.stop)

        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.addCleanup(sock.close)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                      f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += sock.recv(4096)
        head, buf = buf.split(b"\r\n\r\n", 1)
        self.assertIn(b"101", head.split(b"\r\n")[0])
        self.assertEqual(len(app.sessions), 1)

        # 空闲跨过 idle_timeout（旧逻辑在这里之后的首次推送会被误杀）
        time.sleep(0.8)

        # 客户端此时保持沉默，服务端向会话补推一帧
        app.sessions[0].send('{"note": "push after idle"}')

        deadline = time.monotonic() + 3.0
        got = None
        while time.monotonic() < deadline:
            msg = self._pop_text(buf)
            if msg is not None:
                buf = b""
                if '"push after idle"' in msg:
                    got = msg
                    break
            sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
        self.assertIsNotNone(got, "空闲窗口后的补推帧未送达——被误判滞留回收了")
        self.assertEqual(json.loads(got), {"note": "push after idle"})

    @staticmethod
    def _pop_text(buf: bytes):
        if len(buf) < 2:
            return None
        b1, b2 = buf[0], buf[1]
        if not (b1 & 0x80) or (b1 & 0x0F) != 0x1:
            return None
        assert not (b2 & 0x80), "服务器帧不许掩码"
        ln, pos = b2 & 0x7F, 2
        if ln == 126:
            if len(buf) < 4:
                return None
            ln = struct.unpack(">H", buf[2:4])[0]
            pos = 4
        if len(buf) < pos + ln:
            return None
        return buf[pos:pos + ln].decode("utf-8")


if __name__ == "__main__":
    unittest.main()
