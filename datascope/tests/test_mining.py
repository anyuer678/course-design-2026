"""DataScope 挖掘适配与服务自测：对拍 B26 真引擎 + API 全链路 + 真套接字。

对拍口径：适配层的挖掘结果与**直接调用 B26 引擎**同源一致
（Apriori 的频繁项集/规则、K-means 的惯性/轮廓/迭代数）。
"""
import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import datascope
from datascope.mining import apriori_from_rows, kmeans_from_rows
from datascope.server import build_app

from mining.apriori import apriori as b26_apriori
from mining.kmeans import KMeans, silhouette as b26_silhouette

BASKET_CSV = """order,item
O1,键盘
O1,显示器
O2,键盘
O2,显示器
O3,键盘
O4,鼠标
O5,鼠标
"""

NUMERIC_CSV = """x,y
1,1
2,1
1,2
2,2
10,10
10,11
11,10
11,11
"""


class TestMiningAdapters(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.basket = datascope.parse_csv_text(BASKET_CSV)
        self.numeric = datascope.parse_csv_text(NUMERIC_CSV)

    def test_apriori_matches_direct_engine(self):
        """适配层结果与直接调用 B26 apriori 同源一致。"""
        result = apriori_from_rows(self.basket, group_col="order",
                                   item_col="item", min_support=0.4,
                                   min_confidence=0.6)
        transactions = [frozenset(v) for v in
                        {"O1": {"键盘", "显示器"}, "O2": {"键盘", "显示器"},
                         "O3": {"键盘"}, "O4": {"鼠标"}, "O5": {"鼠标"}}.values()]
        frequent, stats = b26_apriori(transactions, 0.4)
        self.assertEqual(result["stats"], stats)
        by_items = {tuple(i["items"]): i["count"] for i in result["itemsets"]}
        for s, count in frequent.items():
            self.assertEqual(by_items[tuple(sorted(s))], count)
        pairs = {(tuple(r["ante"]), tuple(r["cons"])) for r in result["rules"]}
        self.assertTrue(
            (("键盘",), ("显示器",)) in pairs or (("显示器",), ("键盘",)) in pairs,
            msg=result["rules"])

    def test_kmeans_matches_direct_engine(self):
        result = kmeans_from_rows(self.numeric, columns=["x", "y"], k=2, seed=0)
        X = [[1, 1], [2, 1], [1, 2], [2, 2], [10, 10], [10, 11], [11, 10], [11, 11]]
        model = KMeans(k=2, seed=0).fit(X)
        self.assertEqual(result["labels"], model.labels_)
        self.assertEqual(result["metrics"]["inertia"], round(model.inertia_, 4))
        self.assertEqual(result["metrics"]["silhouette"],
                         round(b26_silhouette(X, model.labels_), 4))
        self.assertEqual(result["metrics"]["iterations"], model.iterations_)

    def test_kmeans_bad_value_reports_row(self):
        bad = datascope.parse_csv_text("x\n1\noops\n")
        with self.assertRaises(ValueError) as ctx:
            kmeans_from_rows(bad, columns=["x"], k=1)
        self.assertIn("2", str(ctx.exception))     # 第 2 数据行的行号

    def test_apriori_unknown_column(self):
        with self.assertRaises(ValueError):
            apriori_from_rows(self.basket, group_col="ghost", item_col="item")


class TestServer(unittest.TestCase):
    def setUp(self):
        self.app = build_app()

    def handle(self, method, path, body=b"", headers=None):
        from netlab.http1 import Request
        req = Request(method=method, target=path, version="1.1",
                      headers=[(k.lower(), v) for k, v in list(headers or [])],
                      body=body, path=path, query=[], keep_alive=False,
                      content_length=len(body))
        return self.app.handle(req)

    def test_profile_over_text_csv_body(self):
        status, headers, body = self.handle(
            "POST", "/api/profile", NUMERIC_CSV.encode(),
            [("Content-Type", "text/csv")])
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["rows"], 8)
        self.assertEqual(data["profile"]["x"]["type"], "int")

    def test_profile_wrong_content_type_415(self):
        status, _, _ = self.handle("POST", "/api/profile", b"x",
                                   [("Content-Type", "application/json")])
        self.assertEqual(status, 415)

    def test_clean_over_json(self):
        status, _, body = self.handle(
            "POST", "/api/clean",
            json.dumps({"csv": BASKET_CSV,
                        "recipe": [{"op": "drop_duplicates"}]}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["report"]["steps"][0]["counts"]
                         ["duplicates_removed"], 0)
        self.assertIn("order,item", data["csv"])

    def test_clean_bad_recipe_400(self):
        status, _, body = self.handle(
            "POST", "/api/clean",
            json.dumps({"csv": BASKET_CSV,
                        "recipe": [{"op": "nope"}]}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 400)

    def test_mine_apriori_and_kmeans(self):
        status, _, body = self.handle(
            "POST", "/api/mine",
            json.dumps({"csv": BASKET_CSV, "task": "apriori",
                        "params": {"group_col": "order", "item_col": "item",
                                   "min_support": 0.4}}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["task"], "apriori")
        status, _, body = self.handle(
            "POST", "/api/mine",
            json.dumps({"csv": NUMERIC_CSV, "task": "kmeans",
                        "params": {"columns": ["x", "y"], "k": 2}}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["task"], "kmeans")

    def test_mine_bad_task_and_bad_params(self):
        status, _, _ = self.handle(
            "POST", "/api/mine",
            json.dumps({"csv": NUMERIC_CSV, "task": "xmeans",
                        "params": {}}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 400)
        status, _, _ = self.handle(
            "POST", "/api/mine",
            json.dumps({"csv": NUMERIC_CSV, "task": "kmeans",
                        "params": {"columns": ["ghost"], "k": 1}}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 400)

    def test_index_and_static(self):
        status, _, body = self.handle("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("DataScope".encode(), body)
        status, headers, _ = self.handle("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)["Content-Type"], "text/javascript; charset=utf-8")

    def test_report_endpoint_svg(self):
        """清洗 + 挖掘 → 自包含 SVG 报告：账本计数与规则进图，文本转义。"""
        status, headers, body = self.handle(
            "POST", "/api/report",
            json.dumps({"csv": BASKET_CSV,
                        "recipe": [{"op": "drop_duplicates"}],
                        "mining": {"task": "apriori",
                                   "params": {"group_col": "order",
                                              "item_col": "item",
                                              "min_support": 0.4}}}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)["Content-Type"], "image/svg+xml")
        svg = body.decode("utf-8")
        self.assertIn("<svg", svg)
        self.assertIn("drop_duplicates", svg)
        self.assertIn("duplicates_removed", svg)
        self.assertIn("键盘", svg)                # 挖掘规则进了图

    def test_report_bad_recipe_400(self):
        status, _, _ = self.handle(
            "POST", "/api/report",
            json.dumps({"csv": BASKET_CSV,
                        "recipe": [{"op": "nope"}]}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 400)


class TestOverRealSocket(unittest.TestCase):
    def setUp(self):
        from webframe import MicroServer
        self.server = MicroServer(build_app(), port=0)
        self.port = self.server.start()
        self.addCleanup(self.server.stop)

    def test_profile_over_socket(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/profile", body=NUMERIC_CSV.encode(),
                     headers={"Content-Type": "text/csv"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read())
        self.assertEqual(data["rows"], 8)
        conn.request("GET", "/")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"DataScope", resp.read())
        conn.close()


class TestRecipes(unittest.TestCase):
    """D1 清洗配方保存/重放（2026-10-07 功能增强）：隔离目录，不碰 data/。"""

    def setUp(self):
        self.rdir = Path(tempfile.mkdtemp(prefix="ds-recipes-"))
        self.app = build_app(recipes_dir=self.rdir)

    def handle(self, method, path, body=b"", headers=None):
        from netlab.http1 import Request
        req = Request(method=method, target=path, version="1.1",
                      headers=[(k.lower(), v) for k, v in list(headers or [])],
                      body=body, path=path, query=[], keep_alive=False,
                      content_length=len(body))
        return self.app.handle(req)

    def test_save_list_load_delete(self):
        steps = [{"op": "trim"}, {"op": "drop_duplicates"}]
        status, _, body = self.handle(
            "POST", "/api/recipes",
            json.dumps({"name": "demo-1", "steps": steps}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 201)
        self.assertTrue((self.rdir / "demo-1.json").is_file())
        status, _, body = self.handle("GET", "/api/recipes")
        self.assertIn("demo-1", json.loads(body)["recipes"])
        status, _, body = self.handle("GET", "/api/recipes/demo-1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["steps"], steps)
        status, _, _ = self.handle("DELETE", "/api/recipes/demo-1")
        self.assertEqual(status, 200)
        status, _, _ = self.handle("GET", "/api/recipes/demo-1")
        self.assertEqual(status, 404)

    def test_bad_name_and_empty_steps_400(self):
        status, _, _ = self.handle(
            "POST", "/api/recipes",
            json.dumps({"name": "bad name!", "steps": [{"op": "trim"}]}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 400)
        status, _, _ = self.handle(
            "POST", "/api/recipes",
            json.dumps({"name": "ok", "steps": []}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 400)

    def test_unknown_recipe_404(self):
        status, _, _ = self.handle("GET", "/api/recipes/ghost")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
