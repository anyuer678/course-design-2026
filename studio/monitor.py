"""studio/monitor.py —— 探活历史采样器：把"此刻在线"变成"过去 N 小时在线"。

动机（GAP-ANALYSIS P0）：门户原来只有瞬时状态面板，缺监控大盘的时间维度。
设计口径（与 manager 同源的诚实原则）：
    - 在线 = 端口此刻连得上（复用 ProductManager.probe，不另造一套判定）；
    - 采样在后台线程做（前端轮询 /api/products 不再顺带触发全量探活，
      状态页 3s 一刷也让探活 10s 一轮——探活历史是趋势，不必秒级）；
    - 内存环形缓冲，上限 UPTIME_MAX_SAMPLES 条（默认 10s×2160 ≈ 6 小时），
      重启即清零——这是进程内存账，不是持久化审计（持久化是 audit.sqlite3 的事）；
    - studio 本体（port=None）不采样：它在线是 tautology，画上去没有信息量。
"""
from __future__ import annotations

import threading
import time


UPTIME_MAX_SAMPLES = 2160          # 10s 间隔下约 6 小时历史


class UptimeMonitor:
    """后台线程：周期性 TCP 探活全部带端口的产品，滚动记录上线/掉线。"""

    def __init__(self, manager, *, interval: float = 10.0,
                 max_samples: int = UPTIME_MAX_SAMPLES, clock=time.time):
        self.manager = manager
        self.interval = interval
        self.max_samples = max_samples
        self.clock = clock
        self.samples: list[tuple[float, dict[str, bool]]] = []   # 时间升序
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- 采样
    def sample_once(self) -> dict[str, bool]:
        """立即探活一轮（公开给测试：不必 sleep 等 interval）。"""
        reading: dict[str, bool] = {}
        for pid in self.manager.order:
            p = self.manager.by_id[pid]
            if p.port is None:            # studio 本体与已规划产品不采
                continue
            reading[pid] = self.manager.probe(p.port)
        with self._lock:
            self.samples.append((self.clock(), reading))
            if len(self.samples) > self.max_samples:
                del self.samples[:len(self.samples) - self.max_samples]
        return reading

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.sample_once()
            except Exception:
                pass                      # 采样失败不许带垮线程；下轮再试

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="studio-uptime")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._thread = None

    # ---- 出口
    def history(self) -> dict:
        """给 /api/history 的载荷：产品顺序 + 压缩采样（位掩码按产品序）。"""
        with self._lock:
            rows = list(self.samples)
        pids = [pid for pid in self.manager.order
                if self.manager.by_id[pid].port is not None]
        index = {pid: i for i, pid in enumerate(pids)}
        samples = []
        for ts, reading in rows:
            mask = 0
            for pid, up in reading.items():
                if up and pid in index:
                    mask |= 1 << index[pid]
            samples.append([round(ts, 1), mask])
        return {"interval": self.interval, "products": pids,
                "samples": samples, "capacity": self.max_samples}
