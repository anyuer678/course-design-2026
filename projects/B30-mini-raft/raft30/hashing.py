"""raft30/hashing.py —— 哈希分片：朴素取模 vs 一致性哈希

课程要点：
    - 朴素分片 shard = hash(key) % n：扩容/缩容时几乎所有键都要搬家
      （模数变了，余数全变）。
    - 一致性哈希：把节点与键都放到同一个哈希环上，键归"顺时针第一个节点"；
      增删节点只影响环上相邻区段——理想搬移比例是 1/n。
    - 虚拟节点（vnode）：每个物理节点在环上放多个副本，抹平数据倾斜。
    - 哈希函数必须**跨进程稳定**：Python 内置 hash() 对 str 每次启动随机加盐，
      不能用于分片；这里用 zlib.crc32（教学级，工程可用 murmur3/xxhash）。
"""
from __future__ import annotations

import bisect
import zlib


def stable_hash(key: str) -> int:
    """跨进程稳定的 32 位哈希（内置 hash 对 str 有进程级随机盐，不可用）。"""
    return zlib.crc32(key.encode("utf-8")) & 0xFFFFFFFF


class NaiveShard:
    """hash(key) % n。节点数一变，几乎所有键的归属都会变。"""

    def __init__(self, n: int):
        self.n = n

    def shard(self, key: str) -> int:
        return stable_hash(key) % self.n


class ConsistentHash:
    """一致性哈希环。vnodes = 每个物理节点在环上的虚拟副本数。"""

    def __init__(self, nodes: list[str], vnodes: int = 100):
        if not nodes:
            raise ValueError("至少一个节点")
        self.vnodes = vnodes
        self.ring: list[tuple[int, str]] = []     # (环上位置, 节点名)
        self.nodes: set[str] = set()
        for node in nodes:
            self.add(node, rebuild=False)
        self._rebuild()

    def _vnode_key(self, node: str, i: int) -> int:
        return stable_hash(f"{node}#v{i}")

    def add(self, node: str, rebuild: bool = True) -> None:
        self.nodes.add(node)
        if rebuild:
            self._rebuild()

    def remove(self, node: str, rebuild: bool = True) -> None:
        self.nodes.discard(node)
        if rebuild:
            self._rebuild()

    def _rebuild(self) -> None:
        self.ring = sorted((self._vnode_key(n, i), n)
                           for n in self.nodes
                           for i in range(self.vnodes))
        self.positions = [p for p, _ in self.ring]

    def shard(self, key: str) -> str:
        h = stable_hash(key)
        i = bisect.bisect_right(self.positions, h) % len(self.ring)
        return self.ring[i][1]


def moved_fraction(old, new, keys: list[str]) -> float:
    """扩缩容前后归属变化的键比例——两种分片方案对比的核心指标。"""
    if not keys:
        return 0.0
    moved = sum(1 for k in keys if old.shard(k) != new.shard(k))
    return moved / len(keys)
