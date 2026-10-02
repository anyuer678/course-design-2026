"""mqttlite/broker.py —— 极简 MQTT broker（selectors 单线程事件循环）

课程要点：
    - **broker 的全部工作是三件事**：接连接（CONNECT→CONNACK）、维护"主题过滤器 → 连接"
      的订阅表、把 PUBLISH 按通配符规则投给订阅者。QoS0 下没有 ack/重发/离线队列——
      "至多一次"的语义简单而诚实（测试专门钉住"不存储离线消息"）；
    - **一条坏连接不能拖垮别人**：坏包只关闭它所在的那条连接（rejected 计数），
      其它客户端继续收发（测试里有这条"隔离"断言）；
    - **同 client id 重连 = 顶掉旧连接**（规范行为）：这是"设备重连"在服务端的薄薄一层状态；
    - 事件循环用 `selectors`（同一台机器上的 IO 多路复用经验来自 B11），
      每轮 50ms 超时以便响应停止；不引入任何第三方库。
"""
from __future__ import annotations

import selectors
import socket
import threading
from dataclasses import dataclass, field

from mqttlite import packets as P


@dataclass
class Session:
    sock: socket.socket
    buffer: bytearray = field(default_factory=bytearray)
    client_id: str | None = None
    ready: bool = False
    subscriptions: set = field(default_factory=set)


class Broker:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen(16)
        self._server.setblocking(False)
        self.host, self.port = self._server.getsockname()

        self._selector = selectors.DefaultSelector()
        self._selector.register(self._server, selectors.EVENT_READ, None)
        self._sessions: dict[socket.socket, Session] = {}
        self._subs: dict[str, set[socket.socket]] = {}
        self.stats = {"accepted": 0, "rejected": 0, "connects": 0, "takeovers": 0,
                      "subscribes": 0, "publishes_in": 0, "published_out": 0,
                      "pings": 0, "bytes_in": 0, "bytes_out": 0}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- 生命周期

    def start(self) -> "Broker":
        self._thread = threading.Thread(target=self._run, name="mqttlite-broker", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        for session in list(self._sessions.values()):
            self._close(session)
        try:
            self._selector.unregister(self._server)
        except (KeyError, ValueError):
            pass
        self._server.close()
        self._selector.close()

    def __enter__(self) -> "Broker":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ---------------------------------------------------------------- 事件循环

    def _run(self) -> None:
        while not self._stop.is_set():
            for key, _events in self._selector.select(timeout=0.05):
                if key.data is None:
                    self._accept()
                else:
                    self._on_readable(key.data)

    def _accept(self) -> None:
        try:
            sock, _addr = self._server.accept()
        except OSError:
            return
        sock.setblocking(False)
        session = Session(sock=sock)
        self._sessions[sock] = session
        self._selector.register(sock, selectors.EVENT_READ, session)
        self.stats["accepted"] += 1

    def _on_readable(self, session: Session) -> None:
        try:
            data = session.sock.recv(4096)
        except (ConnectionError, OSError):
            self._close(session)
            return
        if not data:                      # EOF：对端断开
            self._close(session)
            return
        session.buffer += data
        self.stats["bytes_in"] += len(data)
        self._process(session)

    def _process(self, session: Session) -> None:
        while True:
            try:
                ptype, flags, body, total = P.read_packet(bytes(session.buffer))
            except P.IncompletePacket:
                return
            except P.MalformedPacket:
                self.stats["rejected"] += 1
                self._close(session)      # 只断这一条
                return
            del session.buffer[:total]
            if not self._dispatch(session, ptype, flags, body):
                return

    def _dispatch(self, session: Session, ptype: int, flags: int, body: bytes) -> bool:
        """处理一个报文；返回 False 表示已在处理中断开连接。"""
        if ptype == P.CONNECT:
            try:
                connect = P.parse_connect(body)
            except P.MalformedPacket:
                self.stats["rejected"] += 1
                self._close(session)
                return False
            old = next((s for s in self._sessions.values()
                        if s is not session and s.client_id == connect.client_id), None)
            if old is not None:           # 同 id 重连：顶掉旧连接（规范行为）
                self.stats["takeovers"] += 1
                self._close(old)
            session.client_id = connect.client_id
            session.ready = True
            self.stats["connects"] += 1
            self._send(session, P.encode_connack(session_present=False))
            return session.sock in self._sessions

        if not session.ready:             # 没握手就想干别的：拒
            self.stats["rejected"] += 1
            self._close(session)
            return False

        if ptype == P.SUBSCRIBE:
            try:
                sub = P.parse_subscribe(flags, body)
            except P.MalformedPacket:
                self.stats["rejected"] += 1
                self._close(session)
                return False
            granted = [0] * len(sub.filters)      # 教学版一律授 QoS0
            for f in sub.filters:
                session.subscriptions.add(f)
                self._subs.setdefault(f, set()).add(session.sock)
            self.stats["subscribes"] += 1
            self._send(session, P.encode_suback(sub.packet_id, granted))
            return session.sock in self._sessions

        if ptype == P.PUBLISH:
            try:
                pub = P.parse_publish(flags, body)
            except P.MalformedPacket:
                self.stats["rejected"] += 1
                self._close(session)
                return False
            self.stats["publishes_in"] += 1
            self.route(pub.topic, pub.payload, retain=pub.retain)
            return session.sock in self._sessions

        if ptype == P.PINGREQ:
            self.stats["pings"] += 1
            self._send(session, P.encode_pingresp())
            return session.sock in self._sessions

        if ptype == P.DISCONNECT:
            self._close(session)          # 优雅断开：不算 rejected
            return False

        # CONNACK/SUBACK/PINGRESP 是服务端才发的：客户端发来视为协议错误
        self.stats["rejected"] += 1
        self._close(session)
        return False

    # ---------------------------------------------------------------- 路由与工具

    def route(self, topic: str, payload: bytes, retain: bool = False) -> int:
        """把消息投给所有匹配的订阅者；返回实际投出的份数（= 一个订阅者一份）。"""
        packet = P.encode_publish(P.PublishPacket(topic=topic, payload=payload, retain=retain))
        delivered = 0
        for topic_filter, socks in self._subs.items():
            if not P.topic_matches(topic_filter, topic):
                continue
            for sock in list(socks):
                session = self._sessions.get(sock)
                if session is None:
                    continue
                if self._send(session, packet):
                    delivered += 1
        self.stats["published_out"] += delivered
        return delivered

    def _send(self, session: Session, data: bytes) -> bool:
        try:
            session.sock.sendall(data)
            self.stats["bytes_out"] += len(data)
            return True
        except OSError:
            self._close(session)
            return False

    def _close(self, session: Session) -> None:
        if session.sock not in self._sessions:
            return
        del self._sessions[session.sock]
        for topic_filter in list(session.subscriptions):
            socks = self._subs.get(topic_filter)
            if socks is not None:
                socks.discard(session.sock)
                if not socks:
                    del self._subs[topic_filter]
        try:
            self._selector.unregister(session.sock)
        except (KeyError, ValueError):
            pass
        try:
            session.sock.close()
        except OSError:
            pass

    # ---------------------------------------------------------------- 观察口

    def client_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.ready)

    def subscription_table(self) -> dict:
        return {f: len(socks) for f, socks in self._subs.items()}
