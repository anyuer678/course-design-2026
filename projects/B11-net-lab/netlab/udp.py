"""netlab/udp.py —— 数据报格式、真实回环 UDP，和一条能复现的"坏信道"。

UDP 与 TCP 的分工在这一个文件里最直观：
数据报有边界但没有顺序、没有重传、没有流控——所以每个包必须自带序号和校验和，
可靠性得由上层（gbn.py）自己挣。

* PacketFmt：kind + seq + length + crc32，9 字节头 + 体 + 4 字节校验；
* SockLink：真·UDP 套接字，非阻塞收发，用来在 127.0.0.1 上真跑一遍；
* SimChannel：种子化坏信道，丢包/损坏/重复/乱序都由固定随机序列决定，
  同一个 seed 跑两次结果逐字节一致——课程实验要的是可复现，不是碰运气。
"""
from __future__ import annotations

import heapq
import random
import socket
import struct
import time
import zlib

DATA, ACK, DATA_END = 0, 1, 2      # DATA_END：带数据，而且是流的最后一个包
HEADER = struct.Struct(">BHI")     # kind, seq, payload 长度
CRC = struct.Struct(">I")

MAX_DATAGRAM = 65535                     # UDP 单包上限，超了就得自己切
DEFAULT_MSS = 1024                       # 每个数据报装多少字节有效数据


def encode(kind: int, seq: int, payload: bytes = b"") -> bytes:
    body = HEADER.pack(kind, seq, len(payload)) + payload
    return body + CRC.pack(zlib.crc32(body) & 0xFFFFFFFF)


def decode(packet: bytes):
    """解一个数据报；坏包一律返回 None，由上层当"没收到"处理。

    None 的成因有两种（真丢了 / 到了但校验和对不上），对 GBN 来说结论一样——
    不发 ACK，发送方超时重传，所以不必区分，也不用告诉对方"你为什么没回我"。
    """
    if len(packet) < HEADER.size + CRC.size:
        return None
    body, crc = packet[:-CRC.size], packet[-CRC.size:]
    if CRC.unpack(crc)[0] != (zlib.crc32(body) & 0xFFFFFFFF):
        return None
    kind, seq, length = HEADER.unpack_from(body)
    payload = body[HEADER.size:]
    if kind not in (DATA, ACK, DATA_END) or length != len(payload):
        return None
    return kind, seq, payload


class SockLink:
    """真 UDP 套接字的链路视图：非阻塞式轮询收，收到什么算什么。

    poll 是"这一轮最多等多久"，不是整场传输的期限——传输期限由 gbn 的 runner 管，
    把两者混在一个 timeout 参数里，发送方每次空等都会拖满整个期限。
    """

    def __init__(self, sock: socket.socket, peer, poll: float = 0.05):
        self.sock = sock
        self.peer = peer
        self.poll = poll
        self.sock.settimeout(poll)

    def send(self, packet: bytes) -> None:
        self.sock.sendto(packet, self.peer)

    def recv(self) -> bytes | None:
        try:
            data, _ = self.sock.recvfrom(MAX_DATAGRAM)
        except socket.timeout:
            return None                  # 这个轮次没等到包，等价于"丢了"
        return data

    def now(self) -> float:
        return time.monotonic()

    def close(self) -> None:
        self.sock.close()


def make_pair(poll: float = 0.05) -> tuple[SockLink, SockLink]:
    """两个绑在 127.0.0.1 随机端口上的端点，供真发一次的教学实验用。"""
    a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    a.bind(("127.0.0.1", 0))
    b.bind(("127.0.0.1", 0))
    return SockLink(a, b.getsockname(), poll), SockLink(b, a.getsockname(), poll)


class SimChannel:
    """种子化坏信道。

    虚拟时钟每 tick 前进一格，包按 (到达时刻) 排队；所有随机决定在**发送那一刻**做完，
    所以只要 seed 和各概率固定，整条轨迹就是确定的，跟机器快慢无关。
    """

    def __init__(self, seed: int = 1, drop: float = 0.0, corrupt: float = 0.0,
                 duplicate: float = 0.0, reorder: float = 0.0, jitter: int = 0):
        for name, value in (("drop", drop), ("corrupt", corrupt),
                            ("duplicate", duplicate), ("reorder", reorder)):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name}={value} 得是概率")
        if jitter < 0:
            raise ValueError("jitter 不能为负")
        self.rng = random.Random(seed)
        self.drop, self.corrupt = drop, corrupt
        self.duplicate, self.reorder, self.jitter = duplicate, reorder, jitter
        # 每个方向一个到期时间堆：0 是 a→b，1 是 b→a。
        # 必须是堆而不是队列——只看队头的话，一个晚到的头包会把后面全堵住，
        # "乱序"这个参数就永远不生效，测出来的 GBN 是假的。
        self.queues = {0: [], 1: []}
        self.serial = 0
        self.time = 0
        self.counts = {"sent": 0, "dropped": 0, "corrupted": 0,
                       "duplicated": 0, "reordered": 0, "delivered": 0}

    # -------------------------------------------------------- 包的搬运
    def fate(self, packet: bytes) -> tuple[list, int]:
        """这一个包在信道里的命运：要投递的副本列表 + 额外延迟格数。

        所有随机数都在"发送这一刻"抽完，所以同一个 seed 的整条轨迹是确定的，
        跟机器快慢、跟谁先跑都无关——这是实验能复现的前提。
        """
        if self.rng.random() < self.drop:
            self.counts["dropped"] += 1
            return [], 0
        if self.rng.random() < self.corrupt:
            self.counts["corrupted"] += 1
            copies = [self._flip(packet)]
        else:
            copies = [packet]
        if self.rng.random() < self.duplicate:
            self.counts["duplicated"] += 1
            copies.append(packet)
        delay = self.rng.randrange(self.jitter + 1) if self.jitter else 0
        if self.rng.random() < self.reorder:
            self.counts["reordered"] += 1
            delay += 2                          # 乱序：让它比后面到的包更晚
        return copies, delay

    def _flip(self, packet: bytes) -> bytes:
        if not packet:
            return packet
        bad = bytearray(packet)
        bad[self.rng.randrange(len(bad))] ^= 0x01      # 翻一位，crc 一定对不上
        return bytes(bad)

    def send(self, direction: int, packet: bytes) -> None:
        self.counts["sent"] += 1
        copies, delay = self.fate(packet)
        for i, copy in enumerate(copies):
            # serial 保证同一到期时刻仍按发送顺序交付，也避免比较 bytes
            heapq.heappush(self.queues[direction],
                           (self.time + 1 + delay + i, self.serial, copy))
            self.serial += 1

    def pop(self, direction: int) -> bytes | None:
        queue = self.queues[direction]
        if queue and queue[0][0] <= self.time:
            self.counts["delivered"] += 1
            return heapq.heappop(queue)[2]
        return None

    def endpoints(self) -> tuple["Endpoint", "Endpoint"]:
        return Endpoint(self, 0), Endpoint(self, 1)

    def tick(self) -> None:
        self.time += 1

    def pending(self) -> int:
        return sum(len(q) for q in self.queues.values())


class Endpoint:
    """信道的一只插头：和 SockLink 同接口，GBN 不需要知道自己在哪种信道上。

    side=0 是 A 端：发往队列 0（a→b），从队列 1（b→a）读。
    side=1 是 B 端正好相反——两只插头必须交叉，不然双方都在读自己发出的那条线，
    表现就是"一个包都收不到，发送方疯狂重传"。
    """

    def __init__(self, channel: SimChannel, side: int):
        self.channel = channel
        self.side = side
        self.out_queue = side
        self.in_queue = 1 - side

    def send(self, packet: bytes) -> None:
        self.channel.send(self.out_queue, packet)

    def recv(self) -> bytes | None:
        return self.channel.pop(self.in_queue)

    def now(self) -> int:
        return self.channel.time

    def close(self) -> None:
        pass
