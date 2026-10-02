"""redislite/server.py —— selectors 单线程事件循环（多客户端 + 管线 + 坏包 + 主从复制）

课程要点（对应 docs/case-study.md 第 1、8 节）：
    - **单线程串行化**：所有连接的命令在同一个循环里顺序执行——INCR 的
      "读-改-写"永远不被打断，这就是 Redis 不加锁的原子性来源。
    - 每个连接一个输入缓冲（FrameDecoder）+ 输出缓冲：`recv` 到多少解多少、
      `send` 出去多少算多少，剩下的挂 **EVENT_WRITE** 等下次可写——
      慢客户端不会阻塞别人（没有 per-connection 线程）。
    - **坏包处理**：协议错误 → 回 `-ERR Protocol error: <分类>` → 断开该连接；
      其他连接毫发无损（fuzz 的全部要求，测试逐条钉）。
    - 主动过期由**命令计数**触发（每 N 条一次）——真实 Redis 另有时间触发，
      这里简化并声明（见 README 偏离表）。
    - **主从复制（2026-10-02 扩展，case-study §8）**：从库的出向链路也是
      同一 selectors 循环里的一条"连接"，状态机 CONNECTING→PING→PSYNC→
      FULLRESYNC+快照→STREAMING；主库把写命令规范化重编码后推进每个复制链接的
      输出缓冲（背压复用 EVENT_WRITE）；断链按 retry 间隔重连并全量重同步。
"""
from __future__ import annotations

import errno
import selectors
import socket
import threading
import time
from pathlib import Path

from redislite import dbsnap, resp
from redislite.dbsnap import SnapshotError, load_snapshot, save_snapshot
from redislite.store import (CommandError, Store, WRITE_COMMANDS,
                             _Ok, _Pong, _Psync, _Replicaof, _Save)

READ = selectors.EVENT_READ
WRITE = selectors.EVENT_WRITE

#: 装饰性 replid（无部分重同步，不需要真随机；case-study §8.2 第 4 条）
REPLID = "0000000000000000000000000000000000000001"
#: 从库拒写（精确文本，case-study §8.1；测试逐字断言）
READONLY_ERROR = "READONLY You can't write against a read only replica."


class _Conn:
    __slots__ = ("sock", "dec", "out", "addr", "want_write",
                 "close_after_flush", "is_replica_link")

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.dec = resp.FrameDecoder()
        self.out = bytearray()
        self.want_write = False
        self.close_after_flush = False        # 错误帧发完再关（真实 Redis 的 CLOSE_AFTER_REPLY）
        self.is_replica_link = False          # 主库侧：这条连接已 PSYNC，接收传播流


class _MasterLink:
    """从库侧：通往主库的出向链路（同一 selectors 循环里的一条连接）。"""

    __slots__ = ("sock", "dec", "out", "want_write", "host", "port",
                 "state", "base_offset", "last_attempt")

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.dec = resp.FrameDecoder()
        self.out = bytearray()
        self.want_write = False
        self.state = "disconnected"           # connecting/await_pong/await_fullresync/await_snapshot/streaming
        self.base_offset = 0
        self.last_attempt = 0.0


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, dbfile=None,
                 clock=time.time, active_every: int = 64, repl_retry: float = 0.2):
        self.sel = selectors.DefaultSelector()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(64)
        self.sock.setblocking(False)
        self.port = self.sock.getsockname()[1]
        self.store = Store(clock=clock)
        self.store.on_expire = self._propagate_expired     # 主库删除过期键 → 补发 DEL
        self.dbfile = Path(dbfile) if dbfile else None
        self.active_every = active_every
        self._since_cycle = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.conns: dict[int, _Conn] = {}
        self.stats = {"connections": 0, "commands": 0, "protocol_errors": 0,
                      "repl_applied": 0, "repl_apply_errors": 0}
        # ---- 复制状态（case-study §8）
        self.replid = REPLID
        self.repl_offset = 0                   # 主库：流位置 = 累计传播字节数
        self.applied_offset = 0                # 从库：已应用的流位置
        self.is_replica = False
        self.master_link: _MasterLink | None = None
        self.replica_links: set[_Conn] = set()
        self.repl_retry = repl_retry
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
                kind, obj = key.data
                if kind == "accept":
                    self._accept_ready()
                elif kind == "conn":
                    conn = obj
                    if conn.sock.fileno() < 0:      # 本轮里已被关掉
                        continue
                    if mask & READ:
                        self._read_ready(conn)
                    if conn.sock.fileno() >= 0 and (mask & WRITE or conn.want_write):
                        self._write_ready(conn)
                else:                               # kind == "master"
                    self._master_event(obj, mask)
            link = self.master_link
            if link is not None and link.state == "disconnected":
                if time.monotonic() - link.last_attempt >= self.repl_retry:
                    link.last_attempt = time.monotonic()
                    self._master_connect(link)
            if self._stop.is_set():
                break
        self._shutdown()

    def _shutdown(self) -> None:
        if self.master_link is not None:
            self._teardown_master_link(self.master_link)
        for conn in list(self.conns.values()):
            self._close(conn)
        self.sel.unregister(self.sock)
        self.sock.close()
        self.sel.close()

    # ---------------------------------------------------------------- 客户端连接
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
        self.replica_links.discard(conn)

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
            name = args[0].decode("utf-8", "replace").upper()
            # 从库拒写（case-study §8.1；读命令与 PING/REPLICAOF 等照常）
            if self.is_replica and name in WRITE_COMMANDS:
                conn.out += resp.encode_error(READONLY_ERROR)
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
            # 写命令：对主库原样规范化传播（case-study §8.1）；
            # 从库不传播（它只经内部路径应用主库的流）
            if name in WRITE_COMMANDS and not self.is_replica:
                self._propagate(resp.encode_command(*args))
            if isinstance(value, _Ok):
                conn.out += resp.encode_simple("OK")
            elif isinstance(value, _Pong):
                conn.out += resp.encode_simple("PONG")
            elif isinstance(value, _Save):
                self._handle_save(conn)
            elif isinstance(value, _Psync):
                self._handle_psync(conn)
            elif isinstance(value, _Replicaof):
                self._handle_replicaof(conn, value)
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

    # ---------------------------------------------------------------- 主库侧复制
    def _handle_psync(self, conn: _Conn) -> None:
        """PSYNC：回 FULLRESYNC + 快照，并把这条连接标记为复制链接。

        顺序有讲究：先 export_state（它可能触发惰性删除并补发 DEL、推进 repl_offset），
        再取当前 offset 回报——快照状态与 offset 才严格对应（case-study §8）。
        """
        entries = self.store.export_state()
        snapshot = dbsnap.encode_snapshot(entries)
        conn.out += resp.encode_simple(f"FULLRESYNC {self.replid} {self.repl_offset}")
        conn.out += resp.encode_bulk(snapshot)
        conn.is_replica_link = True
        self.replica_links.add(conn)

    def _propagate(self, frame: bytes) -> None:
        """把一帧写入流：偏移量照加（与是否有从库无关），有链接就推送。"""
        self.repl_offset += len(frame)
        for link_conn in list(self.replica_links):
            if link_conn.sock.fileno() < 0:
                self.replica_links.discard(link_conn)
                continue
            link_conn.out += frame
            self._flush(link_conn)

    def _propagate_expired(self, key: bytes) -> None:
        """主库真正删掉过期键时，补发合成 DEL（从库自己不删，等这条）。"""
        self._propagate(resp.encode_command("DEL", key))

    def _drop_replica_links(self) -> None:
        """测试钩子：断开主库侧全部复制链接（模拟链路故障，验证从库重连追平）。"""
        for link_conn in list(self.replica_links):
            self._close(link_conn)

    # ---------------------------------------------------------------- 从库侧链路
    def _handle_replicaof(self, conn: _Conn, cmd: _Replicaof) -> None:
        if cmd.host is None:                           # REPLICAOF NO ONE：脱身为主库
            self.is_replica = False
            self.store.passive_expire = False
            if self.master_link is not None:
                self._teardown_master_link(self.master_link)
                self.master_link = None
        else:
            self.is_replica = True
            self.store.passive_expire = True
            if self.master_link is not None:
                self._teardown_master_link(self.master_link)
            self.master_link = _MasterLink(cmd.host, cmd.port)
            self._master_connect(self.master_link)
        conn.out += resp.encode_simple("OK")

    def _master_connect(self, link: _MasterLink) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        err = sock.connect_ex((link.host, link.port))
        if err not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, 10035):
            sock.close()
            link.last_attempt = time.monotonic()
            return
        link.sock = sock
        link.dec = resp.FrameDecoder()
        link.out = bytearray()
        link.state = "connecting"
        if err == 0:                                   # 立即连上（回环常见）
            self._master_send_ping(link)
        self.sel.register(sock, READ | WRITE, ("master", link))

    def _master_send_ping(self, link: _MasterLink) -> None:
        link.state = "await_pong"
        link.out += resp.encode_command("PING")
        self._link_flush(link)

    def _master_event(self, link: _MasterLink, mask: int) -> None:
        if link.sock is None or link.sock.fileno() < 0:
            return
        if mask & WRITE:
            if link.state == "connecting":
                err = link.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err != 0:
                    self._master_fail(link)
                    return
                self._master_send_ping(link)
            elif link.out:
                self._link_flush(link)
        if mask & READ:
            try:
                data = link.sock.recv(65536)
            except (BlockingIOError, InterruptedError):
                return
            except (ConnectionResetError, OSError):
                self._master_fail(link)
                return
            if not data:
                self._master_fail(link)
                return
            link.dec.feed(data)
            self._master_process(link)

    def _master_process(self, link: _MasterLink) -> None:
        while True:
            if link.state == "await_pong":
                frame = link.dec.next_frame()
                if frame is resp.INCOMPLETE:
                    return
                if frame != b"PONG":
                    self._master_fail(link)
                    return
                link.out += resp.encode_command("PSYNC", "?", "-1")
                link.state = "await_fullresync"
                self._link_flush(link)
            elif link.state == "await_fullresync":
                frame = link.dec.next_frame()
                if frame is resp.INCOMPLETE:
                    return
                if not isinstance(frame, bytes) or not frame.startswith(b"FULLRESYNC "):
                    self._master_fail(link)
                    return
                try:
                    _, _replid, offset = frame.decode("ascii").split()
                    link.base_offset = int(offset)
                except (ValueError, UnicodeDecodeError):
                    self._master_fail(link)
                    return
                link.state = "await_snapshot"
            elif link.state == "await_snapshot":
                frame = link.dec.next_frame()
                if frame is resp.INCOMPLETE:
                    return
                if not isinstance(frame, bytes):
                    self._master_fail(link)
                    return
                try:
                    entries = dbsnap.decode_snapshot(frame, name="<master snapshot>")
                except SnapshotError:
                    self._master_fail(link)
                    return
                self.store.load_state(entries)          # 全量：覆盖本地数据
                self.applied_offset = link.base_offset
                link.state = "streaming"
            elif link.state == "streaming":
                try:
                    args = link.dec.next_command()
                except resp.ProtocolError:
                    self._master_fail(link)
                    return
                if args is resp.INCOMPLETE:
                    return
                if not args:
                    continue
                try:
                    self.store.dispatch(args)           # 内部应用：不经 READONLY 门槛
                    self.stats["repl_applied"] += 1
                except CommandError:
                    self.stats["repl_apply_errors"] += 1
                self.applied_offset += len(resp.encode_command(*args))
            else:
                return

    def _master_fail(self, link: _MasterLink) -> None:
        """链路断了：保留已同步的数据（真实从库同款行为），安排重连。"""
        if link.sock is not None:
            try:
                self.sel.unregister(link.sock)
            except (KeyError, ValueError):
                pass
            link.sock.close()
        link.sock = None
        link.state = "disconnected"
        link.last_attempt = time.monotonic()

    def _teardown_master_link(self, link: _MasterLink) -> None:
        if link.sock is not None:
            try:
                self.sel.unregister(link.sock)
            except (KeyError, ValueError):
                pass
            link.sock.close()
        link.sock = None
        link.state = "disconnected"

    def _link_flush(self, link: _MasterLink) -> None:
        while link.out and link.sock is not None:
            try:
                sent = link.sock.send(link.out)
            except BlockingIOError:
                break
            except (ConnectionResetError, OSError):
                self._master_fail(link)
                return
            if sent == 0:
                break
            del link.out[:sent]

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
