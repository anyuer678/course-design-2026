"""webframe/app.py —— 微框架核心：路由装饰器、Ctx、Response、Cookie 会话、静态文件。

分层立场：netlab 管"字节进字节出"（解析/复用/硬上限/HEAD 发送），
本层管"URL 进对象出"——路由、参数、体、会话、静态资产。
错误语义沿用 B31 的口径：404 码不存在 / 405 带 Allow / 415 类型不对 /
400 体不合法；应用 bug 500 且不许带走事件循环（netlab 再兜一层）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sys
import time
import traceback
from pathlib import Path

from netlab.http1 import HttpError, Request

from .template import esc
from .validate import ValidationError, validate

JSON_TYPE = ("Content-Type", "application/json; charset=utf-8")
MIME_JSON = "application/json; charset=utf-8"
HTML_TYPE = ("Content-Type", "text/html; charset=utf-8")
MIME_HTML = "text/html; charset=utf-8"
TEXT_TYPE = ("Content-Type", "text/plain; charset=utf-8")
NO_STORE = ("Cache-Control", "no-store")
MIME_TEXT = "text/plain; charset=utf-8"

_GLOBAL_METHODS = ("GET", "HEAD", "POST", "PUT", "DELETE")

# 静态资产类型白名单：B31 的表 + 图片字体（png/jpg/ico/woff2）
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


class HttpFail(Exception):
    """处理器主动喊停（框架映射为 JSON 错误响应）。"""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class Response:
    """处理器返回值：框架在 finish 阶段归一成 (status, headers, body)。"""

    def __init__(self, body=b"", *, status: int = 200,
                 content_type: str = MIME_HTML, headers: list | None = None):
        self.status = status
        self.body = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.headers = list(headers or [])
        if content_type and not any(k.lower() == "content-type"
                                    for k, _ in self.headers):
            self.headers.append(("Content-Type", content_type))
        self.cookies: list[str] = []

    def set_cookie(self, name: str, value: str, *, max_age: int | None = None,
                   path: str = "/", http_only: bool = True,
                   same_site: str = "Lax") -> "Response":
        parts = [f"{name}={value}", f"Path={path}", f"SameSite={same_site}"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if http_only:
            parts.append("HttpOnly")
        self.cookies.append("; ".join(parts))
        return self


def _cookie_header(request: Request) -> dict:
    out = {}
    for name, value in request.headers:
        if name == "cookie":
            for item in value.split(";"):
                key, _, val = item.strip().partition("=")
                if key:
                    out[key] = val
    return out


class Ctx:
    """每请求一次的处理器上下文：参数、查询、体、Cookie、签名会话。"""

    def __init__(self, app: "MicroApp", request: Request, params: dict):
        self.app = app
        self.request = request
        self.params = params
        self._json_cache: object = (...)
        self._session: dict | None = None
        self._session_snapshot: dict | None = None
        self._session_forced = False
        self.status_headers_hint: list = []   # 处理器可追加全局响应头

    # ---- 查询与 Cookie
    @property
    def query(self) -> dict:
        return dict(self.request.query)

    def cookie(self, name: str) -> str | None:
        return _cookie_header(self.request).get(name)

    # ---- JSON 体（415/400 语义与 B31 一致）
    def json_body(self, schema: dict | None = None,
                  *, allow_unknown: bool = False) -> dict:
        if self._json_cache is not (...):
            payload = self._json_cache
        else:
            ctype = self.request.header("content-type")
            if ctype is not None and \
                    ctype.split(";")[0].strip() != "application/json":
                raise HttpFail(415, f"只接受 application/json，收到 {ctype!r}")
            try:
                payload = json.loads(self.request.body.decode("utf-8"))
            except UnicodeDecodeError:
                raise HttpFail(400, "请求体不是 UTF-8") from None
            except json.JSONDecodeError as exc:
                raise HttpFail(400, f"JSON 语法错误：{exc.msg}") from None
            self._json_cache = payload
        if schema is not None:
            validate(payload, schema, allow_unknown=allow_unknown)
        return payload

    # ---- 签名会话（无服务端存储：HMAC-SHA256 签名的 JSON cookie）
    @property
    def session(self) -> dict:
        if self._session is None:
            self._session = self.app._load_session(self.cookie(self.app.session_cookie))
            self._session_snapshot = dict(self._session)
        return self._session

    def reset_session(self) -> None:
        """登出语义：强制回写"空会话"cookie 覆盖浏览器里的旧凭据。
        只调 session.clear() 不够——空会话与"从未登录"快照相同，脏检测不触发。"""
        self.session.clear()
        self._session_forced = True

    # ---- 响应助手
    def json(self, payload, status: int = 200) -> Response:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return Response(body, status=status, content_type=MIME_JSON,
                        headers=[NO_STORE])

    def html(self, text: str, status: int = 200) -> Response:
        return Response(text, status=status, content_type=MIME_HTML,
                        headers=[NO_STORE])

    def text(self, text: str, status: int = 200) -> Response:
        return Response(text, status=status, content_type=MIME_TEXT,
                        headers=[NO_STORE])

    def redirect(self, location: str, status: int = 302) -> Response:
        resp = Response(b"", status=status, content_type=None,
                        headers=[("Location", location), NO_STORE])
        resp.body = (f'<!doctype html><meta charset="utf-8">'
                     f'<p>跳到 <a href="{esc(location)}">{esc(location)}</a></p>'
                     ).encode("utf-8")
        return resp


_PARAM_RE = re.compile(r"<([a-z_][a-z0-9_]*)(:path)?>")


def _compile(rule: str) -> re.Pattern:
    """<name> -> 命名 [^/]+；<name:path> -> 命名 .+（静态子路径用）。"""
    pattern = ""
    last = 0
    for match in _PARAM_RE.finditer(rule):
        pattern += re.escape(rule[last:match.start()])
        name, kind = match.group(1), match.group(2)
        pattern += f"(?P<{name}>.+)" if kind else f"(?P<{name}>[^/]+)"
        last = match.end()
    pattern += re.escape(rule[last:])
    return re.compile(f"^{pattern}$")


class MicroApp:
    def __init__(self, *, session_secret: bytes | None = None,
                 session_cookie: str = "wf_session",
                 session_max_age: int = 7 * 86400):
        self.session_secret = session_secret or secrets.token_bytes(32)
        self.session_cookie = session_cookie
        self.session_max_age = session_max_age
        self.routes: list[tuple[tuple[str, re.Pattern], object]] = []
        # WebSocket 路由：[(编译规则, handler(session))]。升级握手与帧协议
        # 全在 netlab（B11）；这里只做规则匹配与回调装配的登记。
        self.ws_routes: list[tuple[re.Pattern, object]] = []
        self.port = None                      # 由 MicroServer.start() 回填

    # ---------------------------------------------------------------- 路由
    def route(self, rule: str, methods: tuple = ("GET",)):
        compiled = _compile(rule)

        def decorator(fn):
            for method in methods:
                self.routes.append(((method, compiled), fn))
            return fn
        return decorator

    def ws(self, rule: str):
        """WebSocket 端点：@app.ws("/ws/live")。

        handler(session) 在升级成功后被调用（服务器事件循环线程），里面赋
        session.on_message / on_poll / on_close，需要首包快照就在这里发。
        之后 netlab 会把会话纳入事件循环泵与关闭回收。
        """
        compiled = _compile(rule)

        def decorator(fn):
            self.ws_routes.append((compiled, fn))
            return fn
        return decorator

    def get(self, rule: str):
        return self.route(rule, ("GET",))

    def post(self, rule: str):
        return self.route(rule, ("POST",))

    def put(self, rule: str):
        return self.route(rule, ("PUT",))

    def delete(self, rule: str):
        return self.route(rule, ("DELETE",))

    def static(self, prefix: str, directory: str | Path) -> None:
        """挂静态目录：类型白名单 + 真实路径必须留在根里（B31 的守卫原样搬）。"""
        root = Path(directory).resolve()

        @self.get(f"{prefix}/<relpath:path>")
        def serve_static(ctx: Ctx) -> Response:
            candidate = (root / ctx.params["relpath"]).resolve()
            if not candidate.is_relative_to(root):
                raise HttpFail(404, "资源不存在")
            if candidate.suffix not in STATIC_TYPES or not candidate.is_file():
                raise HttpFail(404, "资源不存在")
            data = candidate.read_bytes()
            return Response(data, content_type=STATIC_TYPES[candidate.suffix],
                            headers=[("Cache-Control", "no-cache")])

    # ---------------------------------------------------------------- 分发
    def handle(self, request: Request):
        if request.method == "OPTIONS":     # 与 netlab 默认行为一致（_handle 会接住）
            raise HttpError(501, "不实现 OPTIONS")
        method = "GET" if request.method == "HEAD" else request.method
        if request.method not in _GLOBAL_METHODS:
            return 405, [("Allow", ", ".join(_GLOBAL_METHODS))], \
                b"method not allowed\n"
        matched_methods: set[str] = set()
        for (route_method, pattern), handler in self.routes:
            match = pattern.match(request.path)
            if match is None:
                continue
            matched_methods.add(route_method)
            if route_method != method:
                continue
            return self._invoke(handler, request, match.groupdict())
        if matched_methods:
            allow = sorted(m if m != "GET" else "GET, HEAD"
                           for m in matched_methods)
            return 405, [("Allow", ", ".join(allow)), JSON_TYPE, NO_STORE], \
                (json.dumps({"error": f"{request.path} 不支持 {request.method}"},
                            ensure_ascii=False) + "\n").encode("utf-8")
        return 404, [JSON_TYPE, NO_STORE], \
            (json.dumps({"error": f"{request.path} 不存在"},
                        ensure_ascii=False) + "\n").encode("utf-8")

    def _invoke(self, handler, request: Request, params: dict):
        ctx = Ctx(self, request, params)
        try:
            result = handler(ctx)
            status, headers, body, resp_cookies = self._normalize(result)
        except HttpFail as exc:
            status, headers, body = exc.status, [JSON_TYPE, NO_STORE], \
                (json.dumps({"error": exc.message}, ensure_ascii=False)
                 + "\n").encode("utf-8")
            resp_cookies = []
        except ValidationError as exc:
            status, headers, body = 400, [JSON_TYPE, NO_STORE], \
                (json.dumps({"error": "；".join(exc.problems)},
                            ensure_ascii=False) + "\n").encode("utf-8")
            resp_cookies = []
        except Exception:
            traceback.print_exc(file=sys.stderr)
            status, headers, body = 500, [JSON_TYPE], \
                (json.dumps({"error": "internal error"}) + "\n").encode("utf-8")
            resp_cookies = []
        # 会话回写：脏（处理器改了会话）或被显式 reset（登出）
        if ctx._session_forced or (
                ctx._session is not None
                and ctx._session != ctx._session_snapshot):
            token = self._dump_session(ctx._session)
            cookie = Response().set_cookie(self.session_cookie, token,
                                           max_age=self.session_max_age)
            resp_cookies = resp_cookies + cookie.cookies
        headers = headers + [("Set-Cookie", v) for v in resp_cookies]
        return status, headers, body

    @staticmethod
    def _normalize(result):
        if isinstance(result, Response):
            return result.status, result.headers, result.body, result.cookies
        if isinstance(result, tuple):
            status, headers, body = result
            if isinstance(body, str):
                body = body.encode("utf-8")
            return status, list(headers), body, []
        raise TypeError(f"处理器返回类型不支持：{type(result).__name__}")

    # ---------------------------------------------------------------- 会话编解码
    def _sign(self, payload: bytes) -> str:
        return hmac.new(self.session_secret, payload,
                        hashlib.sha256).hexdigest()

    def _dump_session(self, data: dict) -> str:
        payload = json.dumps({"data": data, "exp": int(time.time())
                              + self.session_max_age},
                             separators=(",", ":")).encode("utf-8")
        token = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
        return f"{token}.{self._sign(payload)}"

    def _load_session(self, token: str | None) -> dict:
        if not token or "." not in token:
            return {}
        raw, _, sig = token.rpartition(".")
        try:
            payload = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except Exception:
            return {}
        if not hmac.compare_digest(self._sign(payload), sig):
            return {}                          # 签名不对：当没带会话，不给半点提示
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except Exception:
            return {}
        if not isinstance(parsed, dict) or \
                parsed.get("exp", 0) < time.time():
            return {}
        data = parsed.get("data")
        return data if isinstance(data, dict) else {}
