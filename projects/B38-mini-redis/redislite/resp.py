"""redislite/resp.py —— RESP2 子集：流式帧解码（粘包/拆包）与编解码助手

课程要点（对应 docs/case-study.md 第 2 节）：
    - 网络不按消息边界到达：一次 read 可能拿到半条命令，也可能一个包里三条命令。
      所以解析必须是"**累积缓冲 + 尽力切帧**"：能切出的帧立刻交付，切不出的留缓冲等
      下一次 feed——服务端与客户端用的是同一个解码器，就是这条纪律的体现。
    - **二进制安全**：批量值由显式长度定界，值里出现 `\\r\\n` 也不歧义。
    - **方向不同规则不同**（真实 Redis 同款）：
        请求方向 `next_command()`：首字节 `*` 走 multibulk（元素必须 `$`），否则按
        **内联命令**解析一行；`*0`/`*-1`/空行 → 无命令（跳过）。
        回复方向 `next_frame()`：五种类型都解，数组元素可以是任意类型（含嵌套）。
      两条通道混着发是合法流（ROADMAP 点名要测的解析边界）。
    - 协议错误要**分类**（消息文本可断言），服务端据此回 `-ERR Protocol error: ...`
      并断开连接；fuzz 的全部要求就是"不崩 + 错误必须是定义好的那几种"。

值类型约定（客户端/测试共用的 Python 表示）：
    bytes → 简单字符串/批量值；int → 整数；None → nil；RespError → 错误值。
"""
from __future__ import annotations

#: 上限（docs/case-study.md §6 偏离表第 7 条；超限一律协议错误）
MAX_BULK = 64 * 1024 * 1024          # 单个批量值 64MB（真实 Redis 512MB）
MAX_MULTIBULK = 1024 * 1024          # 数组元素个数 1M（与真实 Redis 相同）
MAX_INLINE = 64 * 1024               # 内联行 64KB（与真实 Redis 相同）


class ProtocolError(Exception):
    """协议错误：message 是分类文本（会被拼进 `-ERR Protocol error: <msg>`）。"""


class RespError:
    """错误值（`-...`）：既能当值传递（客户端读回复），也带原始文本。"""

    __slots__ = ("message",)

    def __init__(self, message: str):
        self.message = message

    def __eq__(self, other):
        return isinstance(other, RespError) and other.message == self.message

    def __repr__(self):
        return f"RespError({self.message!r})"


INCOMPLETE = object()                # 解码器的"还没到齐"哨兵

# ---------------------------------------------------------------- 序列化助手


def encode_simple(text: str) -> bytes:
    return b"+" + text.encode("utf-8") + b"\r\n"


def encode_error(text: str) -> bytes:
    return b"-" + text.encode("utf-8") + b"\r\n"


def encode_int(value: int) -> bytes:
    return b":" + str(value).encode("ascii") + b"\r\n"


def encode_bulk(value: bytes | None) -> bytes:
    if value is None:
        return b"$-1\r\n"
    return b"$" + str(len(value)).encode("ascii") + b"\r\n" + value + b"\r\n"


def encode_array(items: list | None) -> bytes:
    if items is None:
        return b"*-1\r\n"
    out = [b"*" + str(len(items)).encode("ascii") + b"\r\n"]
    for item in items:
        out.append(encode_value(item))
    return b"".join(out)


def encode_value(value) -> bytes:
    if value is None:
        return b"$-1\r\n"
    if isinstance(value, RespError):
        return encode_error(value.message)
    if isinstance(value, bool):
        raise TypeError("bool 不是 RESP 值类型")
    if isinstance(value, int):
        return encode_int(value)
    if isinstance(value, (bytes, bytearray)):
        return encode_bulk(bytes(value))
    if isinstance(value, str):
        return encode_bulk(value.encode("utf-8"))
    if isinstance(value, list):
        return encode_array(value)
    raise TypeError(f"不支持的值类型：{type(value).__name__}")


def encode_command(*args: object) -> bytes:
    """把命令编成 multibulk 请求（客户端用）。

    参数一律编成**批量值**：int/float 先 str 化——请求数组的元素必须是 bulk
    （真实 Redis 同规矩），`c.cmd("EXPIRE", "k", 10)` 的 10 不能变成整数帧 `:10`，
    否则服务器会（正确地）报 `expected '$', got ':'`。这条踩过：见 README 坑记。
    """
    items = []
    for a in args:
        if isinstance(a, (bytes, bytearray)):
            items.append(bytes(a))
        elif isinstance(a, str):
            items.append(a.encode("utf-8"))
        elif isinstance(a, (int, float)):
            items.append(str(a).encode("ascii"))
        else:
            raise TypeError(f"命令参数不支持的类型：{type(a).__name__}")
    return encode_array(items)


# ---------------------------------------------------------------- 严格整数


def parse_int_strict(token: bytes) -> int:
    """严格十进制（RESP 头用）：可选负号 + 数字；不许空白/前导零
    （`$01` 是协议错误，与真实 Redis 的 string2ll 口径一致）。"""
    if not token:
        raise ValueError("empty")
    body = token[1:] if token[:1] == b"-" else token
    if not body or not body.isdigit():
        raise ValueError("not an integer")
    if len(body) > 1 and body[:1] == b"0":
        raise ValueError("leading zero")
    number = int(body)
    return -number if token[:1] == b"-" else number


# ---------------------------------------------------------------- 通用回复解码

def _line_end(buf: bytes | bytearray, start: int) -> int:
    idx = buf.find(b"\r\n", start)
    return -1 if idx < 0 else idx


def _cut_value(buf: bytes | bytearray) -> tuple:
    """从 buf 开头切一个完整的回复值。返回 (值, 消耗字节数) 或 INCOMPLETE。"""
    first = buf[0:1]
    if first == b":":
        end = _line_end(buf, 1)
        if end < 0:
            return INCOMPLETE
        try:
            value = parse_int_strict(bytes(buf[1:end]))
        except ValueError as err:
            raise ProtocolError("invalid integer") from err
        return value, end + 2
    if first in (b"+", b"-"):
        end = _line_end(buf, 1)
        if end < 0:
            return INCOMPLETE
        body = bytes(buf[1:end])
        value = body if first == b"+" else RespError(body.decode("utf-8", "replace"))
        return value, end + 2
    if first == b"$":
        end = _line_end(buf, 1)
        if end < 0:
            return INCOMPLETE
        try:
            length = parse_int_strict(bytes(buf[1:end]))
        except ValueError as err:
            raise ProtocolError("invalid bulk length") from err
        if length < -1 or length > MAX_BULK:
            raise ProtocolError("invalid bulk length")
        if length == -1:
            return None, end + 2
        content_start = end + 2
        content_end = content_start + length
        if len(buf) < content_end + 2:
            return INCOMPLETE
        if bytes(buf[content_end:content_end + 2]) != b"\r\n":
            raise ProtocolError("invalid bulk length")
        return bytes(buf[content_start:content_end]), content_end + 2
    if first == b"*":
        end = _line_end(buf, 1)
        if end < 0:
            return INCOMPLETE
        try:
            count = parse_int_strict(bytes(buf[1:end]))
        except ValueError as err:
            raise ProtocolError("invalid multibulk length") from err
        if count < -1 or count > MAX_MULTIBULK:
            raise ProtocolError("invalid multibulk length")
        if count == -1:
            return None, end + 2
        pos = end + 2
        items: list = []
        for _ in range(count):
            piece = _cut_value(buf[pos:])
            if piece is INCOMPLETE:
                return INCOMPLETE
            value, consumed = piece
            items.append(value)
            pos += consumed
        return items, pos
    got = bytes(buf[0:1]).decode("latin1")
    raise ProtocolError(f"invalid type byte '{got}'")


# ---------------------------------------------------------------- 请求解码

def _split_inline(line: bytes) -> list[bytes]:
    """空白分词 + 双引号分段。口径：引号段只能出现在 token 边界，引号后必须
    是空白或行尾；`a"b"` 里的引号是普通字符（字面量）；`""` 是空参数。"""
    args: list[bytes] = []
    i = 0
    n = len(line)
    while i < n:
        while i < n and line[i:i + 1] in (b" ", b"\t"):
            i += 1
        if i >= n:
            break
        if line[i:i + 1] == b'"':
            end = line.find(b'"', i + 1)
            if end < 0:
                raise ProtocolError("unbalanced quotes in request")
            args.append(line[i + 1:end])
            i = end + 1
            if i < n and line[i:i + 1] not in (b" ", b"\t"):
                raise ProtocolError("unbalanced quotes in request")
        else:
            start = i
            while i < n and line[i:i + 1] not in (b" ", b"\t"):
                i += 1
            args.append(line[start:i])
    return args


def _cut_command(buf: bytes | bytearray):
    """从 buf 开头切一条**请求命令**（list[bytes]，可能为空 = 无命令）。"""
    if buf[0:1] == b"*":
        end = _line_end(buf, 1)
        if end < 0:
            return INCOMPLETE
        try:
            count = parse_int_strict(bytes(buf[1:end]))
        except ValueError as err:
            raise ProtocolError("invalid multibulk length") from err
        if count < -1 or count > MAX_MULTIBULK:
            raise ProtocolError("invalid multibulk length")
        if count <= 0:
            return [], end + 2                     # *0 / *-1：无命令
        pos = end + 2
        args: list[bytes] = []
        for _ in range(count):
            if len(buf) <= pos:
                return INCOMPLETE
            got = buf[pos:pos + 1]
            if got != b"$":
                raise ProtocolError(f"expected '$', got '{got.decode('latin1')}'")
            elem_end = _line_end(buf, pos + 1)
            if elem_end < 0:
                return INCOMPLETE
            try:
                length = parse_int_strict(bytes(buf[pos + 1:elem_end]))
            except ValueError as err:
                raise ProtocolError("invalid bulk length") from err
            if length < 0 or length > MAX_BULK:
                raise ProtocolError("invalid bulk length")
            content_start = elem_end + 2
            content_end = content_start + length
            if len(buf) < content_end + 2:
                return INCOMPLETE
            if bytes(buf[content_end:content_end + 2]) != b"\r\n":
                raise ProtocolError("invalid bulk length")
            args.append(bytes(buf[content_start:content_end]))
            pos = content_end + 2
        return args, pos
    # 内联命令：读到 \r\n 为止
    end = _line_end(buf, 0)
    if end < 0:
        if len(buf) > MAX_INLINE:
            raise ProtocolError("too big inline request")
        return INCOMPLETE
    if end > MAX_INLINE:
        raise ProtocolError("too big inline request")
    line = bytes(buf[:end])
    if not line.strip():
        return [], end + 2                         # 空行：无命令
    return _split_inline(line), end + 2


# ---------------------------------------------------------------- 解码器


class FrameDecoder:
    """累积缓冲 + 尽力切帧。feed() 任意次，按方向取帧。"""

    def __init__(self) -> None:
        self.buf = bytearray()

    def feed(self, data: bytes) -> None:
        self.buf.extend(data)

    def next_frame(self):
        """回复方向：切一个值（bytes/int/None/RespError/list）或 INCOMPLETE。"""
        if not self.buf:
            return INCOMPLETE
        piece = _cut_value(self.buf)
        if piece is INCOMPLETE:
            return INCOMPLETE
        value, consumed = piece
        del self.buf[:consumed]
        return value

    def next_command(self):
        """请求方向：切一条命令（list[bytes]，空列表 = 无命令）或 INCOMPLETE。"""
        if not self.buf:
            return INCOMPLETE
        piece = _cut_command(self.buf)
        if piece is INCOMPLETE:
            return INCOMPLETE
        args, consumed = piece
        del self.buf[:consumed]
        return args


def decode_replies(data: bytes) -> list:
    """一段完整回复流 → 值列表（测试/对拍便利；有半帧会报"trailing bytes"）。"""
    dec = FrameDecoder()
    dec.feed(data)
    out = []
    while dec.buf:
        value = dec.next_frame()
        if value is INCOMPLETE:
            raise ProtocolError("trailing bytes: 半帧或多余数据")
        out.append(value)
    return out


def decode_commands(data: bytes) -> list:
    """一段完整请求流 → 命令列表（跳过无命令帧）。"""
    dec = FrameDecoder()
    dec.feed(data)
    out = []
    while dec.buf:
        args = dec.next_command()
        if args is INCOMPLETE:
            raise ProtocolError("trailing bytes: 半帧或多余数据")
        if args:
            out.append(args)
    return out
