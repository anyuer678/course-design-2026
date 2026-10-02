"""B31 与参照实现对拍。

三个参照，各自独立：

1. **base62 编码**：主实现是 `divmod` 逐位取余；参照用"按 2^32 分块再做长除法"
   （竖式除法的算法路径），两条完全不同的路子必须得到同一个字符串。
2. **URL 判定**：拿标准库 `urlsplit` 做语法参照，同时把"标准库拆得开、我们拒收"的
   每一例钉成一张分歧表——表外的分歧就是回归。
3. **仓储行为**：用一个纯 Python 影子模型（dict + 列表）跑同样的操作序列，
   逐步比对短码、命中数与列表顺序。SQLite 的行为只要和影子模型分叉就会被抓到。

另外用标准库自己的响应解析器（`http.client` / `email.parser`）读我们发出的 302，
确认头部 framing 不是只有 B11 的客户端认。
"""
from __future__ import annotations

import email.parser
import http.client
import json
import math
import random
import sys
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import b31                                              # noqa: E402,F401  首飞装 netlab 路径，不然后两行 import 不到
from netlab.client import Connection                    # noqa: E402
from netlab.http1 import build_response                 # noqa: E402

from b31 import codec, urls                             # noqa: E402
from b31.server import build_server                     # noqa: E402
from b31.store import ConflictError, Store              # noqa: E402

CHUNK = 2 ** 32


def ref_encode(n: int) -> str:
    """参照实现：先按 2^32 分块，再对块做竖式长除法。

    和主实现（对整数反复 divmod）完全不同的路径：主实现一次处理一位，
    参照一次处理一整块。两边一致才说明"进制转换"这件事没写歪。
    """
    if n == 0:
        return codec.ALPHABET[0]
    chunks = []
    while n:
        n, rem = divmod(n, CHUNK)
        chunks.append(rem)
    digits = [0]
    for chunk in reversed(chunks):
        carry = chunk
        for i in range(len(digits) - 1, -1, -1):
            value = digits[i] * CHUNK + carry
            digits[i] = value % len(codec.ALPHABET)
            carry = value // len(codec.ALPHABET)
        while carry:
            digits.insert(0, carry % len(codec.ALPHABET))
            carry //= len(codec.ALPHABET)
    return "".join(codec.ALPHABET[d] for d in digits)


def ref_length(n: int) -> int:
    """位数用对数算，和"逐位生成后数长度"是两条独立的路。"""
    if n == 0:
        return 1
    return int(math.floor(math.log(n, codec.BASE))) + 1


class TestCodecAgainstReference(unittest.TestCase):
    def test_chunked_long_division_matches_divmod_loop(self):
        rng = random.Random(31)
        for n in [0, 1, 61, 62, 63, 3843, 3844, CHUNK - 1, CHUNK, CHUNK + 1,
                  CHUNK * 2, codec.MAX_ID]:      # 参照实现不限范围，主实现限到 MAX_ID，所以不测 2^64
            with self.subTest(n=n):
                self.assertEqual(codec.encode_id(n), ref_encode(n))
        for _ in range(400):
            bits = rng.randrange(1, 63)
            n = rng.randrange(0, 2 ** bits)
            self.assertEqual(codec.encode_id(n), ref_encode(n))

    def test_length_formula_matches(self):
        rng = random.Random(7)
        for _ in range(300):
            n = rng.randrange(0, codec.MAX_ID + 1)
            self.assertEqual(len(codec.encode_id(n)), ref_length(n), n)

    def test_roundtrip_on_random_ids(self):
        rng = random.Random(1991)
        for _ in range(500):
            n = rng.randrange(0, codec.MAX_ID + 1)
            self.assertEqual(codec.decode_code(codec.encode_id(n)), n)

    def test_encoding_is_strictly_increasing_in_value(self):
        """排序键 (长度, 字典序) 必须与数值顺序一致——否则"按码排序"会给出错顺序。"""
        codes = [codec.encode_id(n) for n in range(1, 5000)]
        self.assertEqual(codes, sorted(codes, key=lambda s: (len(s), s)))

    def test_no_alphabet_char_outside_base62(self):
        self.assertRegex(codec.ALPHABET, r"^[0-9A-Za-z]{62}$")


class TestUrlAgainstStdlib(unittest.TestCase):
    """标准库负责"拆得开"，我们负责"能不能跳"。分歧必须写在表上。"""

    DIVERGENCES = {
        # raw: (标准库看到的协议, 我们的判决, 为什么必须由我们判)
        "javascript:alert(1)": ("javascript", "reject", "协议白名单：这不是网页是执行通道"),
        "data:text/html,<b>x</b>": ("data", "reject", "同上，且体里带 HTML"),
        "file:///c:/win.ini": ("file", "reject", "本机文件读取"),
        "http://user@a/": ("http", "reject", "urlsplit 乐意拆出 user，凭据不该出现在短链里"),
        "http://a:99999/": ("http", "reject", "端口越界由 urlsplit 抛 ValueError，得翻译成 400"),
        "http://a%2eb/": ("http", "reject", "主机段不做百分号解码，否则和代理各解一次"),
        "http://a//b": ("http", "reject", "路径以 // 开头会被当成协议相对地址"),
        "http://a/ b": ("http", "reject", "urlsplit 不抱怨空格，Location 里却是非法字节"),
        " http://a/": ("http", "reject", "urlsplit 会悄悄吃掉前导空格，字节数就对不上了"),
        "http://a/\r\nSet-Cookie: x=1": ("http", "reject", "响应拆分：CR/LF 绝不能进头部"),
        "http://a/<b>": ("http", "reject", "尖括号是 HTML 定界符，必须先编码再提交"),
        "http://[::1]:8080/x": ("http", "accept", "urlsplit 剥掉方括号，我们要补回来"),
        "HTTPS://A:443/x": ("https", "accept", "默认端口规范化"),
    }

    def test_divergence_table_is_exact(self):
        for raw, (stdlib_scheme, verdict, _why) in self.DIVERGENCES.items():
            parts = urllib.parse.urlsplit(raw)
            self.assertEqual(parts.scheme.lower(), stdlib_scheme, raw)   # 参照：标准库确实这么拆
            try:
                urls.normalize_target(raw)
                decided = "accept"
            except urls.UrlError:
                decided = "reject"
            with self.subTest(raw=raw):
                self.assertEqual(decided, verdict)

    def test_no_undocumented_rejections(self):
        """白名单里过、标准库也认的地址，我们不能有表外的拒收。"""
        accepted = ["http://a/", "https://a.b.c/x?y=1#z", "http://a:8080/",
                    "http://xn--r8jz45g.xn--zckzah/x", "http://[::1]/x", "http://a_b/c%2Fd",
                    "https://a/~user/", "https://a/path;semi?q=a&b=%2B", "http://a/p?x=%25"]
        for raw in accepted:
            with self.subTest(raw=raw):
                urls.normalize_target(raw)

    def test_host_and_scheme_agree_with_stdlib_on_accepted(self):
        rng = random.Random(3100)
        labels = ["a", "example", "xn--r8jz45g", "127.0.0.1", "a.b.c", "svc-1"]
        for _ in range(200):
            host = ".".join(rng.choice(labels) for _ in range(rng.randrange(1, 4)))
            scheme = rng.choice(["http", "https"])
            path = rng.choice(["/", "/x", "/a/b", "/%20?q=1", "/frag#x"])
            raw = f"{scheme}://{host}{path}"
            normalized = urls.normalize_target(raw)
            parts = urllib.parse.urlsplit(normalized)
            self.assertEqual(parts.scheme, scheme, raw)
            self.assertEqual(parts.hostname or host, host, raw)      # 无端口时 hostname 与原文一致
            self.assertTrue(normalized.isascii())

    def test_stdlib_can_decode_what_we_encoded(self):
        """我们做的 IRI→URI 转换必须让标准库解码回原文——用 `unquote` 这个反向实现验。

        只比"我们的编码和另一个编码函数一样"是不够的：两边同时错也一致。
        反过来走一遍（解码回 UTF-8 文本）才说明字节序没错。
        """
        cases = {"http://a/中文": "/中文", "http://a/😀?x=日本": "/😀",
                 "http://a/路径#片段": "/路径"}
        for raw, original in cases.items():
            normalized = urls.normalize_target(raw)
            self.assertTrue(normalized.isascii(), raw)
            parts = urllib.parse.urlsplit(normalized)
            self.assertEqual(urllib.parse.unquote(parts.path), original, raw)
            if "x=" in raw:
                self.assertEqual(urllib.parse.parse_qs(parts.query)["x"], ["日本"], raw)
            if "片段" in raw:
                self.assertEqual(urllib.parse.unquote(parts.fragment), "片段", raw)

    def test_location_header_parses_with_stdlib_email_parser(self):
        """我们拼的 302 头部，标准库的头部解析器必须读出**一模一样**的 Location。

        注意要把状态行摘掉：`HTTP/1.1 302 Found` 里没有冒号，
        邮件解析器会认为"头部区没开始"，后面的 Location 就一个都读不到。
        """
        targets = ["http://a/", "http://a/x?y=1&z=%2B#f", "http://[::1]:8080/p",
                   "https://xn--r8jz45g.xn--zckzah/%E4%B8%AD"]
        for target in targets:
            raw = build_response(302, body=b"jump", keep_alive=True, date="x",
                                 headers=[("Location", target)])
            head = raw.split(b"\r\n\r\n")[0].decode("ascii")
            self.assertTrue(head.startswith("HTTP/1.1 302 Found\r\n"), head)
            header_block = "\n".join(head.split("\r\n")[1:])
            message = email.parser.Parser().parsestr(header_block)
            self.assertEqual(message["Location"], target, target)
            self.assertEqual(message["Content-Length"], "4")
            self.assertEqual(message["Connection"], "keep-alive")
            self.assertEqual(len(message.items()), len(head.split("\r\n")) - 1, target)

    def test_no_header_smuggling_through_target(self):
        """任何目标都只能产生一条 Location；想用 CR/LF 多写一行必须在校验层就死掉。"""
        for evil in ["http://a/\r\nX-Injected: 1", "http://a/\nX-Injected: 1",
                     "http://a/\rX-Injected: 1"]:
            with self.assertRaises(urls.UrlError, msg=evil):
                urls.normalize_target(evil)
        # 已经百分号编码过的 CRLF 只是普通字符，不会变成行分隔符
        safe = urls.normalize_target("http://a/x%0d%0AX-Injected:1")
        raw = build_response(302, body=b"", date="x", headers=[("Location", safe)])
        head_block = raw.split(b"\r\n\r\n")[0]
        self.assertEqual(head_block.count(b"Location:"), 1)
        self.assertNotIn(b"\r\nX-Injected", head_block)
        self.assertIn(b"%0D%0AX-Injected:1", head_block)      # 规范化成大写，但仍是一整行


class ShadowModel:
    """纯 Python 的影子仓储：dict 存链接，列表存插入顺序。

    和 SQLite 那套（SQL 语句、UNIQUE 索引、RETURNING 计数器）是完全不同的实现路径，
    行为必须逐条一致。
    """

    def __init__(self):
        self.by_code = {}
        self.order = []
        self.next_id = 1

    def create(self, target, alias=None, now=0.0):
        if alias is not None:
            if alias in self.by_code:
                raise ConflictError(alias, self.by_code[alias]["target"])
            code = alias
        else:
            while True:
                code = self._encode(self.next_id)
                self.next_id += 1
                if code not in self.by_code:
                    break
        self.by_code[code] = {"code": code, "target": target, "created_at": now,
                              "hits": 0, "last_visit": None}
        self.order.append(code)
        return code

    @staticmethod
    def _encode(n):
        digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        out = []
        while n:
            n, r = divmod(n, 62)
            out.append(digits[r])
        return "".join(reversed(out)) or "0"

    def visit(self, code, now=0.0):
        row = self.by_code[code]
        row["hits"] += 1
        row["last_visit"] = now
        return row

    def recent(self):
        return [self.by_code[c]["code"] for c in
                sorted(self.order, key=lambda c: (-self.by_code[c]["created_at"],
                                                  -self.order.index(c)))]

    def total_hits(self):
        return sum(row["hits"] for row in self.by_code.values())


class TestStoreAgainstShadowModel(unittest.TestCase):
    def test_random_operation_sequences_agree(self):
        rng = random.Random(20260930)
        for round_index in range(40):
            store, shadow = Store(), ShadowModel()
            seen = []
            with self.subTest(round=round_index):
                for _ in range(200):
                    pick = rng.random()
                    now = rng.randrange(1, 10 ** 6) / 10.0
                    if pick < 0.45 or not seen:
                        alias = None
                        if rng.random() < 0.35:
                            alias = "".join(rng.choice(codec.ALPHABET)
                                            for _ in range(rng.randrange(1, 4)))
                        target = f"http://r{round_index}.example.com/{rng.randrange(1000)}"
                        try:
                            code = store.create(target, alias=alias, now=now).code
                        except ConflictError:
                            self.assertRaises(ConflictError, shadow.create, target, alias, now)
                            continue
                        shadow.create(target, alias, now)
                        self.assertEqual(code, shadow.order[-1])
                        seen.append(code)
                    elif pick < 0.85:
                        code = rng.choice(seen)
                        self.assertEqual(store.visit(code, now=now).hits,
                                         shadow.visit(code, now)["hits"])
                    else:
                        code = rng.choice(codec.ALPHABET) + rng.choice(seen)
                        got = store.lookup(code)
                        expected = shadow.by_code.get(code)
                        self.assertEqual(got is None, expected is None, code)
                        if got is not None:
                            self.assertEqual((got.target, got.hits, got.created_at),
                                             (expected["target"], expected["hits"],
                                              expected["created_at"]))
                self.assertEqual(store.stats()["links"], len(shadow.by_code))
                self.assertEqual(store.stats()["total_hits"], shadow.total_hits())
                self.assertEqual([l.code for l in store.recent(500)], shadow.recent()[:500])
                store.close()

    def test_hit_counts_survive_restart(self):
        import tempfile
        path = Path(tempfile.mkdtemp()) / "again.sqlite"
        store = Store(path)
        store.create("http://x/", alias="k", now=1.0)
        for _ in range(7):
            store.visit("k", now=2.0)
        store.close()
        again = Store(path)
        self.assertEqual(again.lookup("k").hits, 7)
        self.assertEqual(again.stats()["total_hits"], 7)
        again.close()


class TestRedirectViaStdlibClient(unittest.TestCase):
    """同一台服务器，换成标准库的 HTTP 客户端来读：302 的 framing 必须两边都认。"""

    def setUp(self):
        self.server = build_server(db_path=":memory:", port=0)
        self.port = self.server.start()

    def tearDown(self):
        self.server.stop()
        self.server.app.store.close()

    def test_http_client_reads_the_same_location(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/links",
                     body='{"url":"http://example.com/p?a=1&b=%2B"}',
                     headers={"Content-Type": "application/json"})
        created = conn.getresponse()
        payload = created.read()
        self.assertEqual(created.status, 201)
        code = json.loads(payload)["code"]

        conn.request("GET", f"/l/{code}")
        response = conn.getresponse()
        location = response.getheader("Location")
        body = response.read()
        self.assertEqual(response.status, 302)
        self.assertEqual(location, "http://example.com/p?a=1&b=%2B")
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(int(response.getheader("Content-Length")), len(body))
        self.assertEqual(response.getheader("Connection"), "keep-alive")
        conn.close()

    def test_http_client_keeps_the_connection_alive_across_errors(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/links", body='{"url":"javascript:1"}',
                     headers={"Content-Type": "application/json"})
        bad = conn.getresponse()
        bad.read()
        self.assertEqual(bad.status, 400)
        conn.request("GET", "/api/stats")              # 同一条连接继续可用
        good = conn.getresponse()
        good.read()
        self.assertEqual(good.status, 200)
        conn.close()

    def test_both_clients_see_the_same_response(self):
        """同一次跳转让两个解析器各读一遍：B11 的与标准库的必须给出同一个结论。"""
        with Connection(port=self.port) as c:
            created = c.request("POST", "/api/links",
                                body=b'{"url":"http://example.com/two-views"}',
                                headers=[("Content-Type", "application/json")])
            code = json.loads(created.body)["code"]
            ours = c.request("GET", f"/l/{code}")

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", f"/l/{code}")
        theirs = conn.getresponse()
        theirs_body = theirs.read()
        conn.close()

        self.assertEqual((ours.status, ours.header("location"), ours.header("content-length")),
                         (theirs.status, theirs.getheader("Location"),
                          theirs.getheader("Content-Length")))
        self.assertEqual(ours.body, theirs_body)
        # Date 差在毫秒上，不比；其余头部应当是同一套名字
        self.assertEqual({k for k, _ in ours.headers} - {"date"},
                         {k.lower() for k in theirs.msg.keys()} - {"date"})
