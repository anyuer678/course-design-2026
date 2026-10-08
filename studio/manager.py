"""studio/manager.py —— 产品进程管理：TCP 探活、子进程启动、停止。

诚实口径：
    - 在线 = 端口此刻连得上（不管是谁启动的）；门户自己启动的才记进程句柄，
      没句柄但在线的产品不允许"停止"（不知道那进程是什么，不许乱杀）；
    - 已规划产品没有 command，start 直接拒（不装样子）。
"""
from __future__ import annotations

import socket
import subprocess
import time


class Product:
    def __init__(self, pid: str, name: str, tagline: str, *,
                 port: int | None = None, command: list | None = None,
                 cwd: str | None = None, kind: str = "web"):
        self.id = pid
        self.name = name
        self.tagline = tagline
        self.port = port
        self.command = command              # None = 已规划（不可启动）
        self.cwd = cwd
        self.kind = kind                    # web = 浏览器可开；desktop = 桌面窗口应用
                                            # （端口只是探活口/行协议，不是 HTTP，门户不给"打开产品"）

    @property
    def managed(self) -> bool:
        return self.command is not None


class AlreadyOnline(Exception):
    """端口已在线（无论是否门户启动的），不该再 start。"""


class NotOurs(Exception):
    """在线但门户没有它的进程句柄——不许 stop（可能不是门户启的）。"""


class ProductManager:
    def __init__(self, products: list[Product], *, probe_timeout: float = 0.3,
                 boot_timeout: float = 10.0, audit=None):
        self.by_id: dict[str, Product] = {p.id: p for p in products}
        self.order = [p.id for p in products]
        self.procs: dict[str, subprocess.Popen] = {}
        self.probe_timeout = probe_timeout
        self.boot_timeout = boot_timeout
        self.audit = audit                   # M2：AuditLog 或 None（不记账）

    # ------------------------------------------------ 探活
    def probe(self, port: int) -> bool:
        if port is None:
            return False
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.probe_timeout)
        try:
            return sock.connect_ex(("127.0.0.1", port)) == 0
        finally:
            sock.close()

    def status(self, pid: str) -> dict:
        p = self.by_id[pid]
        online = self.probe(p.port) if p.port is not None else False
        proc = self.procs.get(pid)
        return {"id": p.id, "name": p.name, "tagline": p.tagline,
                "port": p.port, "managed": p.managed, "online": online,
                "kind": p.kind,
                "pid": proc.pid if proc is not None else None}

    def listing(self) -> list[dict]:
        return [self.status(pid) for pid in self.order]

    # ------------------------------------------------ 启停
    def _audit(self, action: str, pid: str, outcome: str, detail: str = "") -> None:
        """M2 操作审计：拒绝/失败与成功一样入账。审计出任何问题都不许绊倒管理动作。"""
        if self.audit is None:
            return
        try:
            self.audit.record(action, pid, outcome, detail)
        except Exception:
            pass

    def start(self, pid: str) -> dict:
        p = self.by_id[pid]
        if not p.managed:
            self._audit("start", pid, "refused", f"{p.name} 已规划，无实现")
            raise ValueError(f"{p.name} 还是已规划状态，没有可启动的实现")
        if self.procs.get(pid) is not None or self.probe(p.port):
            self._audit("start", pid, "refused", f"已在 127.0.0.1:{p.port} 运行")
            raise AlreadyOnline(f"{p.name} 已在 127.0.0.1:{p.port} 运行")
        proc = subprocess.Popen(
            p.command, cwd=p.cwd,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs[pid] = proc
        deadline = time.monotonic() + self.boot_timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                self.procs.pop(pid, None)
                self._audit("start", pid, "failed",
                            f"启动后立即退出（码 {proc.returncode}）")
                raise ValueError(f"{p.name} 启动后立即退出（码 {proc.returncode}）")
            if self.probe(p.port):
                self._audit("start", pid, "ok", f"端口 {p.port}")
                return self.status(pid)
            time.sleep(0.15)
        self._audit("start", pid, "timeout",
                    f"{self.boot_timeout:.0f}s 未探活（如实报 offline）")
        return self.status(pid)             # 超时仍未探活：如实报 offline

    def stop(self, pid: str) -> dict:
        p = self.by_id[pid]
        proc = self.procs.get(pid)
        if proc is None:
            if self.probe(p.port) if p.port else False:
                self._audit("stop", pid, "refused", "在线但不是门户启动的")
                raise NotOurs(f"{p.name} 在线但不是本门户启动的，请自行停止")
            return self.status(pid)         # 本来就离线：幂等，无事发生不记账
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        self.procs.pop(pid, None)
        self._audit("stop", pid, "ok", f"端口 {p.port}")
        return self.status(pid)
