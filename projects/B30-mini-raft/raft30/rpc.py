"""raft30/rpc.py —— mini-RPC：JSON 行帧 + id 关联 + 真套接字回声服务

课程要点（为 Raft 模拟的通信层打底，也可独立使用）：
    - 帧：一行一个 JSON（UTF-8，\\n 结尾）——"消息边界"是 TCP 上的第一课，
      接收方必须按行累积缓冲，不能把一次 recv 当一条消息。
    - RPC 语义：请求带自增 msg_id，响应回带同一 id——客户端按 id 关联，
      允许乱序到达。
    - 服务端每连接一线程（教学版）；Raft 模拟不用真套接字，用同样的
      消息语义在事件驱动模拟里跑（可复现、无真实时序）。

约定：坏帧（空行/非 JSON）跳过并不回包——把"收到垃圾"与"收到请求"
区分开，是协议鲁棒性的第一课。
"""
from __future__ import annotations

import json
import socket
import threading


def encode_msg(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


class FrameDecoder:
    """按 \\n 切帧、逐条 json.loads 的累积解码器。"""

    def __init__(self) -> None:
        self.buf = b""

    def feed(self, data: bytes) -> list[dict]:
        self.buf += data
        out = []
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue                        # 坏帧跳过（约定见 docstring）
            if isinstance(obj, dict):
                out.append(obj)
        return out


class RpcClient:
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.decoder = FrameDecoder()
        self._next_id = 1

    def call(self, body: dict) -> dict:
        msg_id = self._next_id
        self._next_id += 1
        self.sock.sendall(encode_msg({"id": msg_id, "body": body}))
        while True:                             # 按 id 关联，跳过乱序/其他响应
            for msg in self.decoder.feed(self._recv_some()):
                if msg.get("id") == msg_id:
                    return msg.get("resp", {})

    def _recv_some(self) -> bytes:
        data = self.sock.recv(65536)
        if not data:
            raise ConnectionError("服务端关闭连接")
        return data

    def close(self) -> None:
        self.sock.close()


class RpcServer:
    """每连接一线程的回声式 RPC 服务。handler(body: dict) -> dict。"""

    def __init__(self, host: str, port: int, handler):
        self.handler = handler
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(8)
        self._running = True
        self._threads: list[threading.Thread] = []

    def serve_forever(self) -> None:
        while self._running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                break
            t = threading.Thread(target=self._serve_conn, args=(conn,),
                                 daemon=True)
            t.start()
            self._threads.append(t)

    def _serve_conn(self, conn: socket.socket) -> None:
        decoder = FrameDecoder()
        while True:
            try:
                data = conn.recv(65536)
            except OSError:
                break
            if not data:
                break
            for msg in decoder.feed(data):
                if "id" not in msg or "body" not in msg:
                    continue                    # 坏帧不回包
                try:
                    resp = self.handler(msg["body"])
                except Exception as exc:        # noqa: BLE001
                    resp = {"error": str(exc)}
                conn.sendall(encode_msg({"id": msg["id"], "resp": resp}))
        conn.close()

    def stop(self) -> None:
        self._running = False
        self.sock.close()
