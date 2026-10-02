"""repro/crdt_lww.py —— 最小复现：LWW-Register 的收敛性（交换/结合/幂等）

对应 docs/records/example-crdt.md 的「原理」一节，专为"可亲手验证"而写：
    - 时间戳 = (计数器, 副本号)：计数器在副本内单调递增，副本号做**全序破平**——
      没有全序就没有确定的赢家；
    - merge = 取 timestamps 较大的一侧 → join（上确界）：交换/结合/幂等，
      这三条性质合起来就是"最终一致"的充分条件；
    - 向量时钟只记录每副本进度（本最小复现不实现因果投递——写明在记录的局限里）。

刻意保持小（<150 行）：雷达的"最小复现"要让人 10 分钟能读完、跑完、改坏看红。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(order=True)
class Timestamp:
    """(计数器, 副本号) 全序：计数器主序，副本号破平（确定性收敛的关键）。"""

    counter: int
    replica: str


class VectorClock:
    """每副本进度计数器；merge = 逐副本取 max（与 LWW 同构的 join）。"""

    def __init__(self) -> None:
        self.progress: dict[str, int] = {}

    def tick(self, replica: str) -> int:
        self.progress[replica] = self.progress.get(replica, 0) + 1
        return self.progress[replica]

    def get(self, replica: str) -> int:
        return self.progress.get(replica, 0)

    def merge(self, other: "VectorClock") -> None:
        for replica, count in other.progress.items():
            if count > self.progress.get(replica, 0):
                self.progress[replica] = count

    def copy(self) -> "VectorClock":
        clone = VectorClock()
        clone.progress = dict(self.progress)
        return clone


@dataclass
class LWWRegister:
    """最后写入赢的寄存器：状态 = (值, 时间戳)；merge = 取较大时间戳。"""

    replica: str
    value: object = None
    ts: Timestamp | None = None
    clock: VectorClock = field(default_factory=VectorClock)

    def set(self, value) -> Timestamp:
        ts = Timestamp(self.clock.tick(self.replica), self.replica)
        self.value, self.ts = value, ts
        return ts

    def merge_in(self, other: "LWWRegister") -> None:
        """把 other 合并进自己（原地）：时间戳大者胜；相等即同一写，幂等。

        守卫：同一 (计数器, 副本号) 出现**两个不同的值**是协议违规
        （一个副本的同一计数不可能写两次），宁可当场报错也不要"悄悄按到达顺序取一个"——
        那正是 LWW 收敛性最容易被误解的地方。
        """
        if other.ts is not None and self.ts is not None \
                and other.ts == self.ts and other.value != self.value:
            raise ValueError(
                f"协议违规：同一时间戳 {other.ts} 出现两个值 "
                f"{self.value!r} / {other.value!r}")
        if self.ts is None or (other.ts is not None and other.ts > self.ts):
            self.value, self.ts = other.value, other.ts
        self.clock.merge(other.clock)

    @staticmethod
    def merged(registers: list["LWWRegister"]) -> "LWWRegister":
        """把一组副本合并出一个新副本（顺序随意——性质测试就是验证这句话）。"""
        out = LWWRegister(replica="merge")
        for reg in registers:
            out.merge_in(reg)
        return out


def apply_ops(register: LWWRegister, ops: list) -> LWWRegister:
    """在副本上顺序施加写操作（每个元素是一个值）。"""
    for value in ops:
        register.set(value)
    return register


def converge(registers: list[LWWRegister], order: list[int]) -> LWWRegister:
    """按给定下标顺序逐个合并（不同顺序 = 不同网络的到达顺序）。"""
    out = LWWRegister(replica="merge")
    for idx in order:
        out.merge_in(registers[idx])
    return out
