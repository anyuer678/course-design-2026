"""webframe 自测：路由/体校验/会话/静态/模板/错误语义 + 真套接字。

可独立推导的性质（不引用凭印象的值）：
    - <param> 命名分组、405 带 Allow、404 JSON；
    - bool 冒充 int 一律拒收（bool 是 int 子类——B23/B31 的教训）；
    - 会话签名：改一个字节就验不过（compare_digest）；
    - 模板默认转义：<script> 必须逃逸；缺键/多余键报错；
    - 静态守卫：resolve 后必须留在根里。
真套接字四条：GET/405/静态/会话走完整协议栈。
"""
import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webframe import (HttpFail, MicroApp, MicroServer, Raw, ValidationError, esc, render, validate)
from webframe.template import _PLACEHOLDER

from netlab.http1 import HttpError, Request


def make_request(method, path, body=b"", headers=None, query=None):
    # 与 netlab 解析器同口径：头名一律小写
    return Request(method=method, target=path, version="1.1",
                   headers=[(k.lower(), v) for k, v in list(headers or [])],
                   body=body, path=path, query=list(query or []),
                   keep_alive=False, content_length=len(body))


def build_app(tmpdir: Path) -> MicroApp:
    app = MicroApp(session_secret=b"test-secret-0123456789abcdef-01234567")

    @app.get("/hello/<name>")
    def hello(ctx):
        return ctx.html(f"<p>你好 {esc(ctx.params['name'])}</p>")

    @app.post("/echo-json")
    def echo(ctx):
        payload = ctx.json_body({"n": (int, True), "s": (str, False),
                                 "f": (float, False)})
        return ctx.json({"got": payload})

    @app.get("/set-session")
    def set_session(ctx):
        ctx.session["user"] = "tester"
        return ctx.text("ok")

    @app.get("/reset-session")
    def reset_session(ctx):
        """登出语义：强制回写空会话 cookie（studio 的 logout 踩出的框架缺口）。"""
        ctx.session["junk"] = "x"            # 先有会话，再 reset
        ctx.reset_session()
        return ctx.text("ok")

    @app.get("/read-session")
    def read_session(ctx):
        return ctx.json({"user": ctx.session.get("user")})

    @app.get("/fail")
    def fail(ctx):
        raise HttpFail(418, "teapot")

    @app.get("/boom")
    def boom(ctx):
        raise ValueError("boom")

    @app.get("/tuple")
    def tuple_handler(ctx):
        return 201, [("X-Test", "1")], "made"

    @app.get("/cookie-set")
    def cookie_set(ctx):
        resp = ctx.text("done")
        resp.set_cookie("flavor", "oat", max_age=60)
        return resp

    @app.get("/cookie-read")
    def cookie_read(ctx):
        return ctx.json({"flavor": ctx.cookie("flavor")})

    (tmpdir / "page.html").write_text("<h1>静态页</h1>", encoding="utf-8")
    app.static("/static", tmpdir)
    return app


class WebframeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = build_app(Path(self._tmp.name))

    def handle(self, method, path, body=b"", headers=None, query=None):
        return self.app.handle(make_request(method, path, body, headers, query))

    # ------------------------------------------------ 路由与错误语义
    def test_route_params(self):
        status, headers, body = self.handle("GET", "/hello/world")
        self.assertEqual(status, 200)
        self.assertIn("你好 world", body.decode("utf-8"))

    def test_404_json(self):
        status, headers, body = self.handle("GET", "/nope")
        self.assertEqual(status, 404)
        self.assertIn("不存在", body.decode("utf-8"))
        self.assertTrue(any(k == "Content-Type" and "json" in v
                            for k, v in headers))

    def test_405_with_allow(self):
        status, headers, body = self.handle("DELETE", "/hello/x")
        self.assertEqual(status, 405)
        allow = dict(headers)["Allow"]
        self.assertIn("GET", allow)

    def test_head_maps_to_get(self):
        """HEAD 路由到 GET 处理器；体按 netlab 的口径发送时剥掉（CL 保留）。"""
        status, headers, body = self.handle("HEAD", "/hello/h")
        self.assertEqual(status, 200)
        self.assertIn("你好 h", body.decode("utf-8"))

    def test_options_raises_501(self):
        with self.assertRaises(HttpError):
            self.handle("OPTIONS", "/hello/x")

    def test_handler_exception_becomes_500(self):
        status, _, body = self.handle("GET", "/boom")
        self.assertEqual(status, 500)
        self.assertIn("internal error", body.decode("utf-8"))

    def test_httpfail_status(self):
        status, _, body = self.handle("GET", "/fail")
        self.assertEqual(status, 418)
        self.assertIn("teapot", body.decode("utf-8"))

    def test_tuple_handler_compat(self):
        """B31 风格的 (status, headers, body) 三元组照收（str 体自动编码）。"""
        status, headers, body = self.handle("GET", "/tuple")
        self.assertEqual(status, 201)
        self.assertEqual(dict(headers)["X-Test"], "1")
        self.assertEqual(body, b"made")

    # ------------------------------------------------ JSON 体校验
    def post_json(self, raw, ctype="application/json"):
        return self.handle("POST", "/echo-json", raw,
                           [("Content-Type", ctype)])

    def test_json_ok(self):
        status, _, body = self.post_json(b'{"n": 3, "s": "x", "f": 2.5}')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["got"]["n"], 3)

    def test_json_int_passes_float_field(self):
        """JSON 只有 number：int 落到 float 字段合法（bool 不行，见下一条）。"""
        status, _, _ = self.post_json(b'{"n": 1, "f": 2}')
        self.assertEqual(status, 200)

    def test_json_wrong_content_type_415(self):
        status, _, _ = self.post_json(b'{"n": 1}', ctype="text/plain")
        self.assertEqual(status, 415)

    def test_json_bad_syntax_400(self):
        status, _, body = self.post_json(b'{"n": ')
        self.assertEqual(status, 400)
        self.assertIn("JSON", body.decode("utf-8"))

    def test_json_missing_required_400(self):
        status, _, body = self.post_json(b'{"s": "x"}')
        self.assertEqual(status, 400)
        self.assertIn("n", body.decode("utf-8"))

    def test_json_unknown_field_400(self):
        status, _, body = self.post_json(b'{"n": 1, "extra": 1}')
        self.assertEqual(status, 400)
        self.assertIn("extra", body.decode("utf-8"))

    def test_json_bool_never_passes_int_field(self):
        """bool 是 int 的子类——不拦住就会出现 true 冒充 1 的静默错误。"""
        status, _, _ = self.post_json(b'{"n": true}')
        self.assertEqual(status, 400)

    def test_validate_bool_not_int_direct(self):
        with self.assertRaises(ValidationError):
            validate({"x": True}, {"x": (int, True)})

    # ------------------------------------------------ Cookie 与签名会话
    def test_cookie_set_and_read(self):
        _, headers, _ = self.handle("GET", "/cookie-set")
        set_cookie = dict(headers)["Set-Cookie"]
        self.assertIn("flavor=oat", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        status, _, body = self.handle(
            "GET", "/cookie-read", headers=[("Cookie", "flavor=oat")])
        self.assertEqual(json.loads(body)["flavor"], "oat")

    def test_session_roundtrip(self):
        _, headers, _ = self.handle("GET", "/set-session")
        token = dict(headers)["Set-Cookie"].split(";")[0].split("=", 1)[1]
        status, _, body = self.handle(
            "GET", "/read-session", headers=[("Cookie", f"wf_session={token}")])
        self.assertEqual(json.loads(body)["user"], "tester")

    def test_session_forged_signature_rejected(self):
        """改签名一个字符就得重来：会话里不许有任何被信任的伪造空间。"""
        _, headers, _ = self.handle("GET", "/set-session")
        token = dict(headers)["Set-Cookie"].split(";")[0].split("=", 1)[1]
        raw, _, sig = token.rpartition(".")
        bad = f"{raw}.{'0' if sig[0] != '0' else '1'}{sig[1:]}"
        status, _, body = self.handle(
            "GET", "/read-session", headers=[("Cookie", f"wf_session={bad}")])
        self.assertEqual(json.loads(body)["user"], None)

    def test_session_garbage_token_ignored(self):
        status, _, body = self.handle(
            "GET", "/read-session", headers=[("Cookie", "wf_session=garbage")])
        self.assertEqual(json.loads(body)["user"], None)

    def test_reset_session_forces_empty_cookie(self):
        """登出：reset_session 必须回写空会话 cookie——只 clear() 与
        "从未登录"快照相同，浏览器旧凭据不会被覆盖（studio 实测踩出的缺口）。"""
        _, headers, _ = self.handle("GET", "/reset-session")
        set_cookie = dict(headers)["Set-Cookie"]
        self.assertIn("wf_session=", set_cookie)
        # 新 token 解出来是空会话
        token = set_cookie.split(";")[0].split("=", 1)[1]
        import base64
        payload = json.loads(base64.urlsafe_b64decode(
            token.rpartition(".")[0] + "=" * (-len(token.rpartition(".")[0]) % 4)))
        self.assertEqual(payload["data"], {})

    # ------------------------------------------------ 静态文件
    def test_static_serves(self):
        status, headers, body = self.handle("GET", "/static/page.html")
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("静态页", body.decode("utf-8"))

    def test_static_missing_and_traversal(self):
        self.assertEqual(self.handle("GET", "/static/none.html")[0], 404)
        # ".." 上跳：解析层被 netlab 拒；框架层的 resolve 守卫是最后一道
        self.assertEqual(self.handle("GET", "/static/../secret.txt")[0], 404)

    # ------------------------------------------------ 模板
    def test_template_escapes_by_default(self):
        out = render("<b>${v}</b>", v="<script>alert(1)</script>")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_template_raw_passthrough(self):
        out = render("<i>${v}</i>", v=Raw("<em>ok</em>"))
        self.assertIn("<em>ok</em>", out)

    def test_template_missing_and_unused_keys_raise(self):
        with self.assertRaises(KeyError):
            render("${nope}", v="x")
        with self.assertRaises(KeyError):
            render("static", v="x")            # 传了没用到的键也要暴露

    def test_placeholder_regex_scope(self):
        self.assertEqual(_PLACEHOLDER.findall("${a} ${b1}"), ["a", "b1"])


class TestOverRealSocket(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.server = MicroServer(build_app(Path(self._tmp.name)), port=0)
        self.port = self.server.start()
        self.addCleanup(self.server.stop)

    def test_get_over_socket(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/hello/socket")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn("你好 socket".encode("utf-8"), resp.read())
        conn.close()

    def test_405_over_socket(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("PUT", "/hello/x")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 405)
        self.assertIn("GET", resp.getheader("Allow"))
        resp.read()
        conn.close()

    def test_static_over_socket(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/static/page.html")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn("静态页".encode("utf-8"), resp.read())
        conn.close()

    def test_session_over_socket(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/set-session")
        resp = conn.getresponse()
        resp.read()
        cookie = resp.getheader("Set-Cookie").split(";")[0]
        conn.request("GET", "/read-session", headers={"Cookie": cookie})
        resp = conn.getresponse()
        self.assertEqual(json.loads(resp.read())["user"], "tester")
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
