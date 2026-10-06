"""SimLab 播放器服务自测：记录库 API（列/读/现算落盘）+ 页面与静态 + 真套接字。

可独立推导的性质：
    - 现算落盘的记录必须过 simlab 自家校验器（自家格式自家把关）；
    - 记录名白名单 + resolve 双保险：穿越进不了 runs/ 之外；
    - 坏记录如实标注（invalid=true + 原因），不悄悄藏；
    - 引擎参数错 → 400（引擎守卫的话术原样透传）。
"""
import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import simlab
from simlab.server import build_app, build_server

KNAPSACK_PARAMS = {"weights": [2, 3, 4], "values": [3, 4, 5], "capacity": 6}


class PlayerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = build_app(runs_dir=Path(self._tmp.name) / "runs")

    def handle(self, method, path, body=b"", headers=None):
        from netlab.http1 import Request
        req = Request(method=method, target=path, version="1.1",
                      headers=[(k.lower(), v) for k, v in list(headers or [])],
                      body=body, path=path, query=[], keep_alive=False,
                      content_length=len(body))
        return self.app.handle(req)

    def post_json(self, path, payload):
        return self.handle("POST", path, json.dumps(payload).encode(),
                           [("Content-Type", "application/json")])

    # ------------------------------------------------ 现算落盘
    def test_render_and_list_and_read(self):
        status, headers, body = self.post_json("/api/records",
                                               {"experiment": "b12-knapsack",
                                                "params": KNAPSACK_PARAMS})
        self.assertEqual(status, 201)
        record = json.loads(body)
        self.assertIn("name", record)            # 落盘名回传
        self.assertEqual(record["experiment"], "b12-knapsack")
        # 列表能看到（元数据口径）
        status, _, body = self.handle("GET", "/api/records")
        items = json.loads(body)["records"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], record["name"])
        self.assertFalse(items[0]["invalid"])
        self.assertEqual(items[0]["frames"], len(record["frames"]))
        # 读取 = 完整记录，且过 simlab 校验器
        status, _, body = self.handle(
            "GET", f"/api/records/{record['name']}")
        self.assertEqual(status, 200)
        loaded = json.loads(body)
        self.assertEqual(loaded["metrics"], record["metrics"])
        simlab.validate(loaded)

    def test_render_rejects_unknown_experiment(self):
        status, _, body = self.post_json("/api/records",
                                         {"experiment": "nope", "params": {}})
        self.assertEqual(status, 400)
        self.assertIn("可用", body.decode("utf-8"))

    def test_render_rejects_bad_params_via_engine_guard(self):
        """负权边：B12 引擎守卫的话术原样透传成 400。"""
        status, _, body = self.post_json(
            "/api/records",
            {"experiment": "b12-dijkstra",
             "params": {"n": 2, "edges": [[0, 1, -5]], "src": 0}})
        self.assertEqual(status, 400)
        self.assertIn("负", body.decode("utf-8"))

    def test_render_rejects_wrong_body(self):
        status, _, _ = self.post_json("/api/records", {"experiment": 1})
        self.assertEqual(status, 400)
        status, _, _ = self.handle("POST", "/api/records", b"{oops",
                                   [("Content-Type", "application/json")])
        self.assertEqual(status, 400)

    # ------------------------------------------------ 名字安全
    def test_bad_record_names(self):
        for name in ("..%2F..%2Fsecret.json", "a/b.json", ".hidden.json",
                     "no-extension"):
            status, _, _ = self.handle("GET", f"/api/records/{name}")
            self.assertIn(status, (400, 404), msg=name)   # 不 200 即可（穿越必 400）

    def test_read_missing_record_404(self):
        status, _, _ = self.handle("GET", "/api/records/nonesuch.json")
        self.assertEqual(status, 404)

    def test_broken_record_listed_as_invalid(self):
        """坏记录如实标注（invalid + 原因），不悄悄藏也不悄悄修。"""
        runs = Path(self._tmp.name) / "runs"
        runs.mkdir(parents=True)
        (runs / "broken.json").write_text("{oops", encoding="utf-8")
        status, _, body = self.handle("GET", "/api/records")
        items = json.loads(body)["records"]
        self.assertTrue(items[0]["invalid"])
        self.assertIn("JSON", items[0]["error"])

    # ------------------------------------------------ 轮三（三）：参数可调实时重算
    def test_params_schema_endpoint(self):
        """schema 端点：类型/默认值/说明齐全；默认参数必须能直接跑通。"""
        for experiment in ("b12-dijkstra", "b12-knapsack", "b34-astar"):
            status, _, body = self.handle(
                "GET", f"/api/params/{experiment}")
            self.assertEqual(status, 200)
            schema = json.loads(body)["schema"]
            self.assertTrue(schema, msg=experiment)
            for field, spec in schema.items():
                self.assertIn("type", spec, msg=field)
                self.assertIn("default", spec, msg=field)
            defaults = {k: v["default"] for k, v in schema.items()}
            status, _, body = self.post_json("/api/render",
                                             {"experiment": experiment,
                                              "params": defaults})
            self.assertEqual(status, 200, msg=experiment)   # 默认值即可跑通

    def test_params_schema_unknown_experiment_404(self):
        status, _, _ = self.handle("GET", "/api/params/nope")
        self.assertEqual(status, 404)

    def test_render_live_does_not_touch_runs(self):
        """实时重算不落盘：render 之后记录库必须原封不动（零垃圾）。"""
        before = len(json.loads(self.handle("GET", "/api/records")[2])["records"])
        status, _, body = self.post_json(
            "/api/render",
            {"experiment": "b12-knapsack", "params": KNAPSACK_PARAMS})
        self.assertEqual(status, 200)
        self.assertNotIn("name", json.loads(body))      # 无文件名 = 未落盘
        status, _, body = self.handle("GET", "/api/records")
        self.assertEqual(len(json.loads(body)["records"]), before)

    def test_render_live_rejects_bad_params(self):
        status, _, body = self.post_json(
            "/api/render",
            {"experiment": "b34-astar",
             "params": {**{"width": 5, "height": 4, "start": [0, 0],
                           "goal": [4, 3]}, "start": [99, 99]}})
        self.assertEqual(status, 400)
        self.assertIn("不可用", body.decode("utf-8"))

    # ------------------------------------------------ 页面与静态
    def test_index_and_static(self):
        status, _, body = self.handle("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("SimLab".encode(), body)
        status, headers, _ = self.handle("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)["Content-Type"], "text/javascript; charset=utf-8")


class TestOverRealSocket(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.server = build_server(port=0, runs_dir=Path(self._tmp.name) / "runs")
        self.port = self.server.start()
        self.addCleanup(self.server.stop)

    def test_render_and_read_over_socket(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/records",
                     body=json.dumps({"experiment": "b34-astar",
                                      "params": {"width": 5, "height": 4,
                                                 "walls": [], "start": [0, 0],
                                                 "goal": [4, 3]}}).encode(),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 201)
        record = json.loads(resp.read())
        self.assertTrue(record["metrics"]["found"])
        conn.request("GET", f"/api/records/{record['name']}")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(resp.read())["experiment"], "b34-astar")
        conn.request("GET", "/")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"SimLab", resp.read())
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
