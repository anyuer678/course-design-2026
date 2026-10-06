"""netlab/http1.py —— HTTP/1.1 的严格子集：解析请求、构造响应。

只做课程要用的最小面，但每条边界都能解释"为什么这么判"：

* 只接受 origin-form 请求目标（`/path?query`）、CRLF 换行、可见 ASCII；
* 只认 `Content-Length`，见到 `Transfer-Encoding` 一律 501 并关闭。
  关键是**不能"忽略"它**：忽略 chunked 就等于把一段长度未知的字节当成体，
  下一个请求会把它当成自己的请求行——这就是请求走私（request smuggling）的入口；
* 请求行、单条头部、头部条数、头部总字节、请求体都有硬上限，
  超限分别给 414 / 431 / 413，而且**在缓冲阶段就拒**，不会先把 1 GiB 收进内存；
* 多个 `Content-Length` 只允许取值完全一致，出现分歧直接 400（同样是走私防护）；
* 方法只实现 GET / HEAD / POST / PUT / DELETE，其余交给路由判 405 / 501。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

CRLF = b"\r\n"

MAX_URI = 2048              # RFC 9110 建议服务端至少支持 2048
MAX_REQUEST_LINE = 8192     # 请求行整体
MAX_HEADER_LINE = 8192
MAX_HEADER_COUNT = 100
MAX_HEADER_BYTES = 32 * 1024
DEFAULT_MAX_BODY = 1024 * 1024

SUPPORTED_VERSIONS = ("1.0", "1.1")

STATUS = {
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    303: "See Other",
    304: "Not Modified",
    307: "Temporary Redirect",
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    413: "Content Too Large",
    414: "URI Too Long",
    415: "Unsupported Media Type",
    417: "Expectation Failed",
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    500: "Internal Server Error",
    501: "Not Implemented",
    503: "Service Unavailable",
    505: "HTTP Version Not Supported",
}

_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
# bytes 下标取出来是 int，十六进制表必须是 int 集合；用字符串集合会一个都判不中。
_HEX = set(b"0123456789abcdefABCDEF")


class HttpError(Exception):
    """带状态码的协议错误。close=True 表示回完这条就必须断开连接。"""

    def __init__(self, status: int, explain: str, close: bool = True,
                 headers: tuple = ()):
        super().__init__(f"{status} {STATUS.get(status, '?')}: {explain}")
        self.status = status
        self.explain = explain
        self.close = close
        self.headers = tuple(headers)


@dataclass
class Request:
    method: str
    target: str                    # 原始请求目标（未解码），`/path?query`
    version: str                   # "1.0" / "1.1"
    headers: list                  # [(小写名, 值)]，保留出现顺序
    body: bytes
    path: str                      # 百分号解码后的路径，不含查询串
    query: list                    # [(键, 值)]
    keep_alive: bool
    content_length: int

    def header(self, name: str) -> str | None:
        for k, v in self.headers:
            if k == name.lower():
                return v
        return None

    def headers_of(self, name: str) -> list:
        return [v for k, v in self.headers if k == name.lower()]


# ---------------------------------------------------------------- 解析工具

def _check_ascii(data: bytes, what: str) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise HttpError(400, f"{what} 含非 ASCII 字节（协议层必须先百分号编码）")
    for ch in text:
        if ch == "\r" or ch == "\n":
            raise HttpError(400, f"{what} 含 CR/LF，禁止头部注入")
        if ord(ch) < 0x21 or ord(ch) > 0x7E:
            raise HttpError(400, f"{what} 含控制字符或空格")
    return text


def _pct_decode(data: bytes, what: str) -> str:
    """严格的百分号解码：% 必须跟两个十六进制位，解出来的字节必须是可见字符。

    先做原始字节检查再解码，解码后再查一次控制字符：
    否则 `%2e%2e` 这类"编码后的遍历"会在解码那一刻变成 `..`。
    """
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == ord("%"):
            if i + 2 >= len(data) or data[i + 1] not in _HEX or data[i + 2] not in _HEX:
                bad = data[i + 1:i + 3].decode("latin-1")
                raise HttpError(400, f"{what} 有残缺的百分号转义 %{bad}")
            out.append(int(data[i + 1:i + 3], 16))
            i += 3
        else:
            if b < 0x21 or b > 0x7E:
                raise HttpError(400, f"{what} 含未转义的控制字符或空格")
            out.append(b)
            i += 1
    try:
        # 线上字节必须是可见 ASCII（中文得先百分号编码），但解码之后按 UTF-8 解释：
        # 路径里存中文键是常见需求，拒成 ASCII 只会把应用限制得过窄。
        text = out.decode("utf-8")
    except UnicodeDecodeError:
        raise HttpError(400, f"{what} 解码后不是合法的 UTF-8")
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in text):
        raise HttpError(400, f"{what} 解码后含控制字符")
    return text


def _decode_query(raw: str) -> list:
    """查询串：`+` 表示空格，`%xx` 严格解码，值可以缺省。"""
    pairs = []
    for item in raw.split("&"):
        if not item:
            continue
        key, sep, value = item.partition("=")
        k = _pct_decode(key.replace("+", "%20").encode(), "查询键")
        v = _pct_decode(value.replace("+", "%20").encode(), "查询值") if sep else ""
        pairs.append((k, v))
    return pairs


# ---------------------------------------------------------------- 请求解析

def _has_lone_lf(buf: bytes) -> bool:
    return any(b == 0x0A and (i == 0 or buf[i - 1] != 0x0D) for i, b in enumerate(buf))


def parse_request(buf: bytes, max_body: int = DEFAULT_MAX_BODY):
    """从缓冲里取一个完整请求。

    返回 (Request, 消耗字节数)；数据还不够时返回 None；
    协议非法或越过硬上限时抛 HttpError（带状态码，服务端直接回错并断开）。
    """
    end = buf.find(CRLF + CRLF)
    if end < 0:
        if len(buf) > MAX_HEADER_BYTES:
            raise HttpError(431, f"头部总字节超过 {MAX_HEADER_BYTES}")
        if _has_lone_lf(buf):
            # 已经出现裸 LF：它永远等不到 CRLF CRLF，继续缓冲只会把连接挂到超时，
            # 所以这里就判定非法，让客户端立刻收到 400。
            raise HttpError(400, "请求头里出现裸 LF（必须用 CRLF 换行）")
        return None
    head_block = buf[:end + 4]
    if len(head_block) > MAX_HEADER_BYTES:
        raise HttpError(431, f"头部总字节超过 {MAX_HEADER_BYTES}")

    # 只认 CRLF。裸 LF 会把同一个字节流切成两种不同的请求，
    # 前后端理解不一致就是走私；单独的 CR 同理。
    for i, b in enumerate(head_block):
        if b == 0x0A and (i == 0 or head_block[i - 1] != 0x0D):
            raise HttpError(400, "请求头里出现裸 LF（必须用 CRLF 换行）")
        if b == 0x0D and (i + 1 >= len(head_block) or head_block[i + 1] != 0x0A):
            raise HttpError(400, "请求头里出现裸 CR（必须用 CRLF 换行）")

    lines = head_block.split(CRLF)[:-2]
    if not lines:
        raise HttpError(400, "空请求行")
    request_line = lines[0]
    if len(request_line) > MAX_REQUEST_LINE:
        raise HttpError(414, f"请求行超过 {MAX_REQUEST_LINE} 字节")

    method_b, sep, rest = request_line.partition(b" ")
    if not sep or not rest:
        raise HttpError(400, "请求行必须是 `方法 SP 目标 SP 版本`")
    rest, sep2, version_b = rest.rpartition(b" ")
    if not sep2:
        raise HttpError(400, "请求行缺少 HTTP 版本")
    method = _check_ascii(method_b, "方法")
    if not _TOKEN_RE.match(method):
        raise HttpError(400, f"方法 {method!r} 不是合法 token")
    target = _check_ascii(rest, "请求目标")
    version = _check_ascii(version_b, "版本")

    if len(rest) > MAX_URI:
        raise HttpError(414, f"请求目标超过 {MAX_URI} 字节")
    if not version.startswith("HTTP/"):
        raise HttpError(400, f"版本 {version!r} 不以 HTTP/ 开头")
    ver = version[5:]
    if ver not in SUPPORTED_VERSIONS:
        raise HttpError(505, f"只支持 HTTP/1.0 与 HTTP/1.1，收到 {version}")

    headers = []
    for line in lines[1:]:
        if len(line) > MAX_HEADER_LINE:
            raise HttpError(431, f"单条头部超过 {MAX_HEADER_LINE} 字节")
        if line[:1] in (b" ", b"\t"):
            # obs-fold（续行）在 RFC 9112 里已建议客户端不再产生，
            # 服务端要么拼接要么拒；这里选择拒，避免和下游代理理解不一致。
            raise HttpError(400, "不支持头部续行（obs-fold）")
        name_b, colon, value_b = line.partition(b":")
        if not colon:
            raise HttpError(400, f"头部 {line!r} 缺少冒号")
        name = _check_ascii(name_b, "头部名").lower()
        if not _TOKEN_RE.match(name):
            raise HttpError(400, f"头部名 {name!r} 不合法")
        value = value_b.strip(b" \t")
        if any(b < 0x20 or b > 0x7E for b in value):
            # 控制字符是注入面，>0x7E 的非 ASCII 字节（裸 UTF-8 中文）同样不能放行：
            # 直接 decode 会抛 UnicodeDecodeError，服务端就变成 500 而不是 400。
            raise HttpError(400, f"头部 {name} 的值含控制字符或非 ASCII 字节")
        headers.append((name, value.decode("ascii")))
    if len(headers) > MAX_HEADER_COUNT:
        raise HttpError(431, f"头部条数超过 {MAX_HEADER_COUNT}")

    path, query = _split_target(target)
    lengths = _content_lengths(headers)
    _reject_chunked(headers)
    expect = next((v for k, v in headers if k == "expect"), None)
    if expect is not None and "100-continue" in expect.lower():
        raise HttpError(417, "本服务器不实现 Expect: 100-continue")

    if lengths is not None and lengths > max_body:
        raise HttpError(413, f"请求体 {lengths} 字节，超过上限 {max_body}")
    need = end + 4 + (lengths or 0)
    if len(buf) < need:
        return None                      # 头齐了但体没收完
    body = buf[end + 4:need]

    keep_alive = _keep_alive(ver, headers)
    # 方法名大小写敏感（RFC 9110）：`get` 不是 `GET`，这里不擅自折叠，
    # 否则同一份字节流在我和标准库里会被当成两种请求。
    return Request(method=method, target=target, version=ver, headers=headers,
                   body=body, path=path, query=query, keep_alive=keep_alive,
                   content_length=lengths or 0), need


def _split_target(target: str) -> tuple[str, list]:
    if target == "*":
        raise HttpError(501, "不实现 `*` 形式的服务器配置查询")
    if _SCHEME_RE.match(target):
        raise HttpError(501, f"只接受 origin-form 目标，收到绝对 URI {target!r}")
    raw_path, sep, raw_query = target.partition("?")
    path = _pct_decode(raw_path.encode(), "路径")
    if not path.startswith("/"):
        raise HttpError(400, f"路径 {raw_path!r} 必须以 / 开头")
    if "://" in path:
        raise HttpError(400, "路径里不能藏 scheme")
    # 我们的应用是内存键值表，`..` 并不会真的访问文件系统；
    # 但把遍历挡在解析层是习惯动作，也是后面接静态文件时不会再想一次的保险。
    if any(seg == ".." for seg in path.split("/")):
        raise HttpError(400, "路径不允许 `..` 上跳")
    return (path, _decode_query(raw_query) if sep and raw_query else [])


def _content_lengths(headers: list):
    values = [v for k, v in headers if k == "content-length"]
    if not values:
        return None
    for v in values:
        if not v or not v.isascii() or not v.isdigit():
            raise HttpError(400, f"Content-Length {v!r} 不是无符号十进制")
    if len(set(values)) > 1:
        raise HttpError(400, f"多个 Content-Length 取值不一致：{values}")
    length = int(values[0])
    if len(values[0]) > 12:              # 十几位长度的"数字"只会是攻击或写错的客户端
        raise HttpError(400, f"Content-Length {values[0]!r} 位数不合理")
    return length


def _reject_chunked(headers: list) -> None:
    for k, v in headers:
        if k == "transfer-encoding":
            raise HttpError(501, f"不支持 Transfer-Encoding: {v}（不实现 chunked，也不忽略它）")
        if k == "te":
            te = {t.strip().lower() for t in v.split(",")}
            if "chunked" in te:
                raise HttpError(501, "不支持 TE: chunked")


def _keep_alive(ver: str, headers: list) -> bool:
    tokens = set()
    for k, v in headers:
        if k == "connection":
            tokens |= {t.strip().lower() for t in v.split(",") if t.strip()}
    if "close" in tokens:
        return False
    if "keep-alive" in tokens:
        return True
    return ver == "1.1"        # 1.1 默认长连接，1.0 默认短连接


# ---------------------------------------------------------------- 响应构造

@dataclass
class Response:
    version: str
    status: int
    reason: str
    headers: list              # [(小写名, 值)]
    body: bytes

    def header(self, name: str) -> str | None:
        for k, v in self.headers:
            if k == name.lower():
                return v
        return None

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


def build_response(status: int, *, body: bytes = b"", headers: () = (), version: str = "1.1",
                   keep_alive: bool | None = None, head: bool = False,
                   reason: str | None = None, date: str | None = None,
                   server: str = "netlab/1.0") -> bytes:
    """生成一段确定的响应字节：状态行 + 头部 + CRLF + 体。

    keep_alive=None 时按版本推默认值；HEAD 带同样准确的 Content-Length 但不带体，
    这是客户端判断"还要不要继续读"的依据，不能省。
    """
    if status not in STATUS and reason is None:
        raise ValueError(f"未知状态码 {status}，请显式给 reason")
    if keep_alive is None:
        keep_alive = version == "1.1"
    out_headers = list(headers)
    # 204 不该带 Content-Length；其余状态一律给准确长度，客户端靠它判断读完了没有。
    # HEAD 也带同一个长度：它描述的是"如果允许有体会是多大"。
    if status not in (204, 304) and not any(k.lower() == "content-length" for k, _ in out_headers):
        out_headers.append(("Content-Length", str(len(body))))
    if date is None and not any(k.lower() == "date" for k, _ in out_headers):
        out_headers.append(("Date", _http_date()))
    if not any(k.lower() == "server" for k, _ in out_headers):
        out_headers.append(("Server", server))
    # 永远显式写 Connection：1.0 想长连接必须让客户端看得见，
    # 而测试也要能直接断言服务端到底承诺了哪种语义。
    out_headers.append(("Connection", "keep-alive" if keep_alive else "close"))

    lines = [f"HTTP/{version} {status} {reason or STATUS[status]}"]
    lines += [f"{k}: {v}" for k, v in out_headers]
    head_bytes = CRLF.join(line.encode("ascii") for line in lines) + CRLF + CRLF
    payload = b"" if head else body
    # 上面的 Content-Length 已经按真实 body 算好，HEAD 只是不把体写出来
    return head_bytes + payload


def _http_date(ts: float | None = None) -> str:
    return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(ts))


# ---------------------------------------------------------------- 响应解析

def parse_response(buf: bytes, body_expected: bool = True):
    """解析响应；数据不够返回 None，遇到 chunked 等不支持的编码抛错。

    body_expected=False 是给 HEAD 用的：响应的 Content-Length 描述的是
    "如果允许带体会是多大"，HEAD 本身永远不带体，按长度等下去就会一直挂着。
    """
    end = buf.find(CRLF + CRLF)
    if end < 0:
        if len(buf) > MAX_HEADER_BYTES:
            raise HttpError(431, "响应头部过大")
        return None
    head_block = buf[:end + 4]
    lines = head_block.split(CRLF)[:-2]
    if not lines:
        raise HttpError(400, "空响应状态行")
    parts = lines[0].split(b" ", 2)
    if len(parts) < 2 or not parts[0].startswith(b"HTTP/"):
        raise HttpError(400, f"状态行非法: {lines[0]!r}")
    version = parts[0][5:].decode("ascii")
    try:
        status = int(parts[1])
    except ValueError:
        raise HttpError(400, f"状态码非法: {parts[1]!r}")
    reason = parts[2].decode("ascii", "replace") if len(parts) > 2 else ""

    headers = []
    for line in lines[1:]:
        name_b, colon, value_b = line.partition(b":")
        if not colon:
            raise HttpError(400, f"响应头 {line!r} 缺少冒号")
        headers.append((name_b.decode("ascii").strip().lower(), value_b.strip(b" \t").decode("ascii")))
    if any(k == "transfer-encoding" for k, _ in headers):
        raise HttpError(400, "客户端不实现 chunked 响应")

    if not body_expected:                # HEAD：只有头，长度是"GET 会有多大"
        return Response(version, status, reason, headers, b""), end + 4

    body_len = None
    for k, v in headers:
        if k == "content-length":
            if not v.isdigit():
                raise HttpError(400, f"响应 Content-Length {v!r} 非法")
            body_len = int(v)
    if status in (204, 304) or 100 <= status < 200:
        body_len = 0
    if body_len is None:
        # "读到连接关闭为止"是合法语义，但我们的客户端不实现它：
        # 悄悄接受半截体比直接报错危险得多（对拍时会把截断当成正确结果）。
        raise HttpError(400, "响应没有 Content-Length，本客户端不支持读到关闭的语义")
    need = end + 4 + body_len
    if len(buf) < need:
        return None
    return Response(version, status, reason, headers, buf[end + 4:need]), need
