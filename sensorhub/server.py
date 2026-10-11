"""sensorhub/server.py —— SensorHub 服务（轮六之一）：跑在自研 webframe 上。

API：
    GET  /                           监测台页面（自刷新；静态资产在 /static）
    GET  /api/status                 总账：broker 统计 + 设备账本 vs 入库对账 + 告警汇总
    GET  /api/series?device&metric[&limit]   曲线数据 [(seq, 值)]（metric = temp/vib；
                                             limit 默认 500、上限 5000，只取最新点）
    GET  /api/chart?device&metric    自包含 SVG（B35 svgplot 现算，温度曲线叠异常点）
    GET  /api/alerts?limit=100       告警台账（最新在前）
    POST /api/tick                   手动推一拍（返回本轮账；自动节拍不受影响）
    POST /api/inject                 管理口注入一条读数（JSON；走 broker 真实订阅表）
只绑回环。引擎节拍默认 1s 一拍（--interval 可调，须 > 0）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
for p in (str(REPO),):
    if p not in sys.path:
        sys.path.insert(0, p)

from webframe import HttpFail, MicroApp, MicroServer, Response  # noqa: E402

from sensorhub import METRICS, SensorHub                        # noqa: E402
from mqttlite.svgplot import line_chart                         # noqa: E402

WEB_ROOT = ROOT / "web"
DATA_DIR = ROOT / "data"
DEFAULT_PORT = 8022   # 8017 studio / 8018 linkbox / 8019 simlab / 8020 datascope / 8021 cachekv

_INJECT_SCHEMA = {
    "device": (str, True), "seq": (int, False),   # 2026-10-11：seq 可省→服务端 next_seq
    "temp": (float, True), "vib": (float, True),
    "anomaly": (str, False),
}
_RULE_SCHEMA = {"rule": (str, True), "threshold": (float, True)}
_ACK_SCHEMA = {"device": (str, True), "seq": (int, True), "rule": (str, True)}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]")


class SensorHubServer(MicroServer):
    """停机即收摊：broker/客户端/库连接都要体面关闭，不留半开套接字。"""

    def stop(self) -> None:
        engine = getattr(self, "engine", None)
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass                             # 停机路径不许被引擎异常卡住
        super().stop()


def build_app(engine: SensorHub, *, charts_dir: str | Path) -> MicroApp:
    app = MicroApp()
    charts = Path(charts_dir)

    def metric_of(ctx) -> str:
        metric = ctx.query.get("metric", "temp")
        if metric not in METRICS:
            raise HttpFail(400, f"metric 只支持 {'/'.join(METRICS)}")
        return metric

    def device_of(ctx) -> str:
        device = ctx.query.get("device", "")
        if not device:
            raise HttpFail(400, "缺 device 参数")
        if device not in engine.known_devices():
            raise HttpFail(404, f"没有叫 {device!r} 的设备")
        return device

    @app.get("/api/status")
    def status(ctx):
        return ctx.json(engine.status())

    @app.get("/api/series")
    def series(ctx):
        device, metric = device_of(ctx), metric_of(ctx)
        raw = ctx.query.get("limit", "")
        try:
            limit = int(raw) if raw else 500
        except ValueError:
            raise HttpFail(400, "limit 必须是整数")
        if not 1 <= limit <= 5000:
            raise HttpFail(400, "limit 须在 1..5000")
        # 2026-10-11 ECharts 化：异常点随曲线一起下发（此前只喂服务端 SVG），
        # B35 自报异常只标温度；窗口与曲线对齐（最近 limit 点的 seq 范围）——
        # 否则全历史异常摊满 X 轴、曲线被挤成一角
        points = engine.series(device, metric, limit=limit)
        anomalies = []
        if metric == "temp" and points:
            seq_min = points[0][0]
            anomalies = [{"seq": float(s), "temp": float(v), "label": label}
                         for s, v, label in engine.anomaly_points(device)
                         if s >= seq_min]
        return ctx.json({"device": device, "metric": metric,
                         "points": points,
                         "anomalies": anomalies})

    # ---------------- WebSocket 实时曲线（轮十八，2026-10-11）
    # 升级握手/帧协议全在 netlab（手写 RFC 6455）；本端点只做订阅账本：
    # on_message 换订阅并回快照，on_poll 每秒查增量（seq > 已发最大值才推），
    # 回调全在服务器事件循环线程执行，引擎的 _call 线程安全靠它自己。
    @app.ws("/ws/live")
    def ws_live(session):
        import json as _json
        import time as _time
        sub = {"device": None, "metric": "temp"}
        state = {"last_seq": None, "last_anom": None, "due": 0.0}
        POLL_SECONDS = 1.0

        def send_snapshot():
            device, metric = sub["device"], sub["metric"]
            points = engine.series(device, metric, limit=500)
            anomalies = []
            if metric == "temp" and points:
                seq_min = points[0][0]
                anomalies = [{"seq": float(s), "temp": float(v), "label": label}
                             for s, v, label in engine.anomaly_points(device)
                             if s >= seq_min]
            state["last_seq"] = points[-1][0] if points else None
            anoms_seq = [a["seq"] for a in anomalies]
            state["last_anom"] = max(anoms_seq) if anoms_seq else None
            session.send(_json.dumps({
                "type": "snapshot", "device": device, "metric": metric,
                "points": points, "anomalies": anomalies}, ensure_ascii=False))

        def on_message(text):
            try:
                msg = _json.loads(text)
                device, metric = str(msg["device"]), str(msg.get("metric", "temp"))
            except (ValueError, KeyError, TypeError):
                session.send('{"type":"error","error":"消息须是 {\\"device\\",\\"metric\\"} JSON"}')
                return
            if metric not in METRICS:
                session.send(_json.dumps({"type": "error",
                                          "error": f"metric 只支持 {'/'.join(METRICS)}"}))
                return
            if device not in engine.known_devices():
                session.send(_json.dumps({"type": "error",
                                          "error": f"没有叫 {device!r} 的设备"}))
                return
            sub["device"], sub["metric"] = device, metric
            state["last_seq"] = None
            send_snapshot()

        def on_poll():
            # 事件循环每 tick（≈20ms）都会调，这里节流到每秒一次增量检查
            now = _time.monotonic()
            if now < state["due"] or sub["device"] is None or session.closing:
                return
            state["due"] = now + POLL_SECONDS
            device, metric = sub["device"], sub["metric"]
            points = engine.series(device, metric, limit=500)
            fresh = ([p for p in points if state["last_seq"] is None
                      or p[0] > state["last_seq"]] if state["last_seq"] is not None
                     else points)
            if not fresh:
                return
            state["last_seq"] = points[-1][0]
            anoms = []
            if metric == "temp":
                floor = state["last_anom"] if state["last_anom"] is not None else 0
                anoms = [{"seq": float(s), "temp": float(v), "label": label}
                         for s, v, label in engine.anomaly_points(device) if s > floor]
                if anoms:
                    state["last_anom"] = max(a["seq"] for a in anoms)
            session.send(_json.dumps({"type": "append", "device": device,
                                      "metric": metric, "points": fresh,
                                      "anomalies": anoms}, ensure_ascii=False))

        session.on_message = on_message
        session.on_poll = on_poll

    @app.get("/api/chart")
    def chart(ctx):
        device, metric = device_of(ctx), metric_of(ctx)
        points = [(float(s), float(v)) for s, v in engine.series(device, metric)]
        if not points:
            raise HttpFail(400, f"设备 {device!r} 暂无 {metric} 数据")
        anomalies = None
        if metric == "temp":                     # B35 的异常点标注的是温度
            anomalies = [(float(s), float(v), label) for s, v, label
                         in engine.anomaly_points(device)]
        charts.mkdir(parents=True, exist_ok=True)
        name = _SAFE_NAME.sub("_", device)       # 设备名进文件名前先消毒
        out = charts / f"curve-{name}-{metric}.svg"
        line_chart(out, {device: points}, anomalies=anomalies,
                   title=f"{device} · {metric}", y_label=metric)
        return Response(out.read_bytes(), content_type="image/svg+xml",
                        headers=[("Cache-Control", "no-store")])

    @app.get("/api/alerts")
    def alerts(ctx):
        raw = ctx.query.get("limit", "100")
        try:
            limit = int(raw)
        except ValueError:
            raise HttpFail(400, "limit 要是整数") from None
        return ctx.json({"rules": {name: spec[1] for name, spec in engine.rules.items()},
                         "alerts": engine.alerts(limit)})

    @app.post("/api/rules")
    def set_rule(ctx):
        """S1 阈值规则页面化：改一条规则立即生效并落盘 rules.json。"""
        body = ctx.json_body(_RULE_SCHEMA)
        try:
            rules = engine.set_rule(body["rule"], body["threshold"])
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        return ctx.json({"rules": rules})

    @app.post("/api/alerts/ack")
    def ack_alert(ctx):
        """S2 告警确认：标记已处理（持久）。没有这条/已确认过 → 404。"""
        body = ctx.json_body(_ACK_SCHEMA)
        try:
            acked = engine.ack_alert(body["device"], body["seq"], body["rule"])
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        if not acked:
            raise HttpFail(404, "没有这条告警（或已确认过）")
        return ctx.json({"acked": True})

    @app.post("/api/tick")
    def tick(ctx):
        return ctx.json(engine.tick())

    @app.post("/api/inject")
    def inject(ctx):
        body = ctx.json_body(_INJECT_SCHEMA)
        seq = body.get("seq")
        if seq is None:                      # 缺省自动分配（max+1），离群 seq 不再进库
            seq = engine.next_seq(body["device"])
        try:
            engine.inject(body["device"], seq, body["temp"], body["vib"],
                          body.get("anomaly", ""))
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None
        return ctx.json({"injected": True, "seq": seq})

    @app.get("/")
    def index(ctx):
        page = (WEB_ROOT / "index.html").read_bytes()
        return Response(page, content_type="text/html; charset=utf-8")

    app.static("/static", WEB_ROOT)
    return app


def build_server(*, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 data_dir: str | Path | None = None,
                 devices=None, seed: int = 2026, interval: float | None = 1.0,
                 temp_max: float = 85.0, vib_max: float = 4.0,
                 plan=None) -> tuple[SensorHubServer, SensorHub]:
    """组装服务。服务器永远跑节拍线程（HTTP 线程与引擎线程不同源，手动模式的
    内联执行只属于测试/脚本——SQLite 连接跟人走，跨线程用就是 ProgrammingError）。"""
    data = Path(data_dir) if data_dir else DATA_DIR
    kwargs = {"seed": seed, "interval": 1.0 if interval is None else interval,
              "temp_max": temp_max, "vib_max": vib_max}
    if devices is not None:
        kwargs["devices"] = devices
    if plan is not None:
        kwargs["plan"] = plan
    engine = SensorHub(data / "readings.sqlite3", **kwargs)
    server = SensorHubServer(build_app(engine, charts_dir=data / "charts"),
                             host=host, port=port)
    server.engine = engine
    return server, engine


def main(argv=None) -> int:
    import argparse
    import threading
    ap = argparse.ArgumentParser(description="SensorHub 物联网监测（只绑回环）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--interval", type=float, default=1.0,
                    help="节拍秒数（必须 > 0；服务模式下引擎跑在节拍线程里）")
    args = ap.parse_args(argv)
    if args.interval <= 0:
        ap.error("--interval 必须 > 0（服务模式不能关节拍线程）")
    server, engine = build_server(port=args.port, interval=args.interval)
    engine.start()
    port = server.start()
    status = engine.status()
    print(f"SensorHub 已启动： http://127.0.0.1:{port}/   （Ctrl+C 退出）")
    print(f"链路： {len(status['devices'])} 台模拟设备 → broker :{status['broker']['port']}"
          f" → SQLite → 阈值告警 {status['rules']}"
          f"（节拍 {args.interval}s）")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n再见（收摊：断设备 → 停 broker → 关库）")
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
