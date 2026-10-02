"""redislite/server.py —— selectors 单线程事件循环（多客户端 + 管线 + 坏包处理）

课程要点（对应 docs/case-study.md 第 1 节）：
    - **单线程串行化**：所有连接的命令在同一个循环里顺序执行——INCR 的
      "读-改-写"永远不被打断，这就是 Redis 不加锁的原子性来源。
    - 每个连接一个输入缓冲（FrameDecoder）+ 输出缓冲：`recv` 到多少解多少、
      `send` 出去多少算多少，剩下的挂 **EVENT_WRITE** 等下次可写——
      慢客户端不会阻塞别人（没有 per-connection 线程）。
    - **坏包处理**：协议错误 → 回 `-ERR Protocol error: <分类>` → 断开该连接；
      其他连接毫发无损（fuzz 的全部要求，测试逐条钉）。
    - 主动过期由**命令计数**触发（每 N 条一次）——真实 Redis 另有时间触发，
      这里简化并声明（见 README 偏离表）。
"""
from __future__ import annotations

import selectors
import socket
import threading
import time
from pathlib import Path

from redislite import resp
from redislite.dbsnap import SnapshotError, load_snapshot, save_snapshot
from redislite.store import CommandError, Store, _Ok, _Pong, _Save

READ = selectors.EVENT_READ
WRITE = selectors.EVENT_WRITE


class _Conn:
    __slots__ = ("sock", "dec", "out", "addr", "want_write", "close_after_flush")

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.dec = resp.FrameDecoder()
        self.out = bytearray()
        self.want_write = False
        self.close_after_flush = False        # 错误帧发完再关（真实 Redis 的 CLOSE_AFTER_REPLY）


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, dbfile=None,
                 clock=time.time, active_every: int = 64):
        self.sel = selectors.DefaultSelector()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(64)
        self.sock.setblocking(False)
        self.port = self.sock.getsockname()[1]
        self.store = Store(clock=clock)
        self.dbfile = Path(dbfile) if dbfile else None
        self.active_every = active_every
        self._since_cycle = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.conns: dict[int, _Conn] = {}
        self.stats = {"connections": 0, "commands": 0, "protocol_errors": 0}
        if self.dbfile and self.dbfile.exists():
            try:
                self.store.load_state(load_snapshot(self.dbfile))
            except SnapshotError:
                self.sock.close()                  # 构造失败不泄漏监听套接字
                self.sel.close()
                raise

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> "Server":
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def serve_forever(self, poll: float = 0.02) -> None:
        self.sel.register(self.sock, READ, ("accept", None))
        while not self._stop.is_set():
            for key, mask in self.sel.select(timeout=poll):
                what, conn = key.data
                if what == "accept":
                    self._accept_ready()
                else:
                    if conn.sock.fileno() < 0:      # 本轮里已被关掉
                        continue
                    if mask & READ:
                        self._read_ready(conn)
                    if conn.sock.fileno() >= 0 and (mask & WRITE or conn.want_write):
                        self._write_ready(conn)
            if self._stop.is_set():
                break
        self._shutdown()

    def _shutdown(self) -> None:
        for conn in list(self.conns.values()):
            self._close(conn)
        self.sel.unregister(self.sock)
        self.sock.close()
        self.sel.close()

    # ---------------------------------------------------------------- 连接
    def _accept_ready(self) -> None:
        while True:
            try:
                sock, addr = self.sock.accept()
            except BlockingIOError:
                return
            sock.setblocking(False)
            conn = _Conn(sock, addr)
            self.conns[sock.fileno()] = conn
            self.sel.register(sock, READ, ("conn", conn))
            self.stats["connections"] += 1

    def _close(self, conn: _Conn) -> None:
        fileno = conn.sock.fileno()
        if fileno >= 0:
            try:
                self.sel.unregister(conn.sock)
            except (KeyError, ValueError):
                pass
            conn.sock.close()
            self.conns.pop(fileno, None)

    def _read_ready(self, conn: _Conn) -> None:
        try:
            data = conn.sock.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except ConnectionResetError:
            self._close(conn)
            return
        if not data:
            self._close(conn)
            return
        conn.dec.feed(data)
        self._process(conn)

    def _process(self, conn: _Conn) -> None:
        while True:
            try:
                args = conn.dec.next_command()
            except resp.ProtocolError as err:
                self.stats["protocol_errors"] += 1
                conn.out += resp.encode_error(f"ERR Protocol error: {err}")
                conn.close_after_flush = True      # 先把错误帧发给对方，再优雅断开
                self._flush(conn)
                return
            if args is resp.INCOMPLETE:
                break
            if not args:                               # *0 / *-1 / 空行：无命令
                continue
            self.stats["commands"] += 1
            self._since_cycle += 1
            if self.active_every and self._since_cycle >= self.active_every:
                self._since_cycle = 0
                self.store.active_expire_cycle()
            try:
                value = self.store.dispatch(args)
            except CommandError as err:
                conn.out += resp.encode_error(err.message)
                continue
            if isinstance(value, _Ok):
                conn.out += resp.encode_simple("OK")
            elif isinstance(value, _Pong):
                conn.out += resp.encode_simple("PONG")
            elif isinstance(value, _Save):
                self._handle_save(conn)
            else:
                conn.out += resp.encode_value(value)
        self._flush(conn)

    def _handle_save(self, conn: _Conn) -> None:
        if not self.dbfile:
            conn.out += resp.encode_error("ERR SAVE 未配置 dbfile（服务器启动参数）")
            return
        try:
            save_snapshot(self.dbfile, self.store.export_state())
        except SnapshotError as err:                   # pragma: no cover - 防御
            conn.out += resp.encode_error(f"ERR snapshot: {err}")
            return
        conn.out += resp.encode_simple("OK")

    # ---------------------------------------------------------------- 写出
    def _flush(self, conn: _Conn) -> None:
        while conn.out:
            try:
                sent = conn.sock.send(conn.out)
            except BlockingIOError:
                break
            except (ConnectionResetError, OSError):
                self._close(conn)
                return
            if sent == 0:                              # 内核缓冲满了：等 EVENT_WRITE
                break
            del conn.out[:sent]
        if conn.close_after_flush and not conn.out:    # 错误帧已发完：现在关
            self._close(conn)
            return
        if conn.out and not conn.want_write:
            conn.want_write = True
            try:
                self.sel.modify(conn.sock, READ | WRITE, ("conn", conn))
            except (KeyError, ValueError):
                pass
        elif not conn.out and conn.want_write:
            conn.want_write = False
            try:
                self.sel.modify(conn.sock, READ, ("conn", conn))
            except (KeyError, ValueError):
                pass

    def _write_ready(self, conn: _Conn) -> None:
        self._flush(conn)

    # ---------------------------------------------------------------- 测试便利
    def address(self) -> tuple[str, int]:
        return ("127.0.0.1", self.port)
