"""netlab/gbn.py —— Go-Back-N 滑动窗口，把不可靠的 UDP 变成按序、无重复的字节流。

教科书规则，一条都不省略：

* 发送方维护窗口 ``[base, nextseq)``：窗口满就停，定时器挂在最老的未确认包上；
* 定时器到点，**base 到 nextseq-1 整窗重传**——这就是 "go-back-n" 这个名字的代价；
* 接收方只认 ``expected`` 号：按序交付；超前的丢弃并回当前累计 ACK，
  落后的是重复包，同样只回 ACK 而绝不重复交付；
* ACK 是累计的（值 = 下一个期望的号），所以一个 ACK 能确认一串包；
* 内部序号是**不回绕的逻辑计数**，上线时才取模；比较一律走 `seq_diff` 的
  "对折有符号距离"，直接 ``a > b`` 在回绕处必然出错。

同一段代码跑在两种链路上：仿真坏信道（时隙为单位，结果可复现）
和 127.0.0.1 上的真 UDP 套接字（秒为单位）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .udp import ACK, DATA, DATA_END, DEFAULT_MSS, decode, encode


def seq_diff(a: int, b: int, space: int) -> int:
    """回绕序号的有符号距离 a-b。

    例：space=8 时 1 与 7 的真实距离是 -2（从 1 往回两格才是 7），
    直接比大小会说 7 比 1 大 6，窗口判定立刻错乱。
    """
    d = (a - b) % space
    return d - space if d > space // 2 else d


class Sender:
    """发送窗口。step() 一次：收 ACK → 判超时 → 补窗口。"""

    def __init__(self, link, data: bytes, *, mss: int = DEFAULT_MSS, window: int = 8,
                 timeout: float = 6, seq_space: int = 1 << 16):
        if window < 1:
            raise ValueError("window 至少为 1")
        if window > seq_space // 2:
            # 经典条件：窗口超过半个序号空间，"新包的号"和"旧包的号"就分不开了
            raise ValueError(f"window={window} 超过 seq_space={seq_space} 的一半")
        self.link = link
        self.packets = [data[i:i + mss] for i in range(0, len(data), mss)]
        self.total = len(self.packets)
        self.window, self.timeout, self.space = window, timeout, seq_space
        self.base = 0                  # 不回绕的逻辑序号
        self.nextseq = 0
        self.sent_at: dict[int, float] = {}
        self.transmitted = 0
        self.retransmitted = 0
        self.timeouts = 0

    def step(self) -> None:
        self._collect_acks()
        if self.done():
            return
        now = self.link.now()
        if self._oldest_unacked_is_late(now):
            self._go_back_n(now)
        self._fill_window()

    def _collect_acks(self) -> None:
        while True:
            packet = self.link.recv()
            if packet is None:
                return
            decoded = decode(packet)
            if decoded is None or decoded[0] != ACK:
                continue                       # 坏包或对方的数据：发送方不处理
            # 线上是取模后的号，换算回"相对 base 的距离"才知道它确认到哪
            gap = seq_diff(decoded[1], self.base % self.space, self.space)
            if 0 < gap <= self.nextseq - self.base:
                self.base += gap

    def _oldest_unacked_is_late(self, now: float) -> bool:
        return (self.base < self.nextseq
                and now - self.sent_at[self.base] >= self.timeout)

    def _go_back_n(self, now: float) -> None:
        self.timeouts += 1
        for seq in range(self.base, self.nextseq):        # 整窗重传，不是只补那一个
            self._send_seq(seq, now)
            self.retransmitted += 1
            self.sent_at[seq] = now                       # 重传就要重新计时，否则立刻再超时

    def _fill_window(self) -> None:
        now = self.link.now()
        while self.nextseq < self.total and self.nextseq - self.base < self.window:
            self._send_seq(self.nextseq, now)
            self.sent_at[self.nextseq] = now
            self.nextseq += 1

    def _send_seq(self, seq: int, now: float) -> None:
        kind = DATA_END if seq == self.total - 1 else DATA
        self.link.send(encode(kind, seq % self.space, self.packets[seq]))
        self.transmitted += 1

    def done(self) -> bool:
        return self.base == self.total

    def pending(self) -> bool:
        return self.base < self.nextseq


class Receiver:
    """按序交付。step() 一次：处理所有当前到达的包，每个数据包都回一个累计 ACK。"""

    def __init__(self, link, *, seq_space: int = 1 << 16):
        self.link = link
        self.space = seq_space
        self.expected = 0              # 不回绕的逻辑序号
        self.received = bytearray()
        self.delivered = 0
        self.duplicates = 0
        self.out_of_order = 0
        self.corrupt = 0
        self.finished = False

    def step(self) -> None:
        while True:
            packet = self.link.recv()
            if packet is None:
                return
            decoded = decode(packet)
            if decoded is None:        # 校验和不对：当没收到，让发送方超时重传
                self.corrupt += 1
                continue
            kind, seq, payload = decoded
            if kind not in (DATA, DATA_END):
                continue
            gap = seq_diff(seq, self.expected % self.space, self.space)
            if gap == 0:
                self.received += payload
                self.delivered += 1
                self.expected += 1
                if kind == DATA_END:
                    self.finished = True
            elif gap < 0:
                self.duplicates += 1   # 早已交付：只回 ACK，绝不重复交付
            else:
                self.out_of_order += 1  # 超前：GBN 不缓冲重排，直接丢
            self.link.send(encode(ACK, self.expected % self.space))


@dataclass
class Result:
    finished: bool
    slots: int
    received: bytes
    sender: Sender
    receiver: Receiver
    channel_counts: dict = field(default_factory=dict)

    @property
    def efficiency(self) -> float:
        """真正交付的包 / 一共发出去的包：坏信道上 GBN 要付的学费。"""
        return self.receiver.delivered / max(self.sender.transmitted, 1)

    def summary(self) -> str:
        counts = self.channel_counts
        return (f"完成={self.finished} 时隙={self.slots} "
                f"发送={self.sender.transmitted}（重传 {self.sender.retransmitted}、"
                f"超时 {self.sender.timeouts}）交付={self.receiver.delivered} "
                f"重复={self.receiver.duplicates} 超前={self.receiver.out_of_order} "
                f"坏包={self.receiver.corrupt} 信道丢包={counts.get('dropped', 0)}")


def run_simulation(data: bytes, channel, *, mss: int = DEFAULT_MSS, window: int = 8,
                   timeout: float = 6, seq_space: int = 1 << 16,
                   max_slots: int = 20000) -> Result:
    """在仿真信道上把 data 传一遍；不抛异常，结论都由调用方断言。"""
    a, b = channel.endpoints()
    sender = Sender(a, data, mss=mss, window=window, timeout=timeout, seq_space=seq_space)
    receiver = Receiver(b, seq_space=seq_space)
    slots = 0
    while not sender.done() and slots < max_slots:
        channel.tick()
        slots += 1
        sender.step()
        receiver.step()
    return Result(sender.done(), slots, bytes(receiver.received), sender, receiver,
                  dict(channel.counts))


def run_real_sender(link, data: bytes, *, deadline: float = 15.0, **kw) -> Sender:
    """真 UDP 上的发送方：阻塞到自己收到全部确认，或到截止时间。"""
    sender = Sender(link, data, **kw)
    limit = time.monotonic() + deadline
    while not sender.done() and time.monotonic() < limit:
        sender.step()
    return sender


def run_real_receiver(link, *, deadline: float = 15.0, seq_space: int = 1 << 16) -> Receiver:
    receiver = Receiver(link, seq_space=seq_space)
    limit = time.monotonic() + deadline
    while not receiver.finished and time.monotonic() < limit:
        receiver.step()
    return receiver
