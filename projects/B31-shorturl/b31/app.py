"""b31/app.py —— 短链应用层：路由、状态码、静态文件。

这一层不碰 socket，也不自己解析 HTTP：请求已经是 `netlab.http1.Request` 对象，
响应就是 `(status, headers, body)` 三元组，协议层的边界由 B11 守住。
所以本层只回答三个 Web 课上的问题：

* **状态码选得对不对**：创建成功是 201 而不是 200，并带 `Location` 指向新资源；
  跳转用 302（临时）而不是 301——目标可能被改，而且 301 会被浏览器永久缓存，
  命中数就再也计不到了；输入不合法是 400，找不到是 404，方法用错是 405，
  体积超了是 413，类型不对是 415，别名撞了是 409。
* **错误要不要断连**：应用层错误一律返回三元组而不是 `raise HttpError`，
  因为 netlab 对协议错误会关闭连接——用户打错一个字符不该把他的 keep-alive 连接也赔进去。
* **输出到哪一层要转义**：`Location` 里的目标由 urls.py 保证纯 ASCII 且无排除字符；
  跳转页的 HTML 体里再 `html.escape` 一次。**两层都做**，因为"上游保证过"是回归的常见入口。
"""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

from netlab.http1 import Request

from . import codec, urls
from .store import AliasError, CapacityError, ConflictError, Store

JSON_TYPE = ("Content-Type", "application/json; charset=utf-8")
HTML_TYPE = ("Content-Type", "text/html; charset=utf-8")
TEXT_TYPE = ("Content-Type", "text/plain; charset=utf-8")

MAX_BODY_BYTES = 8 * 1024          # 创建请求的 JSON 上限：一个 URL + 一个别名，用得着更多吗
MAX_HOST_LEN = 120                 # Host 头部长度上限，防着被塞一整个缓冲区
NO_STORE = ("Cache-Control", "no-store")

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}
REDIRECT_PREFIX = "/l/"
API_PREFIX = "/api/links/"


class ShortUrlApp:
    """把仓储和静态页挂到 netlab 的路由槽上。

    `self_hosts` 用于自指检测与生成绝对短链；`clock` 让测试可以注入时间而不必 sleep。
    """

    def __init__(self, store: Store, web_root: Path, *,
                 self_hosts: tuple = ("127.0.0.1", "localhost"), clock=time.time):
        self.store = store
        self.web_root = Path(web_root).resolve()
        self.self_hosts = tuple(self_hosts)
        self.clock = clock
        self.port = None                   # 由服务器在 start() 之后回填

    # ------------------------------------------------------------------ 路由表

    def routes(self) -> list:
        return [
            (("GET", "/"), self.index),
            (("GET", "/app.js"), self.make_static("app.js")),
            (("GET", "/style.css"), self.make_static("style.css")),
            (("GET", "/favicon.ico"), self.make_static("favicon.svg")),
            (("POST", "/api/links"), self.create_link),
            (("GET", "/api/links"), self.list_links),
            (("GET", "/api/stats"), self.overview),
            (("GET", "/api/links/*"), self.link_stats),
            (("HEAD", "/api/links/*"), self.link_stats),
            (("GET", "/l/*"), self.redirect),
            (("HEAD", "/l/*"), self.redirect),
        ]

    # ------------------------------------------------------------------ 页面与静态资源

    def index(self, request: Request):
        page = self.read_static("index.html")
        if page is None:
            return 500, [TEXT_TYPE], "网页文件 index.html 没找到".encode("utf-8")
        return 200, [HTML_TYPE, NO_STORE], page

    def make_static(self, name: str):
        def handler(request: Request):
            data = self.read_static(name)
            if data is None:
                return 404, [TEXT_TYPE], "资源不存在".encode("utf-8")
            suffix = Path(name).suffix
            return 200, [("Content-Type", STATIC_TYPES[suffix]), NO_STORE], data
        return handler

    def read_static(self, name: str):
        """只允许从 web_root 里取，并且解析后的真实路径必须仍在里面。

        协议层（netlab）已经把 `..` 段挡掉了，这一层不看它也没关系吗？不行——
        路由是 `("/l/*")` 这种模式匹配，将来任何人加一条把路径片段直接当文件名的路由，
        这一层就是最后一道。所以这里按"输入可能是 ../../etc/passwd 或绝对路径"来写，
        测试也从这一层直接进，不经过解析器。
        """
        root = self.web_root
        candidate = (root / name).resolve()          # 绝对路径会把 join 重置到根，正好被下面的检查抓住
        if not candidate.is_relative_to(root):
            return None
        if candidate.suffix not in STATIC_TYPES:
            return None
        if not candidate.is_file():
            return None
        return candidate.read_bytes()

    # ------------------------------------------------------------------ 创建

    def create_link(self, request: Request):
        if len(request.body) > MAX_BODY_BYTES:
            return 413, [JSON_TYPE], self._error(f"请求体 {len(request.body)} 字节，上限 {MAX_BODY_BYTES}")
        content_type = request.header("content-type")
        if content_type is not None and content_type.split(";")[0].strip() != "application/json":
            return 415, [JSON_TYPE], self._error(f"只接受 application/json，收到 {content_type!r}")
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except UnicodeDecodeError:
            return 400, [JSON_TYPE], self._error("请求体不是 UTF-8")
        except json.JSONDecodeError as exc:
            return 400, [JSON_TYPE], self._error(f"JSON 语法错误：{exc.msg}（第 {exc.lineno} 行第 {exc.colno} 列）")
        if not isinstance(payload, dict):
            return 400, [JSON_TYPE], self._error("请求体必须是一个 JSON 对象")
        unknown = sorted(set(payload) - {"url", "alias"})
        if unknown:
            # 静默忽略拼错的键，前端会以为链接建好了但参数没生效——这类"看起来成功了"最难查
            return 400, [JSON_TYPE], self._error(f"不认识的字段：{unknown}，只接受 url 与 alias")
        if "url" not in payload:
            return 400, [JSON_TYPE], self._error("缺少 url")
        if not isinstance(payload["url"], str):
            return 400, [JSON_TYPE], self._error(f"url 必须是字符串，收到 {type(payload['url']).__name__}")
        alias = payload.get("alias")
        if alias is not None and not isinstance(alias, str):
            return 400, [JSON_TYPE], self._error("alias 必须是字符串")
        try:
            target = urls.normalize_target(payload["url"], self_hosts=self.self_hosts)
        except urls.UrlError as exc:
            return 400, [JSON_TYPE], self._error(exc.reason)
        if alias is not None and not codec.is_code_shape(alias):
            return 400, [JSON_TYPE], self._error(
                f"别名 {alias!r} 不合法：只能用 base62 字母表、长度 1..{codec.MAX_CODE_LEN}")
        try:
            link = self.store.create(target, alias=alias, now=self.clock())
        except ConflictError as exc:
            # 409：用户自己挑的名字撞了，换个名字就能继续——这是可操作的冲突
            return 409, [JSON_TYPE], self._error(f"别名 {exc.code!r} 已被占用")
        except CapacityError as exc:
            # 503：容量问题不是用户的错，也不该让他换个别名重试
            return 503, [JSON_TYPE, ("Retry-After", "60"), NO_STORE], self._error(str(exc))
        except AliasError as exc:
            return 400, [JSON_TYPE], self._error(str(exc))

        short = self.short_url(link.code, request)
        body = self._json({"code": link.code, "short_url": short, "target": link.target,
                           "created_at": link.created_at, "hits": link.hits})
        return 201, [JSON_TYPE, ("Location", f"/api/links/{link.code}"), NO_STORE], body

    # ------------------------------------------------------------------ 跳转

    def redirect(self, request: Request):
        code, problem = self._code_from(request.path, REDIRECT_PREFIX)
        if problem is not None:
            return 400, [TEXT_TYPE], problem.encode("utf-8")
        try:
            # HEAD 不计命中：它只是"探一下头部"，算一次访问会把统计灌水
            link = self.store.visit(code, now=self.clock()) \
                if request.method == "GET" else self.store.lookup(code)
        except KeyError:
            return 404, [TEXT_TYPE], f"短码 {code} 不存在\n".encode("utf-8")
        if link is None:
            return 404, [TEXT_TYPE], f"短码 {code} 不存在\n".encode("utf-8")
        try:
            location = urls.merge_query(link.target, request.query)
        except urls.UrlError as exc:
            return 400, [TEXT_TYPE], exc.reason.encode("utf-8")
        safe = html.escape(location, quote=True)
        body = (f"<!doctype html><meta charset=utf-8><title>跳转</title>"
                f"<p>正在跳到 <a href=\"{safe}\">{safe}</a></p>").encode("utf-8")
        return 302, [HTML_TYPE, ("Location", location), NO_STORE], body

    # ------------------------------------------------------------------ 查询与统计

    def list_links(self, request: Request):
        values = dict(request.query)
        limit = values.get("limit", "20")
        try:
            limit = int(limit)
        except ValueError:
            return 400, [JSON_TYPE], self._error(f"limit 要写成整数，收到 {limit!r}")
        links = self.store.recent(limit)
        return 200, [JSON_TYPE, NO_STORE], self._json({
            "links": [link.as_dict() for link in links], "count": len(links),
            "stats": self.store.stats()})

    def link_stats(self, request: Request):
        code, problem = self._code_from(request.path, API_PREFIX)
        if problem is not None:
            return 400, [JSON_TYPE], problem.encode("utf-8")
        link = self.store.lookup(code)
        if link is None:
            return 404, [JSON_TYPE], self._error(f"短码 {code} 不存在")
        return 200, [JSON_TYPE, NO_STORE], self._json(link.as_dict())

    def overview(self, request: Request):
        return 200, [JSON_TYPE, NO_STORE], self._json({
            "stats": self.store.stats(), "top": [link.as_dict() for link in self.store.top(5)],
            "limits": {"max_body_bytes": MAX_BODY_BYTES, "max_target_len": urls.MAX_TARGET_LEN}})

    # ------------------------------------------------------------------ 小工具

    def _code_from(self, path: str, prefix: str):
        """从路径里取出短码。不接受空、多段或字母表外的字符。"""
        tail = path[len(prefix):]
        if not tail:
            return None, f"{prefix} 后面要给短码"
        if "/" in tail:
            return None, "短码里不能再有路径分隔符"
        if not codec.is_code_shape(tail):
            return None, f"短码 {tail!r} 不在字母表里或长度越界"
        return tail, None

    def short_url(self, code: str, request: Request) -> str:
        """用 Host 头部拼绝对短链。

        Host 是客户端可控的：这里只用来"给人看"，跳转本身不依赖它。
        真要放到公网，得改成由配置里的规范域名生成（写进局限了）。

        端口是个实际的坑：`Host: 127.0.0.1` 里没有端口，而服务跑在 8000 上，
        照抄头部就会生成一个打不开的短链。头部自带端口就尊重它，
        没有就补上服务器实际监听的端口（80 是默认端口，补了反而多余）。
        """
        host = (request.header("host") or "").strip()
        if not host or len(host) > MAX_HOST_LEN or not host.isascii() \
                or any(ch in host for ch in "\r\n@ / "):
            host = self.self_hosts[0]
        if ":" not in host and self.port not in (None, 80, 443):
            host = f"{host}:{self.port}"
        return f"http://{host}{REDIRECT_PREFIX}{code}"

    @staticmethod
    def _error(reason: str) -> bytes:
        return json.dumps({"error": reason}, ensure_ascii=False).encode("utf-8") + b"\n"

    @staticmethod
    def _json(payload: dict) -> bytes:
        return json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
