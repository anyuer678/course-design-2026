"""B31 的测试：单元（不碰 socket）+ 集成（真回环，客户端用 B11 的 netlab 与标准库）。

跑法：
    python -m unittest discover -s tests -v
    pytest tests -q
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import b31                                              # noqa: E402,F401  首飞装 netlab 路径，不然后两行 import 不到
from netlab.client import Connection, encode_request    # noqa: E402
from netlab.http1 import Request                        # noqa: E402

from b31 import codec, urls                             # noqa: E402
from b31 import store as store_module                   # noqa: E402
from b31.app import MAX_BODY_BYTES, ShortUrlApp         # noqa: E402
from b31.server import WEB_ROOT, build_server           # noqa: E402
from b31.store import (AliasError, CapacityError, ConflictError,       # noqa: E402
                       MAX_LINKS, Store)


def wait_until(predicate, timeout=3.0, interval=0.02):
    """等一个服务端侧的异步状态成立。计数器由事件循环线程更新，主线程不能假定它已就位。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def make_request(method="GET", path="/", *, target=None, query=None, headers=None, body=b""):
    """造一个 netlab 的 Request 对象：单元层不需要 socket，也不需要解析器。"""
    return Request(method=method, target=target or path, version="1.1",
                   headers=[(k.lower(), v) for k, v in (headers or [])], body=body,
                   path=path, query=query or [], keep_alive=True, content_length=len(body))


class Clock:
    def __init__(self, start=1_700_000_000.0):
        self.now = start

    def __call__(self):
        self.now += 1.0
        return self.now


class AppCase(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.app = ShortUrlApp(self.store, WEB_ROOT, self_hosts=("127.0.0.1", "localhost"),
                               clock=Clock())
        self.app.port = 8000

    def tearDown(self):
        self.store.close()

    def create(self, url, alias=None, **headers):
        payload = {"url": url}
        if alias is not None:
            payload["alias"] = alias
        hdrs = [("Content-Type", "application/json"), ("Host", "127.0.0.1:8000")]
        hdrs.extend((k, v) for k, v in headers.items())
        return self.app.create_link(make_request("POST", "/api/links",
                                                 headers=hdrs, body=json.dumps(payload).encode()))


class TestCodec(unittest.TestCase):
    def test_roundtrip_over_thresholds(self):
        """阈值取自字母表本身：1 位到 61、2 位从 62 开始、上限编码成 11 位。"""
        self.assertEqual(codec.encode_id(0), "0")
        self.assertEqual(codec.encode_id(61), "z")
        self.assertEqual(codec.encode_id(62), "10")
        self.assertEqual(len(codec.encode_id(codec.MAX_ID)), codec.MAX_CODE_LEN)
        for n in list(range(0, 200)) + [10 ** k for k in range(1, 18)] + [codec.MAX_ID]:
            self.assertEqual(codec.decode_code(codec.encode_id(n)), n, n)

    def test_rejects_non_canonical_and_illegal(self):
        for bad in ["", "00", "0z", "0000000000000", "a-b", "a b", "あ", "z" * 12]:
            with self.subTest(code=bad):
                with self.assertRaises(codec.CodecError):
                    codec.decode_code(bad)
        self.assertEqual(codec.decode_code("0"), 0)

    def test_ids_out_of_range(self):
        for bad in (-1, codec.MAX_ID + 1, True, "1"):
            with self.subTest(n=bad):
                with self.assertRaises(codec.CodecError):
                    codec.encode_id(bad)

    def test_alias_shape_is_charset_only(self):
        """别名允许前导零：它是用户挑的字面串，不是整数的写法。"""
        self.assertTrue(codec.is_code_shape("007"))
        self.assertFalse(codec.is_code_shape("007!"))
        self.assertFalse(codec.is_code_shape(""))
        self.assertFalse(codec.is_code_shape("a" * (codec.MAX_CODE_LEN + 1)))


class TestUrlValidation(unittest.TestCase):
    """每条期望的出处写在注释里：RFC 3986 / RFC 1123 / 标准库实测行为。"""

    def accept(self, raw, expected=None, **kw):
        got = urls.normalize_target(raw, **kw)
        self.assertEqual(got, expected if expected is not None else raw, raw)
        self.assertTrue(got.isascii() and all(0x20 <= ord(c) <= 0x7E for c in got), got)
        return got

    def reject(self, raw, keyword, **kw):
        with self.assertRaises(urls.UrlError) as caught:
            urls.normalize_target(raw, **kw)
        self.assertIn(keyword, caught.exception.reason, raw)
        return caught.exception.reason

    def test_case_and_default_port_normalization(self):
        # RFC 3986 6.2.2：scheme 与 host 大小写不敏感，规范化为小写
        self.accept("HTTPS://Example.COM/Path", "https://example.com/Path")
        # 默认端口不写也等价（6.2.3），非默认端口必须保留
        self.accept("http://a:80/x", "http://a/x")
        self.accept("http://a:443/x", "http://a:443/x")
        self.accept("https://a:443/x", "https://a/x")
        self.accept("http://a", "http://a/")          # 空路径等于 "/"
        self.accept("http://a?x", "http://a/?x")      # 没有路径段时补 /
        self.accept("http://a#f", "http://a/#f")

    def test_percent_encoding_normalization(self):
        self.accept("https://a/b%2fC", "https://a/b%2FC")     # 十六进制位大写（RFC 3986 6.2.2.1）
        self.accept("http://a/%2e%2e/x", "http://a/%2E%2E/x")  # 不解码：解码会改变路径结构
        self.reject("http://a/b%zz", "百分号转义")
        self.reject("http://a/b%2", "百分号转义")
        self.reject("http://a/b%", "百分号转义")

    def test_non_ascii_becomes_wire_form(self):
        got = self.accept("http://a/中文", "http://a/%E4%B8%AD%E6%96%87")
        self.assertEqual(got, "http://a/%E4%B8%AD%E6%96%87")
        # 中文域名 → punycode（IDNA），实测 xn-- 前缀
        self.accept("http://例え.テスト/x", "http://xn--r8jz45g.xn--zckzah/x")

    def test_scheme_allowlist(self):
        for bad in ["javascript:alert(1)", "data:text/html,<b>x</b>", "file:///c:/win.ini",
                    "vbscript:msgbox(1)", "mailto:a@b.c", "ftp://a/b", "JAVASCRIPT:alert(1)"]:
            self.reject(bad, "白名单")
        self.reject("/relative/path", "必须带协议")
        self.reject("a.com/b", "必须带协议")

    def test_response_splitting_and_invisible_chars(self):
        self.reject("http://a/\r\nSet-Cookie: session=1", "CR/LF")
        self.reject("http://a/x\ny", "CR/LF")
        self.reject("http://a/\t", "控制字符")          # 制表符归到控制字符，不到"空白"那一支
        self.reject(" http://a/", "空白")                  # 前导空格：urlsplit 会悄悄吃掉
        self.reject("http://a/ ", "空白")
        self.reject("http://a/\x01b", "控制字符")
        self.reject("http://a/\x7f", "DEL")

    def test_html_excluded_characters(self):
        # RFC 3986 2.2：这些是"排除字符"，出现在 URI 里必须先编码
        for ch in '<>"`|\\^{}[]':
            self.reject(f"http://a/x{ch}y", "排除字符")

    def test_authority_rules(self):
        self.reject("http://user@a/", "user:pass")
        self.reject("http://user:pass@a/", "user:pass")
        self.reject("http://a%2eb/", "含 %")
        self.reject("http://a:99999/", "无法解析")     # urlsplit 在这里抛 ValueError，必须翻译成 400
        self.reject("http://a:0/", "越界")
        self.reject("http://a:x/", "无法解析")
        self.reject("http://-a.com/", "RFC 1123")
        self.reject("http://a-.com/", "RFC 1123")           # 尾部的 - 也必须整段匹配
        self.reject("http://a..b/", "RFC 1123")
        self.reject("http:///x", "主机名")
        self.reject("http://:8080/x", "主机名")
        self.reject("http://a//b", "// 开头")

    def test_ipv6_keeps_brackets(self):
        # urlsplit 会把方括号剥掉，不补回去就拼不出合法 URL
        self.accept("http://[::1]:8080/x", "http://[::1]:8080/x")
        self.accept("http://[fe80::1%25eth0]/x", "http://[fe80::1%25eth0]/x")
        self.reject("http://[::1/x", "无法拆分")        # 方括号没闭合：urlsplit 在拆分那一刻就抛
        self.reject("http://a]b/x", "无法拆分")

    def test_self_reference_loop(self):
        kw = dict(self_hosts=("127.0.0.1", "localhost", "::1"), redirect_prefix="/l/")
        self.reject("http://127.0.0.1:8000/l/abc", "跳转环", **kw)
        self.reject("http://localhost/l/abc", "跳转环", **kw)
        self.reject("http://[::1]/l/abc", "跳转环", **kw)
        self.accept("http://127.0.0.1:8000/api/links", "http://127.0.0.1:8000/api/links", **kw)
        self.accept("http://127.0.0.1:8000/plain", "http://127.0.0.1:8000/plain", **kw)

    def test_length_limit(self):
        ok = "http://a/" + "y" * (urls.MAX_TARGET_LEN - 9)
        self.accept(ok)
        self.reject("http://a/" + "y" * len(ok), "超过上限")

    def test_idempotent_normalization(self):
        """规范化必须收敛：norm(norm(x)) == norm(x)。不收敛说明有一步在来回改。"""
        corpus = ["HTTPS://Example.COM/Path", "http://a:80/x", "http://a", "http://a?x",
                  "http://a/中文", "http://例え.テスト/x", "https://a/b%2fC",
                  "http://[::1]:8080/x?q=1#f", "http://a.b:8080/p?q=1#frag"]
        for raw in corpus:
            once = urls.normalize_target(raw)
            self.assertEqual(urls.normalize_target(once), once, raw)

    def test_merge_query(self):
        self.assertEqual(urls.merge_query("http://a/p", []), "http://a/p")
        self.assertEqual(urls.merge_query("http://a/p", [("q", "1")]), "http://a/p?q=1")
        self.assertEqual(urls.merge_query("http://a/p?x=1", [("q", "2")]), "http://a/p?x=1&q=2")
        # 片段必须在最后：查询要插到 # 之前，否则整串变成片段
        self.assertEqual(urls.merge_query("http://a/p#frag", [("q", "1")]), "http://a/p?q=1#frag")
        self.assertEqual(urls.merge_query("http://a/p?x=1#frag", [("q", "2")]),
                         "http://a/p?x=1&q=2#frag")
        # 键与值里的保留字符必须转义，否则会多出参数分隔符
        self.assertEqual(urls.merge_query("http://a/p", [("q", "1&2")]), "http://a/p?q=1%262")
        self.assertEqual(urls.merge_query("http://a/p", [("a b", "c/d")]), "http://a/p?a%20b=c%2Fd")
        with self.assertRaises(urls.UrlError):
            urls.merge_query("http://a/p", [("k", "v") ] * (urls.MAX_MERGED_QUERY + 1))


class TestStore(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_codes_come_from_ids_and_are_unique(self):
        codes = [self.store.create(f"http://a/{i}", now=float(i)).code for i in range(3)]
        self.assertEqual(codes, ["1", "2", "3"])
        self.assertEqual(self.store.count(), 3)

    def test_visit_increments_atomically(self):
        link = self.store.create("http://a/", alias="v1")
        self.assertEqual((link.code, link.hits, link.last_visit), ("v1", 0, None))
        for i in range(50):
            self.store.visit("v1", now=100.0 + i)
        self.assertEqual(self.store.lookup("v1").hits, 50)     # 读—改—写在库里是一条语句
        self.assertEqual(self.store.lookup("v1").last_visit, 149.0)

    def test_visit_unknown_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.store.visit("nope")

    def test_alias_conflict_is_atomic(self):
        self.store.create("http://first/", alias="dup")
        before = self.store.count()
        with self.assertRaises(ConflictError) as caught:
            self.store.create("http://second/", alias="dup")
        self.assertEqual(caught.exception.target, "http://first/")
        self.assertEqual(self.store.count(), before)            # 回滚要真的回滚
        self.assertEqual(self.store.lookup("dup").target, "http://first/")

    def test_auto_code_skips_alias_namespace(self):
        """别名和自动码共用一个名字空间：自增撞上别名时必须跳过，而不是把 409 抛给没挑过码的人。"""
        self.store.create("http://one/", alias="1")
        auto = self.store.create("http://auto/")
        self.assertEqual(auto.code, "2")
        for ch in codec.ALPHABET:                               # 占满所有单字符码
            if self.store.lookup(ch) is None:
                self.store.create(f"http://one-char/{ch}", alias=ch)
        big = self.store.create("http://after-full/")
        self.assertEqual(len(big.code), 2)                      # 跳到两位

    def test_codes_are_case_sensitive(self):
        self.store.create("http://upper/", alias="Ab")
        self.assertEqual(self.store.lookup("Ab").target, "http://upper/")
        self.assertIsNone(self.store.lookup("ab"))
        self.assertIsNone(self.store.lookup("AB"))

    def test_alias_shape_and_injection_strings(self):
        for bad in ["' OR 1=1--", "a; DROP TABLE links--", "../x", "", "中 文", "x" * 40]:
            with self.subTest(alias=bad):
                with self.assertRaises(AliasError):
                    self.store.create("http://a/", alias=bad)
        # 这些串当作"查询用的短码"也必须只是查不到，不能改变语句
        for probe in ["' OR 1=1--", "1; DELETE FROM links", "%", "_"]:
            self.assertIsNone(self.store.lookup(probe))
        self.assertEqual(self.store.count(), 0)

    def test_capacity_guard(self):
        """上限是模块常量，测试用 mock 把它改小：造"满了"的状态不该靠写五千条数据。"""
        with mock.patch.object(store_module, "MAX_LINKS", 3):
            for i in range(3):
                self.store.create(f"http://a/{i}", now=float(i))
            with self.assertRaises(CapacityError):
                self.store.create("http://over/")
            self.assertEqual(self.store.stats()["links"], 3)
        self.store.create("http://after-lifted/")      # 恢复上限后又能建：确认上限是判断不是永久锁

    def test_recent_and_top_ordering(self):
        self.store.create("http://old/", alias="old", now=10.0)
        self.store.create("http://new/", alias="new", now=20.0)
        for _ in range(3):
            self.store.visit("old", now=30.0)
        self.assertEqual([l.code for l in self.store.recent(5)], ["new", "old"])
        self.assertEqual([l.code for l in self.store.top(5)], ["old", "new"])   # 按命中排
        self.assertEqual(self.store.stats(),
                         {"links": 2, "total_hits": 3, "best_hits": 3, "limit": MAX_LINKS})

    def test_persistence_across_reopen(self):
        path = Path(tempfile.mkdtemp()) / "sub" / "db.sqlite"
        store = Store(path)
        store.create("http://keep/", alias="k1", now=1.0)
        store.visit("k1", now=2.0)
        store.close()
        reopened = Store(path)
        link = reopened.lookup("k1")
        self.assertEqual((link.target, link.hits, link.last_visit), ("http://keep/", 1, 2.0))
        reopened.close()

    def test_concurrent_writers_do_not_lose_visits(self):
        """8 个线程各点 25 次：锁 + 单语句更新必须一点不丢。"""
        self.store.create("http://race/", alias="race")
        def hammer():
            for _ in range(25):
                self.store.visit("race")
        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.store.lookup("race").hits, 8 * 25)

    # ------------------------------------------------- 点击流水（LinkBox 趋势统计的数据源）
    def test_click_series_and_top_from_log(self):
        """visit 自动落 'link' 流水；log_click 补暂存/文件两类。
        断言避开具体分日（跨午夜会抽签）：只锚定总数一致、序列长度、排行序。"""
        self.store.create("http://hot/", alias="hot", now=1.0)
        self.store.create("http://cold/", alias="cold", now=1.0)
        base = time.time()
        for _ in range(3):
            self.store.visit("hot", now=base)          # 自动入 'link' 流水
        self.store.visit("cold", now=base)
        self.store.log_click("stash", "s1", now=base)
        self.store.log_click("file", "f1", now=base)
        self.store.log_click("file", "f1", now=base)

        self.assertEqual(self.store.clicks_total(14), 7)
        self.assertEqual(self.store.clicks_total(14, "link"), 4)
        self.assertEqual(self.store.clicks_total(14, "file"), 2)
        series = self.store.click_series(14)
        self.assertEqual(len(series), 14)              # 缺的日子补零，长度是窗口本身
        self.assertEqual([p["date"] for p in series],
                         sorted(p["date"] for p in series))
        self.assertEqual(sum(p["count"] for p in series), 7)   # 分日不管边界，总和必须守恒
        top = self.store.click_top(14, limit=8)
        self.assertEqual(top[0], {"kind": "link", "code": "hot", "count": 3})
        self.assertEqual([t["count"] for t in top],
                         sorted((t["count"] for t in top), reverse=True))
        self.assertEqual(self.store.click_top(14, kind="stash"),
                         [{"kind": "stash", "code": "s1", "count": 1}])
        for bad in ("", "visitor", "LINK"):
            with self.subTest(kind=bad):
                with self.assertRaises(ValueError):
                    self.store.log_click(bad, "x", now=base)
                with self.assertRaises(ValueError):
                    self.store.click_series(7, bad)

    def test_click_window_anchors_at_today_midnight(self):
        """days=1 的窗口是"今天 00:00 起"而不是"此刻起"——曾实测：
        下界取 time.time() 时今天早些时候的访问全部漏掉（days=1 才暴露）。"""
        import datetime as _dt
        midnight = _dt.datetime.combine(_dt.date.today(), _dt.time.min).timestamp()
        self.store.log_click("link", "early", now=midnight + 60.0)   # 今天 00:01
        self.store.log_click("link", "now", now=time.time())         # 现在
        self.store.log_click("link", "yesterday", now=midnight - 60.0)  # 昨天尾
        self.assertEqual(self.store.clicks_total(1), 2)              # 昨天尾不算
        self.assertEqual(self.store.clicks_total(2), 3)
        self.assertEqual(sum(p["count"] for p in self.store.click_series(1)), 2)

    def test_click_log_retention_and_row_cap(self):
        """治理两条：保留窗口外的老流水清掉；行数超上限留最新的。
        上限/窗口是模块常量，用 mock 改小——造状态不靠插五万条。"""
        now = time.time()
        with mock.patch.object(store_module, "CLICK_RETAIN_DAYS", 1):
            self.store.log_click("link", "fresh", now=now)
            self.store.log_click("link", "stale", now=now - 3 * 86400.0)
            codes = {r["code"] for r in self.store.db.execute(
                "SELECT code FROM clicks")}
            self.assertEqual(codes, {"fresh"})
        with mock.patch.object(store_module, "CLICK_MAX_ROWS", 5):
            for i in range(8):
                self.store.log_click("stash", f"c{i}", now=now + i)
            kept = [r["code"] for r in self.store.db.execute(
                "SELECT code FROM clicks ORDER BY ts")]
            self.assertEqual(kept, ["c3", "c4", "c5", "c6", "c7"])


class TestAppUnit(AppCase):
    def test_create_returns_201_with_location_and_absolute_short_url(self):
        status, headers, body = self.create("http://example.com/x")
        self.assertEqual(status, 201)
        self.assertEqual(dict(headers)["Location"], "/api/links/1")
        data = json.loads(body)
        self.assertEqual(data["short_url"], "http://127.0.0.1:8000/l/1")   # 端口来自实际监听
        self.assertEqual(data["target"], "http://example.com/x")
        self.assertEqual(data["hits"], 0)

    def test_bad_json_and_types(self):
        for body, keyword in [(b"", "JSON"), (b"{", "JSON"), (b"[]", "JSON 对象"),
                              (b'{"url":1}', "字符串"), (b'{"url":"http://a/","extra":1}', "不认识"),
                              (b'{"alias":"x"}', "缺少 url")]:
            status, _, response = self.app.create_link(
                make_request("POST", "/api/links", headers=[("Host", "127.0.0.1")], body=body))
            with self.subTest(body=body):
                self.assertEqual(status, 400)
                self.assertIn(keyword, json.loads(response)["error"])

    def test_json_error_line_and_column(self):
        status, _, response = self.app.create_link(
            make_request("POST", "/api/links", body=b'{"url": "http://a/",}'))
        self.assertEqual(status, 400)
        error = json.loads(response)["error"]
        self.assertIn("行", error)
        self.assertIn("列", error)

    def test_413_and_415(self):
        big = b'{"url":"' + b"http://a/" + b"y" * MAX_BODY_BYTES + b'"}'
        status, _, _ = self.app.create_link(make_request("POST", "/api/links", body=big))
        self.assertEqual(status, 413)
        status, _, response = self.app.create_link(
            make_request("POST", "/api/links", headers=[("Content-Type", "text/plain")],
                         body=b'{"url":"http://a/"}'))
        self.assertEqual(status, 415)
        self.assertIn("application/json", json.loads(response)["error"])

    def test_409_on_alias_conflict_and_503_on_capacity(self):
        self.assertEqual(self.create("http://a/", "dup")[0], 201)
        status, _, response = self.create("http://b/", "dup")
        self.assertEqual((status, "已被占用" in json.loads(response)["error"]), (409, True))
        with mock.patch.object(store_module, "MAX_LINKS", 2):
            self.create("http://one/")
            self.create("http://two/")
            status, headers, response = self.create("http://three/")
        self.assertEqual(status, 503)
        self.assertIn(("Retry-After", "60"), list(headers))
        self.assertIn("上限", json.loads(response)["error"])

    def test_redirect_counts_get_but_not_head(self):
        self.store.create("http://example.com/t", alias="r1")
        for _ in range(3):
            status, headers, body = self.app.redirect(make_request("HEAD", "/l/r1"))
            self.assertEqual(status, 302)
            self.assertEqual(dict(headers)["Location"], "http://example.com/t")
            self.assertTrue(body)                                   # 体由协议层按 HEAD 丢弃
        self.assertEqual(self.store.lookup("r1").hits, 0)           # HEAD 不灌水分
        status, headers, body = self.app.redirect(make_request("GET", "/l/r1"))
        self.assertEqual((status, dict(headers)["Location"]), (302, "http://example.com/t"))
        self.assertIn(b"example.com", body)
        self.assertEqual(self.store.lookup("r1").hits, 1)

    def test_redirect_escapes_target_in_html_body(self):
        """目标里合法但 HTML 敏感的字符（`'`、`&`）必须被转义后才能进体。"""
        self.store.create("http://example.com/?a=1&b=2#x'y", alias="esc")
        _, headers, body = self.app.redirect(make_request("GET", "/l/esc"))
        text = body.decode("utf-8")
        self.assertIn("&amp;", text)
        self.assertIn("&#x27;", text)
        self.assertNotIn("<a href=\"http://example.com/?a=1&b=2#x'y\"", text)
        self.assertEqual(dict(headers)["Location"], "http://example.com/?a=1&b=2#x'y")

    def test_redirect_passes_visitor_query_through(self):
        self.store.create("http://example.com/s", alias="q1")
        _, headers, _ = self.app.redirect(make_request("GET", "/l/q1", query=[("wd", "课设")]))
        self.assertEqual(dict(headers)["Location"], "http://example.com/s?wd=%E8%AF%BE%E8%AE%BE")
        self.store.create("http://example.com/p?keep=1#frag", alias="q2")
        _, headers, _ = self.app.redirect(make_request("GET", "/l/q2", query=[("x", "2")]))
        self.assertEqual(dict(headers)["Location"], "http://example.com/p?keep=1&x=2#frag")

    def test_redirect_404_and_bad_code_shapes(self):
        status, _, _ = self.app.redirect(make_request("GET", "/l/nope"))
        self.assertEqual(status, 404)
        for path in ["/l/", "/l/a/b", "/l/%20", "/l/a'b"]:
            status, _, _ = self.app.redirect(make_request("GET", path))
            with self.subTest(path=path):
                self.assertEqual(status, 400)

    def test_stats_endpoints(self):
        self.create("http://a/", "s1")
        self.store.visit("s1", now=5.0)
        status, _, response = self.app.link_stats(make_request("GET", "/api/links/s1"))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["hits"], 1)
        status, _, _ = self.app.link_stats(make_request("GET", "/api/links/missing"))
        self.assertEqual(status, 404)
        status, _, response = self.app.list_links(make_request("GET", "/api/links",
                                                               query=[("limit", "abc")]))
        self.assertEqual((status, "整数" in json.loads(response)["error"]), (400, True))
        status, _, response = self.app.overview(make_request("GET", "/api/stats"))
        payload = json.loads(response)
        self.assertEqual(payload["stats"]["total_hits"], 1)
        self.assertEqual(payload["top"][0]["code"], "s1")

    def test_index_and_static_served(self):
        status, headers, body = self.app.index(make_request("GET", "/"))
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("<!DOCTYPE html>", body.decode("utf-8"))
        handlers = dict(((m, p), h) for (m, p), h in self.app.routes())
        for request_path, mime in [("/app.js", "text/javascript"), ("/style.css", "text/css"),
                                   ("/favicon.ico", "image/svg+xml")]:
            # 路由对外叫 /favicon.ico（浏览器就找这个名字），文件在 web 目录里是 SVG
            with self.subTest(path=request_path):
                status, headers, body = handlers[("GET", request_path)](
                    make_request("GET", request_path))
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertTrue(dict(headers)["Content-Type"].startswith(mime),
                                dict(headers)["Content-Type"])

    def test_static_path_containment_without_the_parser(self):
        """协议层会挡掉 `..`，这里绕过它直接从这一层进：目录限制必须自己站得住。"""
        for name in ["../b31/store.py", "..\\b31\\store.py", "/etc/passwd", "C:\\Windows\\win.ini",
                     str(WEB_ROOT.parent / "b31" / "app.py"), "web/../b31/codec.py"]:
            with self.subTest(name=name):
                self.assertIsNone(self.app.read_static(name))
        # 真在 web 目录里的文件才给读
        self.assertIsNotNone(self.app.read_static("index.html"))
        self.assertIsNone(self.app.read_static("index.html.txt"))
        # 绕了一圈又落回 web 目录里的写法不算越界：检查是在解析之后做的，
        # 判断的是"真实路径在哪里"，不是"字符串里有没有 .."
        self.assertEqual(self.app.read_static("../web/index.html"),
                         self.app.read_static("index.html"))

    def test_symlink_outside_web_root_is_refused(self):
        root = Path(tempfile.mkdtemp())
        (root / "web").mkdir()
        secret = root / "secret.txt"
        secret.write_text("不该被读到", encoding="utf-8")
        link = root / "web" / "link.txt"
        try:
            link.symlink_to(secret)
        except OSError:                                     # Windows 建符号链接需要权限
            self.skipTest("平台不允许建符号链接")
        app = ShortUrlApp(Store(), root / "web")
        # resolve() 会跟着链接走，所以"包含检查"必须在解析之后做
        self.assertIsNone(app.read_static("link.txt"))
        app.store.close()

    def test_every_handler_sets_cache_control_no_store(self):
        """跳转和列表都不能被缓存：302 被缓存住，命中数就再也计不到了。"""
        self.create("http://a/", "c1")
        checks = [
            self.app.redirect(make_request("GET", "/l/c1")),
            self.app.list_links(make_request("GET", "/api/links")),
            self.app.link_stats(make_request("GET", "/api/links/c1")),
            self.app.overview(make_request("GET", "/api/stats")),
            self.app.index(make_request("GET", "/")),
        ]
        for status, headers, _ in checks:
            with self.subTest(status=status):
                self.assertEqual(dict(headers)["Cache-Control"], "no-store")


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.server = build_server(db_path=":memory:", port=0)
        self.port = self.server.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.stop()
        self.server.app.store.close()

    def post(self, conn, payload, **headers):
        hdrs = {"Content-Type": "application/json"}
        hdrs.update(headers)
        return conn.request("POST", "/api/links",
                            body=json.dumps(payload).encode(),
                            headers=list(hdrs.items()))


class TestOverRealSocket(ServerCase):
    def test_full_chain_create_redirect_stats(self):
        with Connection(port=self.port) as c:
            created = self.post(c, {"url": "http://example.com/long/path?x=1"})
            self.assertEqual(created.status, 201)
            code = json.loads(created.text())["code"]
            self.assertEqual(created.header("location"), f"/api/links/{code}")

            jumped = c.request("GET", f"/l/{code}")
            self.assertEqual(jumped.status, 302)
            self.assertEqual(jumped.header("location"), "http://example.com/long/path?x=1")
            self.assertEqual(jumped.header("connection"), "keep-alive")

            stats = c.request("GET", f"/api/links/{code}")
            self.assertEqual(json.loads(stats.text())["hits"], 1)

    def test_one_connection_carries_everything(self):
        """一条连接上跑 30 次跳转：keep-alive 复用的是同一条连接，命中数一点不差。"""
        with Connection(port=self.port) as c:
            code = json.loads(self.post(c, {"url": "http://example.com/keep"}).text())["code"]
            for _ in range(30):
                self.assertEqual(c.request("GET", f"/l/{code}").status, 302)
            after = json.loads(c.request("GET", f"/api/links/{code}").text())
            self.assertEqual(after["hits"], 30)
            self.assertEqual(self.server.stats.connections, 1)

    def test_pipelined_requests_all_counted(self):
        """管线化：两个跳转请求一次写出去，两个响应都不能少，命中数也不能重或丢。"""
        with Connection(port=self.port) as c:
            code = json.loads(self.post(c, {"url": "http://example.com/pipe"}).text())["code"]
            c.send(encode_request("GET", f"/l/{code}", host="127.0.0.1"))
            c.send(encode_request("GET", f"/l/{code}", host="127.0.0.1"))
            first = c.read_response()
            second = c.read_response()
            self.assertEqual((first.status, second.status), (302, 302))
            self.assertEqual(first.header("location"), second.header("location"))
            after = json.loads(c.request("GET", f"/api/links/{code}").text())
            self.assertEqual(after["hits"], 2, "两次请求就该两次命中：一次读两次或两次读一次都是错")

    def test_405_only_when_method_is_not_allowed(self):
        with Connection(port=self.port) as c:
            code = json.loads(self.post(c, {"url": "http://example.com/m"}).text())["code"]
            wrong = c.request("DELETE", f"/l/{code}")
            self.assertEqual(wrong.status, 405)
            self.assertEqual(wrong.header("allow"), "GET, HEAD")
            missing = c.request("GET", "/l/" + "z" * 9)     # 形状合法但没建过：这才是"码不存在"
            self.assertEqual(missing.status, 404, "路径存在但码不存在，不能被升级成 405")
            overlong = c.request("GET", "/l/doesnotexist")   # 12 个字符：连形状都不合法
            self.assertEqual(overlong.status, 400, "超过 11 位的短码是语法错误，轮不到查库")

    def test_bad_request_does_not_drop_the_connection(self):
        """应用层错误必须留着连接：打错一个字符不该把 keep-alive 也赔进去。"""
        with Connection(port=self.port) as c:
            bad = self.post(c, {"url": "javascript:alert(1)"})
            self.assertEqual(bad.status, 400)
            self.assertEqual(bad.header("connection"), "keep-alive")
            good = self.post(c, {"url": "http://example.com/after-bad"})
            self.assertEqual(good.status, 201)             # 同一条连接还能继续用

    def test_host_header_without_port_still_yields_working_link(self):
        with Connection(port=self.port) as c:
            created = self.post(c, {"url": "http://example.com/h"}, Host="127.0.0.1")
            short = json.loads(created.text())["short_url"]
            self.assertIn(f":{self.port}", short, "端口丢了就会生成打不开的短链")
            code = short.rsplit("/", 1)[1]
            self.assertEqual(c.request("GET", f"/l/{code}").status, 302)

    def read_until_head(self, sock):
        """按"头部结束"来读，而不是按 endswith。

        endswith(b"\\r\\n\\r\\n") 是个陷阱：头和体通常在一次 recv 里一起到，
        那时缓冲区结尾是体的最后一个字节，条件永远不成立，循环就在 EOF 的空读上原地打转。
        """
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                self.fail(f"连接在头部结束之前就断了：{data!r}")
            data += chunk
        return data

    def test_raw_socket_sees_the_exact_redirect_bytes(self):
        code = self.make_code("http://example.com/raw")
        request = (f"GET /l/{code} HTTP/1.1\r\n"
                   f"Host: 127.0.0.1:{self.port}\r\nConnection: close\r\n\r\n").encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.sendall(request)
            data = self.read_until_head(s)
            head_bytes, _, rest = data.partition(b"\r\n\r\n")
            self.assertTrue(head_bytes.startswith(b"HTTP/1.1 302 Found\r\n"))
            self.assertIn(b"Location: http://example.com/raw\r\n", head_bytes)
            self.assertIn(b"Cache-Control: no-store\r\n", head_bytes)
            length = int([line for line in head_bytes.split(b"\r\n")
                          if line.lower().startswith(b"content-length:")][0].split(b":")[1])
            while len(rest) < length:
                chunk = s.recv(4096)
                if not chunk:
                    break
                rest += chunk
            self.assertEqual(len(rest), length, "体长必须和 Content-Length 说的完全一致")
            self.assertIn(b'<a href="http://example.com/raw">', rest)

    def make_code(self, target):
        with Connection(port=self.port) as c:
            return json.loads(self.post(c, {"url": target}).text())["code"]

    def test_stdlib_client_follows_our_redirect(self):
        """标准库客户端跟着我们的 302 真的落到了目标——不是只有我们自己的客户端认。
        用显式无代理的 opener：系统代理（如 127.0.0.1:7890）没开时不许假红。"""
        import urllib.request
        home = f"http://127.0.0.1:{self.port}/"
        code = self.make_code(home)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"{home}l/{code}", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertTrue(resp.geturl().endswith("/"))
            self.assertIn(b"<!DOCTYPE html>", resp.read())

    def test_traversal_cannot_reach_source_files(self):
        """每个越界尝试各用一条新连接：协议层判 400 之后会关连接，这是它的承诺。"""
        for target in ["/l/../b31/store.py", "/l/%2e%2e/b31/store.py", "/l/..%2fstore.py",
                       "/api/links/../../b31/store", "/..%2f..%2fetc/passwd"]:
            with self.subTest(target=target), Connection(port=self.port) as c:
                response = c.request("GET", target)
                self.assertIn(response.status, (400, 404))
                self.assertNotIn(b"CREATE TABLE", response.body)
                self.assertNotIn(b"def create(", response.body)

    def test_server_survives_a_hundred_mixed_requests(self):
        """随机混跑：任何一条都不该把事件循环线程打挂（stop() 会把线程里的异常抛回来）。"""
        import random
        rng = random.Random(31)
        codes = [self.make_code(f"http://example.com/{i}") for i in range(5)]
        with Connection(port=self.port) as c:
            for _ in range(200):
                pick = rng.random()
                if pick < 0.55:
                    response = c.request("GET", f"/l/{rng.choice(codes)}")
                    self.assertIn(response.status, (302, 404))
                elif pick < 0.75:
                    response = self.post(c, {"url": f"http://example.com/rand{rng.randrange(9999)}"})
                    self.assertIn(response.status, (201, 400))
                elif pick < 0.9:
                    response = c.request("GET", "/api/links")
                    self.assertEqual(response.status, 200)
                else:
                    response = c.request("GET", "/api/stats")
                    self.assertEqual(response.status, 200)
        total = self.server.stats.as_dict()
        self.assertGreaterEqual(total["requests"], 200)
        self.assertGreaterEqual(total["peak_open"], 1)
        self.server.stop()                                 # stop() 会把事件循环线程里的异常抛回来
        self.assertEqual(self.server.stats.open_now, 0)

    def test_stats_counting_matches_requests_made(self):
        with Connection(port=self.port) as c:
            for _ in range(3):
                self.assertEqual(c.request("GET", "/api/stats", close=False).status, 200)
            c.request("GET", "/api/stats", close=True)     # 最后一句要它关，连接才回收
        snap = self.server.stats.as_dict()
        self.assertGreaterEqual(snap["requests"], 4)
        self.assertTrue(wait_until(lambda: self.server.stats.open_now == 0),
                        "半关闭之后应收到 EOF 并回收，不该把连接挂在表里")


class TestFrontendSource(unittest.TestCase):
    """源码层的静态断言：不能跑浏览器，但"有没有用不安全的写法"是可以检查的。"""

    def setUp(self):
        self.js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        self.html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    def test_no_innerhtml_anywhere(self):
        """查的是"用法"而不是词：注释里提到 innerHTML 不该把这条测试弄红。"""
        patterns = [r"\.\s*innerHTML\s*[+]?=", r"\.\s*outerHTML\s*[+]?=",
                    r"document\s*\.\s*write(?:ln)?\s*\(", r"insertAdjacentHTML\s*\("]
        for name in ("app.js", "index.html"):
            text = (WEB_ROOT / name).read_text(encoding="utf-8")
            for pattern in patterns:
                with self.subTest(name=name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, text),
                                      f"{name} 里出现了 {pattern}：用户数据会被当成标记解析")

    def test_uses_textcontent_for_user_data(self):
        self.assertIn("textContent", self.js)
        self.assertIn("createElement", self.js)

    def test_no_inline_handlers_in_html(self):
        for attr in ("onclick=", "onerror=", "onload="):
            self.assertNotIn(attr, self.html)

    def test_html_has_lang_and_charset_and_labels(self):
        self.assertIn('lang="zh-CN"', self.html)
        self.assertIn('<meta charset="utf-8">', self.html)
        for field in ("url", "alias"):
            self.assertIn(f'for="{field}"', self.html)

    def test_javascript_is_syntactically_valid(self):
        """语法错误在这一层就能抓到：浏览器里它只会表现为"按钮没反应"。"""
        if not shutil.which("node"):
            self.skipTest("本机没有 node，跳过语法检查")
        proc = subprocess.run(["node", "--check", str(WEB_ROOT / "app.js")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
