"""LinkBox M1 自测：暂存闭环 / 过期 / 回归（短链能力不因产品化受损）/ 真套接字。

期望值出处：过期行为与状态码映射是本产品写进 README 的口径（404 不存在 /
410 已过期 / 400 内容不合法 / 413 超长）；短链回归与 B31 同款用例。
XSS 转义是 B32 的教训落地：用户内容必须逃逸后才能进 HTML。
"""
import http.client
import json
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys_path_done = False
if not sys_path_done:
    import sys
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(REPO / "projects" / "B31-shorturl"))
    sys.path.insert(0, str(REPO / "projects" / "B11-net-lab"))
    sys_path_done = True

from b31.store import Store                                  # noqa: E402
from linkbox.app import LinkBoxApp                           # noqa: E402
from linkbox.stash import MAX_CONTENT, StashError, StashStore  # noqa: E402


class FakeRequest:
    def __init__(self, method, path, body=b"", headers=None):
        self.method = method
        self.target = path                       # 原始目标（含查询串）
        clean = path.split("?")[0]
        self.path = clean
        self.query = []                          # 本测试用例不含查询参数
        self.body = body
        self.headers = list(headers or [])
        self.content_length = len(body)
        self.keep_alive = False
        self.version = "1.1"

    def header(self, name):
        for k, v in self.headers:
            if k == name:
                return v
        return None


class AppCase(unittest.TestCase):
    """直接驱动应用对象 + 可注入时钟（不 sleep 就能测过期）。
    测试只调处理器（与 B31 测试同款），路由分发由真套接字用例覆盖。"""

    def setUp(self):
        self.now = 1_700_000_000.0
        self.stash = StashStore(":memory:")
        self.app = LinkBoxApp(Store(), ROOT / "web", stash=self.stash,
                              clock=lambda: self.now)

    def request(self, method, path, payload=None, raw=None):
        body = raw if raw is not None else (
            json.dumps(payload).encode("utf-8") if payload is not None else b"")
        headers = [("Content-Type", "application/json")] if body else []
        req = FakeRequest(method, path, body, headers)
        if path == "/api/stash" and method == "POST":
            return self.app.create_stash(req)
        if path.startswith("/api/stash/") and method == "GET":
            return self.app.stash_api(req)
        if path.startswith("/api/stash/") and method == "DELETE":
            return self.app.delete_stash(req)
        if path.startswith("/s/") and method == "GET":
            return self.app.stash_page(req)
        if path == "/api/links" and method == "POST":
            return self.app.create_link(req)
        if path.startswith("/l/") and method == "GET":
            return self.app.redirect(req)
        if path == "/" and method == "GET":
            return self.app.index(req)
        raise AssertionError(f"测试路由未覆盖: {method} {path}")

    # ------------------------------------------------ 暂存闭环
    def test_stash_roundtrip(self):
        status, headers, body = self.request(
            "POST", "/api/stash", {"content": "hello\nworld", "ttl_hours": 24})
        self.assertEqual(status, 201)
        code = json.loads(body)["code"]
        status, headers, body = self.request("GET", f"/api/stash/{code}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["content"], "hello\nworld")

    def test_stash_view_page_escapes_html(self):
        """XSS 回归：脚本内容必须逃逸成 &lt;script&gt;，绝不原样进 HTML。"""
        status, _, body = self.request(
            "POST", "/api/stash", {"content": "<script>alert(1)</script>"})
        self.assertEqual(status, 201)
        code = json.loads(body)["code"]
        status, _, page = self.request("GET", f"/s/{code}")
        self.assertEqual(status, 200)
        page = page.decode("utf-8")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_expiry_returns_410_and_deletes(self):
        status, _, body = self.request(
            "POST", "/api/stash", {"content": "gone soon", "ttl_hours": 1})
        code = json.loads(body)["code"]
        self.now += 2 * 3600                     # 越过有效期
        status, _, body = self.request("GET", f"/api/stash/{code}")
        self.assertEqual(status, 410)
        self.assertIn("已过期", body.decode("utf-8"))
        self.assertEqual(self.stash.count(), 0)  # 惰性删除生效

    def test_unknown_stash_404(self):
        status, _, _ = self.request("GET", "/api/stash/zzzzzz")
        self.assertEqual(status, 404)

    def test_validation(self):
        cases = [
            ("POST", "/api/stash", {"content": ""}, 400),
            ("POST", "/api/stash", {"content": "x" * (MAX_CONTENT + 1)}, 400),
            ("POST", "/api/stash", {"content": 123}, 400),
            ("POST", "/api/stash", {"content": "ok", "ttl_hours": 0}, 400),
            ("POST", "/api/stash", {"content": "ok", "oops": 1}, 400),
        ]
        for method, path, payload, want in cases:
            status, _, _ = self.request(method, path, payload)
            self.assertEqual(status, want, msg=payload)

    def test_delete_stash(self):
        status, _, body = self.request("POST", "/api/stash", {"content": "bye"})
        code = json.loads(body)["code"]
        status, _, _ = self.request("DELETE", f"/api/stash/{code}")
        self.assertEqual(status, 204)
        status, _, _ = self.request("GET", f"/api/stash/{code}")
        self.assertEqual(status, 404)

    def test_stash_error_is_valueerror_subclass(self):
        self.assertTrue(issubclass(StashError, ValueError))

    # ------------------------------------------------ 产品化回归
    def test_shortlink_regression_through_product_app(self):
        status, headers, body = self.request(
            "POST", "/api/links", {"url": "http://example.com/page"})
        self.assertEqual(status, 201)
        code = json.loads(body)["code"]
        status, headers, body = self.request("GET", f"/l/{code}")
        self.assertEqual(status, 302)
        loc = {k.lower(): v for k, v in headers}["location"]
        self.assertEqual(loc, "http://example.com/page")

    def test_product_index_served(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"LinkBox", body)


# ---------------------------------------------------------------- 真套接字
class LinkBoxServer:
    """组合 LinkBoxApp 与 B31 服务器（同构于 B31 的 build_server）。"""

    def __init__(self, *, db_path=":memory:", stash_path=":memory:", port=0):
        from b31.server import ShortUrlServer
        store = Store(db_path)
        stash = StashStore(stash_path)
        self.app = LinkBoxApp(store, ROOT / "web", stash=stash)
        self.server = ShortUrlServer(self.app, port=port)

    def start(self) -> int:
        return self.server.start()

    def stop(self) -> None:
        self.server.stop()
        self.app.store.close()
        self.app.stash.conn.close()


class TestOverRealSocket(unittest.TestCase):
    def setUp(self):
        self.box = LinkBoxServer(port=0)
        self.port = self.box.start()
        self.addCleanup(self.box.stop)

    def test_stash_over_real_socket(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/stash",
                     body=json.dumps({"content": "real socket",
                                      "ttl_hours": 1}).encode(),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 201)
        code = json.loads(resp.read())["code"]
        conn.request("GET", f"/api/stash/{code}")
        resp = conn.getresponse()
        self.assertEqual(json.loads(resp.read())["content"], "real socket")
        conn.close()

    def test_product_page_over_real_socket(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"LinkBox", resp.read())
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
