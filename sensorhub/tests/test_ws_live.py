"""SensorHub /ws/live 集成测试：真套接字走 WebSocket 升级（netlab 手写 RFC 6455），
验证 订阅→快照→注入后增量推送→坏订阅回错误 四段链路。

客户端帧按规范掩码（浏览器由内核代劳，测试里自己实现）。
跑法：pytest sensorhub/tests/test_ws_live.py -q
"""
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

from sensorhub.server import build_server               # noqa: E402
from mqttlite.sensors import ReadingPlan                # noqa: E402

ZERO = ReadingPlan(spike_p=0.0, freeze_p=0.0, dropout_p=0.0)


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
    def __init__(self, port, path="/ws/live"):
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
            while True:
                msg = self._pop_frame()
                if msg is None:
                    break
                if msg.get("type"):
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

    def _pop_frame(self):
        """从缓冲里剥出一条完整文本帧并解析为 JSON；残包返回 None。"""
        if len(self.buf) < 2:
            return None
        b1 = self.buf[0]
        if not (b1 & 0x80) or (b1 & 0x0F) != 0x1:
            return None                                  # 非完整文本帧，等
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


class TestWsLive(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.server, self.hub = build_server(
            port=0, data_dir=self._tmp.name, interval=0.05, plan=ZERO)
        self.addCleanup(self.server.stop)
        self.addCleanup(self.hub.stop)
        self.hub.start()                       # build_server 不代启引擎——事件循环之外的事
        self.server.start()

    def _seed(self, device="dev-01", n=3):
        for _ in range(n):
            self.hub.inject(device, self.hub.next_seq(device), temp=30.0, vib=0.5)
            self.hub.tick()

    def test_snapshot_then_append(self):
        self._seed()
        client = WsClient(self.server.port)
        self.addCleanup(client.close)
        client.send_json({"device": "dev-01", "metric": "temp"})
        snap = client.recv_json()
        self.assertEqual(snap["type"], "snapshot")
        self.assertGreaterEqual(len(snap["points"]), 3)   # 节拍线程也在灌数，钉不了精确值
        self.assertEqual(snap["anomalies"], [])
        last_seq = snap["points"][-1][0]
        # 新读数落库后，1s 增量窗口内应推到 append，且全是比快照末尾新的 seq
        self.hub.inject("dev-01", self.hub.next_seq("dev-01"), temp=31.0, vib=0.5)
        self.hub.tick()
        append = client.recv_json(timeout=5)
        self.assertIsNotNone(append, "5s 内没等到增量推送")
        self.assertEqual(append["type"], "append")
        self.assertGreaterEqual(len(append["points"]), 1)
        self.assertTrue(all(p[0] > last_seq for p in append["points"]))

    def test_unknown_device_gets_error(self):
        client = WsClient(self.server.port)
        self.addCleanup(client.close)
        client.send_json({"device": "no-such-dev", "metric": "temp"})
        msg = client.recv_json()
        self.assertEqual(msg["type"], "error")
        self.assertIn("no-such-dev", msg["error"])

    def test_metric_switch_resnapshots(self):
        self._seed("dev-02", n=2)
        client = WsClient(self.server.port)
        self.addCleanup(client.close)
        client.send_json({"device": "dev-02", "metric": "vib"})
        snap = client.recv_json()
        self.assertEqual(snap["metric"], "vib")
        self.assertGreaterEqual(len(snap["points"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
