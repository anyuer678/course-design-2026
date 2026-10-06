"""linkbox/sweeper.py —— M3：过期暂存的后台清扫线程。

与 StashStore.sweep 的分工：sweep(now) 是无线程的纯存储操作（可单测、
可在 demo 里手动调）；本模块只负责"定时跑它 + 上报删了几行"。
清扫失败只上报不抛出——后台任务不许把服务器带垮。
"""
from __future__ import annotations

import threading
import time


class StashSweeper:
    """过期清扫线程。轮八起支持多个仓储（暂存 + 文件）：
    StashSweeper(stash, files, interval=…)——逐个 sweep，失败只上报不抛。"""

    def __init__(self, *stores, interval: float = 300.0,
                 clock=time.time, report=print):
        self.stores = list(stores)
        self.interval = interval
        self.clock = clock
        self.report = report
        self.cleaned = 0                        # 累计清扫条数（可观测）
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="stash-sweeper")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def sweep_once(self) -> int:
        """手动跑一轮（测试与 demo 用），返回这轮删了几条。"""
        n = sum(store.sweep(now=self.clock()) for store in self.stores)
        self.cleaned += n
        if n:
            self.report(f"[清扫] 删除 {n} 条过期条目（累计 {self.cleaned}）")
        return n

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.sweep_once()
            except Exception as exc:            # 清扫失败不许带垮服务器
                self.report(f"[清扫] 失败：{exc!r}")
