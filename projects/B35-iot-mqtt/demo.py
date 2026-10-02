"""demo.py —— B35 六段演示：从协议字节到曲线页，全链路真跑真数。

 1) 协议字节：CONNECT/PUBLISH/SUBSCRIBE 的十六进制与手算表当场对照；RL 边界表
 2) 起 broker + 3 台传感器 + recorder(SQLite) + 通配符监控端
 3) 跑固定轮数：实发/实收/按设备分布 / 异常分布；吞吐【实测】
 4) 完整性对账：账本 vs 库（实收、行数、异常、缺口四项逐数）
 5) 断线重连：停 broker → QoS0 丢一条 → 重启同端口 → 自动重连+重订阅 → 恢复；耗时【实测】
 6) SVG 曲线：dev-01 温度曲线（异常红圈）写 build/，打印产物大小

固定种子 ⇒ 内容（条数/对账）逐字可复现；标【实测】的行是实时测量，允许波动。
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mqttlite import packets as P                      # noqa: E402
from mqttlite.broker import Broker                     # noqa: E402
from mqttlite.client import Client, ResilientClient    # noqa: E402
from mqttlite.recorder import Recorder                 # noqa: E402
from mqttlite.sensors import SensorSimulator           # noqa: E402
from mqttlite.svgplot import line_chart                # noqa: E402

LINE = "=" * 78


def section(no: int, title: str) -> None:
    print(f"\n{LINE}\n  {no}) {title}\n{LINE}")


def show(label: str, value: object) -> None:
    print(f"  {label:<26}{value}")


def main() -> int:
    print("B35-iot-mqtt 演示：手写 MQTT（协议字节 → broker → SQLite → SVG 曲线）")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    db_path = build / "sensors.db"
    if db_path.exists():
        db_path.unlink()

    # ------------------------------------------------------------------ 1
    section(1, "协议字节：手算表与实现的十六进制并排")
    connect_hex = P.encode_connect(P.ConnectPacket(client_id="c1")).hex(" ")
    publish_hex = P.encode_publish(P.PublishPacket(topic="a/b", payload=b"hi")).hex(" ")
    subscribe_hex = P.encode_subscribe(P.SubscribePacket(packet_id=1, filters=["a/b"])).hex(" ")
    show("CONNECT(c1)", connect_hex)
    show("  手算", "10 0e 00 04 4d 51 54 54 04 02 00 3c 00 02 63 31")
    show("PUBLISH(a/b, hi)", publish_hex)
    show("  手算", "30 07 00 03 61 2f 62 68 69")
    show("SUBSCRIBE(1, a/b)", subscribe_hex)
    show("  手算", "82 08 00 01 00 03 61 2f 62 00")
    rl = {n: P.encode_remaining_length(n).hex(" ") for n in (127, 128, 16383, 16384)}
    show("RL 边界 127/128/16383/16384", rl)

    # ------------------------------------------------------------------ 2
    section(2, "链路：broker + 3 台传感器 + 入库端(SQLite) + 通配符监控端")
    broker = Broker().start()
    recorder_client = Client("recorder", port=broker.port)
    recorder_client.connect()
    recorder = Recorder(db_path, recorder_client)          # 订阅 sensors/+/data
    watcher = Client("watcher", port=broker.port)
    watcher.connect()
    watcher.subscribe(["sensors/#", "alerts/+"])
    sensors = [SensorSimulator(f"dev-{i:02d}", seed=200 + i) for i in range(1, 4)]
    edge_clients = []
    for sim in sensors:
        c = Client(f"edge-{sim.device_id}", port=broker.port)
        c.connect()
        edge_clients.append(c)
    show("设备数 / 订阅端", f"{len(sensors)} / recorder + watcher(通配符)")

    # ------------------------------------------------------------------ 3
    section(3, "固定轮数运行：实发 / 实收 / 分布（吞吐是实测）")
    rounds = 200
    t0 = time.perf_counter()
    for _ in range(rounds):
        for sim, client in zip(sensors, edge_clients):
            sim.publish(client)
        recorder_client.poll(0.02)
    elapsed = time.perf_counter() - t0
    target = sum(sim.sent for sim in sensors)
    deadline = time.monotonic() + 3.0
    while recorder.received < target and time.monotonic() < deadline:
        recorder_client.poll(0.05)
    watcher_extra = 0
    while watcher.poll(0.05):
        watcher_extra += 1
    summary = recorder.summary()
    show("轮数 × 设备", f"{rounds} × {len(sensors)}")
    show("传感器实发合计", target)
    show("入库端实收", summary["received"])
    show("按设备分布", dict(sorted(summary["by_device"].items())))
    show("吞吐【实测】", f"{rounds * len(sensors) / elapsed:.0f} 条/秒（含解析与入库）")

    # ------------------------------------------------------------------ 4
    section(4, "完整性对账：账本 vs 库（四项逐数）")
    expect_anom: dict[str, int] = {}
    for sim in sensors:
        for kind, n in sim.ledger.items():
            if kind != "dropout" and n:
                expect_anom[kind] = expect_anom.get(kind, 0) + n
    expect_gaps = {sim.device_id: sim.ledger["dropout"] for sim in sensors}
    show("异常账本（spike/freeze）", dict(sorted(expect_anom.items())))
    show("库里异常计数", dict(sorted(summary["anomalies"].items())))
    show("  一致", summary["anomalies"] == expect_anom)
    show("缺口账本（dropout）", dict(sorted(expect_gaps.items())))
    show("库里 seq 缺口", dict(sorted(recorder.gaps().items())))
    show("  一致", recorder.gaps() == expect_gaps)
    show("解析失败（应为 0）", summary["parse_errors"])

    # ------------------------------------------------------------------ 5
    section(5, "断线重连：停 broker → 丢一条（QoS0）→ 重启同端口 → 自动恢复")
    port = broker.port
    edge = ResilientClient("edge-01", ["sensors/+/data"], port=port)
    edge.connect()
    edge.subscribe(edge.filters)
    ok_before = edge.safe_publish("sensors/dev-01/data", b"before")
    broker.stop()
    time.sleep(0.2)
    ok_down = edge.safe_publish("sensors/dev-01/data", b"while-down")
    t0 = time.perf_counter()
    broker = Broker(port=port).start()
    ok_after = edge.safe_publish("sensors/dev-01/data", b"after")
    recovery = time.perf_counter() - t0
    show("宕机前发布 / 宕机中发布 / 恢复后发布", f"{ok_before} / {ok_down} / {ok_after}")
    show("自动重连次数", edge.reconnects)
    show("重订阅是否恢复", "sensors/+/data" in broker.subscription_table())
    show("重连耗时【实测】", f"{recovery * 1000:.0f} ms（含 broker 启动）")

    # ------------------------------------------------------------------ 6
    section(6, "SVG 曲线：dev-01 温度（异常红圈）")
    series = {sim.device_id: recorder.series(sim.device_id, "temp") for sim in sensors}
    anomalies = [(x, y, label) for x, y, label in recorder.anomaly_points("dev-01")]
    out = build / "dev01_temperature.svg"
    size = line_chart(out, series, anomalies,
                      title="工业传感器温度曲线（dev-01..03，200 轮）",
                      y_label="temperature C")
    show("产物", f"build/{out.name}")
    show("字节数", size)
    show("曲线点数（三设备合计）", sum(len(v) for v in series.values()))
    show("dev-01 异常标记数", len(anomalies))

    # 收尾
    edge.disconnect()
    for c in edge_clients:
        c.disconnect()
    watcher.disconnect()
    recorder.close()
    recorder_client.disconnect()
    broker.stop()

    print("\n" + LINE)
    print("完成：6 段演示全部跑通。标【实测】的两处是实时测量（吞吐 / 重连耗时），")
    print("其余内容由固定种子驱动，逐字可复现（tools/logdiff.py 可核对两次 run.bat 日志）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
