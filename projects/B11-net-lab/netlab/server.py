"""netlab/server.py —— select 多路复用 + keep-alive 的单线程 HTTP/1.1 服务器。

一个线程 + 一次 select 同时管住监听套接字和所有连接：
每个连接有一份接收缓冲（对付半包/粘包）和一份发送缓冲（对付非阻塞下的部分写）。
所有上限都在收字节的过程中生效，不会先把超限的请求整个读进内存再判断。

应用是一个内存键值表，够演示 增删改查 + 统计，也让"并发"这件事能被观察：
/stats 里的 peak_open 只有在一条线程里同时挂着多个连接时才可能大于 1。
"""
from __future__ import annotations

import fnmatch
import json
import select
import socket
import threading
import time

from .http1 import (DEFAULT_MAX_BODY, MAX_HEADER_BYTES, HttpError, Request,
                    build_response, parse_request)
from .websocket import WsSession, handshake_response, is_upgrade_request


class Stats:
    def __init__(self):
        self.requests = 0
        self.connections = 0        # 累计接受过的连接数
        self.peak_open = 0
        self.open_now = 0
        self.timed_out = 0          # 空闲超时踢掉的连接
        self.refused = 0            # 超过 max_conn 直接回 503 的
        self.errors = 0             # 4xx / 5xx 计数

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("requests", "connections", "peak_open", "open_now",
                 "timed_out", "refused", "errors")}


class Conn:
    """一条连接的状态机：收 → 解析出一个完整请求 → 处理 → 排队发送。"""

    __slots__ = ("sock", "addr", "inbuf", "outbuf", "outbuf_since", "last_active",
                 "closing", "alive", "half_closed", "ws")

    def __init__(self, sock: socket.socket, addr):
        self.sock = sock
        self.addr = addr
        self.inbuf = b""
        self.outbuf = b""
        self.outbuf_since: float | None = None   # outbuf 从空变非空的时刻（滞留计）
        self.last_active = time.monotonic()
        self.closing = False        # 承诺的响应已排队，发完就该收尾
        self.alive = True
        self.half_closed = False    # 已经 shutdown(SHUT_WR)，只剩收摊
        self.ws: WsSession | None = None   # 非 None = 已升级为 WebSocket 连接

    def fileno(self) -> int:
        return self.sock.fileno()


class Server:
    """单线程 select 服务器。路由写成 (方法, 路径模式) -> handler。

    handler(request) 返回 (status, headers, body)，headers 是 [(名, 值)]。
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0, *,
                 max_conn: int = 64, idle_timeout: float = 5.0,
                 max_body: int = DEFAULT_MAX_BODY, verbose: bool = False):
        if host not in ("127.0.0.1", "localhost", "::1"):
            # 这是教学实验，不是给外人用的服务：绑到非回环地址要先显式打开开关。
            raise ValueError(f"只允许绑定回环地址，收到 {host!r}")
        self.host, self.port = host, port
        self.max_conn, self.idle_timeout, self.max_body = max_conn, idle_timeout, max_body
        self.verbose = verbose
        self.stats = Stats()
        self.conns: dict[int, Conn] = {}
        self.store: dict[str, bytes] = {}
        self.routes = _default_routes(self)
        # WebSocket 路由：[(路径通配, handler(session))]，handler 里赋回调/订阅。
        # 升级连接不占 HTTP 超时，登记在 ws_sessions 供事件循环泵回调。
        self.ws_routes: list = []
        self.ws_sessions: set = set()
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    # ------------------------------------------------ 生命周期

    def start(self) -> int:
        """绑定回环端口并让事件循环在后台线程跑起来，返回实际端口。"""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(128)
        self._sock.setblocking(False)
        self.port = self._sock.getsockname()[1]
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, daemon=True, name="netlab-server")
        self._thread.start()
        return self.port

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise RuntimeError("事件循环线程没能退出，可能有连接卡在 select 里")
        self._cleanup()
        if self._error is not None:
            # 循环线程里的异常必须在这里冒出来：否则表现只是"客户端等不到响应"，
            # 排查时会以为是超时或死锁，实际是服务端早就死了。
            error, self._error = self._error, None
            raise error

    def run(self) -> None:
        """事件循环本体；测试里也可以在当前线程直接调用。"""
        assert self._sock is not None, "start() 之前不能直接跑事件循环"
        try:
            while not self._stop.is_set():
                self._tick()
        except BaseException as exc:            # 线程里的异常要能传回主线程
            self._error = exc
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        for conn in list(self.conns.values()):
            self._close(conn, "shutdown")
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _tick(self) -> None:
        if self._sock is None:
            return
        now = time.monotonic()
        # 出站滞留看 outbuf 自身"持续未清"的时长，不看 last_active（读活动）：
        # 给空闲 25s 的长连接补推一帧，帧龄是 0ms，绝不能按"滞留"误杀——
        # 2026-10-11 boardweb 协同实测抓出（帧入队与超时清扫同 tick 竞速）。
        # 真正的只写不读：outbuf 连续一个空闲窗口没被 select 写出去 → 回收。
        for conn in list(self.conns.values()):
            if conn.outbuf:
                if conn.outbuf_since is None:
                    conn.outbuf_since = now
                elif now - conn.outbuf_since >= self.idle_timeout:
                    self.stats.timed_out += 1
                    if self.verbose:
                        print(f"  [连接] 回收 {conn.addr} （outbuf 滞留 "
                              f"{now - conn.outbuf_since:.1f}s：对端只写不读）")
                    self._close(conn, "stuck output")
                    continue
            else:
                conn.outbuf_since = None
            # 空闲额度只约束"没有未发响应"的连接；到点的先踢掉，
            # 否则超时值会变成负数，select 就退化成"一直等"。
            if conn.outbuf_since is None and \
                    self.idle_timeout - (now - conn.last_active) <= 0:
                self._timeout(conn)
        left = [self.idle_timeout - (time.monotonic() - c.last_active)
                for c in self.conns.values() if c.outbuf_since is None]
        wait = max(min([0.02] + left, default=0.02), 0.0)
        # 收尾中的连接也要留在可读集合里：回收它的唯一信号是对端那个 FIN，
        # 不读就永远等不到 EOF。
        readable = [self._sock] + list(self.conns.values())
        writable = [c for c in self.conns.values() if c.outbuf]
        r, w, _ = select.select(readable, writable, [], wait)
        for fd in r:
            if fd is self._sock:
                self._accept()
                continue
            conn = self.conns.get(fd.fileno())
            if conn is not None:
                self._read(conn)
        for fd in w:
            conn = self.conns.get(fd.fileno())
            if conn is not None:
                self._write(conn)
        # WS 会话的事件泵：应用在这里做"有没有新数据可推"的检查（自己节流）。
        # list() 拷贝：on_poll 里可能 close() 改动集合。
        for session in list(self.ws_sessions):
            session.pump()

    def _accept(self) -> None:
        try:
            sock, addr = self._sock.accept()
        except (BlockingIOError, OSError):
            return
        sock.setblocking(False)
        conn = Conn(sock, addr)
        if len(self.conns) >= self.max_conn:
            # 拒绝不能"发完立刻 close"：Windows 上只要接收缓冲还有没读走的字节，
            # close 就会发 RST，把刚写进去的 503 一起冲掉，客户端只等到连接被重置。
            # 所以这里也走通用收尾流程：排队 503 → 发完半关闭 → 等 EOF 或超时回收。
            self.stats.refused += 1
            conn.closing = True
            conn.outbuf = build_response(
                503, body=b"server busy\r\n", keep_alive=False,
                headers=[("Retry-After", "1"),
                         ("Content-Type", "text/plain; charset=utf-8")])
        self.conns[sock.fileno()] = conn
        self.stats.connections += 1
        self.stats.open_now += 1
        self.stats.peak_open = max(self.stats.peak_open, self.stats.open_now)

    # ------------------------------------------------ 读写

    def _read(self, conn: Conn) -> None:
        try:
            chunk = conn.sock.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except (ConnectionResetError, ConnectionAbortedError, OSError):
            self._close(conn, "peer gone")
            return
        if not chunk:
            self._close(conn, "peer closed")
            return
        if conn.closing:
            # 这条连接已经被判定要收尾（拒绝、协议错误、超限、Connection: close）：
            # 读走的字节直接丢掉——不缓冲、不解析，也不刷新 last_active。
            # 不续命是有必要的：对方每秒滴一个字节就能把名额一直占着。
            return
        conn.inbuf += chunk
        conn.last_active = time.monotonic()
        if len(conn.inbuf) > MAX_HEADER_BYTES + self.max_body:
            self._reply(conn, 413, b"request too large", explain="请求整体超过上限")
            conn.closing = True
            return
        self._drain(conn)

    def _drain(self, conn: Conn) -> None:
        """一次 recv 可能带来多个请求（pipelining），也可能只有半个：按字节数推进。
        升级为 WS 后字节流归帧解析器管，不再进 HTTP 状态机。"""
        while conn.alive and not conn.closing and conn.ws is None:
            try:
                parsed = parse_request(conn.inbuf, max_body=self.max_body)
            except HttpError as exc:
                self._reply(conn, exc.status, exc.explain.encode(), explain=exc.explain,
                            headers=exc.headers)
                conn.closing = True
                return
            if parsed is None:
                break
            request, used = parsed
            conn.inbuf = conn.inbuf[used:]
            self._handle(conn, request)
        if conn.ws is not None and conn.inbuf:
            # 升级应答和前几个 WS 帧挤在同一次 recv 里的情况：余量交给帧解析器。
            data, conn.inbuf = conn.inbuf, b""
            conn.ws.feed(data)
            conn.last_active = time.monotonic()

    def _write(self, conn: Conn) -> None:
        try:
            sent = conn.sock.send(conn.outbuf)       # 非阻塞：可能只写出去一部分
        except (BlockingIOError, InterruptedError):
            return
        except (ConnectionResetError, BrokenPipeError, OSError):
            self._close(conn, "write failed")
            return
        conn.outbuf = conn.outbuf[sent:]
        if sent:
            # 写出也算活动：慢读者在持续拿字节就该续命；真正的"只写不读"
            # 由 _timeout 的滞留回收兜底（2026-10-07 审查收口）。
            conn.last_active = time.monotonic()
        if conn.outbuf or not conn.closing or conn.half_closed:
            return
        # 承诺的响应发完了，但不能马上 close()：内核里可能还压着对方没被读走的字节，
        # Windows 上带着未读数据 close 会发 RST，把刚发出去的 413/431/503 一起作废，
        # 客户端只等到"连接被中止"。先写 FIN（半关闭），继续把对方的字节读干净，
        # 收到 EOF 才真正回收；对方赖着不走就由空闲超时兜底。
        try:
            conn.sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        conn.half_closed = True
        # 半关闭之后给一个完整的空闲窗口：对方读完响应就会关，我们收到 EOF 立刻回收；
        # 赖着不关的，到点强制回收（此时响应和 FIN 都已经发出去了）。
        conn.last_active = time.monotonic()

    def _close(self, conn: Conn, why: str) -> None:
        if not conn.alive:
            return
        conn.alive = False
        if conn.ws is not None:
            conn.ws.fire_close(1006)        # 异常断开也要给应用清理机会
        self.conns.pop(conn.fileno(), None)
        self.stats.open_now -= 1
        if self.verbose:
            print(f"  [连接] 关闭 {conn.addr} （{why}）")
        try:
            conn.sock.close()
        except OSError:
            pass

    def _timeout(self, conn: Conn) -> None:
        # 出站滞留已由 _tick 的 outbuf_since 集中判定；这里只管"无未发响应
        # 却干等"的空闲：HTTP 空闲 408 收尾，WS 是长连接不吃空闲超时。
        if conn.ws is not None:
            return
        self.stats.timed_out += 1
        if conn.closing:
            self._close(conn, "idle after close")      # 对方读完不关， grace 用完了
            return
        self._reply(conn, 408, b"request timeout", explain="空闲超时")
        conn.closing = True           # 交给事件循环发：它比"关之前硬挤一次写"可靠

    # ------------------------------------------------ 响应与路由

    def _reply(self, conn: Conn, status: int, body: bytes, *, explain: str = "",
               headers: () = (), keep_alive: bool = False, head: bool = False,
               version: str = "1.1") -> None:
        if status >= 400:
            self.stats.errors += 1
        extra = list(headers)
        if explain and status >= 400:
            extra.append(("X-Error", _quote_header(explain)))
        if body and not any(k.lower() == "content-type" for k, _ in extra):
            # 协议层错误（400/413/408…）是我们自己拼的响应，也得给客户端一个 MIME，
            # 否则标准客户端只能猜，抓包看着像半成品。
            extra.append(("Content-Type", "text/plain; charset=utf-8"))
        # HEAD 传进来的还是 GET 那份体：build_response 会按它的真实长度写
        # Content-Length，只是不把体发出去。这里若提前清空，客户端就以为资源是空的。
        payload = b"" if status == 204 else body
        conn.outbuf += build_response(status, body=payload, headers=extra,
                                      keep_alive=keep_alive, head=head, version=version)

    def _handle(self, conn: Conn, request: Request) -> None:
        self.stats.requests += 1
        conn.last_active = time.monotonic()
        if is_upgrade_request(request):
            self._handle_ws(conn, request)
            return
        try:
            status, headers, body = self._dispatch(request)
        except HttpError as exc:
            status, headers, body = exc.status, exc.headers, exc.explain.encode()
            conn.closing = exc.close
        except Exception as exc:                     # 应用 bug 不能带走整个服务器
            status, headers, body = 500, [], f"internal error: {exc}".encode()
        keep = request.keep_alive and not conn.closing
        if not keep:
            # 只把 Connection: close 写进响应头是不够的：客户端发了 close 却还
            # 等着连接保持，说明我们没真的执行这个承诺。
            conn.closing = True
        self._reply(conn, status, body, headers=headers, keep_alive=keep,
                    head=request.method == "HEAD", version=request.version)

    # ------------------------------------------------ WebSocket 升级（RFC 6455）
    def _match_ws(self, path: str):
        """WS 路由匹配，返回 (handler, 路径参数) 或 (None, None)。
        默认 fnmatch 通配；子类（如 webframe）可覆写成自己的规则语法。"""
        for pattern, handler in self.ws_routes:
            if fnmatch.fnmatch(path, pattern):
                return handler, {}
        return None, None

    def _handle_ws(self, conn: Conn, request: Request) -> None:
        key = request.header("sec-websocket-key")
        if (request.header("connection") or "").lower().find("upgrade") < 0 or not key:
            self._reply(conn, 400, b"not a valid websocket handshake")
            conn.closing = True
            return
        handler, params = self._match_ws(request.path)
        if handler is not None:
            conn.outbuf += handshake_response(key)
            session = WsSession(self, conn, request, path_params=params)
            conn.ws = session
            self.ws_sessions.add(session)
            try:
                handler(session)          # 应用在这里赋回调、发首包快照
            except Exception as exc:      # 应用 bug 不能带走整个服务器
                session.close(1011, "handler error")
                if self.verbose:
                    print(f"  [ws] handler 异常：{exc!r}")
            return
        self._reply(conn, 404, b"no such websocket endpoint")
        conn.closing = True

    def _dispatch(self, request: Request):
        if request.method not in ("GET", "HEAD", "POST", "PUT", "DELETE"):
            if request.method == "OPTIONS":
                raise HttpError(501, "不实现 OPTIONS")
            return 405, [("Allow", "GET, HEAD, POST, PUT, DELETE")], b"method not allowed\n"
        for (method, pattern), handler in self.routes:
            if method == request.method and fnmatch.fnmatch(request.path, pattern):
                return handler(request)
        return 404, [("Content-Type", "text/plain; charset=utf-8")], b"not found\n"


def _quote_header(text: str) -> str:
    """错误说明要放进头部，必须先压成可见 ASCII，否则头部注入就顺着这里进来了。"""
    out = "".join(ch if 0x20 <= ord(ch) <= 0x7E else "?" for ch in text)
    return out[:200]


def _default_routes(server: Server) -> list:
    text = [("Content-Type", "text/plain; charset=utf-8")]

    def index(req):
        body = ("netlab 迷你 HTTP 服务器\r\n"
                "GET  /               本帮助\r\n"
                "GET  /kv             列出所有键\r\n"
                "GET  /kv/<key>       读一个键\r\n"
                "PUT  /kv/<key>       写一个键（体是值）\r\n"
                "DELETE /kv/<key>     删一个键\r\n"
                "GET  /sum?a=1&b=2    求和，演示查询串解码\r\n"
                "GET  /echo?text=...  原样回显\r\n"
                "GET  /stats          运行统计（并发与失败场景都记在这里）\r\n").encode()
        return 200, text, body

    def stats(req):
        return 200, [("Content-Type", "application/json")], \
            json.dumps(server.stats.as_dict(), ensure_ascii=False).encode() + b"\n"

    def list_keys(req):
        body = "".join(f"{k}\n" for k in sorted(server.store)).encode()
        return 200, text, body

    def read_key(req):
        key = _tail(req.path, "/kv/")
        if key not in server.store:
            return 404, text, b"no such key\n"
        return 200, [("Content-Type", "application/octet-stream")], server.store[key]

    def write_key(req):
        key = _tail(req.path, "/kv/")
        if len(req.body) > 4096:
            return 413, text, b"value too long (limit 4096)\n"
        created = key not in server.store
        server.store[key] = req.body
        return (201 if created else 200), text, b"ok\n" if created else b"updated\n"

    def delete_key(req):
        key = _tail(req.path, "/kv/")
        if server.store.pop(key, None) is None:
            return 404, text, b"no such key\n"
        return 204, [], b""

    def sum_query(req):
        values = dict(req.query)
        try:
            total = sum(float(values[k]) for k in ("a", "b") if k in values)
        except ValueError:
            return 400, text, b"a and b must be numbers\n"
        out = ("%g" % total).encode() + b"\n"
        return 200, text, out

    def echo(req):
        values = dict(req.query)
        return 200, text, values.get("text", "").encode() + b"\n"

    def _tail(path: str, prefix: str) -> str:
        key = path[len(prefix):]
        if not key:
            raise HttpError(400, f"{prefix} 后面要给键名")
        return key

    return [
        (("GET", "/"), index),
        (("GET", "/stats"), stats),
        (("GET", "/kv"), list_keys),
        (("GET", "/kv/*"), read_key),
        (("HEAD", "/kv/*"), read_key),
        (("PUT", "/kv/*"), write_key),
        (("POST", "/kv/*"), write_key),
        (("DELETE", "/kv/*"), delete_key),
        (("GET", "/sum"), sum_query),
        (("GET", "/echo"), echo),
    ]
