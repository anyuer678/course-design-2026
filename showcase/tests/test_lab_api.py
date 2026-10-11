"""showcase/tests/test_lab_api.py —— 实验台控制 API 的 Origin 门回归（2026-10-08 加固）。

背景：/lab/api/* 能起停真实服务、发原始字节，而 _body() 不看 Content-Type——
此前 ACAO:* + 无来源校验意味着任意网页可用 text/plain 简单请求（免 preflight）
跨站驱动本机服务。加固后按来源放行：无 Origin（脚本）、null（file://）、与 Host
同源（浏览器控制台）；其余跨站 POST 一律 403，且 CORS 头只镜像允许来源。

测试方式：真套接字起 Handler（ThreadingHTTPServer + lab.Handler），精确控制
Origin/Host 头逐例验证。选 /lab/api/stop + 未知项目号做探针：无副作用、语义稳定。
"""
from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from showcase import lab as lab_mod                       # noqa: E402


def _free_port(start: int) -> int:
    import socket
    port = start
    while port < start + 50:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            port += 1
            continue
        except OSError:
            return port
    raise RuntimeError("no free port")


class LabApiOriginGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port(17888)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), lab_mod.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.server_close()

    def post(self, origin: str | None) -> tuple[int, dict, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "text/plain"}       # 恶意网页的免 preflight 形态
        if origin is not None:
            headers["Origin"] = origin
        conn.request("POST", "/lab/api/stop",
                     body=json.dumps({"project": "no-such-project"}).encode(),
                     headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, data, hdrs

    def get(self, origin: str | None) -> tuple[int, dict, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Origin": origin} if origin is not None else {}
        conn.request("GET", "/lab/api/ping", headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, data, hdrs

    # ------------------------------------------------ POST 门：放行三类合法来源
    def test_post_without_origin_is_script_semantics(self):
        status, data, hdrs = self.post(None)
        self.assertEqual(status, 200)
        self.assertNotIn("access-control-allow-origin", hdrs)

    def test_post_null_origin_is_file_page(self):
        status, data, hdrs = self.post("null")
        self.assertEqual(status, 200)
        self.assertEqual(hdrs.get("access-control-allow-origin"), "null")

    def test_post_same_origin_is_console(self):
        origin = f"http://127.0.0.1:{self.port}"
        status, data, hdrs = self.post(origin)
        self.assertEqual(status, 200)
        self.assertEqual(hdrs.get("access-control-allow-origin"), origin)

    def test_post_localhost_alias_same_host_header(self):
        # Host 头由测试自己控制：Origin 与 Host 一致即同源（与连接用的 IP 无关）
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/lab/api/stop",
                     body=json.dumps({"project": "no-such-project"}).encode(),
                     headers={"Content-Type": "text/plain",
                              "Host": f"localhost:{self.port}",
                              "Origin": f"http://localhost:{self.port}"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)

    # ------------------------------------------------ POST 门：跨站拒绝
    def test_post_cross_site_origin_403(self):
        status, data, hdrs = self.post("http://evil.example")
        self.assertEqual(status, 403)
        self.assertIn("Origin", data.get("error", ""))
        self.assertNotIn("access-control-allow-origin", hdrs)

    def test_post_ftp_scheme_origin_403(self):
        status, _, _ = self.post(f"ftp://127.0.0.1:{self.port}")
        self.assertEqual(status, 403)

    # ------------------------------------------------ GET 读不设门但 CORS 收紧
    def test_get_served_but_unreadable_cross_site(self):
        status, data, hdrs = self.get("http://evil.example")
        self.assertEqual(status, 200)                       # GET 不设门（只读）
        self.assertEqual(data.get("hub"), "showcase-lab")
        self.assertNotIn("access-control-allow-origin", hdrs)   # 跨站读不到

    def test_get_null_origin_still_gets_cors(self):
        status, data, hdrs = self.get("null")
        self.assertEqual(status, 200)
        self.assertEqual(hdrs.get("access-control-allow-origin"), "null")

    # ------------------------------------------------ 预检：跨站拿不到放行头
    def test_options_preflight_cross_site_gets_no_acao(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("OPTIONS", "/lab/api/stop",
                     headers={"Origin": "http://evil.example",
                              "Access-Control-Request-Method": "POST"})
        resp = conn.getresponse()
        resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        self.assertNotIn("access-control-allow-origin", hdrs)


if __name__ == "__main__":
    unittest.main()
