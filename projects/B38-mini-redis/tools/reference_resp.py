"""tools/reference_resp.py —— RESP2 的**独立第二实现**（对拍参照，不 import redislite）

为什么要有它（ROADMAP §3.8 对拍要求①"协议层用自写第二个解析器交叉读"）：
    唯一的实现对拍自己等于没有参照。本文件与 `redislite/resp.py` **从零各写一遍**，
    刻意用不同风格：主实现是"累积缓冲 + 分类切帧"的状态机；这里是
    "游标对象 + expect/递归"的直接推进——同一批线字节，两边必须得到同一串帧；
    改坏一个字节，两边必须都报错（不能一个宽松一个严格、在好数据上碰巧一致）。

对拍口径（与主实现共同遵守，见 docs/case-study.md）：
    - 首字节 `*` 走 multibulk（元素必须是 `$`），否则按内联命令行解析；
    - 严格十进制头（无前导零/空白）；`*0`/`*-1`/空内联行 → 无命令（跳过）；
    - 上限：bulk 64MB、数组 1M、内联行 64KB；
    - 错误分类文本与主实现一致（测试逐条比对两个异常消息）。

本文件只做**请求方向**的解析（服务器要执行的命令序列）与**回复方向**的解码
（客户端要读的值），均从完整字节串出发——它是参照不是服务器，不需要流式。
"""
from __future__ import annotations

MAX_BULK = 64 * 1024 * 1024
MAX_MULTIBULK = 1024 * 1024
MAX_INLINE = 64 * 1024


class RefProtocolError(Exception):
    pass


class _Cursor:
    """把完整 bytes 当磁带：位置推进 + 断言式读取（与主实现的风格完全不同）。"""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def at_end(self) -> bool:
        return self.pos >= len(self.data)

    def peek(self) -> bytes:
        return self.data[self.pos:self.pos + 1]

    def read_line(self) -> bytes:
        """读到 `\\r\\n` 为止（不含行尾），消耗掉。"""
        end = self.data.find(b"\r\n", self.pos)
        if end < 0:
            raise RefProtocolError("incomplete: no CRLF")
        line = self.data[self.pos:end]
        self.pos = end + 2
        return line

    def read_bytes(self, count: int) -> bytes:
        chunk = self.data[self.pos:self.pos + count]
        if len(chunk) != count:
            raise RefProtocolError("incomplete: short read")
        self.pos += count
        return chunk

    def expect_crlf(self) -> None:
        if self.data[self.pos:self.pos + 2] != b"\r\n":
            raise RefProtocolError("expected CRLF")


def _strict_int(token: bytes) -> int:
    text = token.decode("ascii", "replace")
    ok = text != "" and text not in ("-",)
    if ok and text[:1] == "-":
        ok = text[1:].isdigit() and (text[1] == "0" and len(text) == 2 or text[1] != "0")
    elif ok:
        ok = text.isdigit() and (text == "0" or text[0] != "0")
    if not ok:
        raise RefProtocolError("not a strict integer")
    return int(text)


def _split_inline(line: bytes) -> list[bytes]:
    """空白分词 + 双引号分段（与主实现同一口径，写法不同：按下标扫描）。
    引号段只能出现在 token 边界、引号后必须是空白或行尾；`a"b"` 的引号是字面量；
    `""` 是空参数。"""
    parts: list[bytes] = []
    i, n = 0, len(line)
    while True:
        while i < n and line[i] in (0x20, 0x09):
            i += 1
        if i >= n:
            return parts
        if line[i] == 0x22:                                # 双引号
            j = i + 1
            while j < n and line[j] != 0x22:
                j += 1
            if j >= n:
                raise RefProtocolError("unbalanced quotes in request")
            parts.append(line[i + 1:j])
            i = j + 1
            if i < n and line[i] not in (0x20, 0x09):
                raise RefProtocolError("unbalanced quotes in request")
        else:
            j = i
            while j < n and line[j] not in (0x20, 0x09):
                j += 1
            parts.append(line[i:j])
            i = j


def parse_requests(data: bytes) -> list[list[bytes]]:
    """把请求字节流解成命令列表（每条命令 = 参数表）；坏流抛 RefProtocolError。"""
    cur = _Cursor(data)
    commands: list[list[bytes]] = []
    while not cur.at_end():
        if cur.peek() == b"*":
            cur.pos += 1
            header = cur.read_line()
            try:
                count = _strict_int(header)
            except RefProtocolError:
                raise RefProtocolError("invalid multibulk length")
            if count < -1 or count > MAX_MULTIBULK:
                raise RefProtocolError("invalid multibulk length")
            if count <= 0:
                continue                                  # *0 / *-1：无命令
            args: list[bytes] = []
            for _ in range(count):
                if cur.at_end():
                    raise RefProtocolError("incomplete: array cut off")
                got = cur.peek()
                if got != b"$":
                    raise RefProtocolError(f"expected '$', got '{got.decode('latin1')}'")
                cur.pos += 1
                try:
                    length = _strict_int(cur.read_line())
                except RefProtocolError:
                    raise RefProtocolError("invalid bulk length")
                if length < 0 or length > MAX_BULK:
                    raise RefProtocolError("invalid bulk length")
                content = cur.read_bytes(length)
                if cur.data[cur.pos:cur.pos + 2] != b"\r\n":
                    raise RefProtocolError("invalid bulk length")
                cur.pos += 2
                args.append(content)
            commands.append(args)
        else:
            line = cur.read_line()
            if len(line) > MAX_INLINE:
                raise RefProtocolError("too big inline request")
            if not line.strip():
                continue
            commands.append(_split_inline(line))
    return commands


def decode_replies(data: bytes) -> list:
    """回复方向解码（参照风格）：返回 [bytes|int|None|('-', 文本), ...]。"""
    cur = _Cursor(data)
    out = []
    while not cur.at_end():
        out.append(_one_reply(cur))
    return out


def _one_reply(cur: _Cursor):
    tag = cur.peek()
    if tag == b"+":
        cur.pos += 1
        return cur.read_line()
    if tag == b"-":
        cur.pos += 1
        return ("-", cur.read_line().decode("utf-8", "replace"))
    if tag == b":":
        cur.pos += 1
        try:
            return _strict_int(cur.read_line())
        except RefProtocolError:
            raise RefProtocolError("invalid integer")
    if tag == b"$":
        cur.pos += 1
        length = _strict_int(cur.read_line())
        if length == -1:
            return None
        if length < -1 or length > MAX_BULK:
            raise RefProtocolError("invalid bulk length")
        content = cur.read_bytes(length)
        if cur.data[cur.pos:cur.pos + 2] != b"\r\n":
            raise RefProtocolError("invalid bulk length")
        cur.pos += 2
        return content
    if tag == b"*":
        cur.pos += 1
        count = _strict_int(cur.read_line())
        if count == -1:
            return None
        if count < -1 or count > MAX_MULTIBULK:
            raise RefProtocolError("invalid multibulk length")
        return [_one_reply(cur) for _ in range(count)]
    raise RefProtocolError(f"unknown reply tag {cur.peek()!r}")


if __name__ == "__main__":
    import sys
    corpus = sys.argv[1].encode("utf-8") if len(sys.argv) > 1 else b"PING\r\n"
    print(parse_requests(corpus))
