"""与标准库对拍：同一份请求字节，我们的解析器和 http.server 的解析器各看到什么。

两件事分开做：
1) parser 对拍用 socketpair 把 stdlib 的 BaseHTTPRequestHandler 当纯解析器使，
   没有端口、没有线程、没有时序，喂进去的字节和读到的结论一一对应；
2) 互操作测试用 stdlib 的 http.client 打我们自己的服务器，
   证明响应字节标准客户端能读，顺手把 keep-alive、HEAD、错误路径都过一遍。

第三类把"我们与标准库的分歧"写成断言：这些不是 bug，是我们有意更严，
但必须有人盯着——哪天标准库改了默认，测试会先叫。
"""
from __future__ import annotations

import http.client
import io
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from netlab.http1 import HttpError, parse_request, parse_response  # noqa: E402
from netlab.server import Server                                    # noqa: E402


class _Tap(BaseHTTPRequestHandler):
    """把 stdlib 的请求解析结果录下来；不真的服务任何资源。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):        # 静音
        pass

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.server.result.update(
            ok=True,
            command=self.command,
            path=self.path,
            version=self.request_version,
            headers=[(k.lower(), v) for k, v in self.headers.items()],
            body=self.rfile.read(length) if length else b"",
        )
        # 一次只判一个请求：留着不关，stdlib 会接着把残留字节当第二个请求解析，
        # 于是"chunked 体"这种残留会冒出一个假结论，把真正要记的东西盖掉。
        self.close_connection = True

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = _record

    def send_error(self, code, message=None, explain=None):
        # 标准库的 send_error 会关掉连接；不照做就会继续解析残留字节（同上）
        self.close_connection = True
        if self.server.result["ok"] is None:      # 只认第一个结论
            self.server.result.update(ok=False, error_code=int(code), message=message)


class _SilentServer:
    """BaseHTTPRequestHandler 只需要三个钩子：结果字典我们存在这里。"""

    def __init__(self):
        self.result = {"ok": None}

    def shutdown_request(self, request):
        pass

    def close_request(self, request):
        pass

    def handle_error(self, request, client_address):
        pass


def stdlib_parse(raw: bytes) -> dict:
    """把一段请求字节交给 stdlib 的解析器，返回它的结论。

    用 socketpair 当"假网络"：没有端口、没有线程、没有时序，
    喂进去什么字节就能复现什么结论。注意 BaseHTTPRequestHandler 的
    __init__ 里就跑完了 setup/handle/finish，所以结果必须存在 server 对象上。
    """
    host, client = socket.socketpair()
    server = _SilentServer()
    try:
        client.sendall(raw)
        client.shutdown(socket.SHUT_WR)
        _Tap(host, ("127.0.0.1", 0), server)
    except OSError:                       # 非法请求走到关连接，是正常路径
        pass
    finally:
        host.close()
        client.close()
    return server.result


class _FakeSocket:
    """http.client 只向这个对象要 makefile()：给它一段字节就能离线读响应。"""

    def __init__(self, data: bytes):
        self._data = data

    def makefile(self, mode="rb", *args, **kwargs):
        return io.BytesIO(self._data)

    def sendall(self, data):
        pass

    def close(self):
        pass


def stdlib_response_view(raw: bytes, head: bool = False):
    response = http.client.HTTPResponse(_FakeSocket(raw),
                                        method="HEAD" if head else None)
    response.begin()
    return (response.status,
            sorted((k.lower(), v) for k, v in response.getheaders()),
            response.read())


def our_response_view(raw: bytes, head: bool = False):
    """我们的解析结论 + "是不是刚好吃完这份字节"。"""
    parsed = parse_response(raw, body_expected=not head)
    if parsed is None:
        return None, False
    response, used = parsed
    return (response.status,
            sorted((k, v) for k, v in response.headers),
            response.body), used == len(raw)


class TestParserAgainstStdlib(unittest.TestCase):
    def ours(self, raw: bytes):
        parsed = parse_request(raw, max_body=1024 * 1024)
        self.assertIsNotNone(parsed, f"我们的解析器认为字节流还不完整: {raw[:60]!r}")
        return parsed[0]

    def test_valid_requests_agree(self):
        cases = [
            b"GET / HTTP/1.1\r\nHost: h\r\n\r\n",
            b"GET /kv/a HTTP/1.1\r\nHost: h\r\nAccept: */*\r\nX-Trace: 1\r\n\r\n",
            b"GET /a%20b/%E4%BF%AE?q=1+%21 HTTP/1.1\r\nHost: h\r\n\r\n",
            b"POST /p HTTP/1.1\r\nHost: h\r\nContent-Length: 5\r\n\r\nhello",
            b"PUT /p HTTP/1.0\r\nHost: h\r\nContent-Length: 0\r\n\r\n",
            b"DELETE /p HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n",
            b"HEAD /p HTTP/1.1\r\nHost: h\r\nRange: bytes=0-1\r\n\r\n",
        ]
        for raw in cases:
            with self.subTest(request=raw[:48]):
                theirs, ours = stdlib_parse(raw), self.ours(raw)
                self.assertTrue(theirs["ok"], f"stdlib 拒绝了合法请求: {theirs}")
                self.assertEqual(ours.method, theirs["command"])
                self.assertEqual(ours.target, theirs["path"])       # 原始目标必须一字不差
                self.assertEqual(f"HTTP/{ours.version}", theirs["version"])
                self.assertEqual(ours.headers, theirs["headers"])
                self.assertEqual(ours.body, theirs["body"])

    def test_repeated_headers_keep_order_and_values(self):
        raw = b"GET / HTTP/1.1\r\nHost: h\r\nX-A: 1\r\nX-A: 2\r\nAccept: text\r\n\r\n"
        theirs, ours = stdlib_parse(raw), self.ours(raw)
        self.assertTrue(theirs["ok"])
        self.assertEqual(ours.headers, theirs["headers"])
        self.assertEqual(ours.headers_of("x-a"), ["1", "2"])

    def test_lowercase_method_both_refuse_to_run_it(self):
        # stdlib 报 501，我们把它交给路由判 405：共同点是都不当成 GET 执行
        ours = self.ours(b"get / HTTP/1.1\r\nHost: h\r\n\r\n")
        self.assertEqual(ours.method, "get")
        theirs = stdlib_parse(b"get / HTTP/1.1\r\nHost: h\r\n\r\n")
        self.assertFalse(theirs["ok"])
        self.assertEqual(theirs["error_code"], 501)

    def test_too_many_headers_agree(self):
        raw = b"GET / HTTP/1.1\r\n" + b"X: 1\r\n" * 200 + b"\r\n"
        with self.assertRaises(HttpError) as ours_exc:
            parse_request(raw)
        self.assertEqual(ours_exc.exception.status, 431)
        self.assertEqual(stdlib_parse(raw)["error_code"], 431)     # 标准库同样拒

    def test_bad_request_line_agrees(self):
        for raw in (b"G T / HTTP/1.1\r\n\r\n", b"GET\r\n\r\n", b"GET / RT/1.1\r\n\r\n"):
            with self.subTest(request=raw[:24]):
                with self.assertRaises(HttpError):
                    parse_request(raw)
                self.assertFalse(stdlib_parse(raw)["ok"])


class TestDocumentedDivergences(unittest.TestCase):
    """我们比 stdlib 严的地方，逐条写死成断言（Python 3.12.3 实测）。"""

    CASES = [
        ("chunked 但不实现它", b"POST / HTTP/1.1\r\nHost: h\r\n"
                              b"Transfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n0\r\n\r\n",
         501, 200),
        ("裸 LF 当换行", b"GET /a HTTP/1.1\nHost: h\n\n", 400, 200),
        ("两个不一致的 Content-Length",
         b"POST / HTTP/1.1\r\nHost: h\r\nContent-Length: 3\r\nContent-Length: 4\r\n\r\nabc",
         400, 200),
        ("超长的请求目标", b"GET /" + b"a" * 9000 + b" HTTP/1.1\r\nHost: h\r\n\r\n", 414, 200),
        ("路径里的 ..", b"GET /a/../b HTTP/1.1\r\nHost: h\r\n\r\n", 400, 200),
        ("编码后露出来的 ..", b"GET /a/%2e%2e/b HTTP/1.1\r\nHost: h\r\n\r\n", 400, 200),
        ("Expect: 100-continue",
         b"POST / HTTP/1.1\r\nHost: h\r\nExpect: 100-continue\r\nContent-Length: 0\r\n\r\n",
         417, 200),
    ]

    def test_we_refuse_what_stdlib_accepts(self):
        for name, raw, our_status, stdlib_status in self.CASES:
            with self.subTest(case=name):
                with self.assertRaises(HttpError) as exc:
                    parse_request(raw)
                self.assertEqual(exc.exception.status, our_status, name)
                theirs = stdlib_parse(raw)
                got = theirs["error_code"] if not theirs["ok"] else 200
                self.assertEqual(got, stdlib_status,
                                 f"{name}：标准库行为变了（现在 {got}），"
                                 f"README 里的分歧表要改")

    def test_divergence_is_enforced_end_to_end(self):
        """解析层的判断必须真的落到响应码上，不能只是解析器里的一条规则。"""
        server = Server(port=0)
        server.start()
        self.addCleanup(server.stop)
        for name, raw, our_status, _ in self.CASES:
            with self.subTest(case=name):
                with socket.create_connection(("127.0.0.1", server.port), timeout=3) as s:
                    s.sendall(raw)
                    s.settimeout(3)
                    head = b""
                    while b"\r\n\r\n" not in head:
                        chunk = s.recv(4096)
                        if not chunk:
                            break
                        head += chunk
                self.assertEqual(int(head.split(b" ")[1]), our_status, name)


class TestStdlibClientDrivesOurServer(unittest.TestCase):
    """标准客户端读我们吐出去的字节：状态行、头部、体、连接语义都得对。"""

    def setUp(self):
        self.server = Server(port=0)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        self.addCleanup(self.conn.close)

    def test_crud_through_stdlib_client(self):
        self.conn.request("PUT", "/kv/%E4%BF%AE", body="水管".encode())
        r = self.conn.getresponse()
        self.assertEqual((r.status, r.read()), (201, b"ok\n"))
        self.conn.request("GET", "/kv/%E4%BF%AE")
        r = self.conn.getresponse()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.read().decode(), "水管")
        self.conn.request("DELETE", "/kv/%E4%BF%AE")
        r = self.conn.getresponse()
        self.assertEqual((r.status, r.read()), (204, b""))
        self.conn.request("GET", "/kv/%E4%BF%AE")
        self.assertEqual(self.conn.getresponse().status, 404)

    def test_keepalive_reuses_one_connection(self):
        for _ in range(3):
            self.conn.request("GET", "/")
            r = self.conn.getresponse()
            self.assertEqual(r.status, 200)
            self.assertTrue(len(r.read()) > 0)
        self.assertEqual(self.server.stats.connections, 1)
        self.assertEqual(self.server.stats.requests, 3)

    def test_close_makes_stdlib_client_drop_the_socket(self):
        self.conn.request("GET", "/", headers={"Connection": "close"})
        r = self.conn.getresponse()
        self.assertEqual(r.status, 200)
        r.read()
        self.assertTrue(r.will_close)
        self.conn.close()
        # 我们确实关了：再发一次就得重连，服务端连接数会 +1
        self.conn.connect()
        self.conn.request("GET", "/")
        self.conn.getresponse().read()
        self.assertEqual(self.server.stats.connections, 2)

    def test_head_has_no_body_but_promises_length(self):
        self.conn.request("PUT", "/kv/h", body=b"12345")
        self.conn.getresponse().read()
        self.conn.request("HEAD", "/kv/h")
        r = self.conn.getresponse()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Content-Length"), "5")
        self.assertEqual(r.read(), b"")

    def test_413_is_readable_by_stdlib_client(self):
        # 声明巨大体但只发一点：我们必须在不读体的情况下就把 413 送回去
        self.conn.request("POST", "/kv/big", body=b"x",
                          headers={"Content-Length": "9000000"})
        response = self.conn.getresponse()
        self.assertEqual(response.status, 413)
        self.assertIn("超过上限", response.read().decode())

    def test_our_response_headers_are_a_superset_of_what_stdlib_needs(self):
        self.conn.request("GET", "/")
        r = self.conn.getresponse()
        r.read()
        for required in ("Server", "Date", "Content-Length", "Connection"):
            self.assertIsNotNone(r.getheader(required), f"响应缺少 {required}")
        self.assertEqual(r.status, 200)
        # Python 3.12 把 HTTPResponse.version 存成整数 11，别再拿它跟 "1.1" 比
        self.assertEqual(str(r.version).replace(".", ""), "11")


class TestResponseParsingAgainstStdlib(unittest.TestCase):
    """同一份响应字节，我们的 parse_response 和 http.client 必须给出同样的结论。

    生产者取两个（我们的服务器、stdlib 的服务器），解析器也取两个，
    对得上才说明我们的响应既"发得出去"也"读得回来"。
    """

    class Reference(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _fixed(self):
            body = b"reference-body"
            if self.command == "DELETE":
                self.send_response(204)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = _fixed

    def setUp(self):
        self.ours = Server(port=0)
        self.ours.start()
        self.addCleanup(self.ours.stop)
        from http.server import ThreadingHTTPServer
        self.ref = ThreadingHTTPServer(("127.0.0.1", 0), self.Reference)
        threading.Thread(target=self.ref.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.ref.shutdown(), self.ref.server_close()))

    def capture(self, port: int, request: bytes) -> bytes:
        """拿原始响应字节：请求里带 Connection: close，所以读到 EOF 就是完整一份。"""
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(request)
            s.settimeout(5)
            chunks = []
            while True:
                got = s.recv(65536)
                if not got:
                    break
                chunks.append(got)
            return b"".join(chunks)

    def assert_same_conclusion(self, raw: bytes, head: bool = False, *, label: str):
        self.assertTrue(raw, f"{label}：一个响应字节都没拿到")
        theirs = stdlib_response_view(raw, head)
        ours, consumed_all = our_response_view(raw, head)
        self.assertIsNotNone(ours, f"{label}：我们的解析器认为响应不完整")
        self.assertEqual((ours, consumed_all), (theirs, True),
                         f"{label}：两个解析器结论不一致")

    def test_both_parsers_agree_on_our_responses(self):
        close = b"Connection: close\r\n"
        cases = [
            ("200 首页", b"GET / HTTP/1.1\r\nHost: h\r\n" + close + b"\r\n", False),
            ("HEAD 只给长度", b"HEAD / HTTP/1.1\r\nHost: h\r\n" + close + b"\r\n", True),
            ("404", b"GET /nope HTTP/1.1\r\nHost: h\r\n" + close + b"\r\n", False),
            ("405", b"TRACE / HTTP/1.1\r\nHost: h\r\n" + close + b"\r\n", False),
            ("204 删除", b"DELETE /kv/gone HTTP/1.1\r\nHost: h\r\n" + close + b"\r\n", False),
            ("413 巨体", b"POST /kv/x HTTP/1.1\r\nHost: h\r\nContent-Length: 9000000\r\n"
                         + close + b"\r\nx", False),
            ("400 裸 LF", b"GET / HTTP/1.1\n\n", False),
        ]
        for name, request, head in cases:
            with self.subTest(case=name):
                self.assert_same_conclusion(
                    self.capture(self.ours.port, request), head=head, label=name)

    def test_both_parsers_agree_on_stdlib_responses(self):
        close = b"Connection: close\r\n"
        for name, request, head in [
            ("200", b"GET / HTTP/1.1\r\nHost: h\r\n" + close + b"\r\n", False),
            ("HEAD", b"HEAD / HTTP/1.1\r\nHost: h\r\n" + close + b"\r\n", True),
            ("204", b"DELETE / HTTP/1.1\r\nHost: h\r\n" + close + b"\r\n", False),
        ]:
            with self.subTest(case=name):
                self.assert_same_conclusion(
                    self.capture(self.ref.server_address[1], request), head=head, label=name)

    def test_our_parser_refuses_truncated_response(self):
        """少一个字节的响应必须报"不完整"，不能被当成读完了——对拍时这最容易骗人。"""
        raw = self.capture(self.ref.server_address[1],
                           b"GET / HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n")
        self.assertTrue(raw.endswith(b"reference-body"))
        self.assertIsNone(parse_response(raw[:-1]))
        self.assertIsNotNone(parse_response(raw))
        # 标准客户端对同一份截断字节会抛 IncompleteRead：结论同样是"没读完"
        response = http.client.HTTPResponse(_FakeSocket(raw[:-1]))
        response.begin()
        with self.assertRaises(http.client.IncompleteRead):
            response.read()


if __name__ == "__main__":
    unittest.main(verbosity=2)
