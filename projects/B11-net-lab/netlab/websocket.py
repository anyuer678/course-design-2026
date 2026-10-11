"""netlab/websocket.py —— 手写 RFC 6455 WebSocket（服务器侧）。

为什么手写：B11 的立身之本就是"协议层自己写一遍才算懂"。WebSocket 是 HTTP/1.1
的升级协议，跟 netlab 现有单线程 select 服务器是绝配——升级成功后连接继续
留在同一个事件循环里，出站帧直接排队进 conn.outbuf，入站帧由 WsParser 解。

只实现服务器侧需要的部分：
* accept_key      握手应答键（RFC 6455 §1.3 的固定算法，测试用 RFC 原向量钉住）
* handshake_response  101 升级应答字节串
* encode_frame    服务器出站帧（不掩码——RFC 要求服务器帧必须不掩码）
* WsParser        入站字节流 → 完整帧；处理掩码、扩展长度、分片续帧、
                  ping→pong、close 握手；超限/协议错误以 Close 帧回敬
* WsSession      一条升级后的连接：send/close/pump，回调 on_message/on_poll/on_close
                  由应用赋值；全部方法只在服务器事件循环线程里调用

明确不做的（教学边界，够用即可）：二进制消息（收到按文本拒 1003）、
压缩扩展（permessage-deflate）、UTF-8 增量校验只在完整消息上做一次。
"""
from __future__ import annotations

import base64
import hashlib
import struct

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

MAX_MESSAGE_BYTES = 64 * 1024        # 单条消息上限：配置订阅就几十字节，64KiB 是十倍宽容

OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


class WsError(Exception):
    """协议层错误——参数 message 会作为 Close 帧的理由发回对端。"""


def accept_key(client_key: str) -> str:
    digest = hashlib.sha1((client_key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def handshake_response(client_key: str) -> bytes:
    """101 升级应答。不能走 build_response：那会塞 Content-Length，升级应答没有体。"""
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key(client_key)}\r\n"
        "\r\n"
    ).encode("ascii")


def is_upgrade_request(request) -> bool:
    return (request.method == "GET"
            and (request.header("upgrade") or "").strip().lower() == "websocket"
            and request.header("sec-websocket-key") is not None)


def encode_frame(opcode: int, payload: bytes = b"", *, fin: bool = True) -> bytes:
    """服务器出站帧：不掩码（RFC 6455 §5.1 服务器必须不掩码）。"""
    head = bytearray([ (0x80 if fin else 0) | opcode ])
    n = len(payload)
    if n < 126:
        head.append(n)
    elif n < 65536:
        head.append(126)
        head += struct.pack(">H", n)
    else:
        head.append(127)
        head += struct.pack(">Q", n)
    return bytes(head) + payload


def _decode_length(buf: memoryview, pos: int):
    """从 pos（指向第二个字节）解析掩码位 + 7 位长度 + 扩展长度 + 掩码键。
    字节不够返回 None（半包）；长度超限抛 WsError。返回 (长度, 掩码或 None, 新位置)。"""
    b2 = buf[pos]
    length = b2 & 0x7F
    masked = bool(b2 & 0x80)
    pos += 1
    if length == 126:
        if len(buf) < pos + 2:
            return None
        length = struct.unpack(">H", buf[pos:pos + 2])[0]
        pos += 2
    elif length == 127:
        if len(buf) < pos + 8:
            return None
        length = struct.unpack(">Q", buf[pos:pos + 8])[0]
        pos += 8
    if length > MAX_MESSAGE_BYTES:
        raise WsError("message too big")
    if masked:
        if len(buf) < pos + 4:
            return None
        mask = bytes(buf[pos:pos + 4])
        pos += 4
        return length, mask, pos
    return length, None, pos


def _unmask(payload: bytes, mask: bytes | None) -> bytes:
    if mask is None:
        return payload
    return bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


class WsParser:
    """入站字节流解析器。feed() 逐帧消化，产出回调给 session。"""

    def __init__(self, session: "WsSession"):
        self.session = session
        self.buf = bytearray()
        self.frag_op: int | None = None      # 分片累计中的消息 opcode
        self.frag_buf = bytearray()

    def feed(self, data: bytes) -> None:
        self.buf += data
        while True:
            if len(self.buf) < 2:
                return
            view = memoryview(self.buf)
            b1 = view[0]
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            parsed = _decode_length(view, 1)
            if parsed is None:
                return
            length, mask, pos = parsed
            if len(view) < pos + length:
                return                       # 半包：等下一个 recv
            payload = _unmask(bytes(view[pos:pos + length]), mask)
            self.buf = self.buf[pos + length:]
            self._frame(fin, opcode, payload)

    def _frame(self, fin: bool, opcode: int, payload: bytes) -> None:
        s = self.session
        if opcode == OP_PING:
            s.queue_frame(OP_PONG, payload)          # 控制帧不许分片，原样回
            return
        if opcode == OP_PONG:
            return                                   # 我们不发心跳挑战，收到了也只当没听见
        if opcode == OP_CLOSE:
            # 回敬一个同码 Close 再收摊；对方码可能缺省，按 1000 处理
            code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 1000
            s.queue_frame(OP_CLOSE, struct.pack(">H", code))
            s.closing = True
            s.fire_close(code)
            return
        if opcode == OP_TEXT:
            if self.frag_op is not None:
                s.protocol_error("分片中夹了新的 TEXT")
                return
            self._message(fin, OP_TEXT, payload)
            return
        if opcode == OP_CONT:
            if self.frag_op is None:
                s.protocol_error("没有开头的 CONT 续帧")
                return
            self.frag_buf += payload
            if len(self.frag_buf) > MAX_MESSAGE_BYTES:
                s.protocol_error("分片消息超限")
                return
            if fin:
                op, data = self.frag_op, bytes(self.frag_buf)
                self.frag_op, self.frag_buf = None, bytearray()
                self._message(True, op, data)
            return
        if opcode == OP_BIN:
            s.protocol_error("只接受文本消息")
            return
        s.protocol_error(f"未知 opcode {opcode}")

    def _message(self, fin: bool, opcode: int, payload: bytes) -> None:
        s = self.session
        if not fin:
            self.frag_op, self.frag_buf = opcode, bytearray(payload)
            if len(self.frag_buf) > MAX_MESSAGE_BYTES:
                s.protocol_error("分片消息超限")
            return
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            s.protocol_error("消息不是合法 UTF-8")
            return
        s.fire_message(text)


class WsSession:
    """一条升级后的连接。属性在服务器线程里被驱动，全部回调也在同一线程。"""

    def __init__(self, server, conn, request, path_params: dict | None = None):
        self.server = server
        self.conn = conn
        self.request = request
        self.path = request.path
        self.query = dict(request.query)
        self.params = path_params or {}
        self.closing = False
        self.closed = False
        self.on_message = None            # fn(text)；应用赋值
        self.on_poll = None               # fn()；事件循环每 tick 调（≈20ms），自己节流
        self.on_close = None              # fn()；关闭前最后机会做清理
        self._parser: WsParser | None = None   # 缓冲跨 recv 存续——绝不能每包新建

    # ------------------------------------------------ 出站
    def queue_frame(self, opcode: int, payload: bytes) -> None:
        if self.conn.alive:
            self.conn.outbuf += encode_frame(opcode, payload)

    def send(self, text: str) -> None:
        """推一条文本消息。半包/粘包都由事件循环的 outbuf 兜底。"""
        if not self.closing:
            self.queue_frame(OP_TEXT, text.encode("utf-8"))

    def close(self, code: int = 1000, reason: str = "") -> None:
        if not self.closing:
            payload = struct.pack(">H", code) + reason.encode("utf-8")[:120]
            self.queue_frame(OP_CLOSE, payload)
            self.closing = True
            self.fire_close(code)

    def protocol_error(self, message: str) -> None:
        self.close(1002, message)

    # ------------------------------------------------ 事件（服务器线程调用）
    def feed(self, data: bytes) -> None:
        if self._parser is None:
            self._parser = WsParser(self)
        try:
            self._parser.feed(data)
        except WsError as exc:
            self.close(1009, str(exc))

    def fire_message(self, text: str) -> None:
        if self.on_message and not self.closing:
            try:
                self.on_message(text)
            except Exception as exc:      # 应用回调炸了不能带走事件循环
                import traceback
                traceback.print_exc()
                self.send('{"type":"error","error":"internal"}')
                if self.server.verbose:
                    print(f"  [ws] on_message 异常：{exc!r}")

    def fire_close(self, code: int) -> None:
        if self.closed:
            return
        self.closed = True
        if self.on_close:
            try:
                self.on_close()
            except Exception:
                pass
        self.server.ws_sessions.discard(self)

    def pump(self) -> None:
        if self.on_poll and not self.closing:
            try:
                self.on_poll()
            except Exception as exc:
                if self.server.verbose:
                    print(f"  [ws] on_poll 异常：{exc!r}")
