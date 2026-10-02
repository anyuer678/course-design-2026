"""redislite/client.py —— 极简客户端（测试/演示用；与服务器共用同一个解码器）

课程要点：客户端与服务器**共用协议实现**是本项目刻意的选择——协议是双方
共同的契约，写两套就有一份会烂；真正需要"第二实现"的地方（交叉对拍）在
tools/reference_resp.py，那里是用来检验这份契约的，不是拿来日常用的。
"""
from __future__ import annotations

import socket

from redislite import resp


class ConnectionClosed(ConnectionError):
    pass


class Client:
    def __init__(self, host: str = "127.0.0.1", port: int = 6379, timeout: float = 5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.dec = resp.FrameDecoder()

    # ---------------------------------------------------------------- 发送
    def send_raw(self, data: bytes) -> None:
        try:
            self.sock.sendall(data)
        except (ConnectionResetError, ConnectionAbortedError) as err:
            raise ConnectionClosed("连接已断开（发送时被重置）") from err

    def send(self, *args) -> None:
        self.send_raw(resp.encode_command(*args))

    # ---------------------------------------------------------------- 接收
    def read_reply(self):
        """读一条完整回复；对端关闭或被重置都归一为 ConnectionClosed。

        （Windows 上服务器关连接时客户端可能收到 RST 而不是优雅 EOF——
        对使用者这两种语义一样：连接没了。）"""
        while True:
            value = self.dec.next_frame()
            if value is not resp.INCOMPLETE:
                return value
            try:
                data = self.sock.recv(65536)
            except (ConnectionResetError, ConnectionAbortedError) as err:
                raise ConnectionClosed("连接被对端重置") from err
            if not data:
                raise ConnectionClosed("服务器已关闭连接")
            self.dec.feed(data)

    def read_replies(self, count: int) -> list:
        return [self.read_reply() for _ in range(count)]

    def cmd(self, *args: str | bytes):
        self.send(*args)
        return self.read_reply()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
