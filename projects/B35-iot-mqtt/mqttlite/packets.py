"""mqttlite/packets.py —— MQTT 3.1.1 子集：字节级编解码（教学版，零依赖）

课程要点（工业物联网）：
    - MQTT 的报文 = **固定头 + 可变头 + 载荷**。固定头第一个字节 = 报文类型<<4 | 标志位，
      第二个字段是**变长整数 Remaining Length**（base-128，每字节 7 位、最高位是延续位）——
      这一个字段就是"协议要能在 2 字节的传感器报文和 256MB 的固件分包之间通用"的答案；
    - 本子集覆盖链路验证所需：CONNECT / CONNACK / PUBLISH(QoS0) / SUBSCRIBE / SUBACK /
      PINGREQ / PINGRESP / DISCONNECT。**QoS0 = 至多一次**：没有 ack、不重发——
      断线期间的消息就是丢了，"不存储离线消息"是语义而不是缺陷（测试钉住）；
    - 主题通配符有两个层级：`+` 单层、`#` 多层（必须在末尾）；**`$` 开头的主题不被
      `#`/`+` 匹配**（规范细节，实现里有专门的测试）；
    - 解码一律**先验后读**：长度不合法、类型未知、标志位保留值不对——全部抛
      `MalformedPacket`，由 broker 决定"只断这一条连接"（一条坏连接不能拖垮别人）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 报文类型
CONNECT = 1
CONNACK = 2
PUBLISH = 3
SUBSCRIBE = 8
SUBACK = 9
PINGREQ = 12
PINGRESP = 13
DISCONNECT = 14

TYPE_NAMES = {CONNECT: "CONNECT", CONNACK: "CONNACK", PUBLISH: "PUBLISH",
              SUBSCRIBE: "SUBSCRIBE", SUBACK: "SUBACK", PINGREQ: "PINGREQ",
              PINGRESP: "PINGRESP", DISCONNECT: "DISCONNECT"}

MAX_REMAINING = 268435455          # 规范上限：4 字节 base-128


class MalformedPacket(ValueError):
    """结构不合法（长度越界/未知类型/标志位不对/主题非法）。"""


# ---------------------------------------------------------------- 变长整数

def encode_remaining_length(n: int) -> bytes:
    """base-128：手算样例 127→7F、128→80 01、16383→FF 7F、16384→80 80 01。"""
    if not 0 <= n <= MAX_REMAINING:
        raise MalformedPacket(f"remaining length 越界：{n}")
    out = bytearray()
    while True:
        digit = n % 128
        n //= 128
        if n > 0:
            digit |= 0x80
        out.append(digit)
        if n == 0:
            return bytes(out)


def decode_remaining_length(buf: bytes, offset: int = 0) -> tuple[int, int]:
    """返回 (值, 消耗的字节数)。默认 offset=0 表示 buf 从 RL 字段开始；
    broker 解析整包时传 offset=1 跳过固定头第一个字节。超过 4 字节 → MalformedPacket。"""
    value = 0
    shift = 0
    consumed = 0
    while True:
        if offset + consumed >= len(buf):
            raise IncompletePacket()          # 数据还没到齐，等下一批
        byte = buf[offset + consumed]
        consumed += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, consumed
        shift += 7
        if consumed >= 4:
            raise MalformedPacket("remaining length 超过 4 字节")


class IncompletePacket(Exception):
    """缓冲区里还不是一个完整报文——调用方继续 recv。"""


# ---------------------------------------------------------------- CONNECT / CONNACK

@dataclass
class ConnectPacket:
    client_id: str
    clean_session: bool = True
    keepalive: int = 60


def encode_connect(pkt: ConnectPacket) -> bytes:
    payload = pkt.client_id.encode("utf-8")
    variable = (b"\x00\x04MQTT"          # 协议名
                + b"\x04"                # 协议级别 4（3.1.1）
                + bytes([0x02 if pkt.clean_session else 0x00])
                + pkt.keepalive.to_bytes(2, "big"))
    body = variable + len(payload).to_bytes(2, "big") + payload
    return bytes([CONNECT << 4]) + encode_remaining_length(len(body)) + body


def parse_connect(body: bytes) -> ConnectPacket:
    if len(body) < 10:
        raise MalformedPacket("CONNECT 太短")
    if body[0:6] != b"\x00\x04MQTT":
        raise MalformedPacket("协议名不是 MQTT")
    if body[6] != 4:
        raise MalformedPacket(f"不支持协议级别 {body[6]}")
    flags = body[7]
    if flags & 0x01:
        raise MalformedPacket("保留标志位必须为 0")
    keepalive = int.from_bytes(body[8:10], "big")
    if len(body) < 12:
        raise MalformedPacket("CONNECT 缺 client id")
    id_len = int.from_bytes(body[10:12], "big")
    if len(body) != 12 + id_len:
        raise MalformedPacket("client id 长度与实际不符")
    client_id = body[12:].decode("utf-8", errors="replace")
    if not client_id:
        raise MalformedPacket("client id 不能为空（本教学版不支持空 id）")
    return ConnectPacket(client_id=client_id, clean_session=bool(flags & 0x02),
                         keepalive=keepalive)


def encode_connack(session_present: bool = False, return_code: int = 0) -> bytes:
    return bytes([CONNACK << 4, 2, 1 if session_present else 0, return_code])


def parse_connack(body: bytes) -> tuple[bool, int]:
    if len(body) != 2:
        raise MalformedPacket("CONNACK 长度必须为 2")
    if body[0] & 0xFE:
        raise MalformedPacket("CONNACK 保留位不为 0")
    return bool(body[0] & 0x01), body[1]


# ---------------------------------------------------------------- PUBLISH

@dataclass
class PublishPacket:
    topic: str
    payload: bytes
    retain: bool = False


def encode_publish(pkt: PublishPacket) -> bytes:
    topic = pkt.topic.encode("utf-8")
    if not topic or b"+" in topic or b"#" in topic:
        raise MalformedPacket(f"发布主题不能为空或含通配符：{pkt.topic!r}")
    body = len(topic).to_bytes(2, "big") + topic + pkt.payload
    flags = 0x30 | (0x01 if pkt.retain else 0x00)     # QoS0
    return bytes([(PUBLISH << 4) | (flags & 0x0F)]) + encode_remaining_length(len(body)) + body


def parse_publish(flags: int, body: bytes) -> PublishPacket:
    qos = (flags >> 1) & 0x03
    if qos != 0:
        raise MalformedPacket(f"本教学版只支持 QoS0，收到 QoS{qos}")
    if len(body) < 2:
        raise MalformedPacket("PUBLISH 太短")
    topic_len = int.from_bytes(body[0:2], "big")
    if topic_len == 0 or 2 + topic_len > len(body):
        raise MalformedPacket("PUBLISH 主题长度非法")
    topic = body[2:2 + topic_len].decode("utf-8", errors="replace")
    if "+" in topic or "#" in topic:
        raise MalformedPacket("发布主题不得含通配符")
    return PublishPacket(topic=topic, payload=body[2 + topic_len:], retain=bool(flags & 0x01))


# ---------------------------------------------------------------- SUBSCRIBE / SUBACK

@dataclass
class SubscribePacket:
    packet_id: int
    filters: list[str] = field(default_factory=list)


def encode_subscribe(pkt: SubscribePacket) -> bytes:
    body = pkt.packet_id.to_bytes(2, "big")
    for f in pkt.filters:
        validate_filter(f)
        fb = f.encode("utf-8")
        body += len(fb).to_bytes(2, "big") + fb + b"\x00"    # 要求 QoS0
    if not pkt.filters:
        raise MalformedPacket("SUBSCRIBE 至少要带一个过滤器")
    return bytes([(SUBSCRIBE << 4) | 0x02]) + encode_remaining_length(len(body)) + body


def parse_subscribe(flags: int, body: bytes) -> SubscribePacket:
    if flags != 0x02:
        raise MalformedPacket(f"SUBSCRIBE 标志位必须为 0x02，收到 {flags:#x}")
    if len(body) < 3:
        raise MalformedPacket("SUBSCRIBE 太短")
    packet_id = int.from_bytes(body[0:2], "big")
    filters = []
    pos = 2
    while pos < len(body):
        if pos + 2 > len(body):
            raise MalformedPacket("过滤器的长度字段不完整")
        flen = int.from_bytes(body[pos:pos + 2], "big")
        pos += 2
        if flen == 0 or pos + flen + 1 > len(body):
            raise MalformedPacket("过滤器长度非法")
        name = body[pos:pos + flen].decode("utf-8", errors="replace")
        pos += flen
        requested_qos = body[pos]
        pos += 1
        if requested_qos & 0xFC:
            raise MalformedPacket("订阅请求的 QoS 字段非法")
        validate_filter(name)                 # 校验在 parse 里做：坏过滤器=坏包
        filters.append(name)
    if not filters:
        raise MalformedPacket("SUBSCRIBE 至少要带一个过滤器")
    return SubscribePacket(packet_id=packet_id, filters=filters)


def encode_suback(packet_id: int, granted: list[int]) -> bytes:
    body = packet_id.to_bytes(2, "big") + bytes(granted)
    return bytes([SUBACK << 4]) + encode_remaining_length(len(body)) + body


def parse_suback(body: bytes) -> tuple[int, list[int]]:
    if len(body) < 3:
        raise MalformedPacket("SUBACK 太短")
    return int.from_bytes(body[0:2], "big"), list(body[2:])


# ---------------------------------------------------------------- 无载荷报文

def encode_pingreq() -> bytes:
    return bytes([PINGREQ << 4, 0])


def encode_pingresp() -> bytes:
    return bytes([PINGRESP << 4, 0])


def encode_disconnect() -> bytes:
    return bytes([DISCONNECT << 4, 0])


# ---------------------------------------------------------------- 通用解析（broker 用）

def read_packet(buf: bytes) -> tuple[int, int, bytes, int]:
    """从缓冲区头部尝试读一个报文。

    返回 (type, flags, body, total_consumed)；不完整抛 IncompletePacket；
    结构非法抛 MalformedPacket。**只读不消费**——由调用方决定何时从缓冲里剔除。
    """
    if len(buf) < 2:
        raise IncompletePacket()
    first = buf[0]
    ptype = first >> 4
    flags = first & 0x0F
    if ptype not in TYPE_NAMES:
        raise MalformedPacket(f"未知报文类型 {ptype}")
    length, len_bytes = decode_remaining_length(buf, 1)
    total = 1 + len_bytes + length
    if len(buf) < total:
        raise IncompletePacket()
    return ptype, flags, buf[1 + len_bytes:total], total


# ---------------------------------------------------------------- 主题与通配符

def validate_filter(topic_filter: str) -> None:
    if not topic_filter:
        raise MalformedPacket("主题过滤器不能为空")
    parts = topic_filter.split("/")
    for i, part in enumerate(parts):
        if "#" in part and part != "#":
            raise MalformedPacket(f"'#' 必须是独立层级：{topic_filter!r}")
        if part == "#" and i != len(parts) - 1:
            raise MalformedPacket(f"'#' 必须在末尾：{topic_filter!r}")
        if "+" in part and part != "+":
            raise MalformedPacket(f"'+' 必须是独立层级：{topic_filter!r}")


def topic_matches(topic_filter: str, topic: str) -> bool:
    """通配符订阅匹配。`$` 开头的主题不被 `#`/`+` 匹配（规范细节）。

    手算表（测试里有）：a/+/c↔a/b/c ✓；a/+ 不匹配 a/b/c；a/# 匹配 a（规范允许）；
    # 匹配 a/b/c；# 不匹配 $SYS/x；+/x 不匹配 $SYS/x。
    """
    if topic.startswith("$") and topic_filter[0] in "#+":
        return False
    f_parts = topic_filter.split("/")
    t_parts = topic.split("/")
    i = 0
    while i < len(f_parts):
        if f_parts[i] == "#":
            return True                       # 末尾多层通配：剩下全包
        if i >= len(t_parts):
            return f_parts[i] == "#"          # "a/#" 要能匹配 "a"
        if f_parts[i] != "+" and f_parts[i] != t_parts[i]:
            return False
        i += 1
    return i == len(t_parts)
