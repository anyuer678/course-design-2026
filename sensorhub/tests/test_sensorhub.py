"""SensorHub 自测：MQTT 全链路对账 + 告警台账 + 确定性 + HTTP API + 真套接字。

对账口径（B35 的账本纪律）：
    发出 + 断数 == 最后 seq；实收行数 == 发出；自报异常 == 设备账本；
    告警 == readings 越限行的精确投影（双向对账）。
钉值出处（探针实测 2026-10-05，同种子两次运行剔除 ts 逐条一致）：
    seed=2026 + devices=(dev-01/02/03) + 8 拍 + ReadingPlan(0.2/0.2/0.2)
    → 发出 21、自报 spike 3 / freeze 7、gaps {0,1,1}、告警 temp_max 14。
    注意 dev-01 的断数落在 seq 1（首条成功之前），Recorder 的 gaps 量的是
    min..max 区间内的洞，所以 gaps[dev-01]=0 而断数账=1——两条账各自都对。
    服务端测试用零异常计划（spike/freeze/dropout 全 0），账面完全确定。
"""
import http.client
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 先建 B35 路径桥（mqttlite 的 import 依赖它，须在下面两行之前）
from sensorhub import SensorHub                       # noqa: E402
from sensorhub.server import build_app, build_server  # noqa: E402

from mqttlite.client import Client                    # noqa: E402
from mqttlite.sensors import ReadingPlan              # noqa: E402

PLAN = ReadingPlan(spike_p=0.2, freeze_p=0.2, dropout_p=0.2)
ZERO = ReadingPlan(spike_p=0.0, freeze_p=0.0, dropout_p=0.0)
# 钉值出处：seed=2026 + PLAN + 8 拍（确定性随机流，可复算）
LEDGER = {
    "dev-01": {"sent": 7, "spike": 0, "freeze": 3, "dropout": 1},
    "dev-02": {"sent": 7, "spike": 2, "freeze": 2, "dropout": 1},
    "dev-03": {"sent": 7, "spike": 1, "freeze": 2, "dropout": 1},
}
GAPS = {"dev-01": 0, "dev-02": 1, "dev-03": 1}


def make_hub(tmp, db_name="hub.sqlite3", plan=ZERO, **kw):
    kw.setdefault("interval", None)            # 手动模式：测试线程自己推拍
    return SensorHub(Path(tmp) / db_name, plan=plan, **kw)


def strip_ts(rows):
    return [{k: v for k, v in r.items() if k != "ts"} for r in rows]


class TestEngine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_ledger_reconciliation(self):
        """全链路对账：发出/断数/实收/自报异常/缺口逐数对上（钉值见模块头）。"""
        hub = make_hub(self._tmp.name, plan=PLAN)
        self.addCleanup(hub.stop)
        hub.start()
        for _ in range(8):
            hub.tick()
        s = hub.status()
        for dev, want in LEDGER.items():
            got = s["sims"][dev]
            self.assertEqual(got["sent"], want["sent"], msg=dev)
            self.assertEqual(got["ledger"]["spike"], want["spike"], msg=dev)
            self.assertEqual(got["ledger"]["freeze"], want["freeze"], msg=dev)
            self.assertEqual(got["ledger"]["dropout"], want["dropout"], msg=dev)
            # 真账本恒等式：发出 + 断数 == 最后 seq（8 拍）
            self.assertEqual(want["sent"] + want["dropout"], 8, msg=dev)
        rec = s["recorder"]
        self.assertEqual(rec["rows"], 21)
        self.assertEqual(rec["received"], 21)
        self.assertEqual(rec["by_device"], {d: 7 for d in LEDGER})
        self.assertEqual(rec["anomalies"], {"spike": 3, "freeze": 7})
        self.assertEqual(rec["parse_errors"], 0)
        self.assertEqual(rec["gaps"], GAPS)
        # broker 侧：21 条 PUBLISH 进来，只有一个订阅者 → 21 份投出去
        self.assertEqual(s["broker"]["stats"]["publishes_in"], 21)
        self.assertEqual(s["broker"]["stats"]["published_out"], 21)
        self.assertEqual(s["broker"]["clients"], 4)
        self.assertEqual(s["broker"]["subscriptions"], {"sensors/+/data": 1})
        # 告警：随机游走温度过线（spike 后居高不下），振动离 4.0 很远
        self.assertEqual(s["alerts"]["by_rule"], {"temp_max": 14})
        self.assertEqual(s["alerts"]["total"], 14)

    def test_alerts_from_injection(self):
        """注入确定性样本：越限即告警；压线（==阈值）不告警；台账与 readings 双向对账。"""
        hub = make_hub(self._tmp.name)
        self.addCleanup(hub.stop)
        hub.start()
        hub.inject("dev-01", 101, temp=120.0, vib=0.5)
        hub.inject("dev-01", 102, temp=70.0, vib=5.0)
        hub.inject("dev-01", 103, temp=85.0, vib=0.5)   # 压线：严格大于才算
        hub.tick()
        s = hub.status()
        self.assertEqual(s["alerts"]["total"], 2)
        self.assertEqual(s["alerts"]["by_rule"], {"temp_max": 1, "vib_max": 1})
        # 双向对账：每条告警 ↔ 一条越限读数
        rows = {(r["device"], r["seq"]): r for r in hub.readings()}
        seen = set()
        for a in hub.alerts():
            row = rows[(a["device"], a["seq"])]
            self.assertEqual(a["metric"],
                             "temp" if a["rule"] == "temp_max" else "vib")
            self.assertEqual(a["value"], row["temp"] if a["rule"] == "temp_max"
                             else row["vib"])
            self.assertGreater(a["value"], a["threshold"])
            seen.add((a["device"], a["seq"], a["rule"]))
        self.assertEqual(seen, {("dev-01", 101, "temp_max"),
                                ("dev-01", 102, "vib_max")})

    def test_alerts_idempotent(self):
        """重复评估不重复计数：同样的越限行，再拍两拍 new_alerts 归零、总数不变。"""
        hub = make_hub(self._tmp.name)
        self.addCleanup(hub.stop)
        hub.start()
        hub.inject("dev-02", 201, temp=130.0, vib=0.5)
        hub.tick()
        self.assertEqual(hub.status()["alerts"]["total"], 1)
        for _ in range(2):
            self.assertEqual(hub.tick()["new_alerts"], 0)
        self.assertEqual(hub.status()["alerts"]["total"], 1)

    def test_restart_persistence(self):
        """重启：读数与告警台账都在库里；重评估（幂等）不产生新告警。"""
        hub = make_hub(self._tmp.name)
        hub.start()
        hub.inject("dev-03", 301, temp=140.0, vib=0.5)
        hub.tick()                              # 注入行 + 三台设备的 seq 1
        rows_before = len(hub.readings())       # = 4
        total_before = hub.status()["alerts"]["total"]  # = 1
        self.assertEqual((rows_before, total_before), (4, 1))
        hub.stop()
        revived = make_hub(self._tmp.name)      # 同一库文件
        self.addCleanup(revived.stop)
        revived.start()
        self.assertEqual(revived.status()["alerts"]["total"], total_before)
        for _ in range(8):                     # 设备从 seq 1 重放：seq1 幂等覆盖，2..8 新增
            revived.tick()
        self.assertEqual(len(revived.readings()), 1 + 3 * 8)
        self.assertEqual(revived.status()["alerts"]["total"], total_before)

    def test_determinism_same_seed(self):
        """确定性：同种子两次运行剔除 ts 逐条一致；换种子则不同。"""
        a1 = make_hub(self._tmp.name, db_name="a1.sqlite3", plan=PLAN, seed=2026)
        a2 = make_hub(self._tmp.name, db_name="a2.sqlite3", plan=PLAN, seed=2026)
        b = make_hub(self._tmp.name, db_name="b.sqlite3", plan=PLAN, seed=2027)
        for h in (a1, a2, b):
            self.addCleanup(h.stop)
            h.start()
        for _ in range(8):
            a1.tick()
            a2.tick()
            b.tick()
        self.assertEqual(strip_ts(a1.readings()), strip_ts(a2.readings()))
        self.assertNotEqual(strip_ts(a1.readings()), strip_ts(b.readings()))

    def test_external_client_over_socket(self):
        """外部真客户端：真套接字发布一条自报正常、实际越限的读数 → 规则独立抓到。"""
        hub = make_hub(self._tmp.name)
        self.addCleanup(hub.stop)
        hub.start()
        port = hub.status()["broker"]["port"]
        probe = Client("ext-probe", port=port)
        probe.connect()
        self.addCleanup(probe.close)
        payload = json.dumps({"device": "probe-1", "seq": 1, "ts": 0.0,
                              "temp": 90.0, "vib": 0.5, "anomaly": ""})
        probe.publish("sensors/probe-1/data", payload)
        hub.tick()
        rows = [r for r in hub.readings("probe-1") if r["seq"] == 1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["temp"], 90.0)
        # 零异常计划下设备侧不告警，唯一告警来自产品侧规则抓外部读数
        self.assertEqual(hub.status()["alerts"]["by_rule"], {"temp_max": 1})
        self.assertEqual(hub.alerts()[0]["device"], "probe-1")

    def test_inject_guards(self):
        """注入口守卫：设备名白名单（topic 注入面）；停机后操作明着拒绝。"""
        hub = make_hub(self._tmp.name)
        self.addCleanup(hub.stop)
        hub.start()
        with self.assertRaises(ValueError):
            hub.inject("a/b", 1, temp=1.0, vib=0.5)
        hub.stop()
        with self.assertRaises(RuntimeError):
            hub.tick()

    def test_status_before_start(self):
        """未启动的引擎：status 是诚实的 running=False。"""
        cold = SensorHub(Path(self._tmp.name) / "cold.sqlite3", interval=None)
        self.addCleanup(cold.stop)
        self.assertFalse(cold.status()["running"])
        self.assertEqual(cold.status()["devices"], ["dev-01", "dev-02", "dev-03"])

    def test_thread_mode_live(self):
        """服务模式：hub 线程自转，外部线程经队列汇入读 status/推 tick；停机干净。"""
        live = SensorHub(Path(self._tmp.name) / "live.sqlite3",
                         plan=ZERO, interval=0.05)
        self.addCleanup(live.stop)
        live.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if live.status()["recorder"]["rows"] >= 3:
                break
            time.sleep(0.05)
        s = live.status()
        self.assertGreaterEqual(s["recorder"]["rows"], 3)
        self.assertEqual(s["tick_errors"], 0)
        report = live.tick()                   # 跨线程汇入 hub 线程执行
        self.assertIn("sent", report)
        live.stop()
        self.assertFalse(live.status()["running"])
        live.stop()                            # 幂等
        with self.assertRaises(RuntimeError):
            live.tick()                        # 停后再操作要明着拒绝


class TestServer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.hub = make_hub(self._tmp.name)    # 零异常计划：账面完全确定
        self.hub.start()
        self.addCleanup(self.hub.stop)
        self.app = build_app(self.hub, charts_dir=Path(self._tmp.name) / "charts")

    def handle(self, method, path, body=b"", headers=None):
        from netlab.http1 import Request
        req = Request(method=method, target=path, version="1.1",
                      headers=[(k.lower(), v) for k, v in list(headers or [])],
                      body=body, path=path.split("?")[0],
                      query=[tuple(p.split("=", 1)) if "=" in p else (p, "")
                             for p in path.split("?")[1].split("&")] if "?" in path else [],
                      keep_alive=False, content_length=len(body))
        return self.app.handle(req)

    def test_status_api(self):
        self.hub.tick()
        status, _, body = self.handle("GET", "/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["running"])
        for key in ("broker", "recorder", "alerts", "sims", "rules"):
            self.assertIn(key, data)
        self.assertEqual(data["recorder"]["rows"], 3)

    def test_series_api(self):
        self.hub.tick()
        status, _, body = self.handle("GET", "/api/series?device=dev-01")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["metric"], "temp")           # 缺省 temp
        self.assertEqual(data["points"], [[1, data["points"][0][1]]])
        self.assertIsInstance(data["points"][0][1], float)
        status, _, _ = self.handle("GET", "/api/series?device=dev-01&metric=vib")
        self.assertEqual(status, 200)
        status, _, _ = self.handle("GET", "/api/series?device=dev-01&metric=pressure")
        self.assertEqual(status, 400)
        status, _, _ = self.handle("GET", "/api/series?device=ghost")
        self.assertEqual(status, 404)
        status, _, _ = self.handle("GET", "/api/series")
        self.assertEqual(status, 400)

    def test_chart_svg(self):
        # 用游走够不着的高 seq：同 (device, seq) 会被设备重放幂等覆盖（INSERT OR REPLACE）
        self.hub.inject("dev-01", 501, temp=120.0, vib=0.5, anomaly="spike")
        self.hub.tick()
        status, headers, body = self.handle("GET", "/api/chart?device=dev-01")
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)["Content-Type"], "image/svg+xml")
        self.assertTrue(body.lstrip().startswith(b"<svg"))
        self.assertIn(b"dev-01", body)                     # 图例里的设备名
        self.assertIn(b"<circle", body)                    # 自报异常点标红圈
        status, _, _ = self.handle("GET", "/api/chart?device=dev-01&metric=vib")
        self.assertEqual(status, 200)                      # 振动曲线（无异常叠加层）

    def test_chart_empty_400(self):
        status, _, _ = self.handle("GET", "/api/chart?device=dev-01")
        self.assertEqual(status, 400)                      # 设备合法但暂无数据

    def test_alerts_api(self):
        self.hub.inject("dev-02", 5, temp=110.0, vib=0.5)
        self.hub.tick()
        status, _, body = self.handle("GET", "/api/alerts")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["rules"], {"temp_max": 85.0, "vib_max": 4.0})
        self.assertEqual(len(data["alerts"]), 1)
        status, _, body = self.handle("GET", "/api/alerts?limit=1")
        self.assertEqual(len(json.loads(body)["alerts"]), 1)
        status, _, _ = self.handle("GET", "/api/alerts?limit=abc")
        self.assertEqual(status, 400)

    def test_inject_api(self):
        payload = json.dumps({"device": "dev-03", "seq": 9,
                              "temp": 99.5, "vib": 0.6}).encode()
        status, _, body = self.handle(
            "POST", "/api/inject", payload,
            headers=[("Content-Type", "application/json")])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"injected": True})
        self.hub.tick()
        self.assertIn(("dev-03", 9),
                      [(r["device"], r["seq"]) for r in self.hub.readings()])
        # 坏体：未知字段 / bool 冒充数字 / 非法设备名 → 400
        bad = [
            json.dumps({"device": "d", "seq": 1, "temp": 1.0, "vib": 0.5, "x": 1}).encode(),
            json.dumps({"device": "d", "seq": 1, "temp": True, "vib": 0.5}).encode(),
            json.dumps({"device": "a b", "seq": 1, "temp": 1.0, "vib": 0.5}).encode(),
        ]
        for raw in bad:
            status, _, _ = self.handle("POST", "/api/inject", raw,
                                       headers=[("Content-Type", "application/json")])
            self.assertEqual(status, 400, msg=raw)

    def test_tick_api(self):
        status, _, body = self.handle("POST", "/api/tick")
        self.assertEqual(status, 200)
        report = json.loads(body)
        for key in ("sent", "dropped", "received", "new_alerts"):
            self.assertIn(key, report)
        self.assertEqual(report["sent"], 3)
        self.assertEqual(report["dropped"], 0)

    def test_index_and_static(self):
        status, _, body = self.handle("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"SensorHub", body)
        status, headers, _ = self.handle("GET", "/static/style.css")
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)["Content-Type"], "text/css; charset=utf-8")
        status, _, _ = self.handle("GET", "/static/nope.js")
        self.assertEqual(status, 404)


class TestOverRealSocket(unittest.TestCase):
    def test_http_end_to_end(self):
        """真套接字 HTTP：起服务（节拍线程）→ 推拍 → 状态/曲线 → 停机收干净。"""
        with tempfile.TemporaryDirectory() as td:
            server, engine = build_server(port=0, data_dir=td, plan=ZERO)
            engine.start()
            port = server.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.request("POST", "/api/tick")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                report = json.loads(resp.read())
                self.assertEqual(report["sent"], 3)
                conn.request("GET", "/api/status")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                status = json.loads(resp.read())
                self.assertGreaterEqual(status["recorder"]["rows"], 3)
                conn.request("GET", "/api/chart?device=dev-01")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                self.assertTrue(resp.read().lstrip().startswith(b"<svg"))
                conn.close()
            finally:
                server.stop()
            self.assertFalse(engine.status()["running"])
            server.stop()                      # 幂等
            self.assertTrue(Path(td, "readings.sqlite3").exists())  # 数据落了盘


if __name__ == "__main__":
    unittest.main(verbosity=2)
