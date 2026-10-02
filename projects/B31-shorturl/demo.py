"""B31 演示：短链系统从"一个字符串"到"浏览器被领到另一个站点"的全过程。

跑法：`python demo.py`（约 2 秒，只在临时目录里建数据库，项目目录不留文件）。

六段：
  1) 短码从哪来——自增 id 编成 base62，与竖式长除法参照一致
  2) 目标地址的关卡——协议白名单、CR/LF、百分号、IDNA、自指环
  3) 一次真实请求的字节——请求行、302 头部、Location
  4) 状态码语义——400/404/405/409/413/415 各来一发
  5) keep-alive 与管线化——一条连接跑完创建 + 30 次跳转，命中数一点不差
  6) 统计与影子模型——随机操作序列下，SQLite 与纯 Python 模型逐步一致
"""
from __future__ import annotations

import json
import random
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import b31                                              # noqa: E402,F401
from netlab.client import Connection, encode_request    # noqa: E402

from b31 import codec, urls                             # noqa: E402
from b31.server import build_server                     # noqa: E402
from b31.store import ConflictError, Store              # noqa: E402

WIDTH = 78


def section(index: int, title: str) -> None:
    print()
    print("=" * WIDTH)
    print(f"{index}) {title}")
    print("=" * WIDTH)


def show(label: str, value) -> None:
    print(f"  {label:<22} {value}")


def main() -> int:
    section(1, "短码从哪来：自增 id → base62")
    for n in [1, 9, 10, 61, 62, 372642325, codec.MAX_ID]:
        code = codec.encode_id(n)
        show(f"id={n}", f"{code!r}  （{len(code)} 位，解回 {codec.decode_code(code)}）")
    show("字母表", codec.ALPHABET)
    show("为什么不用 base64", "`+` 在查询串里等于空格，`/` 撞路径分隔符")
    for bad in ["00", "a-b", "z" * 12]:
        try:
            codec.decode_code(bad)
        except codec.CodecError as exc:
            show(f"拒绝 {bad!r}", exc)

    section(2, "目标地址的关卡")
    ok = ["https://Example.COM/Path", "http://a:80/x", "http://a/中文",
          "http://例え.テスト/x", "http://[::1]:8080/p?q=1#f", "http://a/b%2fc"]
    for raw in ok:
        show("收下并规范化", f"{raw}  →  {urls.normalize_target(raw)}")
    bad = ["javascript:alert(1)", "data:text/html,x", "file:///c:/win.ini",
           "http://user@a/", "http://a/ b", "http://a/\r\nSet-Cookie: x=1",
           "http://a/<b>", "http://a%2eb/", "http://a:99999/", "http://[::1/x"]
    for raw in bad:
        try:
            urls.normalize_target(raw)
            show("不该收下", raw)
        except urls.UrlError as exc:
            show("拒收", f"{raw[:24]!r:<28} {exc.reason[:34]}")
    show("自指环也拒", urls.UrlError.__name__ + "：目标指向本站 /l/ 路径")
    try:
        urls.normalize_target("http://127.0.0.1:8000/l/abc", self_hosts=("127.0.0.1",))
    except urls.UrlError as exc:
        show("  现场示范", exc.reason)

    db = Path(tempfile.mkdtemp()) / "demo.sqlite"
    server = build_server(db_path=str(db), port=0)
    port = server.start()
    try:
        section(3, "一次真实请求的字节")
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            body = json.dumps({"url": "http://example.com/a?x=1"}).encode()
            request = (encode_request("POST", "/api/links", body=body, host="127.0.0.1",
                                      headers=[("Content-Type", "application/json")],
                                      close=True))
            print("  发出去的请求：")
            for line in request[:len(request) - len(body)].decode().split("\r\n"):
                print(f"    | {line or '<空白行=头部结束>'}")
            sock.sendall(request)
            data = b""
            while b"\r\n\r\n" not in data:
                data += sock.recv(4096)
            print("  收到的响应头：")
            for line in data.split(b"\r\n\r\n")[0].decode().split("\r\n"):
                print(f"    | {line}")
            created = json.loads(data.split(b"\r\n\r\n")[1] or b"{}")
        code = created.get("code")
        show("解析出的短码", f"{code}  绝对地址 {created.get('short_url')}")

        with Connection(port=port) as c:
            jumped = c.request("GET", f"/l/{code}")
            show("GET /l/" + str(code), f"{jumped.status} {jumped.reason}")
            show("Location", jumped.header("location"))
            show("Cache-Control", jumped.header("cache-control"))
            show("Content-Length", jumped.header("content-length"))

        section(4, "状态码语义")
        cases = [
            ("POST", "/api/links", b'{"url":"http://a/"}', [("Content-Type", "application/json")], 201),
            ("POST", "/api/links", b'{"url":"javascript:1"}', [("Content-Type", "application/json")], 400),
            ("POST", "/api/links", b'{"url":"http://a/","x":1}', [("Content-Type", "application/json")], 400),
            ("POST", "/api/links", b'not json', [("Content-Type", "application/json")], 400),
            ("POST", "/api/links", b'{"url":"http://a/"}', [("Content-Type", "text/csv")], 415),
            ("POST", "/api/links", json.dumps({"url": "http://a/", "alias": "dup"}).encode(),
             [("Content-Type", "application/json")], 201),
            ("POST", "/api/links", json.dumps({"url": "http://b/", "alias": "dup"}).encode(),
             [("Content-Type", "application/json")], 409),
            ("GET", f"/l/{code}", b"", [], 302),
            ("GET", "/l/" + "z" * 9, b"", [], 404),
            ("GET", "/l/" + "q" * 12, b"", [], 400),
            ("DELETE", f"/l/{code}", b"", [], 405),
            ("GET", "/api/nothing", b"", [], 404),
        ]
        with Connection(port=port) as c:
            for method, target, payload, headers, expected in cases:
                response = c.request(method, target, body=payload, headers=headers)
                allow = response.header("allow")
                got = response.status
                mark = "对" if got == expected else f"≠ 期望 {expected}"
                show(f"{method} {target[:22]}", f"{got} ({mark})" + (f"  Allow={allow}" if allow else ""))

        section(5, "keep-alive 与管线化")
        with Connection(port=port) as c:
            link = json.loads(c.request("POST", "/api/links",
                                        body=json.dumps({"url": "http://example.com/keep"}).encode(),
                                        headers=[("Content-Type", "application/json")]).text())["code"]
            for _ in range(30):
                c.request("GET", f"/l/{link}")
            hits = json.loads(c.request("GET", f"/api/links/{link}").text())["hits"]
            show("一条连接 30 次跳转", f"命中 {hits}（应为 30）")
            show("服务端累计连接数", server.stats.as_dict()["connections"])
            code_a = link
            c.send(encode_request("GET", f"/l/{code_a}", host="127.0.0.1"))
            c.send(encode_request("HEAD", f"/l/{code_a}", host="127.0.0.1"))
            first = c.read_response()
            # HEAD 的响应没有体，但 Content-Length 描述的是"GET 会有多大"。
            # 不显式告诉解析器"这次没有体"，客户端就会把下一个响应的开头当体吃掉。
            second = c.read_response(body_expected=False)
            show("管线化两个请求", f"{first.status} 与 {second.status}，都是 302")
            show("HEAD 的体长度", f"{len(second.body)}（声明的 Content-Length 是 "
                                  f"{second.header('content-length')}）")
            after = json.loads(c.request("GET", f"/api/links/{code_a}").text())["hits"]
            show("HEAD 不计数", f"{after}（30 次 GET + 1 次管线 GET，HEAD 没加分）")

        section(6, "统计与影子模型")
        rng = random.Random(31)
        store = Store()
        shadow = {}
        seq = 0
        for _ in range(120):
            if rng.random() < 0.4 or not shadow:
                now = rng.randrange(1, 10 ** 6) / 100.0
                try:
                    link = store.create(f"http://r.example.com/{rng.randrange(1000)}", now=now)
                except ConflictError:
                    continue
                seq += 1
                shadow[link.code] = [0, now, seq]
            else:
                code = rng.choice(list(shadow))
                store.visit(code, now=rng.randrange(1, 10 ** 6) / 100.0)
                shadow[code][0] += 1
        total = sum(v[0] for v in shadow.values())
        show("影子模型累计命中", total)
        show("数据库累计命中", store.stats()["total_hits"])
        assert store.stats()["total_hits"] == total
        show("最近 3 条（新→旧）", [(l.code, l.hits) for l in store.recent(3)])
        show("命中榜前 3", [(l.code, l.hits) for l in store.top(3)])
        # 排序键与 SQL 完全一致：created_at 降序、同分再按插入顺序降序
        order = sorted(shadow, key=lambda k: (-shadow[k][1], -shadow[k][2]))
        assert [l.code for l in store.recent(200)] == order[:200], "列表顺序必须与影子模型一致"
        print("  两条完全不同的实现（SQL 语句 vs 字典累加）在这 120 步上逐步一致")
        store.close()
    finally:
        server.stop()
        server.app.store.close()
        print()
        show("服务已关闭", f"统计 {server.stats.as_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
