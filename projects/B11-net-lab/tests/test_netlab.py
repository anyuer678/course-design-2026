"""B11-net-lab 自测：HTTP 解析边界 → 服务器行为 → 多路复用与资源释放 → UDP/GBN → 与 stdlib 对拍。

跑法：
    python tests\\test_netlab.py
    pytest tests\\test_netlab.py -v
只绑 127.0.0.1，端口交给系统分配，测完全部关掉。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from netlab import gbn, udp                                                # noqa: E402
from netlab.client import ClientError, Connection, encode_request, one_shot      # noqa: E402
from netlab.http1 import HttpError, build_response, parse_request, parse_response  # noqa: E402
from netlab.server import Server                                                  # noqa: E402


def raw(method="GET", target="/", headers=(), body=b"", version="1.1", close=False):
    """拼一段最原始的请求字节，用来打解析器的边界。"""
    lines = [f"{method} {target} HTTP/{version}"]
    lines += [f"{k}: {v}" for k, v in headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


class TestRequestParsing(unittest.TestCase):
    def parse(self, buf, **kw):
        return parse_request(buf, **kw)

    def assert_error(self, buf, status, **kw):
        try:
            self.parse(buf, **kw)
        except HttpError as exc:
            self.assertEqual(exc.status, status, f"{exc}（期望 {status}）")
            return exc
        self.fail(f"期望 {status}，实际解析成功：{buf[:60]!r}")

    def test_basic_get(self):
        req, used = self.parse(raw(headers=[("Host", "h")]))
        self.assertEqual((req.method, req.path, req.version), ("GET", "/", "1.1"))
        self.assertEqual(req.headers, [("host", "h")])
        self.assertTrue(req.keep_alive)
        self.assertEqual(used, len(raw(headers=[("Host", "h")])))

    def test_method_is_case_sensitive(self):
        req, _ = self.parse(b"get / HTTP/1.1\r\n\r\n")
        self.assertEqual(req.method, "get")          # 不擅自折叠大小写

    def test_need_more_data(self):
        self.assertIsNone(self.parse(b"GET / HTT"))
        self.assertIsNone(self.parse(b"GET / HTTP/1.1\r\nHost: h\r\n"))      # 头部还没写完
        self.assertIsNone(self.parse(b"POST / HTTP/1.1\r\nContent-Length: 5\r\n\r\nab"))

    def test_percent_and_query_decoding(self):
        req, _ = self.parse(raw(target="/a%20b/%E4%BD%A0?k=a+b&flag&x=%25"))
        self.assertEqual(req.path, "/a b/你")
        self.assertEqual(req.query, [("k", "a b"), ("flag", ""), ("x", "%")])

    def test_bare_lf_rejected_immediately(self):
        # 裸 LF 永远等不到 CRLFCRLF：必须马上 400，而不是把连接挂到超时
        exc = self.assert_error(b"GET / HTTP/1.1\n\n", 400)
        self.assertIn("裸 LF", exc.explain)
        self.assert_error(b"GET / HTTP/1.1\r\nX: 1\n", 400)
        self.assert_error(b"GET / HTTP/1.1\r\r\n\r\n", 400)

    def test_absolute_form_and_star(self):
        self.assert_error(raw(target="http://a/b"), 501)
        self.assert_error(raw(target="*"), 501)

    def test_bad_request_line(self):
        self.assert_error(b"GET\r\n\r\n", 400)
        self.assert_error(b"GET  / HTTP/1.1\r\n\r\n", 400)      # 两个空格
        self.assert_error(b"GET / http/1.1\r\n\r\n", 400)       # 版本小写不合法
        self.assert_error(b"GET / RT/1.1\r\n\r\n", 400)
        self.assert_error(b"GET / HTTP/2.0\r\n\r\n", 505)
        self.assert_error(b"G T / HTTP/1.1\r\n\r\n", 400)       # 方法里有空格

    def test_header_syntax(self):
        self.assert_error(b"GET / HTTP/1.1\r\nNoColon\r\n\r\n", 400)
        self.assert_error(b"GET / HTTP/1.1\r\nBad Name: 1\r\n\r\n", 400)
        self.assert_error(b"GET / HTTP/1.1\r\nX: 1\r\n cont\r\n\r\n", 400)  # obs-fold
        self.assert_error("GET / HTTP/1.1\r\nX: 中文\r\n\r\n".encode(), 400)
        self.assert_error(b"GET / HTTP/1.1\r\nX: a\x00b\r\n\r\n", 400)

    def test_limits(self):
        self.assert_error(raw(target="/" + "a" * 2049), 414)
        self.assert_error(b"GET / HTTP/1.1\r\n" + b"X: 1\r\n" * 101 + b"\r\n", 431)
        self.assert_error(b"GET / HTTP/1.1\r\nX: " + b"y" * 9000 + b"\r\n\r\n", 431)
        self.assert_error(b"Z" * (40 * 1024), 431)
        self.assert_error(raw(method="POST", headers=[("Content-Length", "20")],
                              body=b"0" * 20), 413, max_body=10)

    def test_content_length_rules(self):
        req, _ = self.parse(raw(method="POST", headers=[("Content-Length", "3")], body=b"abc"))
        self.assertEqual(req.body, b"abc")
        self.assertEqual(req.content_length, 3)
        # 取值一致才允许重复
        self.parse(raw(method="POST",
                       headers=[("Content-Length", "3"), ("Content-Length", "3")], body=b"abc"))
        self.assert_error(raw(method="POST",
                              headers=[("Content-Length", "3"), ("Content-Length", "4")],
                              body=b"abc"), 400)
        for bad in ("abc", "-1", "+1", "0x3", "3.5", "3,3", "", "1" * 13):
            self.assert_error(raw(method="POST", headers=[("Content-Length", bad)],
                                  body=b"abc"), 400, max_body=1000)
        # 全角数字：isdigit() 会认，但线上必须是 ASCII 十进制
        self.assert_error("POST / HTTP/1.1\r\nContent-Length: ３\r\n\r\nabc".encode(), 400)
        # 首尾空白是合法的 OWS，不是非法值
        req, _ = self.parse(raw(method="POST", headers=[("Content-Length", " 3 ")], body=b"abc"))
        self.assertEqual(req.content_length, 3)

    def test_chunked_is_refused_not_ignored(self):
        # 忽略 chunked 等于把未知长度的字节当成体，是请求走私的入口
        self.assert_error(raw(method="POST", headers=[("Transfer-Encoding", "chunked")]), 501)
        self.assert_error(raw(method="POST", headers=[("TE", "chunked")]), 501)

    def test_expect_100_continue(self):
        self.assert_error(raw(method="POST", headers=[("Expect", "100-continue"),
                                                      ("Content-Length", "0")]), 417)

    def test_path_traversal(self):
        self.assert_error(raw(target="/a/../b"), 400)
        self.assert_error(raw(target="/a/%2e%2e/b"), 400)      # 解码后才露出来的 ..
        self.assert_error(raw(target="/%00"), 400)
        self.assert_error(raw(target="a/b"), 400)              # 不以 / 开头

    def test_connection_semantics(self):
        self.assertFalse(self.parse(raw(version="1.0"))[0].keep_alive)
        self.assertTrue(self.parse(raw(version="1.0",
                                        headers=[("Connection", "keep-alive")]))[0].keep_alive)
        self.assertFalse(self.parse(raw(headers=[("Connection", "close")]))[0].keep_alive)
        self.assertFalse(self.parse(raw(headers=[("Connection", "keep-alive, close")]))[0].keep_alive)
        self.assertTrue(self.parse(raw())[0].keep_alive)

    def test_pipelined_requests_take_their_own_bytes(self):
        two = raw(target="/a") + raw(target="/b")
        first, used = self.parse(two)
        self.assertEqual(first.path, "/a")
        second, used2 = self.parse(two[used:])
        self.assertEqual((second.path, used + used2), ("/b", len(two)))

    def test_body_extra_bytes_belong_to_next_request(self):
        buf = raw(method="POST", headers=[("Content-Length", "3")], body=b"abcGET /x HTTP/1.1\r\n\r\n")
        req, used = self.parse(buf)
        self.assertEqual(req.body, b"abc")
        nxt, _ = self.parse(buf[used:])
        self.assertEqual(nxt.path, "/x")

    def test_header_injection_in_target(self):
        self.assert_error(b"GET /a%0d%0aSet-Cookie:%20x HTTP/1.1\r\n\r\n", 400)


class TestResponseRoundtrip(unittest.TestCase):
    def test_build_then_parse(self):
        data = build_response(200, body=b"hi", keep_alive=True, date="x")
        resp, used = parse_response(data)
        self.assertEqual((resp.status, resp.body, used), (200, b"hi", len(data)))
        self.assertEqual(resp.header("Content-Length"), "2")
        self.assertEqual(resp.header("Connection"), "keep-alive")

    def test_head_keeps_length_but_no_body(self):
        data = build_response(200, body=b"12345", head=True, date="x")
        self.assertTrue(data.endswith(b"\r\n\r\n"))
        self.assertIn(b"Content-Length: 5", data)
        resp, used = parse_response(data, body_expected=False)
        self.assertEqual((resp.status, resp.body, used), (200, b"", len(data)))
        # 不按 HEAD 处理时，客户端会等那 5 个字节：所以客户端必须显式声明"没体"
        self.assertIsNone(parse_response(data))
        self.assertIsNotNone(parse_response(data + b"12345"))

    def test_204_has_no_content_length(self):
        data = build_response(204, body=b"", date="x")
        self.assertNotIn(b"Content-Length", data)
        resp, used = parse_response(data)
        self.assertEqual((resp.status, resp.body, used), (204, b"", len(data)))

    def test_close_is_always_explicit(self):
        for version, keep in (("1.0", True), ("1.0", False), ("1.1", True), ("1.1", False)):
            data = build_response(200, body=b"x", version=version, keep_alive=keep, date="x")
            self.assertIn(f"Connection: {'keep-alive' if keep else 'close'}".encode(), data)

    def test_redirect_status_codes_are_buildable(self):
        """3xx/4xx 是给应用层用的（短链跳转、别名冲突、限流）。
        状态码表里少一条的后果很不直观：Server._reply 在事件循环线程里抛 ValueError，
        客户端那边只是"等不到响应"，排查方向会跑到超时和死锁上去。"""
        data = build_response(302, body=b"redirecting", headers=[("Location", "/l/abc")], date="x")
        resp, used = parse_response(data)
        self.assertEqual((resp.status, resp.reason, resp.header("Location"), resp.body),
                         (302, "Found", "/l/abc", b"redirecting"))
        self.assertEqual(resp.header("Content-Length"), "11")   # 302 允许带体，长度必须准确
        for status in (301, 303, 307, 409, 415, 429):
            self.assertIn(f"{status} ".encode("ascii"), build_response(status, date="x"))
        # 304 按定义不能带体，长度字段也得一起省掉，否则客户端会等一个不存在的体
        self.assertNotIn(b"Content-Length", build_response(304, body=b"", date="x"))
        with self.assertRaises(ValueError):
            build_response(418, date="x")             # 表外的码仍要求显式给 reason

    def test_parse_rejects_unsupported_or_truncated(self):
        self.assertIsNone(parse_response(b"HTTP/1.1 200 OC"))
        head = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nab"
        self.assertIsNone(parse_response(head))
        with self.assertRaises(HttpError):
            parse_response(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
        with self.assertRaises(HttpError):
            parse_response(b"HTTP/1.1 200 OK\r\nX: 1\r\n\r\n")     # 没长度信息


class ServerCase(unittest.TestCase):
    """每个用例起一台自己的服务器，关掉之后断言连接表和计数都清零。"""

    make_server = Server

    def setUp(self):
        self.server = self.make_server(port=0)
        self.server.start()
        self.addCleanup(self.server.stop)      # 用例抛异常时也要收摊

    def tearDown(self):
        # 先停服务端，再看还剩什么：客户端断开是异步被 select 发现的，
        # 拿"进程里所有 socket 对象"当泄漏指标会因为时序而假报警。
        self.server.stop()
        self.assertEqual(self.server.conns, {}, "连接表里还留着没关的连接")
        self.assertEqual(self.server.stats.open_now, 0, "open_now 没有归零")

    def wait_until(self, predicate, timeout=2.0, why="") -> None:
        """服务端要等下一次 select 才会发现客户端断开，断言前给它一点时间。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail(f"等 {timeout}s 仍未满足：{why}")


class TestServerBasics(ServerCase):
    def get(self, target, **kw):
        return one_shot(self.server.port, "GET", target, **kw)

    def test_crud_cycle(self):
        self.assertEqual(self.get("/").status, 200)
        self.assertEqual(self.get("/kv/name").status, 404)
        r = one_shot(self.server.port, "PUT", "/kv/name", body=b"an")
        self.assertEqual((r.status, r.text()), (201, "ok\n"))
        self.assertEqual(self.get("/kv/name").body, b"an")
        r = one_shot(self.server.port, "PUT", "/kv/name", body=b"another")
        self.assertEqual((r.status, r.text()), (200, "updated\n"))
        self.assertEqual(self.get("/kv").text().split(), ["name"])
        self.assertEqual(self.get("/kv/name").body, b"another")
        self.assertEqual(self.one_delete("/kv/name").status, 204)
        self.assertEqual(self.get("/kv/name").status, 404)
        self.assertEqual(self.one_delete("/kv/name").status, 404)

    def one_delete(self, target):
        return one_shot(self.server.port, "DELETE", target)

    def test_204_has_no_body(self):
        one_shot(self.server.port, "PUT", "/kv/k", body=b"v")
        self.assertEqual(self.one_delete("/kv/k").status, 204)

    def test_head_matches_get_length(self):
        one_shot(self.server.port, "PUT", "/kv/k", body=b"12345")
        get = self.get("/kv/k")
        head = one_shot(self.server.port, "HEAD", "/kv/k")
        self.assertEqual(head.body, b"")
        self.assertEqual(head.header("Content-Length"), get.header("Content-Length"))
        self.assertEqual(head.header("content-type"), get.header("content-type"))

    def test_query_parsing_endpoints(self):
        self.assertEqual(self.get("/sum?a=1.5&b=2").text(), "3.5\n")
        self.assertEqual(self.get("/sum").text(), "0\n")
        self.assertEqual(self.get("/sum?a=x&b=2").status, 400)
        self.assertEqual(self.get("/echo?text=a+b%20c").text(), "a b c\n")

    def test_method_not_allowed_and_unknown_method(self):
        r = one_shot(self.server.port, "TRACE", "/kv/k")
        self.assertEqual(r.status, 405)
        self.assertIn("GET", r.header("Allow"))
        r = one_shot(self.server.port, "OPTIONS", "/")
        self.assertEqual(r.status, 501)

    def test_404_and_error_bodies_have_content_type(self):
        r = self.get("/nope")
        self.assertEqual(r.status, 404)
        self.assertTrue(r.header("Content-Type").startswith("text/plain"))

    def test_utf8_body_roundtrip(self):
        value = "宿舍报修-水管漏水".encode()
        one_shot(self.server.port, "PUT", "/kv/%E4%BF%AE", body=value)
        self.assertEqual(self.get("/kv/修").body, value)


class TestKeepAliveAndPipelining(ServerCase):
    def test_reuse_one_connection(self):
        with Connection(port=self.server.port) as c:
            self.assertEqual(c.request("PUT", "/kv/a", body=b"1").status, 201)
            self.assertEqual(c.request("GET", "/kv/a").body, b"1")
            self.assertEqual(c.request("GET", "/kv/a").body, b"1")   # 同一连接再来一次
        self.wait_until(lambda: self.server.stats.open_now == 0,
                        why="客户端已关闭，服务端应发现并回收")
        self.assertEqual(self.server.stats.connections, 1)
        self.assertEqual(self.server.stats.requests, 3)              # 一条连接三个请求

    def test_connection_close_header_ends_connection(self):
        with Connection(port=self.server.port) as c:
            c.request("GET", "/", close=True)
            c.sock.settimeout(0.5)
            self.assertEqual(c.sock.recv(10), b"")     # 服务端主动关

    def test_http10_needs_explicit_keepalive(self):
        with Connection(port=self.server.port) as c:
            # 不写 Connection 头：HTTP/1.0 的默认语义就是发完即关
            c.send(encode_request("GET", "/", version="1.0", close=None))
            first = c.read_response()
            self.assertEqual(first.status, 200)
            self.assertEqual(first.header("Connection"), "close")
            self.assertEqual(c.sock.recv(65536), b"")
        with Connection(port=self.server.port) as c:
            c.send(encode_request("GET", "/", version="1.0",
                                  headers=[("Connection", "keep-alive")]))
            self.assertEqual(c.read_response().status, 200)
            c.send(encode_request("GET", "/kv", version="1.0",
                                  headers=[("Connection", "keep-alive")]))
            self.assertEqual(c.read_response().status, 200)

    def test_pipelined_requests_all_answered(self):
        with Connection(port=self.server.port) as c:
            c.send(encode_request("GET", "/sum?a=1&b=2"))
            c.send(encode_request("GET", "/echo?text=hi"))
            c.send(encode_request("GET", "/stats"))
            self.assertEqual(c.read_response().text(), "3\n")
            self.assertEqual(c.read_response().text(), "hi\n")
            self.assertEqual(c.read_response().status, 200)

    def test_half_packet_then_rest(self):
        with Connection(port=self.server.port) as c:
            data = encode_request("PUT", "/kv/half", body=b"value")
            c.send(data[:7])
            time.sleep(0.05)
            c.send(data[7:])
            self.assertEqual(c.read_response().status, 201)
        self.assertEqual(self.get("/kv/half").body, b"value")

    def get(self, target):
        return one_shot(self.server.port, "GET", target)


class TestServerBoundaries(ServerCase):
    def send_raw_and_read(self, payload: bytes):
        with socket.create_connection(("127.0.0.1", self.server.port), timeout=3) as s:
            s.sendall(payload)
            s.settimeout(3)
            chunks = []
            while True:
                try:
                    got = s.recv(65536)
                except socket.timeout:
                    break
                if not got:
                    break
                chunks.append(got)
                if b"\r\n\r\n" in b"".join(chunks):
                    break
            return b"".join(chunks)

    def status_of(self, head_bytes: bytes) -> int:
        line = head_bytes.split(b"\r\n", 1)[0]
        return int(line.split(b" ")[1])

    def test_413_before_reading_the_whole_body(self):
        # 声明巨大长度但只发头：服务端应在读完头部后就拒绝，不用等体
        out = self.send_raw_and_read(raw(method="POST", target="/kv/big",
                                         headers=[("Content-Length", "999999999")]))
        self.assertEqual(self.status_of(out), 413)

    def test_414_long_uri(self):
        out = self.send_raw_and_read(raw(target="/" + "a" * 3000))
        self.assertEqual(self.status_of(out), 414)

    def test_431_many_headers(self):
        out = self.send_raw_and_read(b"GET / HTTP/1.1\r\n" + b"X: 1\r\n" * 200 + b"\r\n")
        self.assertEqual(self.status_of(out), 431)

    def test_400_bare_lf(self):
        out = self.send_raw_and_read(b"GET / HTTP/1.1\n\n")
        self.assertEqual(self.status_of(out), 400)

    def test_400_conflicting_content_length(self):
        out = self.send_raw_and_read(raw(method="POST", headers=[("Content-Length", "1"),
                                                                 ("Content-Length", "2")],
                                        body=b"ab"))
        self.assertEqual(self.status_of(out), 400)

    def test_501_chunked(self):
        out = self.send_raw_and_read(raw(method="POST",
                                         headers=[("Transfer-Encoding", "chunked")],
                                         body=b"3\r\nabc\r\n0\r\n\r\n"))
        self.assertEqual(self.status_of(out), 501)

    def test_error_explain_cannot_inject_headers(self):
        # 400 的说明文案会进 X-Error 头部，进之前必须压成可见 ASCII
        out = self.send_raw_and_read(b"GET / HTTP/1.1\n\n")
        self.assertEqual(self.status_of(out), 400)
        head = out.split(b"\r\n\r\n")[0]
        self.assertIn(b"X-Error", head)
        for line in head.split(b"\r\n")[1:]:
            self.assertTrue(line.isascii(), f"头部出现非 ASCII：{line!r}")
            self.assertIn(b":", line, f"出现不像头部的行：{line!r}")

    def test_idle_timeout_returns_408_then_closes(self):
        self.server.stop()
        slow = Server(port=0, idle_timeout=0.3)
        slow.start()
        self.addCleanup(slow.stop)
        with socket.create_connection(("127.0.0.1", slow.port), timeout=5) as s:
            s.sendall(b"GET / HTTP/1.1\r\nX: partial")        # 永远不写完
            s.settimeout(5)
            time.sleep(0.1)
            got = s.recv(4096)
            self.assertIn(b"408", got.split(b"\r\n")[0])
            self.assertEqual(s.recv(4096), b"")
        self.assertGreaterEqual(slow.stats.timed_out, 1)

    def test_truncated_then_closed(self):
        with socket.create_connection(("127.0.0.1", self.server.port), timeout=3) as s:
            s.sendall(b"GET / HTTP/1.1\r\nX: 1\r\n")          # 半截头就断开
            s.shutdown(socket.SHUT_WR)
            self.assertEqual(s.recv(10), b"")                 # 服务端安静收尾，不崩
        self.assertEqual(self.get("/").status, 200)

    def get(self, target):
        return one_shot(self.server.port, "GET", target)

    def test_server_survives_garbage(self):
        for payload in (b"\r\n\r\n", b"\x00\x01\x02", b"G", raw(method="BAD\x01METHOD")):
            with self.subTest(payload=payload[:8]):
                try:
                    out = self.send_raw_and_read(payload)
                except (ConnectionResetError, ClientError):
                    continue
                if out:
                    self.assertIn(out[:5], (b"HTTP/", b"HTTP"))
        self.assertEqual(self.get("/").status, 200)
        self.assertGreater(self.server.stats.errors, 0)


class TestMultiplexing(ServerCase):
    def test_two_connections_open_at_once(self):
        a = Connection(port=self.server.port)
        b = Connection(port=self.server.port)
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        a.request("GET", "/")
        b.request("GET", "/kv")
        self.assertEqual(self.server.stats.open_now, 2)
        self.assertGreaterEqual(self.server.stats.peak_open, 2)

    def test_many_concurrent_connections_single_thread(self):
        errors = []

        def worker(i):
            try:
                with Connection(port=self.server.port, timeout=5) as c:
                    for _ in range(3):
                        r = c.request("PUT", f"/kv/k{i}", body=str(i).encode())
                        assert r.status in (200, 201), r.status
                        assert c.request("GET", f"/kv/k{i}").body == str(i).encode()
            except Exception as exc:                     # 线程里的断言要能传出来
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
            self.assertFalse(t.is_alive(), "工作线程卡住了")
        self.assertEqual(errors, [])
        self.assertGreaterEqual(self.server.stats.peak_open, 5)
        self.wait_until(lambda: self.server.stats.open_now == 0,
                        why="10 条连接都该被回收")
        self.assertEqual(len(self.server.store), 10)

    def test_over_connection_limit_gets_503(self):
        self.server.stop()
        small = Server(port=0, max_conn=2)
        small.start()
        self.addCleanup(small.stop)
        held = [Connection(port=small.port) for _ in range(2)]
        for c in held:
            c.request("GET", "/")
        with socket.create_connection(("127.0.0.1", small.port), timeout=3) as extra:
            extra.sendall(raw())
            head = extra.recv(4096)
        self.assertIn(b"503", head.split(b"\r\n")[0])
        self.assertIn(b"Retry-After", head)
        self.assertEqual(small.stats.refused, 1)
        for c in held:
            c.close()
        # 被拒的那条也要能被回收：客户端读完 503 关连接后，服务端不能留着它
        self.wait_until(lambda: small.stats.open_now == 0,
                        why="拒绝的连接没被回收", timeout=3.0)


class TestKeepAliveAccounting(unittest.TestCase):
    """keep-alive 的价值要能被统计看见：一条连接上跑两个请求，连接数不涨。"""

    def test_second_request_reuses_socket(self):
        server = Server(port=0)
        server.start()
        self.addCleanup(server.stop)
        with Connection(port=server.port) as c:
            fileno = c.sock.fileno()
            c.request("GET", "/")
            c.request("GET", "/")
            self.assertEqual(c.sock.fileno(), fileno)
            self.assertEqual(server.stats.connections, 1)
            self.assertEqual(server.stats.requests, 2)


class TestResourceRelease(ServerCase):
    """失败路径不能把资源留在服务端：这是"多路复用"最容易被跳过的一半。"""

    def test_many_short_connections_are_all_released(self):
        for _ in range(150):
            self.assertEqual(one_shot(self.server.port, "GET", "/").status, 200)
        self.wait_until(lambda: self.server.stats.open_now == 0,
                        why="150 条短连接应当全部回收")
        self.assertEqual(self.server.stats.connections, 150)
        self.assertEqual(len(self.server.conns), 0)

    def test_abandoned_connections_reclaimed_by_timeout(self):
        # 客户端连上就再也不说话（slowloris 的最小形态）：靠空闲上限兜底
        self.server.stop()
        quiet = Server(port=0, idle_timeout=0.4)
        quiet.start()
        self.addCleanup(quiet.stop)
        socks = [socket.create_connection(("127.0.0.1", quiet.port), timeout=5)
                 for _ in range(5)]
        for s in socks:
            self.addCleanup(s.close)
            s.settimeout(5)
        self.wait_until(lambda: quiet.stats.open_now == 5, why="五条挂着的连接")
        # 先收到 408，再看到 FIN：超时是"给个交代再收尾"，不是直接掐
        first = socks[0].recv(4096)
        self.assertIn(b"408", first.split(b"\r\n")[0])
        self.assertEqual(socks[0].recv(1), b"", "408 之后应该收到 EOF")
        self.wait_until(lambda: quiet.stats.timed_out >= 5,
                        why="空闲超时该把它们全踢掉", timeout=6.0)
        self.wait_until(lambda: quiet.stats.open_now == 0, why="回收没走完")

    def test_refused_connection_dribbling_bytes_gets_reclaimed(self):
        self.server.stop()
        small = Server(port=0, max_conn=1, idle_timeout=0.6)
        small.start()
        self.addCleanup(small.stop)
        hold = Connection(port=small.port)
        self.addCleanup(hold.close)
        hold.request("GET", "/")
        s = socket.create_connection(("127.0.0.1", small.port), timeout=5)
        self.addCleanup(s.close)
        s.sendall(raw())
        self.assertIn(b"503", s.recv(4096).split(b"\r\n")[0])
        s.settimeout(5)
        try:
            self.assertEqual(s.recv(1), b"", "被拒连接的 503 后面应该收到 EOF")
        except ConnectionError as exc:
            self.fail(f"503 被 RST 冲掉了（{exc}）：拒绝路径又回到 close-with-unread-data")
        for _ in range(3):                     # 对方赖着不走，隔一点时间滴一个字节
            try:
                s.sendall(b" ")
            except OSError:
                break
            time.sleep(0.1)
        # 滴进来的字节不给续命：到空闲上限必须被回收
        self.wait_until(lambda: small.stats.timed_out >= 1,
                        why="被拒连接没被超时回收", timeout=5.0)
        self.wait_until(lambda: small.stats.open_now == 0, timeout=5.0)


class TestDatagramFormat(unittest.TestCase):
    """UDP 只有边界，没有顺序和可靠性：每个包得自己带身份。"""

    def test_roundtrip(self):
        for kind, seq, payload in ((udp.DATA, 0, b""), (udp.DATA, 65535, b"x" * 100),
                                   (udp.ACK, 7, b""), (udp.DATA_END, 3, b"tail")):
            self.assertEqual(udp.decode(udp.encode(kind, seq, payload)),
                             (kind, seq, payload))

    def test_one_bit_flip_is_caught(self):
        for seed in range(40):
            packet = bytearray(udp.encode(udp.DATA, seed % 8, b"payload-%d" % seed))
            packet[seed % len(packet)] ^= 0x01        # 翻一位
            self.assertIsNone(udp.decode(bytes(packet)), f"第 {seed} 个改动没被 crc 抓到")

    def test_truncated_and_unknown_kind(self):
        good = udp.encode(udp.DATA, 1, b"abc")
        for short in (b"", good[:-1], good[:4], good + b"\x00"):
            self.assertIsNone(udp.decode(short), f"畸形包没被拒：{short!r}")
        self.assertIsNone(udp.decode(udp.encode(99, 1, b"")))
        # 头部说长度 5 但只带了 3 字节
        forged = udp.HEADER.pack(udp.DATA, 1, 5) + b"abc"
        forged += udp.CRC.pack(zlib.crc32(forged) & 0xFFFFFFFF)
        self.assertIsNone(udp.decode(forged))

    def test_datagram_boundaries_survive_real_sockets(self):
        """UDP 的"边界"是它跟 TCP 最实在的区别：两次 send 就是两次 recv。"""
        a, b = udp.make_pair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        a.send(b"first")
        a.send(b"second")
        self.assertEqual(b.recv(), b"first")
        self.assertEqual(b.recv(), b"second")


class TestSeqArithmetic(unittest.TestCase):
    def test_wrap_aware_distance(self):
        self.assertEqual(gbn.seq_diff(1, 0, 8), 1)
        self.assertEqual(gbn.seq_diff(0, 7, 8), 1)        # 0 是 7 的下一个
        self.assertEqual(gbn.seq_diff(7, 0, 8), -1)
        self.assertEqual(gbn.seq_diff(1, 7, 8), 2)        # 对折：往前两格
        # 恰好差半个空间时按"超前"处理；正因如此窗口必须 <= space/2，才不会走到歧义点
        self.assertEqual(gbn.seq_diff(4, 0, 8), 4)

    def test_window_must_fit_half_the_sequence_space(self):
        link = udp.SimChannel().endpoints()[0]
        with self.assertRaises(ValueError):
            gbn.Sender(link, b"abc", window=5, seq_space=8)
        gbn.Sender(link, b"abc", window=4, seq_space=8)    # 一半正好允许


class TestSimChannel(unittest.TestCase):
    def test_same_seed_same_fate(self):
        data = b"reproducible"
        fates = []
        for _ in range(2):
            ch = udp.SimChannel(seed=5, drop=0.3, corrupt=0.3, duplicate=0.3,
                                reorder=0.3, jitter=3)
            fates.append([ch.fate(data) for _ in range(50)])
        self.assertEqual(fates[0], fates[1])

    def test_probabilities_actually_happen(self):
        ch = udp.SimChannel(seed=1, drop=0.25, corrupt=0.25, duplicate=0.25, reorder=0.25)
        for _ in range(400):
            ch.send(0, b"payload")
        self.assertGreater(ch.counts["dropped"], 50, "25% 丢包一个都没丢，随机数可疑")
        self.assertGreater(ch.counts["corrupted"], 50)
        self.assertGreater(ch.counts["duplicated"], 50)
        self.assertGreater(ch.counts["reordered"], 50)

    def test_corrupted_packet_differs_by_one_bit(self):
        ch = udp.SimChannel(seed=2, corrupt=1.0)
        original = udp.encode(udp.DATA, 1, b"abcdef")
        copies, _ = ch.fate(original)
        self.assertEqual(len(copies), 1)
        self.assertEqual(sum(a ^ b for a, b in zip(original, copies[0])), 1)

    def test_jitter_can_actually_invert_delivery_order(self):
        """信道必须真能乱序：只看队头的队列会让 jitter 形同虚设，GBN 也就测不到点上。"""
        inverted = False
        for seed in range(1, 40):
            ch = udp.SimChannel(seed=seed, jitter=3)
            ch.send(0, b"A")
            ch.send(0, b"B")
            order = []
            for _ in range(8):
                ch.tick()
                packet = ch.pop(0)
                if packet:
                    order.append(packet)
            if order == [b"B", b"A"]:
                inverted = True
                break
        self.assertTrue(inverted, "40 个 seed 里一次都没乱过序：信道退化成了先进先出队列")

    def test_invalid_parameters_rejected(self):
        for kw in ({"drop": 1.5}, {"corrupt": -0.1}, {"jitter": -1}):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    udp.SimChannel(**kw)


class TestGbnOverSimChannel(unittest.TestCase):
    """GBN 的底线只有一条：拿到的字节必须和发出的逐字节相同，且一次不多一次不少。"""

    def setUp(self):
        self.payload = os.urandom(2048)      # mss=256 → 正好 8 个包
        self.small = os.urandom(200)         # mss=8 → 25 个包，必然绕回序号空间

    def transfer(self, data, *, seed=1, window=8, mss=256, **kwargs):
        channel_kw = {k: kwargs.pop(k) for k in
                      ("drop", "corrupt", "duplicate", "reorder", "jitter")
                      if k in kwargs}
        ch = udp.SimChannel(seed=seed, **channel_kw)
        return gbn.run_simulation(data, ch, mss=mss, window=window, **kwargs)

    def test_clean_channel_no_retransmit(self):
        result = self.transfer(self.payload)
        self.assertTrue(result.finished)
        self.assertEqual(result.received, self.payload)
        self.assertEqual(result.sender.retransmitted, 0)
        self.assertEqual(result.sender.timeouts, 0)
        self.assertAlmostEqual(result.efficiency, 1.0)

    def test_empty_stream_finishes_immediately(self):
        result = self.transfer(b"")
        self.assertTrue(result.finished)
        self.assertEqual(result.received, b"")
        self.assertEqual(result.slots, 0)

    def test_every_impairment_still_delivers_exactly(self):
        scenarios = [
            ("丢包", {"drop": 0.35}),
            ("损坏", {"corrupt": 0.35}),
            ("重复", {"duplicate": 0.35}),
            ("乱序", {"reorder": 0.4, "jitter": 2}),
            ("全叠加", {"drop": 0.2, "corrupt": 0.2, "duplicate": 0.2, "reorder": 0.2}),
            ("窗口只剩 1", {"drop": 0.3}),
        ]
        for name, kwargs in scenarios:
            for seed in (1, 2, 3):
                with self.subTest(scenario=name, seed=seed):
                    result = self.transfer(self.payload, seed=seed,
                                           window=1 if name.startswith("窗口") else 8,
                                           **kwargs)
                    self.assertTrue(result.finished, result.summary())
                    self.assertEqual(result.received, self.payload, result.summary())
                    # 每个包只交付一次：窗口=1 时 8 个包也要绕一轮序号
                    self.assertEqual(result.receiver.delivered, 8, result.summary())

    def test_no_duplicate_delivery_under_duplicates(self):
        result = self.transfer(self.payload, duplicate=0.5, seed=9)
        self.assertEqual(result.received, self.payload)
        self.assertGreater(result.receiver.duplicates, 0, "这轮没触发重复，测不到点上")

    def test_out_of_order_is_dropped_not_buffered(self):
        """GBN 不重排：超前的包直接丢，靠发送方整窗重传把它带回来。"""
        result = self.transfer(self.payload, reorder=0.6, jitter=3, seed=4)
        self.assertEqual(result.received, self.payload)
        self.assertGreater(result.receiver.out_of_order, 0)
        self.assertGreaterEqual(result.sender.timeouts, 1, "超前包应由超时重传补救")

    def test_sequence_numbers_wrap_around(self):
        """序号空间只有 8，25 个包必须绕三轮，绕回来还得是对的。"""
        for drop in (0.0, 0.2, 0.4):
            with self.subTest(drop=drop):
                result = self.transfer(self.small, seed=17, window=4,
                                       mss=8, seq_space=8, drop=drop)
                self.assertTrue(result.finished, result.summary())
                self.assertEqual(result.received, self.small, result.summary())
                self.assertEqual(result.receiver.delivered, 25)

    def test_total_loss_stops_at_deadline_instead_of_looping(self):
        result = self.transfer(self.payload, drop=1.0, max_slots=50)
        self.assertFalse(result.finished)
        self.assertEqual(result.slots, 50)
        self.assertGreater(result.sender.transmitted, 0)

    def test_bigger_window_finishes_faster_on_a_lossy_link(self):
        """窗口的意义：丢一个包不必等整条链停住。同 seed、同丢包率下比时隙。"""
        slots = {}
        for window in (1, 2, 4, 8):
            result = self.transfer(b"g" * 8192, seed=42, window=window, drop=0.2)
            self.assertTrue(result.finished, result.summary())
            slots[window] = result.slots
        self.assertLess(slots[2], slots[1], f"窗口 2 应该比 1 快：{slots}")
        self.assertLess(slots[8], slots[1], f"窗口 8 应该比 1 快：{slots}")

    def test_retransmission_cost_grows_with_loss(self):
        low = self.transfer(self.payload, seed=8, drop=0.05)
        high = self.transfer(self.payload, seed=8, drop=0.4)
        self.assertGreater(high.sender.transmitted, low.sender.transmitted * 1.5,
                           f"40% 丢包应该明显更贵：{low.sender.transmitted} vs "
                           f"{high.sender.transmitted}")


class TestGbnOverRealUdp(unittest.TestCase):
    """同一段 GBN 代码搬到 127.0.0.1 的真 UDP 上，也必须一个字节都不差。"""

    def send_and_receive(self, payload: bytes, **sender_kw) -> gbn.Receiver:
        a, b = udp.make_pair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        box = {}
        receiver = threading.Thread(
            target=lambda: box.update(r=gbn.run_real_receiver(b, deadline=20)))
        receiver.start()
        sender = gbn.run_real_sender(a, payload, deadline=20, **sender_kw)
        receiver.join(25)
        self.assertFalse(receiver.is_alive(), "接收线程没结束")
        self.assertTrue(sender.done(), "发送方没等到全部确认")
        return box["r"]

    def test_exact_delivery_over_loopback(self):
        payload = os.urandom(30000)
        receiver = self.send_and_receive(payload, timeout=0.4, window=8, mss=1024)
        self.assertTrue(receiver.finished)
        self.assertEqual(bytes(receiver.received), payload)
        self.assertGreaterEqual(receiver.delivered, 30)

    def test_many_small_datagrams(self):
        payload = bytes(range(256)) * 40          # 10240 字节，全部非空小包
        receiver = self.send_and_receive(payload, timeout=0.3, window=4, mss=64)
        self.assertEqual(bytes(receiver.received), payload)

    def test_receiver_stops_only_at_the_end_marker(self):
        receiver = self.send_and_receive(b"tail?" * 100, timeout=0.4, window=3, mss=128)
        self.assertTrue(receiver.finished, "没收到 DATA_END 就结束说明终止条件不成立")


if __name__ == "__main__":
    unittest.main(verbosity=2)
