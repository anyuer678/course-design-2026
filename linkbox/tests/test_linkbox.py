"""LinkBox M2 自测：M1 全量回归 + 访问口令 + 二维码 + 真套接字。

期望值出处：状态码映射是本产品写进 README 的口径（404 不存在 / 410 已过期 /
400 内容不合法 / 401 设口令的暂存缺口令或口令不对 / 413 超长）；
口令只存 PBKDF2（OWASP 口径），校验用恒时比较；二维码编码查看页 URL。
XSS 转义是 B32 的教训落地：用户内容必须逃逸后才能进 HTML。
"""
import http.client
import json
import sqlite3
import sys
import tempfile
import unittest
import urllib.parse
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
from linkbox.files import (MAX_FILE_BYTES, FileError,        # noqa: E402
                           FileGone, FileStore, content_disposition,
                           safe_name)
from linkbox.qr import qr_svg                                # noqa: E402
from linkbox.stash import (MAX_CONTENT, StashError,          # noqa: E402
                           StashStore)


class FakeRequest:
    def __init__(self, method, path, body=b"", headers=None):
        self.method = method
        self.target = path                       # 原始目标（含查询串）
        clean, _, raw_query = path.partition("?")
        self.path = clean
        # 与 netlab 同口径：+ 归空格、%xx 解码、值可缺省
        self.query = urllib.parse.parse_qsl(raw_query, keep_blank_values=True)
        self.body = body
        # 与 netlab 同口径：头名一律小写（header() 的查找键也是小写）
        self.headers = [(k.lower(), v) for k, v in list(headers or [])]
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
        self.files = FileStore(":memory:")
        self.app = LinkBoxApp(Store(), ROOT / "web", stash=self.stash,
                              files=self.files, clock=lambda: self.now)

    def request(self, method, path, payload=None, raw=None, headers=None):
        body = raw if raw is not None else (
            json.dumps(payload).encode("utf-8") if payload is not None else b"")
        if body and headers is None:
            headers = [("Content-Type", "application/json")]
        req = FakeRequest(method, path, body, headers)
        clean = path.partition("?")[0]
        if path == "/api/stash" and method == "POST":
            return self.app.create_stash(req)
        if clean.startswith("/api/stash/") and method == "GET":
            return self.app.stash_api(req)
        if clean.startswith("/api/stash/") and method == "DELETE":
            return self.app.delete_stash(req)
        if clean.endswith("/qr.svg") and clean.startswith("/s/") and method == "GET":
            return self.app.stash_qr(req)
        if clean.startswith("/s/") and method == "GET":
            return self.app.stash_page(req)
        if clean.startswith("/s/") and method == "POST":
            return self.app.stash_page_post(req)
        if clean == "/api/files" and method == "POST":
            return self.app.create_file(req)
        if clean.startswith("/api/files/") and method in ("GET", "DELETE"):
            return self.app.file_api(req)
        if clean.endswith("/qr.svg") and clean.startswith("/f/") and method == "GET":
            return self.app.file_qr(req)
        if clean.startswith("/f/") and method in ("GET", "HEAD"):
            return self.app.file_download(req)
        if clean.startswith("/f/") and method == "POST":
            return self.app.file_download_post(req)
        if path == "/api/links" and method == "POST":
            return self.app.create_link(req)
        if path.startswith("/l/") and method == "GET":
            return self.app.redirect(req)
        if path == "/" and method == "GET":
            return self.app.index(req)
        raise AssertionError(f"测试路由未覆盖: {method} {path}")

    def make_stash(self, payload=None, **kwargs):
        payload = {"content": "hello\nworld", **(payload or {}), **kwargs}
        status, _, body = self.request("POST", "/api/stash", payload)
        assert status == 201, body
        return json.loads(body)

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

    # ------------------------------------------------ 访问口令（M2）
    def test_passcode_api_flow(self):
        """设口令的暂存：API 缺口令/错口令都 401，对口令才放行；
        创建响应只报 protected 布尔，不回显口令。"""
        info = self.make_stash({"content": "机密"}, passcode="secret1")
        self.assertTrue(info["protected"])
        status, _, body = self.request("GET", f"/api/stash/{info['code']}")
        self.assertEqual(status, 401)
        self.assertIn("口令", body.decode("utf-8"))
        status, _, _ = self.request(
            "GET", f"/api/stash/{info['code']}?passcode=wrong")
        self.assertEqual(status, 401)
        status, _, body = self.request(
            "GET", f"/api/stash/{info['code']}?passcode=secret1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["content"], "机密")

    def test_passcode_page_flow(self):
        """页面侧：缺口令/错口令给 200 表单页（不出内容），口令对才见正文+二维码。
        页面是给人看的：200 + 表单是浏览器友好的重试路径，API 侧才是 401。"""
        info = self.make_stash({"content": "白板内容"}, passcode="secret1")
        code = info["code"]
        status, _, page = self.request("GET", f"/s/{code}")
        self.assertEqual(status, 200)
        page = page.decode("utf-8")
        self.assertIn("设有访问口令", page)
        self.assertIn("<form", page)
        self.assertNotIn("白板内容", page)          # 锁着时不漏内容
        status, _, page = self.request("GET", f"/s/{code}?passcode=wrong")
        self.assertIn("口令不正确", page.decode("utf-8"))
        status, _, page = self.request("GET", f"/s/{code}?passcode=secret1")
        self.assertEqual(status, 200)
        page = page.decode("utf-8")
        self.assertIn("白板内容", page)
        self.assertIn("<svg", page)                 # 内联二维码
        self.assertNotIn("口令不正确", page)

    def test_passcode_validation(self):
        """口令类型/长度校验 → 400（与 content/ttl 同一套 StashError 口径）。"""
        cases = [
            {"content": "ok", "passcode": ""},               # 空：要设就设非空
            {"content": "ok", "passcode": 123},              # 非字符串
            {"content": "ok", "passcode": "x" * 129},        # 超长
        ]
        for payload in cases:
            status, _, _ = self.request("POST", "/api/stash", payload)
            self.assertEqual(status, 400, msg=payload)

    def test_delete_passcode_stash(self):
        """删除设口令的暂存也要口令；M1 语义保持：过期行删除照样 204。"""
        info = self.make_stash({"content": "bye"}, passcode="secret1")
        code = info["code"]
        status, _, _ = self.request("DELETE", f"/api/stash/{code}")
        self.assertEqual(status, 401)
        status, _, _ = self.request(
            "DELETE", f"/api/stash/{code}?passcode=secret1")
        self.assertEqual(status, 204)
        status, _, _ = self.request("GET", f"/api/stash/{code}")
        self.assertEqual(status, 404)

    def test_plain_stash_needs_no_passcode(self):
        """M1 回归：不设口令的暂存不带 passcode 直接可读。"""
        info = self.make_stash({"content": "plain"})
        self.assertFalse(info["protected"])
        status, _, body = self.request("GET", f"/api/stash/{info['code']}")
        self.assertEqual(status, 200)

    def test_expired_passcode_stash_still_410(self):
        """判定次序 404 -> 410 -> 401：过期状态不因口令隐藏。"""
        info = self.make_stash({"content": "gone"}, ttl_hours=1,
                               passcode="secret1")
        self.now += 2 * 3600
        status, _, body = self.request("GET", f"/api/stash/{info['code']}")
        self.assertEqual(status, 410)
        self.assertEqual(self.stash.count(), 0)      # 惰性删除不因口令失效

    # ------------------------------------------------ 二维码（M2）
    def test_qr_route_encodes_view_url(self):
        """/s/<码>/qr.svg 是独立 SVG；无 Host 头时按 B31 口径回退 127.0.0.1。"""
        info = self.make_stash({"content": "scan me"})
        code = info["code"]
        status, headers, body = self.request("GET", f"/s/{code}/qr.svg")
        self.assertEqual(status, 200)
        ctype = dict(headers)["Content-Type"]
        self.assertEqual(ctype, "image/svg+xml")
        want = qr_svg(f"http://127.0.0.1/s/{code}")
        self.assertEqual(body.decode("utf-8"), want)   # 确定性：同一 URL 同一 SVG

    def test_qr_route_uses_host_header(self):
        """Host 头拼装查看页绝对 URL（手机同网段访问的正是这个地址）。"""
        info = self.make_stash({"content": "scan me"})
        code = info["code"]
        status, _, body = self.request(
            "GET", f"/s/{code}/qr.svg",
            headers=[("Host", "192.168.1.7:8018")])
        self.assertEqual(status, 200)
        self.assertEqual(body.decode("utf-8"),
                         qr_svg(f"http://192.168.1.7:8018/s/{code}"))

    def test_qr_route_unknown_code_404(self):
        status, _, _ = self.request("GET", "/s/zzzzzz/qr.svg")
        self.assertEqual(status, 404)

    # ------------------------------------------------ M3：POST 口令表单
    def test_post_passcode_form_flow(self):
        """表单页是 method=post；口令走请求体不进 URL；类型不对 415。"""
        info = self.make_stash({"content": "白板内容"}, passcode="secret1")
        code = info["code"]
        status, _, page = self.request("GET", f"/s/{code}")
        self.assertIn('method="post"', page.decode("utf-8"))
        # POST 错口令 -> 表单页 + 提示，不出内容
        status, _, page = self.request(
            "POST", f"/s/{code}", raw=b"passcode=wrong",
            headers=[("Content-Type", "application/x-www-form-urlencoded")])
        self.assertEqual(status, 200)
        page = page.decode("utf-8")
        self.assertIn("口令不正确", page)
        self.assertNotIn("白板内容", page)
        # POST 对口令 -> 解锁
        status, _, page = self.request(
            "POST", f"/s/{code}", raw=b"passcode=secret1",
            headers=[("Content-Type", "application/x-www-form-urlencoded")])
        self.assertEqual(status, 200)
        self.assertIn("白板内容", page.decode("utf-8"))
        # Content-Type 不对 -> 415
        status, _, _ = self.request(
            "POST", f"/s/{code}", raw=b"passcode=secret1",
            headers=[("Content-Type", "application/json")])
        self.assertEqual(status, 415)

    # ------------------------------------------------ M3：过期清扫
    def test_sweep_deletes_only_expired(self):
        """sweep 删光过期行、未过期的不动；再扫一轮 0 条。"""
        self.make_stash({"content": "short", "ttl_hours": 1})
        self.make_stash({"content": "long-a"})
        self.make_stash({"content": "long-b"})
        self.now += 2 * 3600                        # 越过短命那条
        n = self.stash.sweep(now=self.now)
        self.assertEqual(n, 1)
        self.assertEqual(self.stash.count(), 2)
        self.assertEqual(self.stash.sweep(now=self.now), 0)  # 再扫无活干

    def test_sweeper_thread_reports_and_cleans(self):
        """真线程（50ms 一轮）：到点清扫、上报条数、停止可退。"""
        import time
        from linkbox.sweeper import StashSweeper
        stash = StashStore(":memory:")
        stash.create("dying", ttl_hours=0.01, now=1.0)   # 36 秒后过期
        reports = []
        sweeper = StashSweeper(stash, interval=0.05, clock=lambda: 100.0,
                               report=reports.append)
        sweeper.start()
        deadline = time.time() + 2
        while not reports and time.time() < deadline:
            time.sleep(0.02)
        sweeper.stop()
        self.assertTrue(any("1 条" in r for r in reports), reports)
        self.assertEqual(sweeper.cleaned, 1)
        self.assertEqual(stash.count(), 0)

    # ------------------------------------------------ 存储层：老库迁移
    def test_migration_from_old_schema(self):
        """M1 老库（无口令两列）打开即迁移：老行可读（无口令），新能力可用。"""
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "old.sqlite"
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE stashes (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "code TEXT UNIQUE, content TEXT NOT NULL, created_at REAL NOT NULL, "
                "expires_at REAL NOT NULL)")
            conn.execute("INSERT INTO stashes (code, content, created_at, expires_at) "
                         "VALUES ('abc', 'old row', 0, 9e18)")
            conn.commit()
            conn.close()
            store = StashStore(db)
            try:
                rec = store.get("abc", now=1.0)
                self.assertIsNotNone(rec)
                self.assertFalse(rec.has_passcode)
                new = store.create("new row", now=1.0, passcode="pw")
                self.assertTrue(new.has_passcode)
                self.assertTrue(store.verify_passcode(new.code, "pw"))
            finally:
                store.conn.close()

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

    # ------------------------------------------------ 文件暂存（轮八）
    def make_file(self, data=b"hello file", name="note.txt", **kw):
        """上传一个文件，返回创建响应 JSON。raw 字节走 ?name=&ttl=&passcode=。"""
        qs = "?name=" + urllib.parse.quote(name)
        if "ttl_hours" in kw:
            qs += "&ttl_hours=" + urllib.parse.quote(str(kw.pop("ttl_hours")))
        if "passcode" in kw:
            qs += "&passcode=" + urllib.parse.quote(kw.pop("passcode"))
        assert not kw, f"未消化的参数：{kw}"
        status, _, body = self.request("POST", "/api/files" + qs,
                                       raw=data, headers=[])
        assert status == 201, body
        return json.loads(body)

    def test_file_roundtrip_bytes_identical(self):
        """上传即下载：字节逐位一致、文件名与大小如实、头是 attachment。"""
        payload = bytes(range(256)) * 5
        info = self.make_file(payload, name="相册 照片.png")
        self.assertTrue(info["code"])
        self.assertEqual(info["name"], "相册 照片.png")
        self.assertEqual(info["size"], len(payload))
        self.assertFalse(info["protected"])
        status, headers, body = self.request("GET", f"/f/{info['code']}")
        self.assertEqual(status, 200)
        self.assertEqual(body, payload)          # 逐位一致
        hd = {k.lower(): v for k, v in headers}
        self.assertTrue(hd["content-disposition"].startswith("attachment"))
        self.assertIn("filename*=UTF-8''", hd["content-disposition"])
        self.assertEqual(hd["content-type"], "application/octet-stream")

    def test_file_meta_api_and_delete(self):
        info = self.make_file(b"data", name="a.bin")
        status, _, body = self.request("GET", f"/api/files/{info['code']}")
        self.assertEqual(status, 200)
        meta = json.loads(body)
        self.assertEqual((meta["name"], meta["size"]), ("a.bin", 4))
        self.assertNotIn("content", meta)        # 元数据接口不给字节
        status, _, _ = self.request("DELETE", f"/api/files/{info['code']}")
        self.assertEqual(status, 204)
        status, _, _ = self.request("GET", f"/f/{info['code']}")
        self.assertEqual(status, 404)

    def test_file_empty_and_bad_ttl_400(self):
        status, _, _ = self.request("POST", "/api/files?name=x", raw=b"",
                                    headers=[])
        self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/api/files?name=x&ttl_hours=0",
                                    raw=b"x", headers=[])
        self.assertEqual(status, 400)

    def test_file_expiry_410_and_blob_gone(self):
        """落盘版惰性过期：行删了、盘上字节也必须删掉。"""
        with tempfile.TemporaryDirectory() as td:
            store = FileStore(Path(td) / "files.sqlite")
            try:
                rec = store.create(b"soon gone", "x.txt", ttl_hours=1, now=self.now)
                blob = Path(td) / "files" / f"{rec.code}.bin"
                self.assertTrue(blob.exists())
                self.now += 2 * 3600
                with self.assertRaises(FileGone):
                    store.get(rec.code, now=self.now)
                self.assertFalse(blob.exists())   # 盘上清干净
                self.assertEqual(store.count(), 0)
            finally:
                store.conn.close()

    def test_file_passcode_flow(self):
        """口令门三态：无口令出表单、错口令出表单（带提示）、对口令放行字节。"""
        info = self.make_file(b"secret file", name="s.txt", passcode="pw123")
        self.assertTrue(info["protected"])
        status, _, body = self.request("GET", f"/f/{info['code']}")
        self.assertEqual(status, 200)            # 表单页（不是 401：页面侧走表单）
        self.assertIn("访问口令", body.decode("utf-8"))
        status, _, body = self.request(
            "GET", f"/f/{info['code']}?passcode=wrong")
        self.assertEqual(status, 200)
        self.assertIn("口令不正确", body.decode("utf-8"))
        status, _, body = self.request(
            "GET", f"/f/{info['code']}?passcode=pw123")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"secret file")
        # 表单 POST：口令不进 URL，成功即下载
        status, _, body = self.request(
            "POST", f"/f/{info['code']}", raw=b"passcode=pw123",
            headers=[("Content-Type", "application/x-www-form-urlencoded")])
        self.assertEqual(status, 200)
        self.assertEqual(body, b"secret file")
        # API 侧保持 401 口径
        status, _, body = self.request("GET", f"/api/files/{info['code']}")
        self.assertEqual(status, 401)

    def test_file_qr_encodes_download_url(self):
        info = self.make_file(b"qr", name="q.txt")
        status, _, body = self.request("GET", f"/f/{info['code']}/qr.svg")
        self.assertEqual(status, 200)
        self.assertEqual(body.decode("utf-8"),
                         qr_svg(f"http://127.0.0.1/f/{info['code']}"))
        self.assertNotIn("passcode", body.decode("utf-8"))  # 口令永不进二维码

    def test_safe_name_strips_path_and_controls(self):
        """文件名只是元数据：路径成分/控制字符全剥掉，中文保留。"""
        self.assertEqual(safe_name("../evil/..\\name.txt"), "name.txt")
        self.assertEqual(safe_name("..hidden"), "hidden")
        self.assertEqual(safe_name("报告 最终版.docx"), "报告 最终版.docx")
        self.assertEqual(safe_name("a\x00b/c:d*e?.txt"), "c_d_e_.txt")
        self.assertEqual(safe_name(""), "file.bin")
        self.assertEqual(safe_name("...."), "file.bin")
        self.assertEqual(len(safe_name("x" * 500)), 120)

    def test_content_disposition_rfc5987(self):
        hd = content_disposition("报告.docx")
        self.assertTrue(hd.startswith("attachment; filename=\""))
        self.assertIn("filename*=UTF-8''%E6%8A%A5%E5%91%8A.docx", hd)

    def test_file_store_rejects_oversize(self):
        with self.assertRaises(FileError):
            self.files.create(b"x" * (MAX_FILE_BYTES + 1), "big.bin",
                              now=self.now)

    def test_file_sweep_removes_rows_and_blobs(self):
        with tempfile.TemporaryDirectory() as td:
            store = FileStore(Path(td) / "files.sqlite")
            try:
                gone = store.create(b"short", "s.txt", ttl_hours=1, now=self.now)
                keep = store.create(b"long", "l.txt", now=self.now)
                blob = Path(td) / "files" / f"{gone.code}.bin"
                self.assertTrue(blob.exists())
                self.now += 2 * 3600
                self.assertEqual(store.sweep(now=self.now), 1)
                self.assertFalse(blob.exists())   # 过期文件连盘一起清
                self.assertEqual(store.count(), 1)
                self.assertEqual(store.read(keep.code), b"long")
            finally:
                store.conn.close()

    def test_file_error_is_valueerror_subclass(self):
        self.assertTrue(issubclass(FileError, ValueError))


# ---------------------------------------------------------------- 真套接字
class LinkBoxServer:
    """组合 LinkBoxApp 与 B31 服务器（同构于 B31 的 build_server）。
    轮八：装配文件暂存，并把传输层 max_body 放宽到文件上限（与 server.py 同口径）。"""

    def __init__(self, *, db_path=":memory:", stash_path=":memory:",
                 files_path=":memory:", port=0):
        from b31.server import ShortUrlServer
        store = Store(db_path)
        stash = StashStore(stash_path)
        files = FileStore(files_path)
        self.app = LinkBoxApp(store, ROOT / "web", stash=stash, files=files)
        self.server = ShortUrlServer(self.app, port=port,
                                     max_body=MAX_FILE_BYTES + 4096)

    def start(self) -> int:
        return self.server.start()

    def stop(self) -> None:
        self.server.stop()
        self.app.store.close()
        self.app.stash.conn.close()
        self.app.files.conn.close()


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

    def test_shared_assets_over_real_socket(self):
        """共享资产走真协议栈：产品页 <link assets/kb.css> 必须拿到样式——
        曾因 B31 静态白名单没有 /assets/ 路由而整页 404 裸样式
        （2026-10-07 无头浏览器实测抓出）。边界行为按惯例每步一条新连接。"""
        def talk(target):
            conn = http.client.HTTPConnection("127.0.0.1", self.port)
            conn.request("GET", target)
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            return resp.status, resp.getheader("Content-Type"), body

        status, ctype, body = talk("/assets/kb.css")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "text/css; charset=utf-8")
        self.assertGreater(len(body), 500)
        self.assertIn(b"--", body)          # token 文件必含自定义属性
        self.assertEqual(talk("/assets/not-exist.css")[0], 404)
        # `..` 上跳被 netlab 协议层挡死（http1 §安全），到不了 read_static
        self.assertEqual(talk("/assets/../app.js")[0], 400)

    def test_file_over_real_socket(self):
        """文件链路走真协议栈：1 MiB 二进制上传→下载逐位一致——
        专门钉住"传输层 max_body 已放宽"这件事（netlab 默认 1 MiB 会 413）。"""
        payload = bytes(range(256)) * 4096        # 恰好 1 MiB
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/files?name=bin.dat&ttl_hours=1",
                     body=payload, headers={"Content-Type": "application/octet-stream"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 201)
        code = json.loads(resp.read())["code"]
        conn.request("GET", f"/f/{code}")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.read(), payload)
        self.assertTrue(resp.getheader("Content-Disposition").startswith("attachment"))
        conn.close()

    def test_passcode_over_real_socket(self):
        """口令链路走真协议栈：netlab 的查询串解码（+ 归空格、%xx）必须
        把 'ab+cd%2Fef' 还原成 'ab cd/ef'，否则校验过不去。
        每步一条新连接：这里验的是状态码与解码口径，不绑 keep-alive 行为。"""
        def talk(method, target, body=None, ctype="application/json"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port)
            conn.request(method, target, body=body,
                         headers={"Content-Type": ctype} if body
                         else {"Host": "127.0.0.1"})
            resp = conn.getresponse()
            payload = resp.read()
            conn.close()
            return resp.status, payload

        status, payload = talk(
            "POST", "/api/stash",
            json.dumps({"content": "locked",
                        "passcode": "ab cd/ef"}).encode())
        self.assertEqual(status, 201)
        code = json.loads(payload)["code"]
        self.assertEqual(talk("GET", f"/api/stash/{code}")[0], 401)
        self.assertEqual(
            talk("GET", f"/api/stash/{code}?passcode=wrong")[0], 401)
        status, payload = talk(
            "GET", f"/api/stash/{code}?passcode=ab+cd%2Fef")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["content"], "locked")
        status, payload = talk("GET", f"/s/{code}/qr.svg")
        self.assertEqual(status, 200)
        self.assertTrue(payload.startswith(b"<svg"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
