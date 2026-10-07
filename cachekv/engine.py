"""cachekv/engine.py —— 产品层引擎：统计计数 + 快照调度（KV 核心是 B38 的 Store）。

复用边界（如实声明）：
    - SET/GET/DEL/EXPIRE/TTL/INCR 的全部语义、惰性+主动过期双策略，
      都来自 B38 redislite.store.Store（clock 可注入，测试不 sleep）；
    - 快照编码/原子写来自 B38 redislite.dbsnap；
    - CacheKV 新增的只有：命中/未命中/写入/删除的统计账（线程安全）、
      变更置脏 + 定时快照的调度（SnapshotSaver）。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from redislite.dbsnap import load_snapshot, save_snapshot
from redislite.store import Store


class CacheKV(Store):
    """B38 Store 的产品化子类：每个命令都记账，快照随取随存。"""

    def __init__(self, *, clock=time.time, snapshot_path: str | Path | None = None):
        super().__init__(clock=clock)
        self.snapshot_path = Path(snapshot_path) if snapshot_path else None
        self.dirty = False
        self._lock = threading.Lock()
        # 注意：不能叫 self.stats——B38 Store 内部有自己的 stats 账
        #（expired_lazy 等），覆盖它会让惰性过期当场 KeyError。
        self.account = {"hits": 0, "misses": 0, "sets": 0, "deletes": 0,
                        "snapshots_saved": 0}

    # ---- 命令记账（语义零改动，只加账）
    def cmd_get(self, key: bytes) -> bytes | None:
        value = super().cmd_get(key)
        with self._lock:
            self.account["hits" if value is not None else "misses"] += 1
        return value

    def cmd_set(self, key: bytes, value: bytes) -> None:
        super().cmd_set(key, value)
        with self._lock:
            self.account["sets"] += 1
        self.dirty = True

    def cmd_del(self, keys: list[bytes]) -> int:
        removed = super().cmd_del(keys)
        with self._lock:
            self.account["deletes"] += removed
        if removed:
            self.dirty = True
        return removed

    def cmd_expire(self, key: bytes, seconds: int) -> int:
        result = super().cmd_expire(key, seconds)
        if result == 1:
            self.dirty = True
        return result

    # ---- 统计出口
    def stats_view(self) -> dict:
        with self._lock:
            base = dict(self.account)
        base["keys"] = sum(1 for key, _, _ in self.export_state()
                           if not self._check_expired(key))
        base["gets"] = base["hits"] + base["misses"]
        if base["gets"]:
            base["hit_rate"] = round(base["hits"] / base["gets"], 4)
        else:
            base["hit_rate"] = None
        return base

    def overview(self) -> dict:
        """仪表盘聚合（轮九）：存活键明细（大小/剩余 TTL）+ 统计。
        TTL 一律按引擎自己的时钟算（clock 可注入 → 测试不必 sleep）。"""
        now = self.clock()
        rows = []
        for key, value, expires_at in self.export_state():
            if self._check_expired(key):
                continue
            rows.append({"key": key.decode("utf-8", "replace"),
                         "size": len(value),
                         "expires_at": expires_at,
                         "ttl": round(expires_at - now, 1) if expires_at else None})
        rows.sort(key=lambda r: (r["ttl"] is None,
                                 r["ttl"] if r["ttl"] is not None else 0))
        return {"stats": self.stats_view(), "keys": rows}

    # ---- 快照（B38 dbsnap：同目录临时文件 + fsync + os.replace 原子写）
    def save(self) -> int:
        """保存快照，返回写入的键数（B38 的 save_snapshot 返回字节数，记进账）。"""
        if not self.snapshot_path:
            return 0
        entries = self.export_state()
        payload_bytes = save_snapshot(self.snapshot_path, entries)
        self.dirty = False
        with self._lock:
            self.account["snapshots_saved"] += 1
            self.account["snapshot_bytes"] = payload_bytes
        return len(entries)

    def load(self) -> int:
        if not self.snapshot_path or not self.snapshot_path.is_file():
            return 0
        entries = load_snapshot(self.snapshot_path)
        loaded = self.load_state(entries)
        return loaded


class SnapshotSaver:
    """定时快照线程：脏了才写（B10 的"没改动别写盘"经验）。失败只上报不带垮服务。"""

    def __init__(self, engine: CacheKV, *, interval: float = 60.0, report=print):
        self.engine = engine
        self.interval = interval
        self.report = report
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="cachekv-snapshot")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            # 在途快照写完再放行：停机刷盘（engine.save）与快照线程写的是同一个
            # 临时文件，不 join 就是两写竞态 → 坏快照（2026-10-07 审查收口）
            thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            if not self.engine.dirty:
                continue
            try:
                count = self.engine.save()
                self.report(f"[快照] 已保存 {count} 个键")
            except Exception as exc:
                self.report(f"[快照] 失败：{exc!r}")
