"""mqttlite/client.py —— 极简客户端 + 断线重连的韧性外壳

课程要点（工业物联网）：
    - 客户端是"一台会喘气的设备"：连接、订阅、发布、**保活**（PINGREQ/PINGRESP）、
      优雅断开。QoS0 下 publish 立即返回——没有 ack 可等，"发出去"与"被收到"之间
      的差距就是 QoS0 的语义本身；
    - 读侧要**按报文边界收字节**：TCP 是流不是包，`README 里读"数据还没到齐"是常态
      （IncompletePacket 让上层继续 recv，而不是把半截包当错误砸掉）；
    - `ResilientClient` 是"边缘设备"的必修课：断线→指数退避重连→**自动重新订阅**
      （broker 不替你记订阅，QoS0 也不补历史——恢复的是"从现在起"的通道）。
"""
from __future__ import annotations

import select
import socket
import time

from mqttlite import packets as P


class Client:
    def __init__(self, client_id: str, host: str = "127.0.0.1", port: int = 1883):
        self.client_id = client_id
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.buffer = bytearray()
        self._packet_id = 0
        self.on_message = None                      # callable(topic, payload) 或 None
        self.messages: list[tuple[str, bytes]] = []  # 未设回调时也会收集

    # ---------------------------------------------------------------- 连接管理

    def connect(self, timeout: float = 2.0) -> bool:
        """发 CONNECT、等 CONNACK；返回 session_present。失败抛 OSError 家族。

        先 close 旧连接：重复 connect 时不许把旧 socket 丢给 GC（残留的 fd 实为泄漏）。
        """
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.buffer.clear()
        self._send(P.encode_connect(P.ConnectPacket(client_id=self.client_id)))
        _ptype, _flags, body = self._read_packet(expected=P.CONNACK, timeout=timeout)
        session_present, code = P.parse_connack(body)
        if code != 0:
            raise ConnectionError(f"CONNACK 拒绝码 {code}")
        return session_present

    def disconnect(self, timeout: float = 1.0) -> None:
        if self.sock is None:
            return
        try:
            self.sock.settimeout(timeout)
            self.sock.sendall(P.encode_disconnect())
        except OSError:
            pass
        self.close()

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def __del__(self) -> None:            # 兜底：忘关的连接在回收时也把 socket 关掉
        try:
            self.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- 收发

    def _send(self, data: bytes) -> None:
        if self.sock is None:
            raise ConnectionError("尚未连接")
        self.sock.sendall(data)

    def _recv_more(self) -> None:
        if self.sock is None:
            raise ConnectionError("尚未连接")
        data = self.sock.recv(4096)          # 超时由 settimeout 兜住 → socket.timeout
        if not data:
            raise ConnectionError("broker 关闭了连接")
        self.buffer += data

    def _read_packet(self, expected: int | None = None, timeout: float = 2.0,
                     dispatch: bool = True):
        """读到下一个完整报文。沿途收到的 PUBLISH 先派发给回调（订阅确认可能被数据抢先）。"""
        deadline = time.monotonic() + timeout
        while True:
            try:
                ptype, flags, body, total = P.read_packet(bytes(self.buffer))
            except P.IncompletePacket:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("等待报文超时") from None
                if self.sock is None:
                    raise ConnectionError("尚未连接")
                self.sock.settimeout(max(0.01, remaining))
                try:
                    self._recv_more()
                except socket.timeout:
                    raise TimeoutError("等待报文超时") from None
                continue
            del self.buffer[:total]
            if ptype == P.PUBLISH:
                self._handle_publish(flags, body)
                if expected != P.PUBLISH:
                    continue
            if expected is not None and ptype != expected:
                raise P.MalformedPacket(f"期望报文类型 {expected}，收到 {ptype}")
            return ptype, flags, body

    def _handle_publish(self, flags: int, body: bytes) -> None:
        pub = P.parse_publish(flags, body)
        self.messages.append((pub.topic, pub.payload))
        if self.on_message is not None:
            self.on_message(pub.topic, pub.payload)

    def subscribe(self, filters: list[str], timeout: float = 2.0) -> list[int]:
        self._packet_id += 1
        packet = P.SubscribePacket(packet_id=self._packet_id, filters=list(filters))
        self._send(P.encode_subscribe(packet))
        _ptype, _flags, body = self._read_packet(expected=P.SUBACK, timeout=timeout)
        packet_id, granted = P.parse_suback(body)
        if packet_id != self._packet_id:
            raise P.MalformedPacket("SUBACK 的 packet id 不匹配")
        return granted

    def publish(self, topic: str, payload: bytes | str, retain: bool = False) -> None:
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self._send(P.encode_publish(P.PublishPacket(topic=topic, payload=payload, retain=retain)))

    def ping(self, timeout: float = 2.0) -> None:
        self._send(P.encode_pingreq())
        self._read_packet(expected=P.PINGRESP, timeout=timeout)

    def poll(self, timeout: float = 0.2) -> int:
        """把当前可读的报文全部消化（PUBLISH 派发给回调），返回派发条数。"""
        if self.sock is None:
            raise ConnectionError("尚未连接")
        dispatched = 0
        ready, _w, _x = select.select([self.sock], [], [], timeout)
        if not ready:
            return 0
        self._recv_more()
        while True:
            try:
                ptype, flags, body, total = P.read_packet(bytes(self.buffer))
            except P.IncompletePacket:
                return dispatched
            del self.buffer[:total]
            if ptype == P.PUBLISH:
                self._handle_publish(flags, body)
                dispatched += 1
            elif ptype == P.PINGRESP:
                pass
            else:
                raise P.MalformedPacket(f"客户端收到意外报文类型 {ptype}")


class ResilientClient(Client):
    """带断线重连与自动重订阅的客户端（边缘设备的日常形态）。"""

    def __init__(self, client_id: str, filters: list[str],
                 host: str = "127.0.0.1", port: int = 1883):
        super().__init__(client_id, host, port)
        self.filters = list(filters)
        self.reconnects = 0
        self.last_error: Exception | None = None

    def reconnect(self, timeout: float = 2.0) -> bool:
        self.close()
        self.buffer.clear()
        try:
            self.connect(timeout=timeout)
            if self.filters:
                self.subscribe(self.filters, timeout=timeout)
        except (OSError, ConnectionError, TimeoutError, P.MalformedPacket) as err:
            self.last_error = err
            self.close()
            return False
        self.reconnects += 1
        return True

    def ensure_connected(self) -> bool:
        """确认连接**真的还活着**：QoS0 下唯一的存活探针就是 PINGREQ/PINGRESP——
        对端已消失时，下一次 sendall 往往还会"成功"（TCP 半关闭语义），只有 ping 能戳破。"""
        if self.sock is not None:
            try:
                self.ping(timeout=0.5)
                return True
            except (OSError, ConnectionError, TimeoutError):
                self.close()
        return self.reconnect()

    def safe_publish(self, topic: str, payload: bytes | str) -> bool:
        """尽力发布：断了就重连再试一次；仍然失败返回 False（调用方决定计数/告警）。"""
        try:
            self.ensure_connected()
            self.publish(topic, payload)
            return True
        except (OSError, ConnectionError, TimeoutError):
            pass
        if self.reconnect():
            try:
                self.publish(topic, payload)
                return True
            except (OSError, ConnectionError, TimeoutError) as err:
                self.last_error = err
        return False

    def safe_poll(self, timeout: float = 0.2) -> int:
        try:
            return self.poll(timeout)
        except (OSError, ConnectionError, TimeoutError) as err:
            self.last_error = err
            self.close()
            return 0
