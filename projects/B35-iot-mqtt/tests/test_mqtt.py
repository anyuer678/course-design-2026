"""tests/test_mqtt.py —— B35 自测：字节级协议对拍 + 端到端语义 + 完整性对账。

纪律（和本仓库其它项目一致）：
  1. 编解码的期望值**手算到位**（Remaining Length 的 127/128/16383/16384 边界、
     CONNECT/PUBLISH/SUBSCRIBE 的逐字节十六进制）——不是"跑通了就算对"；
  2. 端到端全部走 **127.0.0.1 真 socket**：broker 随机端口、客户端真连真发；
  3. QoS0 的"不存储离线消息"是**语义**不是缺陷：用"断线期间的发布不会补收"钉住；
  4. 数据完整性对着**传感器账本**逐数对账（发送数/异常数/缺口数三项都要相等）；
  5. 临时目录只来自 tempfile 并断言不在仓库内（事故后纪律），库文件用完即删。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import socket
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mqttlite import packets as P                      # noqa: E402
from mqttlite.broker import Broker                     # noqa: E402
from mqttlite.client import Client, ResilientClient    # noqa: E402
from mqttlite.recorder import Recorder                 # noqa: E402
from mqttlite.sensors import ReadingPlan, SensorSimulator  # noqa: E402


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b35-{name}-"))
    if str(base.resolve()).lower().startswith(str(ROOT.parent.parent.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


def drain(client, deadline_seconds: float = 2.0) -> int:
    """反复 poll 直到再也收不到消息（把在途报文吃干净）。"""
    total = 0
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        total += client.poll(0.05)
        if total and time.monotonic() > deadline - 0.2:
            break
    return total


# ---------------------------------------------------------------- 字节级编解码

class TestPackets(unittest.TestCase):
    def test_remaining_length_hand_cases(self):
        self.assertEqual(P.encode_remaining_length(0), b"\x00")
        self.assertEqual(P.encode_remaining_length(127), b"\x7f")
        self.assertEqual(P.encode_remaining_length(128), b"\x80\x01")
        self.assertEqual(P.encode_remaining_length(16383), b"\xff\x7f")
        self.assertEqual(P.encode_remaining_length(16384), b"\x80\x80\x01")
        for n in (0, 1, 127, 128, 16383, 16384, 2097151, 2097152, 268435455):
            value, consumed = P.decode_remaining_length(
                P.encode_remaining_length(n))
            self.assertEqual(value, n)
            self.assertEqual(consumed, len(P.encode_remaining_length(n)))

    def test_remaining_length_over_four_bytes_refused(self):
        buf = bytes([P.PINGREQ << 4]) + b"\x80\x80\x80\x80\x01"
        with self.assertRaises(P.MalformedPacket):
            P.read_packet(buf)

    def test_connect_bytes_exact(self):
        # 手算：可变头 10 字节 + 载荷 4 字节 → RL=14=0x0E
        want = bytes.fromhex("100e00044d5154540402003c00026331")
        got = P.encode_connect(P.ConnectPacket(client_id="c1"))
        self.assertEqual(got, want)
        parsed = P.parse_connect(got[2:])
        self.assertEqual((parsed.client_id, parsed.clean_session, parsed.keepalive),
                         ("c1", True, 60))

    def test_publish_bytes_exact(self):
        want = bytes.fromhex("30070003612f626869")     # topic "a/b" payload "hi"
        got = P.encode_publish(P.PublishPacket(topic="a/b", payload=b"hi"))
        self.assertEqual(got, want)
        ptype, flags, body, total = P.read_packet(got)
        pub = P.parse_publish(flags, body)
        self.assertEqual((ptype, pub.topic, pub.payload), (P.PUBLISH, "a/b", b"hi"))
        self.assertEqual(total, len(got))

    def test_subscribe_bytes_exact(self):
        want = bytes.fromhex("820800010003612f6200")   # pid=1, filter "a/b", QoS0
        got = P.encode_subscribe(P.SubscribePacket(packet_id=1, filters=["a/b"]))
        self.assertEqual(got, want)
        parsed = P.parse_subscribe(0x02, got[2:])
        self.assertEqual((parsed.packet_id, parsed.filters), (1, ["a/b"]))

    def test_fixed_packets_bytes(self):
        self.assertEqual(P.encode_connack(False, 0), bytes.fromhex("20020000"))
        self.assertEqual(P.encode_pingreq(), bytes.fromhex("c000"))
        self.assertEqual(P.encode_pingresp(), bytes.fromhex("d000"))
        self.assertEqual(P.encode_disconnect(), bytes.fromhex("e000"))
        self.assertEqual(P.encode_suback(1, [0, 0]), bytes.fromhex("900400010000"))

    def test_publish_binary_payload_roundtrip(self):
        payload = bytes(range(256))
        raw = P.encode_publish(P.PublishPacket(topic="x/y", payload=payload))
        _t, flags, body, _n = P.read_packet(raw)
        self.assertEqual(P.parse_publish(flags, body).payload, payload)

    def test_malformed_cases(self):
        with self.assertRaises(P.MalformedPacket):           # 未知类型
            P.read_packet(bytes([0xF0, 0x00]))
        with self.assertRaises(P.MalformedPacket):           # 发布主题带通配符
            P.encode_publish(P.PublishPacket(topic="a/+/b", payload=b"x"))
        with self.assertRaises(P.MalformedPacket):           # SUBSCRIBE 标志位错
            P.parse_subscribe(0x00, bytes.fromhex("0001000361") + b"\x00")
        with self.assertRaises(P.MalformedPacket):           # 协议名不对
            P.parse_connect(bytes.fromhex("0004585858580402003c00026331"))
        with self.assertRaises(P.MalformedPacket):           # 保留标志位为 1
            body = bytes.fromhex("00044d5154540403003c00026331")
            P.parse_connect(body)
        with self.assertRaises(P.MalformedPacket):           # 空 client id
            P.parse_connect(bytes.fromhex("00044d5154540402003c0000"))

    def test_topic_matching_hand_table(self):
        cases = [
            ("a/+/c", "a/b/c", True),
            ("a/+", "a/b/c", False),
            ("a/#", "a", True),
            ("#", "a/b/c", True),
            ("#", "$SYS/x", False),
            ("+/x", "$SYS/x", False),
            ("a/b", "a/b", True),
            ("a/b", "a/b/c", False),
            ("+/+", "a/b", True),
            ("a/+/+", "a/b/c", True),
            ("a/+/+", "a/b", False),
            ("+", "a", True),
            ("+", "a/b", False),
        ]
        for filt, topic, want in cases:
            self.assertEqual(P.topic_matches(filt, topic), want, msg=f"{filt} vs {topic}")

    def test_validate_filter_rejects(self):
        for bad in ("#/a", "a/#/b", "a+b", "a/b+", ""):
            with self.assertRaises(P.MalformedPacket, msg=bad):
                P.validate_filter(bad)
        for good in ("a/b", "a/+/c", "a/#", "+", "#", "$SYS/+/x"):
            P.validate_filter(good)                        # 不该抛


# ---------------------------------------------------------------- 端到端（真 socket）

class BrokerCase(unittest.TestCase):
    def setUp(self):
        self.broker = Broker().start()
        self.addCleanup(self.broker.stop)
        self.clients: list[Client] = []

    def make_client(self, client_id: str, connect: bool = True) -> Client:
        c = Client(client_id, port=self.broker.port)
        if connect:
            c.connect()
        self.clients.append(c)
        self.addCleanup(c.close)
        return c


class TestBrokerE2E(BrokerCase):
    def test_pub_sub_and_isolation(self):
        sub = self.make_client("s1")
        self.assertEqual(sub.subscribe(["t/room"]), [0])
        pub = self.make_client("p1")
        pub.publish("t/room", b"22.5")
        pub.publish("t/other", b"nope")
        self.assertEqual(drain(sub), 1)
        self.assertEqual(sub.messages, [("t/room", b"22.5")])

    def test_wildcards_plus_and_hash(self):
        sub = self.make_client("s1")
        sub.subscribe(["s/+/data", "alerts/#"])
        pub = self.make_client("p1")
        pub.publish("s/dev-01/data", b"a")
        pub.publish("s/dev-01/raw", b"b")
        pub.publish("alerts/overheat/line1", b"c")
        self.assertEqual(drain(sub), 2)
        self.assertEqual([t for t, _ in sub.messages], ["s/dev-01/data", "alerts/overheat/line1"])

    def test_multiple_subscribers(self):
        a = self.make_client("a")
        b = self.make_client("b")
        a.subscribe(["t/x"])
        b.subscribe(["t/#"])
        pub = self.make_client("p")
        delivered = self.broker.route("t/x", b"hello")
        self.assertEqual(delivered, 2)
        self.assertEqual(drain(a), 1)
        self.assertEqual(drain(b), 1)

    def test_same_client_id_takeover(self):
        first = self.make_client("dup-id")
        first.subscribe(["t/x"])
        second = Client("dup-id", port=self.broker.port)
        self.clients.append(second)
        second.connect()
        time.sleep(0.2)                                    # 等 broker 处理顶号
        self.assertEqual(self.broker.stats["takeovers"], 1)
        self.assertEqual(self.broker.client_count(), 1)
        # 旧连接已被顶掉：再发会拿到错误
        with self.assertRaises((ConnectionError, OSError, TimeoutError)):
            first.publish("t/x", b"ghost")
            drain(first, 0.5)

    def test_bad_packet_closes_only_that_connection(self):
        good = self.make_client("good")
        good.subscribe(["t/x"])
        raw = socket.create_connection(("127.0.0.1", self.broker.port), timeout=2)
        raw.sendall(bytes([0xF0, 0x00]))                   # 未知类型
        time.sleep(0.2)
        self.assertEqual(raw.recv(16), b"")                # 它只被关闭……
        raw.close()
        pub = self.make_client("pub")
        pub.publish("t/x", b"still-alive")
        self.assertEqual(drain(good), 1)                   # ……好连接毫发无损
        self.assertEqual(self.broker.stats["rejected"], 1)

    def test_premature_publish_rejected(self):
        raw = socket.create_connection(("127.0.0.1", self.broker.port), timeout=2)
        raw.sendall(P.encode_publish(P.PublishPacket(topic="t/x", payload=b"x")))
        time.sleep(0.2)
        self.assertEqual(raw.recv(16), b"")
        raw.close()
        self.assertGreaterEqual(self.broker.stats["rejected"], 1)

    def test_ping_pong_counted(self):
        c = self.make_client("pinger")
        c.ping()
        self.assertEqual(self.broker.stats["pings"], 1)

    def test_retain_flag_passthrough_no_store(self):
        # 教学版不实现"保留消息"存储：retain 位原样转发，README 里明说
        sub = self.make_client("s")
        sub.subscribe(["t/r"])
        pub = self.make_client("p")
        pub.publish("t/r", b"v1", retain=True)
        self.assertEqual(drain(sub), 1)
        sub.messages.clear()
        time.sleep(0.1)
        self.assertEqual(drain(sub, 0.3), 0)               # 新订阅者不会收到"历史保留值"

    def test_qos0_no_offline_queue(self):
        watcher = self.make_client("watcher")
        watcher.subscribe(["gap/topic"])
        watcher.disconnect()                               # 离线
        pub = self.make_client("pub")
        self.assertEqual(self.broker.route("gap/topic", b"lost-floor"), 0)  # 没人可投
        watcher2 = Client("watcher", port=self.broker.port)
        self.clients.append(watcher2)
        watcher2.connect()
        watcher2.subscribe(["gap/topic"])                  # 重连后重新订阅
        self.assertEqual(drain(watcher2, 0.4), 0)          # 离线期间的消息不补
        pub.publish("gap/topic", b"fresh")
        self.assertEqual(drain(watcher2), 1)
        self.assertEqual(watcher2.messages, [("gap/topic", b"fresh")])


class TestResilient(BrokerCase):
    def test_reconnect_after_broker_restart(self):
        port = self.broker.port
        rc = ResilientClient("edge-01", ["s/+/data"], port=port)
        self.clients.append(rc)
        rc.connect()
        rc.subscribe(rc.filters)
        collector = self.make_client("collector")
        collector.subscribe(["s/#"])

        rc.safe_publish("s/edge-01/data", b"before")
        self.assertEqual(drain(collector), 1)              # 先确认第一条真的到了
        self.assertEqual(rc.reconnects, 0)

        self.broker.stop()                                 # 宕机
        time.sleep(0.2)
        self.assertFalse(rc.safe_publish("s/edge-01/data", b"while-down"))

        self.broker = Broker(port=port).start()            # 同端口重启
        self.addCleanup(self.broker.stop)

        # collector 也是普通客户端：broker 换了，它同样要重连重订阅——**先恢复通道再发**，
        # 因为 QoS0 不补历史（如果先发后连，消息就是丢了，测试会红在上面这条顺序上）
        collector.connect()
        collector.subscribe(["s/#"])
        collector.messages.clear()

        self.assertTrue(rc.safe_publish("s/edge-01/data", b"after"))
        self.assertEqual(rc.reconnects, 1)                 # 自动重连 + 重订阅
        self.assertIn("s/+/data", self.broker.subscription_table())

        self.assertEqual(drain(collector), 1)
        self.assertEqual(collector.messages, [("s/edge-01/data", b"after")])  # while-down 丢了：QoS0 语义


# ---------------------------------------------------------------- 传感器与完整性

class TestPipelineIntegrity(unittest.TestCase):
    def test_sensor_reading_schema_and_ledger(self):
        sim = SensorSimulator("dev-01", seed=1)
        rounds = 0
        anomaly_counts = {"spike": 0, "freeze": 0, "dropout": 0}
        for _ in range(400):
            rounds += 1
            reading = sim.next_reading()
            if reading is None:
                anomaly_counts["dropout"] += 1
                continue
            self.assertEqual(reading["device"], "dev-01")
            # seq 是**轮次号**（含断数那几轮）——接收端的"缺口"就是它数出来的
            self.assertEqual(reading["seq"], rounds)
            self.assertIn(reading["anomaly"], (None, "spike", "freeze"))
            if reading["anomaly"]:
                anomaly_counts[reading["anomaly"]] += 1
        self.assertEqual(sim.ledger, anomaly_counts)       # 账本 = 实际发生
        self.assertEqual(sim.sent, 400 - sim.ledger["dropout"])

    def test_end_to_end_recorder_integrity(self):
        tmp = make_tmp("db")
        self.addCleanup(shutil.rmtree, tmp, True)
        broker = Broker().start()
        self.addCleanup(broker.stop)

        recorder_client = Client("recorder", port=broker.port)
        recorder_client.connect()
        self.addCleanup(recorder_client.close)
        recorder = Recorder(tmp / "readings.db", recorder_client)
        self.addCleanup(recorder.close)

        sensors = [SensorSimulator(f"dev-{i:02d}", seed=100 + i) for i in range(1, 4)]
        clients = []
        for sim in sensors:
            client = Client(f"edge-{sim.device_id}", port=broker.port)
            client.connect()
            clients.append(client)
            self.addCleanup(client.close)

        rounds = 150
        for _ in range(rounds):
            for sim, client in zip(sensors, clients):
                sim.publish(client)
            recorder_client.poll(0.05)
        # 把在途的吃干净
        deadline = time.monotonic() + 3.0
        target = sum(sim.sent for sim in sensors)
        while recorder.received < target and time.monotonic() < deadline:
            recorder_client.poll(0.1)

        summary = recorder.summary()
        expected_sent = sum(sim.sent for sim in sensors)
        self.assertEqual(summary["received"], expected_sent)     # 一条不丢（同机 QoS0）
        self.assertEqual(summary["rows"], expected_sent)
        self.assertEqual(summary["parse_errors"], 0)
        self.assertEqual(summary["by_device"],
                         {sim.device_id: sim.sent for sim in sensors})
        expect_anom: dict[str, int] = {}
        for sim in sensors:
            for kind, n in sim.ledger.items():
                if kind != "dropout" and n:
                    expect_anom[kind] = expect_anom.get(kind, 0) + n
        self.assertEqual(summary["anomalies"], expect_anom)
        self.assertEqual(recorder.gaps(),
                         {sim.device_id: sim.ledger["dropout"] for sim in sensors})
        series = recorder.series("dev-01")
        self.assertEqual(len(series), sensors[0].sent)
        self.assertEqual([x for x, _ in series], sorted(x for x, _ in series))

    def test_svg_plot_writes_valid_file(self):
        from mqttlite.svgplot import line_chart
        tmp = make_tmp("svg")
        self.addCleanup(shutil.rmtree, tmp, True)
        series = {"dev-01": [(i, 70.0 + (i % 5)) for i in range(20)],
                  "dev-02": [(i, 68.0 + (i % 3)) for i in range(20)]}
        anomalies = [(5, 95.0, "spike"), (12, 70.0, "freeze")]
        size = line_chart(tmp / "curve.svg", series, anomalies,
                          title="温度曲线", y_label="°C")
        text = (tmp / "curve.svg").read_text(encoding="utf-8")
        self.assertGreater(size, 500)
        self.assertIn("<svg", text)
        self.assertIn("</svg>", text)
        self.assertEqual(text.count("<polyline"), 2)
        self.assertEqual(text.count("<circle"), 2)         # 两个异常圈
        self.assertIn("dev-01", text)


if __name__ == "__main__":
    unittest.main()
