"""b31/urls.py —— 目标 URL 的校验与规范化：短链系统真正的风险面都在这里。

短链服务天生是一台"**开放重定向器**"：用户给什么，我们就把浏览器往那儿领。
所以危险的不是"跳"，而是"跳到不该跳的地方"。这个模块按四条线把关：

1. **协议白名单**（只收 http/https）。`javascript:` / `data:` / `file:` / `vbscript:` 一律拒——
   它们不是"另一种网页"，而是把内容当代码执行的通道。
2. **响应拆分**。`Location` 头是我们拼进 HTTP 响应字节的；目标里藏一个 CR/LF，
   就等于让用户往响应头里多写几行（Set-Cookie，甚至伪造后半段响应）。
   所以控制字符在**入库之前**就得挡掉，不能指望拼包那一层兜着。
3. **上线的必须是 ASCII**。非 ASCII 主机名走 IDNA（punycode），路径里的非 ASCII 走百分号编码；
   转换失败就拒，不猜。
4. **不给自己挖坑**：指向本站自己的短链路径会形成跳转环，浏览器原地转圈、命中数被自己刷爆。

与标准库的分工写在 tests/test_against_reference.py 里：`urlsplit` 只做**语法拆分**，
不做**安全判断**——`javascript:`、`user:pass@host`、`http://a:99999` 它都拆得漂漂亮亮。
"拆得开"和"能跳"是两件事。
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http", "https")
MAX_TARGET_LEN = 2048                  # 与 netlab 的 MAX_URI 对齐：入口和出口同一个上限
MAX_LABEL_LEN = 63                     # RFC 1034：DNS 单标签长度上限
DEFAULT_PORTS = {"http": 80, "https": 443}

_PCT = re.compile(r"%[0-9A-Fa-f]{2}")
_IPV6 = re.compile(r"^\[[0-9A-Fa-f:.]+(?:%[0-9A-Za-z_.\-]+)?\]$")   # 可带 %zone 标识
_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_\-]*[A-Za-z0-9])?")   # RFC 1123：首尾不能是 -

# RFC 3986 的"排除字符"：这些必须先百分号编码才能出现在 URI 里。
# 我们直接拒而不是"顺手接受"，因为它们中的每一个（`< > " `）都是 HTML 的定界符：
# 原样写进 Location，再被前端显示出来，就等于把"要不要转义"的责任推给了下一层。
# `[ ]` 也在这里——它们只在 IPv6 字面量主机段里合法，PHP 风格的 ?a[]=1 要写成 %5B%5D。
EXCLUDED = '<>"`|\\^{}[]'
MAX_MERGED_QUERY = 32


def _reject_excluded(rest: str) -> None:
    for i, ch in enumerate(rest):
        if ch in EXCLUDED:
            raise UrlError(f"路径/查询里第 {i + 1} 个字符 {ch!r} 是 RFC 3986 排除字符，"
                           "必须先百分号编码")


class UrlError(ValueError):
    """目标 URL 不可用。reason 会原样返回给调用方，所以每条都得能解释"为什么拒"。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _reject_invisible(text: str) -> None:
    """控制字符、CR/LF、空白——必须在拆分之前查。

    标准库 `urlsplit`（Python 3.10 起对齐 WHATWG）会**悄悄吃掉**首尾空白和 C0 控制字符。
    先拆分再检查的话，`" http://a/ "` 和 `"http://a/"` 在我们眼里就成了同一个目标，
    可拼进 `Location` 的字节却不一样多——"同一份输入有两种解释"就是分歧的来源。
    """
    for i, ch in enumerate(text):
        if ch in ("\r", "\n"):
            raise UrlError(f"第 {i + 1} 个字符是 CR/LF：会被拼进响应头，拒收")
        if ord(ch) < 0x20:
            raise UrlError(f"第 {i + 1} 个字符是控制字符 U+{ord(ch):04X}")
        if ord(ch) == 0x7F:
            raise UrlError(f"第 {i + 1} 个字符是 DEL")
        if ch in (" ", "\t"):
            raise UrlError(f"第 {i + 1} 个字符是空白：URL 里空格要写成 %20")


def _normalize_percent(text: str) -> str:
    """百分号转义必须完整，并把十六进制位统一大写（RFC 3986 的规范化建议）。

    只做语法规范化，不解码再重编码：解码会把 `%2F` 变成 `/`，
    而这两者在路径里含义不同，来回一趟就把目标改了。
    """
    out, i = [], 0
    while i < len(text):
        if text[i] == "%":
            if not _PCT.match(text, i):
                raise UrlError(f"百分号转义不完整或非法：{text[i:i + 3]!r} 后面要跟两个十六进制位")
            out.append("%" + text[i + 1:i + 3].upper())
            i += 3
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _host_to_wire(netloc: str, hostname: str | None) -> str:
    """主机名上线形式：IPv6 补回方括号，其余走 IDNA 并检查标签形状。"""
    if "[" in netloc:
        # urlsplit 会把方括号剥掉（hostname 直接给 "::1"），不补回去就拼出坏 URL。
        literal = f"[{hostname}]" if hostname else "[]"
        if not _IPV6.match(literal):
            raise UrlError(f"IPv6 字面量 {netloc!r} 形状不对")
        return literal.lower()
    if not hostname:
        raise UrlError(f"主机名解析不出来：{netloc!r}")
    if "%" in hostname:
        raise UrlError(f"主机名 {hostname!r} 含 %：主机段不做百分号解码。"
                       "在这里解一次，就和代理/浏览器对同一地址有两种理解")
    wire = hostname
    if not hostname.isascii():
        try:
            wire = hostname.encode("idna").decode("ascii")     # 中文/emoji 域名 → punycode
        except (UnicodeError, UnicodeDecodeError) as exc:
            raise UrlError(f"主机名 {hostname!r} 转不成上线形式：{exc}")
    labels = wire.split(".")
    if any(len(label) > MAX_LABEL_LEN for label in labels):
        raise UrlError(f"主机名有超过 {MAX_LABEL_LEN} 字符的标签（RFC 1034）")
    for label in labels:
        if not _LABEL.fullmatch(label):   # 必须整段匹配：match 会放过 "a-" 这种尾巴不合规的写法
            raise UrlError(f"主机名标签 {label!r} 不符合 RFC 1123（不能为空、不能以 - 开头或结尾）")
    return wire.lower()


def split_target(raw: str):
    """校验并拆成 (scheme, host, port, rest)。rest 以 / 开头，含查询串与片段。"""
    if not isinstance(raw, str):
        raise UrlError(f"目标必须是字符串，收到 {type(raw).__name__}")
    if not raw:
        raise UrlError("目标不能为空")
    if len(raw) > MAX_TARGET_LEN:
        raise UrlError(f"目标长 {len(raw)} 字符，超过上限 {MAX_TARGET_LEN}")
    _reject_invisible(raw)

    try:
        parts = urlsplit(raw)                         # 语法拆分：标准库够用
    except ValueError as exc:
        # `http://[::1/x` 这种"方括号没闭合"的写法，urlsplit 在拆分那一刻就抛 ValueError，
        # 不是等读到 hostname/port 才抛。不接住它，非法输入就变成 500 而不是 400。
        raise UrlError(f"无法拆分：{exc}")
    scheme = (parts.scheme or "").lower()
    if not scheme:
        raise UrlError("必须带协议：相对地址会被当成站内路径，不能当目标")
    if scheme not in ALLOWED_SCHEMES:
        raise UrlError(f"协议 {scheme!r} 不在白名单 {ALLOWED_SCHEMES} 里："
                       "javascript:/data:/file: 不是网页地址，是执行通道")
    if parts.username is not None or parts.password is not None:
        raise UrlError("目标不能带 user:pass@：把凭据藏进短链是钓鱼的常见做法")

    try:
        # 这两个属性都会抛 ValueError：端口不是数字、IPv6 方括号没闭合（`http://[::1/x`）。
        # 不接住的话，非法输入就从"400 一条说明"变成"500 加一句 Python 内部错误"。
        port = parts.port
        hostname = parts.hostname
    except ValueError as exc:
        raise UrlError(f"主机/端口无法解析：{exc}")
    if port is not None and not 1 <= port <= 65535:
        raise UrlError(f"端口 {port} 越界")     # 兜底：标准库放行范围之外的写法
    host = _host_to_wire(parts.netloc, hostname)

    # rest 用"协议 + :// + 授权段"的长度定位，不能用 index(netloc)：
    # http://h/p 里 netloc 是 "h"，而 "h" 先出现在协议名里，切片会切错。
    if not raw.lower().startswith(f"{scheme}://"):
        raise UrlError("协议后面必须是 //")
    rest = raw[len(parts.scheme) + 3 + len(parts.netloc):]
    if not rest:
        rest = "/"                             # http://a 与 http://a/ 是同一个目标
    elif rest[0] in "?#":
        rest = "/" + rest                      # 没有路径段时补 /，免得 "http://a?x" 变成相对写法
    if rest.startswith("//"):
        raise UrlError("路径以 // 开头：浏览器会当成协议相对地址重新选主机")
    rest = _normalize_percent(rest)
    _reject_excluded(rest)
    return scheme, host, port, rest


def _assemble(scheme: str, host: str, port: int | None, rest: str) -> str:
    target = f"{scheme}://{host}"
    if port and port != DEFAULT_PORTS.get(scheme):
        target += f":{port}"                   # 默认端口写出来也等价，规范化时省掉
    return target + rest


def normalize_target(raw: str, *, self_hosts: tuple = (), redirect_prefix: str = "/l/") -> str:
    """校验 + 规范化成可以直接写进 `Location` 的纯 ASCII 目标。

    self_hosts / redirect_prefix 由应用层给出（它才知道自己监听在哪），
    用来挡"短链指向自己的短链"这种自指环。
    """
    scheme, host, port, rest = split_target(raw)
    bare = host.strip("[]").lower()            # [::1] 与 ::1 是同一台机器
    if bare in {h.strip("[]").lower() for h in self_hosts} \
            and redirect_prefix and rest.startswith(redirect_prefix):
        raise UrlError(f"目标指向本站自己的 {redirect_prefix} 路径，会形成跳转环")
    wire = _iri_to_uri(_assemble(scheme, host, port, rest))
    if any(not (0x20 <= ord(ch) <= 0x7E) for ch in wire):
        raise UrlError("规范化之后仍含不可打印字符")   # 兜底：Location 只允许可见 ASCII
    return wire


def merge_query(target: str, pairs) -> str:
    """把访客带进来的查询串并进目标：搜索词、utm 这类参数理应跟着一起跳过去。

    顺序是"目标自带的在前、访客的在后"，两边同名键就都留着——去重是业务判断，
    不是 URL 拼装该偷偷做的事。片段必须留在最后：`#` 之后的东西永远到不了服务器，
    但也别把查询拼到片段后面，那会把它变成片段的一部分。
    """
    pairs = list(pairs)
    if not pairs:
        return target
    if len(pairs) > MAX_MERGED_QUERY:
        raise UrlError(f"查询参数 {len(pairs)} 个，超过 {MAX_MERGED_QUERY} 个上限")
    scheme, host, port, rest = split_target(target)
    path_query, _, fragment = rest.partition("#")
    extras = "&".join(f"{_quote_pair(k)}={_quote_pair(v)}" for k, v in pairs)
    joined = path_query + ("&" if "?" in path_query else "?") + extras
    merged = _iri_to_uri(_assemble(scheme, host, port, joined + (f"#{fragment}" if fragment else "")))
    if len(merged) > MAX_TARGET_LEN:
        raise UrlError(f"合并查询串后目标长 {len(merged)}，超过 {MAX_TARGET_LEN}")
    return merged


def _quote_pair(text: str) -> str:
    """键与值只保留 RFC 3986 的非保留字符，其余一律百分号编码。"""
    out = []
    for ch in text:
        if ch.isalnum() or ch in "-._~":
            out.append(ch)
        else:
            out.extend("%%%02X" % b for b in ch.encode("utf-8"))
    return "".join(out)


def _iri_to_uri(text: str) -> str:
    """残留的非 ASCII 字符按 UTF-8 百分号编码——响应头只允许 ASCII 字节。"""
    if text.isascii():
        return text
    out = []
    for ch in text:
        if ord(ch) < 0x80:
            out.append(ch)
        else:
            out.extend("%%%02X" % b for b in ch.encode("utf-8"))
    return "".join(out)
