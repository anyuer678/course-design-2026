"""netlab/client.py —— 裸 socket 的最小 HTTP/1.1 客户端。

故意不用 urllib：测试和演示要打到**我们自己**的解析器和服务器上，
标准客户端一来就把很多边界（半包、畸形字节、keep-alive 复用）藏起来了。
"""
from __future__ import annotations

import socket

from .http1 import Response, parse_response


class ClientError(Exception):
    pass


def wire_target(target: str) -> str:
    """把请求目标写成线上形态。

    已有的 `%xx` 不二次转义（目标按线上形态书写），只把空格和非 ASCII 字符
    编成 UTF-8 百分号；CR/LF 直接拒——那等于往请求行里塞第二个请求。
    """
    if any(ch in target for ch in ("\r", "\n")):
        raise ClientError("请求目标里不能有 CR/LF")
    out = []
    for ch in target:
        code = ord(ch)
        if 0x21 <= code <= 0x7E:
            out.append(ch)
        else:
            out += [f"%{b:02X}" for b in ch.encode("utf-8")]
    return "".join(out)


def encode_request(method: str, target: str, *, body: bytes = b"",
                   headers: () = (), host: str = "127.0.0.1", version: str = "1.1",
                   close: bool | None = False) -> bytes:
    """拼请求字节。close=None 时完全不写 Connection，用来测服务端的默认判断。"""
    lines = [f"{method} {wire_target(target)} HTTP/{version}".encode("ascii")]
    seen_host = False
    for name, value in headers:
        v = str(value)
        if any(ch in v for ch in ("\r", "\n")):
            raise ClientError(f"头部 {name} 的值里不能有 CR/LF")
        lines.append(f"{name}: {v}".encode("ascii"))
        if name.lower() == "host":
            seen_host = True
    if not seen_host:
        lines.append(f"Host: {host}".encode("ascii"))
    if body or method in ("POST", "PUT"):
        lines.append(f"Content-Length: {len(body)}".encode("ascii"))
    if close is not None:
        lines.append(f"Connection: {'close' if close else 'keep-alive'}".encode("ascii"))
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


class Connection:
    """一条可复用的连接：同一个对象连续发多个请求就是 keep-alive。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, timeout: float = 5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.host, self.port, self.timeout = host, port, timeout
        self.buf = b""

    def request(self, method: str, target: str, **kw) -> Response:
        self.send(encode_request(method, target, host=self.host, **kw))
        # HEAD 的响应一定没有体，哪怕 Content-Length 写了个正数
        return self.read_response(body_expected=method != "HEAD")

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def read_response(self, body_expected: bool = True) -> Response:
        """循环读直到攒出一个完整响应；半包、分片到达都在这里被吸收。"""
        while True:
            parsed = parse_response(self.buf, body_expected=body_expected)
            if parsed is not None:
                response, used = parsed
                self.buf = self.buf[used:]
                return response
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ClientError("服务端在没有给出完整响应前关闭了连接")
            self.buf += chunk

    def close(self) -> None:
        self.sock.close()

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def one_shot(port: int, method: str = "GET", target: str = "/", **kw) -> Response:
    """发一个请求就断开，方便演示里只关心响应本身。"""
    with Connection(port=port) as conn:
        kw.setdefault("close", True)
        return conn.request(method, target, **kw)
