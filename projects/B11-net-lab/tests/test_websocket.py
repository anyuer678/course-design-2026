"""netlab WebSocket 层测试：RFC 向量钉住握手算法，帧编解码对拍，
真 socket 客户端走完整升级→收发→关闭链路（客户端帧按规范掩码）。"""
import base64
import os
import socket
import struct
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from netlab.http1 import parse_request
from netlab.server import Server
from netlab.websocket import (OP_CLOSE, OP_PING, OP_PONG, OP_TEXT, MAX_MESSAGE_BYTES,
                              WsParser, WsSession, accept_key, encode_frame,
                              handshake_response, is_upgrade_request)


def _mask_frame(opcode: int, payload: bytes, *, fin: bool = True) -> bytes:
    """客户端侧帧：必须掩码（RFC 6455 §5.3）。测试与真 socket 客户端共用。"""
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


class _FakeSession:
    """只喂 WsParser 用的最小会话替身：收集出站帧与回调。"""

    def __init__(self):
        self.frames = []
        self.messages = []
        self.closing = False
        self.closed = False

    def queue_frame(self, opcode, payload):
        self.frames.append((opcode, payload))

    def send(self, text):
        self.frames.append((OP_TEXT, text.encode()))

    def protocol_error(self, message):
        self.close(1002, message)

    def close(self, code=1000, reason=""):
        self.closing = True
        self.closed = True

    def fire_message(self, text):
        self.messages.append(text)

    def fire_close(self, code):
        self.closed = True


class TestHandshake(unittest.TestCase):
    def test_accept_key_rfc_vector(self):
        # RFC 6455 §1.3 的原向量：钉死算法实现
        self.assertEqual(accept_key("dGhlIHNhbXBsZSBub25jZQ=="),
                         "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_handshake_response_contains_accept(self):
        raw = handshake_response("dGhlIHNhbXBsZSBub25jZQ==").decode()
        self.assertIn("101 Switching Protocols", raw)
        self.assertIn("Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", raw)
        self.assertNotIn("Content-Length", raw)

    def test_is_upgrade_request(self):
        raw = (b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
               b"Connection: Upgrade\r\nSec-WebSocket-Key: abc==\r\n"
               b"Sec-WebSocket-Version: 13\r\n\r\n")
        req, _ = parse_request(raw)
        self.assertTrue(is_upgrade_request(req))
        plain, _ = parse_request(b"GET /ws HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertFalse(is_upgrade_request(plain))


class TestFrames(unittest.TestCase):
    def setUp(self):
        self.session = _FakeSession()
        self.parser = WsParser(self.session)   # 类型上收 WsSession，鸭子类型即可

    def test_server_frame_unmasked_roundtrip(self):
        frame = encode_frame(OP_TEXT, "你好 ws".encode())
        self.parser.feed(frame)
        self.assertEqual(self.session.messages, ["你好 ws"])

    def test_masked_client_frame(self):
        self.parser.feed(_mask_frame(OP_TEXT, "masked".encode()))
        self.assertEqual(self.session.messages, ["masked"])

    def test_fragmented_message(self):
        self.parser.feed(_mask_frame(OP_TEXT, b"hel", fin=False))
        self.parser.feed(_mask_frame(0x0, b"lo", fin=True))     # CONT 续帧
        self.assertEqual(self.session.messages, ["hello"])

    def test_ping_gets_pong(self):
        self.parser.feed(_mask_frame(OP_PING, b"hb"))
        self.assertEqual(self.session.frames, [(OP_PONG, b"hb")])

    def test_close_echoes_code(self):
        self.parser.feed(_mask_frame(OP_CLOSE, struct.pack(">H", 1000)))
        self.assertTrue(self.session.closing)
        self.assertEqual(self.session.frames, [(OP_CLOSE, struct.pack(">H", 1000))])

    def test_binary_rejected(self):
        self.parser.feed(_mask_frame(0x2, b"\x00\x01"))
        self.assertTrue(self.session.closed)

    def test_oversize_rejected(self):
        with self.assertRaises(Exception):
            self.parser.feed(_mask_frame(OP_TEXT, b"x" * (MAX_MESSAGE_BYTES + 1)))

    def test_half_packet_waits(self):
        full = _mask_frame(OP_TEXT, "延迟到达".encode())
        self.parser.feed(full[:5])
        self.assertEqual(self.session.messages, [])
        self.parser.feed(full[5:])
        self.assertEqual(self.session.messages, ["延迟到达"])


class _WsClient:
    """测试专用最小 WS 客户端：真 socket、真掩码，服务端帧不掩码。"""

    def __init__(self, port, path="/ws"):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
             "Upgrade: websocket\r\nConnection: Upgrade\r\n"
             f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self.buf += self.sock.recv(4096)
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        assert b"101" in head.split(b"\r\n")[0], head

    def send_text(self, text):
        self.sock.sendall(_mask_frame(OP_TEXT, text.encode()))

    def send_close(self, code=1000):
        self.sock.sendall(_mask_frame(OP_CLOSE, struct.pack(">H", code)))

    def recv_text(self, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.buf) >= 2:
                b1, b2 = self.buf[0], self.buf[1]
                length = b2 & 0x7F
                pos = 2
                if length == 126 and len(self.buf) >= 4:
                    length = struct.unpack(">H", self.buf[2:4])[0]
                    pos = 4
                if length == 127 and len(self.buf) >= 10:
                    length = struct.unpack(">Q", self.buf[2:10])[0]
                    pos = 10
                if len(self.buf) >= pos + length and (b1 & 0x0F) == OP_TEXT:
                    payload = self.buf[pos:pos + length]
                    self.buf = self.buf[pos + length:]
                    return payload.decode()
            self.sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                return None
            self.buf += chunk
        return None

    def close(self):
        try:
            self.send_close()
        except OSError:
            pass
        self.sock.close()


class TestServerIntegration(unittest.TestCase):
    def test_echo_over_real_socket(self):
        server = Server(port=0)
        seen = []

        def ws_handler(session: WsSession):
            session.on_message = lambda text: session.send("echo:" + text)

        server.ws_routes.append(("/ws", ws_handler))
        server.start()
        try:
            client = _WsClient(server.port)
            client.send_text("hi")
            self.assertEqual(client.recv_text(), "echo:hi")
            client.send_text("again")
            self.assertEqual(client.recv_text(), "echo:again")
            client.close()
            seen.append(True)
        finally:
            server.stop(timeout=3)
        self.assertTrue(seen)

    def test_unknown_endpoint_404(self):
        server = Server(port=0)
        server.start()
        try:
            sock = socket.create_connection(("127.0.0.1", server.port), timeout=3)
            sock.sendall(b"GET /nowhere HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
                         b"Connection: Upgrade\r\nSec-WebSocket-Key: abc==\r\n"
                         b"Sec-WebSocket-Version: 13\r\n\r\n")
            data = sock.recv(4096)
            self.assertTrue(data.startswith(b"HTTP/1.1 404"), data[:40])
            sock.close()
        finally:
            server.stop(timeout=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
