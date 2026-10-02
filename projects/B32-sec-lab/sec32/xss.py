"""sec32/xss.py —— HTML 注入（XSS 的机制层）：回显给浏览器的字节里，脚本还在不在。

课程概念：
    HTML 是**标记语言**，定界符（`< > " ' &`）一旦由数据携带，数据就升格成标记。
    这和 SQL 注入是同一个错误模型——数据与代码共用一条通道——只是解析方从数据库
    换成了浏览器。防御也是同一句话：**别让承载数据的位置拥有语法身份**。

三件课本讲得含糊、这里用实测说清的事：

1. **转义要按上下文**。文本节点、属性值、`<script>` 里的字符串、`href` 的协议位，
   四者的定界符不同。`html.escape(quote=True)` 管不了 `<script>` 内部（脚本内容不解析
   HTML 实体），而数据里的反斜杠（backslash）会**吞掉** JS 字符串的右定界符，把后面的代码吸进
   字面量。所以脚本上下文要用 `json.dumps` 并按 JS 词法处理。
2. **`&` 不转义会造成"假转义"**：只替换 `< >` 时，输入 `&lt;script&gt;` 会被浏览器
   解回 `<script>`。判定表里单列一条载荷专门量这个。
3. **Content-Type 决定这些字节算不算 HTML**。`text/plain` 里 `<script>` 是文本，
   `text/html` 里才是标记——所以 HTTP 层不是旁观者，本模块真的起服务真发请求。

验收边界（写明，不假装）：本模块证明到**响应字节**与**Content-Type**这一层。
"浏览器打开后会不会真的执行脚本"属浏览器行为，本机策略禁止自动化驱动浏览器，
那一步标**未验证**，写成 README 的练习而不是勾选项。
"""
from __future__ import annotations

import html
import http.client
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 载荷集合：只对本实验自己的回显生效，是机制样本而不是攻击工具。
PAYLOADS = {
    "脚本标签": "<script>alert(1)</script>",
    "属性逃逸": '"><img src=x onerror=alert(1)>',
    "假转义（二次解码）": "&lt;script&gt;alert(1)&lt;/script&gt;",
    "吞定界符的反斜杠": "\\",
    "提前闭合脚本块": "</script><script>alert(1)</script>",
    "javascript 协议": "javascript:alert(1)",
}

TEXT_MARKERS = ("<script>", "<img", "</p>", "</script>")


# ---------------------------------------------------------------- 两种渲染
def render_vuln(name: str) -> str:
    """四种上下文全部直接回显——"没转义"的教科书形态。"""
    return "\n".join([
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><title>echo</title></head><body>",
        f"<p>{name}</p>",                       # 文本节点
        f"<input value=\"{name}\">",                   # 属性值
        f"<script>var greeting = \"{name}\";</script>",   # JS 字符串
        f"<a href=\"{name}\">我的链接</a>",             # URL 协议位
        "</body></html>",
    ])


def escape_text(name: str) -> str:
    """文本节点与属性值：`html.escape(quote=True)`。

    `quote=True` 不是可选项——属性值由引号闭合，不转义 `"` 就是给逃逸留出口。
    `&` 必须转，否则 `&lt;` 会被浏览器解回 `<`（假转义）。
    """
    return html.escape(name, quote=True)


def escape_script(name: str) -> str:
    """`<script>` 里的字符串：按 **JS 词法**生成字面量。

    `json.dumps` 连反斜杠一起处理，因此不会出现"数据吞掉右定界符"；
    再把 `</` 断开，防止数据里的 `</script>` 提前闭合脚本块。
    """
    return json.dumps(name).replace("</", "<\\/")


def safe_href(name: str) -> str:
    """URL 上下文不靠转义，靠**协议白名单**：`javascript:` 不是"另一种网页"。"""
    scheme = urllib.parse.urlsplit(name).scheme.lower()
    return html.escape(name if scheme in ("", "http", "https") else "#blocked",
                       quote=True)


def render_safe(name: str) -> str:
    """按上下文分别处理；输出仍要能逐字还原成原输入（见 roundtrip 判定）。"""
    guarded = escape_text(name)
    return "\n".join([
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><title>echo</title></head><body>",
        f"<p>{guarded}</p>",
        f"<input value=\"{guarded}\">",
        f"<script>var greeting = {escape_script(name)};</script>",
        f"<a href=\"{safe_href(name)}\">我的链接</a>",
        "</body></html>",
    ])


# ---------------------------------------------------------------- 字节级取证
def text_node(page: str) -> str:
    return page.split("<p>", 1)[1].split("</p>", 1)[0]


def js_literal(page: str) -> str:
    """取出 `var greeting = ` 之后、行尾 `;` 之前的源码片段。"""
    line = next(ln for ln in page.splitlines() if "var greeting" in ln)
    return line.split("var greeting = ", 1)[1].rsplit(";", 1)[0]


def js_literal_hijacked(page: str, name: str) -> bool:
    """数据有没有改写 JS 字面量的边界？判定 = 按 JS 词法解析这段字面量，看能否还原输入。

    还原不了（解析抛错或结果不等）就说明定界符被数据动了——这是**语法层**的证据，
    不依赖浏览器。
    """
    try:
        return json.loads(js_literal(page)) != name
    except (ValueError, json.JSONDecodeError):
        return True


def evidence(page: str, name: str) -> list[str]:
    """页面上"数据拿到了语法身份"的信号，逐条列出。

    每条判定都对应一个**具体的解析器行为**，不是"字符串里出现了尖括号"这种松口径：
      1. 文本节点应当**逐字等于** `html.escape(quote=True)` 的输出（标准库就是参照实现）。
         不等时再分两种情形报告：数据里的标记是原样留下的，还是留成了实体
         （`&lt;` 这种，浏览器解一次就变回标记——`&` 没转义的直接后果）；
      2. `</script` 出现多于一次 ⇒ 数据提前闭合了脚本块（`<script` 本身不算，
         脚本内容按原始文本处理；把它也当信号是我把判定写强了，实测会在修复版上误报）；
      3. JS 字面量按词法还原不回原输入 ⇒ 定界符被数据改写（反斜杠吞引号那类）；
      4. 属性行上双引号数量异常 ⇒ 数据提前闭合了属性；
      5. `href` 落在 `javascript:` 协议上 ⇒ 协议位被数据决定。
    """
    out = []
    node = text_node(page)
    if node != escape_text(name):
        if any(marker in node for marker in TEXT_MARKERS):
            out.append("文本节点未被转义，数据里的标记原样在场")
        elif any(marker in html.unescape(node) for marker in TEXT_MARKERS):
            out.append("文本节点里的实体解一次就变成标记（& 未转义的直接后果）")
        else:
            out.append("文本节点与参照转义输出不一致")
    closes = page.count("</script")
    if closes > 1:
        out.append(f"脚本块被数据提前闭合（</script 出现 {closes} 次，页面自己应是 1 次）")
    if js_literal_hijacked(page, name):
        out.append("JS 字面量被数据改写（按词法还原失败）")
    for tag in ("<input value=", '<a href='):
        line = next(ln for ln in page.splitlines() if tag in ln)
        if line.count('"') > 2:
            out.append(f"属性 {tag!r} 所在行出现 {line.count(chr(34))} 个双引号（应为 2）")
    href = page.split('<a href="', 1)[1].split('"', 1)[0]
    if href.startswith("javascript:"):
        out.append("href 协议位接受了 javascript:")
    return out


def payload_table() -> list[dict]:
    """六个载荷 × 两种渲染，判定全部现跑。"""
    rows = []
    for label, payload in PAYLOADS.items():
        vuln, safe = render_vuln(payload), render_safe(payload)
        rows.append({
            "label": label, "payload": payload,
            "vuln_evidence": evidence(vuln, payload),
            "safe_evidence": evidence(safe, payload),
            "safe_roundtrip": (html.unescape(text_node(safe)) == payload
                               and json.loads(js_literal(safe)) == payload),
            "vuln_raw_echo": payload in vuln,
        })
    return rows


# ---------------------------------------------------------------- HTTP 取证层
class _EchoHandler(BaseHTTPRequestHandler):
    """把两种渲染真的做成 HTTP 响应：证明 Content-Type 与字节都上了线。"""

    mode = "safe"
    protocol_version = "HTTP/1.1"

    def do_GET(self):                          # noqa: N802（stdlib 约定的方法名）
        query = urllib.parse.urlsplit(self.path).query
        name = urllib.parse.parse_qs(query, keep_blank_values=True).get("name", [""])[0]
        body = (render_safe if self.mode == "safe" else render_vuln)(name).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):               # demo 里不要 stderr 噪声
        pass


def serve_once(payload: str, mode: str) -> dict:
    """起一次真服务（127.0.0.1 临时端口）→ 真发 GET → 读回状态/头/体 → 关掉。

    价值在于把"渲染函数返回了一个字符串"升级成"线上跑的字节就是这些"。
    不写文件、不留进程（`finally` 里 shutdown + server_close + join）。
    """
    _EchoHandler.mode = mode
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/?name=" + urllib.parse.quote(payload))
        resp = conn.getresponse()
        raw = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        status = resp.status
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    body = raw.decode("utf-8")
    return {"status": status, "headers": headers, "body": body,
            "evidence": evidence(body, payload), "port": port,
            "is_html": headers.get("content-type", "").startswith("text/html")}


def serve_both(payload: str) -> dict:
    """同一载荷走两种渲染各一次；HTTP 层证据必须和纯函数层一致。"""
    return {"vuln": serve_once(payload, "vuln"), "safe": serve_once(payload, "safe")}
