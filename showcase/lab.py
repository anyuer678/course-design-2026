"""showcase/lab.py —— 本地"实验台"：把静态展示页接上**真实后端**（纯标准库，零依赖）。

静态展示页双击即看只是"录像"；本实验台让页面变成**控制台**：真的启动/停止各项目的
真实服务、真的发请求（原始字节进、原始字节出）、真的把服务日志流回页面。

用法：
    python showcase/lab.py                # 起在 127.0.0.1:7788（双击仓库根 lab.bat 同款）
    # 总入口 http://127.0.0.1:7788/showcase/index.html 即「项目群控制台」：
    #   每个项目行可 启动/停止真实服务、跑 demo/测试/run.bat（可随时停止）、看实时日志；
    #   各项目页的「实时实验台」分节也会就地变成控制台。
    python showcase/lab.py --lan          # 静态页绑 0.0.0.0 供局域网访问（控制仍只限本机）
    python showcase/lab.py --open         # 启动后自动打开浏览器总入口（lab.bat 默认传）
    python showcase/lab.py --selftest     # 自检：真起 B31 服务 → 真发请求 → 真停，PASS/FAIL
    # 已在跑时再启动不是错误（2026-10-04）：复用已有实验台、按需开页面、退出 0。

安全边界（先说死）：
- 默认只绑回环地址；静态根 = 仓库根（实验台就是本机开发工具）；
- `--lan` 只把**静态页**放开给局域网；`/lab/api/*`（含只读的 overview）一律**只接受回环
  来源**，远端拿到的只有 403——控制面永远不出去；
- `/lab/api/*` 只认识注册表里的**固定命令**：客户端只能选 id，不能携带命令/参数/路径；
- `/lab/api/sock` 只在"本实验台启动的端口"上做连接转发，不接受任意地址；
- 所有子进程在实验台退出时统一清理（atexit），不会留孤儿。
"""
from __future__ import annotations

import argparse
import atexit
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # 仓库根
PY = sys.executable

#: 可启动的真实服务（命令固定、端口固定、示例请求供页面预填）。
#: 每个命令都是"照着各自 demo/文档抄的构造方式"，不含任何客户端可控参数。
SERVE = {
    "B11-net-lab": {
        "argv": [PY, "-c",
                 ("from netlab.server import Server; s = Server(port=8311); s.start(); "
                  "print('netlab 已启动 127.0.0.1:%d' % s.port, flush=True); "
                  "import time; time.sleep(10**8)")],
        "port": 8311,
        "sample": "GET /kv/repair HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\nConnection: close\\r\\n\\r\\n",
        "hint": "HTTP/1.1 子集 + 单线程 select；示例是读回演示里 PUT 过的键",
    },
    "B31-shorturl": {
        "argv": [PY, "-m", "b31.server", "--port", "8312", "--memory"],
        "port": 8312,
        "sample": 'POST /api/links HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\nContent-Type: application/json\\r\\n'
                  'Content-Length: 19\\r\\nConnection: close\\r\\n\\r\\n{"url":"http://a/"}',
        "hint": "真短链服务：POST 建链 → 302 跳转计命中（示例就是建一条）",
    },
    "B38-mini-redis": {
        "argv": [PY, "-c",
                 ("from redislite.server import Server; s = Server(port=8313).start(); "
                  "print('redis 子集已启动 127.0.0.1:%d' % s.port, flush=True); "
                  "import time; time.sleep(10**8)")],
        "port": 8313,
        "sample": "PING\\r\\nSET demo hello\\r\\nGET demo\\r\\nINCR n\\r\\nTTL demo\\r\\n",
        "hint": "RESP2：一行一条 inline 命令（也可发数组帧），回复按行返回",
    },
    "B35-iot-mqtt": {
        "argv": [PY, "-c",
                 ("from mqttlite.broker import Broker; b = Broker(port=8314).start(); "
                  "print('mqtt broker 已启动 127.0.0.1:%d' % b.port, flush=True); "
                  "import time; time.sleep(10**8)")],
        "port": 8314,
        "sample": "\\x10\\x13\\x00\\x04MQTT\\x04\\x02\\x00\\x3c\\x00\\x07lab-cli",
        "hint": "MQTT：示例是 CONNECT 报文（\\xNN 转义），回包应为 CONNACK 20 02 00 00",
    },
    "B28-bi-dashboard": {
        "argv": [PY, "-m", "bi.server", "--port", "8315"],
        "port": 8315,
        "sample": "GET /api/summary HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\nConnection: close\\r\\n\\r\\n",
        "hint": "看板服务：/api/summary、/api/drill?month_from=&month_to=",
    },
    "dorm-repair": {
        "argv": [PY, "-m", "prototype.server", "--port", "8316"],
        "port": 8316,
        "sample": "GET / HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\nConnection: close\\r\\n\\r\\n",
        "hint": "B16 原型服务：非回环访问会被拒（服务端自身策略）",
    },
}

def _actions_of(pid: str) -> list:
    """某项目在实验台里的可做动作（info 与 overview 共用，口径唯一）。"""
    serve = SERVE.get(pid)
    acts = []
    if serve:
        acts.append({"id": "serve_start", "label": f"启动真实服务（:{serve['port']}）"})
        acts.append({"id": "serve_stop", "label": "停止服务"})
    for key, label in (("demo", "运行 demo.py"), ("tests", "跑测试套件"), ("run", "运行 run.bat")):
        if pid in RUN and key in RUN[pid]:
            acts.append({"id": key, "label": label})
    if pid in RUN and pid not in SERVE:
        # run/demo/测试是长任务，必须有中止入口（_stop 对任意 kind 都有效；
        # SERVE 项目已有"停止服务"按钮，不重复给）——2026-10-04 操作补全
        acts.append({"id": "stop_run", "label": "停止运行"})
    return acts


def _is_loopback(host: str) -> bool:
    """回环判定：控制类 API 只认这些来源（含 IPv4 映射形式）。"""
    return host in ("127.0.0.1", "::1", "::ffff:127.0.0.1") or host.startswith("127.")


#: 可运行的现成动作（demo / 测试 / run.bat），全部按 run.bat 同款命令。
def _run_entries(pid: str, demo: bool, tests: bool, bat=None) -> dict:
    out = {}
    if demo:
        out["demo"] = [PY, "demo.py"]
    if tests:
        out["tests"] = [PY, "-m", "unittest", "discover", "-s", "tests"]
    if bat is not None:
        # 注意 bat=[] 是合法用法（run.bat 不带附加参数）——不能用 `if bat:` 判（2026-10-04 修：
        # 这个真值判断曾让 B1/B2/B5/B6/B7/B9 的 run 动作整个消失，动作表静默为空）
        out["run"] = ["cmd", "/c", "run.bat"] + bat
    return out


RUN = {}
for _pid, (_demo, _tests) in {
    "B3-logic-lab": (True, True), "B4-algebra-rsa": (True, True),
    "B10-minidb": (True, True), "B11-net-lab": (True, True),
    "B12-algo-arena": (True, True), "B13-tinylang": (True, True),
    "B23-ml-from-scratch": (True, True), "B24-cv-scanner": (True, True),
    "B25-nlp-lab": (True, True), "B26-datamining": (True, True),
    "B27-course-kg": (True, True), "B28-bi-dashboard": (True, True),
    "B29-bigdata-spark": (True, True), "B30-mini-raft": (True, True),
    "B31-shorturl": (True, True), "B32-sec-lab": (True, True),
    "B33-viz-algo": (True, True), "B34-path-planner": (True, True),
    "B35-iot-mqtt": (True, True), "B37-industry-ai": (True, True),
    "B38-mini-redis": (True, True), "B39-tech-radar": (True, True),
    "B40-career-map": (True, True), "B41-thesis-seeds": (True, True),
    "dorm-repair": (True, True),
}.items():
    RUN[_pid] = _run_entries(_pid, _demo, _tests)
RUN["B1-cpp-ministl"] = _run_entries("", False, False, bat=[])
RUN["B2-datastruct-lab"] = _run_entries("", False, False, bat=[])
RUN["B5-cpu-sim"] = _run_entries("", False, False, bat=[])
RUN["B6-asm-lab"] = _run_entries("", False, False, bat=[])
RUN["B7-mini-make"] = _run_entries("", False, False, bat=[])
RUN["B9-os-sim"] = _run_entries("", False, False, bat=[])
RUN["B14-java-paint"] = _run_entries("", False, False, bat=["no-gui"])
# B8 的演示/测试要在 WSL 里跑（run.bat 走 wsl -d Ubuntu-24.04），实验台不替它决定环境，
# 页面控制台会如实显示"本项目未接实验台动作（见 README 的 WSL 入口）"。

LOCK = threading.Lock()
STATES: dict = {}          # pid -> {"proc", "kind", "started", "lines": deque, "reader"}
PORT_OWNERS: dict = {}     # port -> pid（sock 转发只认它）


def _log(pid: str, text: str) -> None:
    st = STATES.setdefault(pid, {"proc": None, "kind": None, "started": 0.0,
                                 "lines": deque(maxlen=4000)})
    st["lines"].append(text.rstrip("\n"))


def _pump(pid: str, stream) -> None:
    for line in iter(stream.readline, ""):
        _log(pid, line)
    stream.close()


def _state_of(pid: str) -> dict:
    st = STATES.get(pid, {})
    proc = st.get("proc")
    running = proc is not None and proc.poll() is None
    return {
        "project": pid,
        "kind": st.get("kind"),
        "running": running,
        "pid": proc.pid if running else None,
        "port": SERVE.get(pid, {}).get("port") if running else None,
        "up": round(time.time() - st.get("started", 0), 1) if running else None,
    }


def _spawn(pid: str, argv: list, kind: str, cwd: Path) -> dict:
    with LOCK:
        st = STATES.setdefault(pid, {"proc": None, "kind": None, "started": 0.0,
                                     "lines": deque(maxlen=4000)})
        if st.get("proc") is not None and st["proc"].poll() is None:
            return {"ok": False, "error": "已有进程在跑，请先停"}
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        assert str(ROOT) in str(cwd) or cwd.is_dir(), cwd
        proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", bufsize=1)
        st.update({"proc": proc, "kind": kind, "started": time.time()})
        _log(pid, f"$ {' '.join(argv)}")
        t = threading.Thread(target=_pump, args=(pid, proc.stdout), daemon=True)
        t.start()
        st["reader"] = t
        return {"ok": True, "pid": proc.pid}


def _stop(pid: str) -> dict:
    with LOCK:
        st = STATES.get(pid) or {}
        proc = st.get("proc")
    if proc is None or proc.poll() is not None:
        return {"ok": True, "already": True}
    # Windows 下 terminate() 只杀外壳：cmd /c run.bat 的子进程会活下来继续跑到完成，
    # 页面显示"已停止"日志却还在长——用 taskkill /T 杀整棵树才对得上用户预期（2026-10-04）
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=10)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    _log(pid, "[实验台] 已停止")
    return {"ok": True}


def _wait_port(port: int, proc, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def start_server(pid: str) -> dict:
    spec = SERVE.get(pid)
    if not spec:
        return {"ok": False, "error": "本项目没有注册可启动的常驻服务"}
    out = _spawn(pid, spec["argv"], "serve", ROOT / "projects" / pid)
    if not out.get("ok"):
        return out
    proc = STATES[pid]["proc"]
    if not _wait_port(spec["port"], proc):
        tail = "\n".join(list(STATES[pid]["lines"])[-8:])
        _stop(pid)
        return {"ok": False, "error": "服务 10 秒内未就绪", "tail": tail}
    PORT_OWNERS[spec["port"]] = pid
    _log(pid, f"[实验台] 服务就绪：127.0.0.1:{spec['port']}")
    return {"ok": True, "port": spec["port"], "pid": proc.pid}


def unescape_bytes(text: str) -> bytes:
    """把文本框里的转义文本还原成字节：\\r \\n \\t \\\\ \\xNN（与页面 lab.js 同一规则）。"""
    out = bytearray()
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            n = text[i + 1]
            if n == "r":
                out.append(13); i += 2; continue
            if n == "n":
                out.append(10); i += 2; continue
            if n == "t":
                out.append(9); i += 2; continue
            if n == "\\":
                out.append(92); i += 2; continue
            if n == "x" and i + 4 <= len(text):
                try:
                    out.append(int(text[i + 2:i + 4], 16)); i += 4; continue
                except ValueError:
                    pass
        out.extend(c.encode("utf-8"))
        i += 1
    return bytes(out)


def sock_probe(pid: str, data: bytes, wait: float = 1.5) -> dict:
    port = SERVE.get(pid, {}).get("port")
    if not port or PORT_OWNERS.get(port) != pid:
        return {"ok": False, "error": "请先在实验台里启动该项目的服务"}
    t0 = time.time()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            pass
        s = socket.create_connection(("127.0.0.1", port), timeout=3)
        s.sendall(data)
        s.settimeout(wait)
        buf = b""
        while len(buf) < 65536:
            try:
                chunk = s.recv(4096)
            except TimeoutError:
                break
            if not chunk:
                break
            buf += chunk
        s.close()
    except OSError as e:
        return {"ok": False, "error": f"连接失败：{e}"}
    return {"ok": True, "sent": len(data), "got": len(buf),
            "ms": round((time.time() - t0) * 1000, 1),
            "hex": buf.hex(" "), "text": buf.decode("utf-8", "replace"),
            "bytes": list(buf)}


def _cleanup() -> None:
    for pid in list(STATES):
        _stop(pid)


atexit.register(_cleanup)


# ------------------------------------------------------------------ HTTP 层

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):        # 静音：实验台不打自己访问日志
        pass

    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    def send_error(self, code, message=None, explain=None):
        # 404 换成指路页：实验台的静态根 = 仓库根，总入口最省事（2026-10-03 用户实测 404 后补）
        if code == 404:
            body = (
                "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head><meta charset=\"utf-8\">"
                "<title>404 · 展示层实验台</title></head>\n"
                "<body style=\"font:15px/1.8 system-ui,'Microsoft YaHei',sans-serif;"
                "margin:2rem;color:#1c2330\">\n"
                "<h2>404：没有这个路径</h2>\n"
                "<p>实验台的静态根是<b>仓库根</b>——总入口在 "
                "<a href=\"/showcase/index.html\">/showcase/index.html</a>，"
                "各项目页在 /projects/&lt;项目&gt;/web/showcase.html（从总入口点进去最省事）。</p>\n"
                "</body></html>").encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        super().send_error(code, message, explain)

    # 跨源预检：file:// 打开页面时，POST JSON 会先发 OPTIONS
    def do_OPTIONS(self):
        self._json({"ok": True})

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        u = urlparse(self.path)
        if u.path == "/":
            self.send_response(302)
            self.send_header("Location", "/showcase/index.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not u.path.startswith("/lab/api/"):
            return super().do_GET()
        if not _is_loopback(self.client_address[0]):
            return self._json({"ok": False,
                               "error": "控制 API 只接受本机（回环）请求；局域网可访问静态页"}, 403)
        q = parse_qs(u.query)
        if u.path == "/lab/api/ping":
            return self._json({"ok": True, "hub": "showcase-lab", "version": 1})
        if u.path == "/lab/api/overview":
            # 项目群控制台用：一次拿到全部项目的动作与实时状态（只读）
            ids = []
            manifest = ROOT / "showcase" / "manifest.json"
            if manifest.is_file():
                try:
                    ids = [p["id"] for p in
                           json.loads(manifest.read_text(encoding="utf-8"))["projects"]]
                except (ValueError, KeyError):
                    ids = []
            projects = [{
                "project": pid,
                "port": SERVE[pid]["port"] if pid in SERVE else None,
                "actions": _actions_of(pid),
                "state": _state_of(pid),
                "page": f"/projects/{pid}/web/showcase.html",
            } for pid in (ids or sorted(set(SERVE) | set(RUN)))]
            return self._json({"ok": True, "projects": projects})
        if u.path == "/lab/api/info":
            pid = (q.get("project") or [""])[0]
            serve = SERVE.get(pid)
            return self._json({
                "ok": True, "project": pid, "actions": _actions_of(pid),
                "state": _state_of(pid),
                "sample": serve.get("sample") if serve else None,
                "hint": serve.get("hint") if serve else None,
            })
        if u.path == "/lab/api/log":
            pid = (q.get("project") or [""])[0]
            start = int((q.get("from") or ["0"])[0])
            lines = list((STATES.get(pid) or {}).get("lines", []))
            return self._json({"ok": True, "from": len(lines), "lines": lines[start:],
                               "state": _state_of(pid)})
        return self._json({"ok": False, "error": "unknown api"}, 404)

    def do_POST(self):
        if not self.path.startswith("/lab/api/"):
            return self._json({"ok": False, "error": "unknown"}, 404)
        if not _is_loopback(self.client_address[0]):
            return self._json({"ok": False,
                               "error": "控制 API 只接受本机（回环）请求；局域网可访问静态页"}, 403)
        data = self._body()
        pid = str(data.get("project") or "")
        if self.path == "/lab/api/start":
            return self._json(start_server(pid))
        if self.path == "/lab/api/stop":
            return self._json(_stop(pid))
        if self.path == "/lab/api/run":
            kind = str(data.get("kind") or "")
            cmds = RUN.get(pid, {})
            if kind not in cmds:
                return self._json({"ok": False, "error": "本项目未注册该动作"}, 400)
            return self._json(_spawn(pid, cmds[kind], kind, ROOT / "projects" / pid))
        if self.path == "/lab/api/sock":
            arr = data.get("bytes") or []
            if not isinstance(arr, list) or not all(isinstance(b, int) and 0 <= b <= 255 for b in arr):
                return self._json({"ok": False, "error": "bytes 必须是 0..255 的数组"}, 400)
            return self._json(sock_probe(pid, bytes(arr)))
        return self._json({"ok": False, "error": "unknown api"}, 404)


def _busy_hint(port: int) -> str:
    """端口有人应答时，尽力分辨是另一个实验台还是别的程序（只影响提示文案）。"""
    import urllib.request

    lab_running = False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/lab/api/ping", timeout=0.8) as r:
            lab_running = json.loads(r.read().decode("utf-8")).get("hub") == "showcase-lab"
    except (OSError, ValueError, http.client.HTTPException):
        lab_running = False     # 答非所问（非 HTTP 或坏 JSON）也算"被占"
    return "已经有一个实验台在跑" if lab_running else "这个端口被别的程序占着"


def _open_browser(url: str) -> None:
    """尽力打开浏览器；失败只提示（自动开页面是锦上添花，不影响实验台本身）。"""
    import webbrowser
    try:
        webbrowser.open(url)
    except Exception:
        print(f"    （自动打开浏览器失败，手动访问即可：{url}）")


def serve(port: int, lan: bool = False, open_browser: bool = False) -> int:
    url = f"http://127.0.0.1:{port}/showcase/index.html"
    # Windows 的 SO_REUSEADDR 允许第二个进程绑同一端口，光靠 bind 失败判不出占用；
    # 先连一下：有应答就是被占。是实验台就当"再点一次图标"——复用、开页面、退出 0；
    # 是别的程序才是错误（2026-10-04 重复双击顺滑度）。
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
    except OSError:
        pass
    else:
        hint = _busy_hint(port)
        if hint == "已经有一个实验台在跑":
            print("已有一个实验台在跑——直接用它就好（同一台机器不需要开两个）。")
            if open_browser:
                _open_browser(url)
            else:
                print(f"    要打开页面：浏览器里访问 {url}（或重跑不带 no-open 的 lab.bat）")
            if lan:
                print("    本次的 --lan 未生效：要切换局域网模式，请先在原实验台窗口按 Ctrl+C 停掉，再重跑。")
            return 0
        print(f"[!] 端口 {port} 起不来：{hint}。")
        print(f"    先在浏览器里看看 http://127.0.0.1:{port}/ ，确认是不是你想用的那个；")
        print(f"    或换端口：python showcase/lab.py --port {port + 1}")
        return 1
    host = "0.0.0.0" if lan else "127.0.0.1"
    try:
        httpd = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        print(f"[!] 端口 {port} 仍然起不来：{exc}")
        print(f"    或换端口：python showcase/lab.py --port {port + 1}")
        return 1
    print(f"实验台已启动：{url}")
    if lan:
        print("局域网模式：静态页可被同网段访问；**控制 API 只接受本机请求**（远端只会看到 403）。")
        try:
            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                if not ip.startswith("127."):
                    print(f"    局域网入口：http://{ip}:{port}/showcase/index.html")
        except OSError:
            pass
    if open_browser:
        print(f"    浏览器将在 2 秒后自动打开：{url}")
        threading.Timer(2.0, _open_browser, args=(url,)).start()
    print("（总入口与各展示页的「实时实验台」会就地变成控制台；Ctrl+C 结束，子进程会一并清理）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


# ------------------------------------------------------------------ 自检

def selftest(port: int = 7799) -> int:
    import urllib.request

    t = threading.Thread(target=serve, args=(port,), daemon=True)
    t.start()
    time.sleep(0.5)
    base = f"http://127.0.0.1:{port}"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(path, obj):
        req = urllib.request.Request(base + path, json.dumps(obj).encode("utf-8"),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))

    ok = True

    def check(label, cond, extra=""):
        nonlocal ok
        print(("[PASS] " if cond else "[FAIL] ") + label + (f"  {extra}" if extra else ""))
        ok = ok and bool(cond)

    check("ping", get("/lab/api/ping").get("ok"))
    ov = get("/lab/api/overview")
    n_ov = len(ov.get("projects") or [])
    check("overview 覆盖全部项目", ov.get("ok") and n_ov >= 33, f"{n_ov} 项")
    check("overview 里 B31 带服务动作",
          any(p["project"] == "B31-shorturl" and p["port"] == 8312
              and any(a["id"] == "serve_start" for a in p["actions"]) for p in ov["projects"]))
    b1_ids = next(([a["id"] for a in p["actions"]]
                   for p in ov["projects"] if p["project"] == "B1-cpp-ministl"), [])
    check("B1 带 run + stop_run 动作（bat=[] 回归 + 长任务可中止）",
          "run" in b1_ids and "stop_run" in b1_ids, str(b1_ids))
    no_act = [p["project"] for p in ov["projects"] if not p["actions"]]
    check("无动作项目只有 B8（WSL 入口不替它选环境）", no_act == ["B8-mini-shell"], str(no_act))
    check("回环判定（控制 API 的边界）",
          _is_loopback("127.0.0.1") and _is_loopback("::1") and _is_loopback("::ffff:127.0.0.1")
          and not _is_loopback("192.168.1.5") and not _is_loopback("::ffff:192.168.1.5")
          and not _is_loopback("10.0.0.7"))
    info = get("/lab/api/info?project=B31-shorturl")
    check("info 提供 B31 动作", any(a["id"] == "serve_start" for a in info["actions"]))
    with urllib.request.urlopen(base + "/showcase/index.html", timeout=10) as r:
        check("静态总入口 200", r.status == 200)
    rc = serve(port)   # 本自检的 hub 已在 port 上：重复启动应走快路径（复用提示）而不是报错
    check("重复启动走快路径、退出 0", rc == 0)
    r = start_server("B31-shorturl")
    check("启动真实服务", r.get("ok"), f"port={r.get('port')}")
    sample = SERVE["B31-shorturl"]["sample"]
    got = sock_probe("B31-shorturl", unescape_bytes(sample))
    check("真实请求 → 201", got.get("ok") and "201" in got.get("text", ""),
          f"got={got.get('got')}B")
    r = _stop("B31-shorturl")
    check("停止服务", r.get("ok"))
    print("实验台自检：" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="展示层实验台（本地真实后端控制）")
    ap.add_argument("--port", type=int, default=7788)
    ap.add_argument("--lan", action="store_true",
                    help="静态页绑 0.0.0.0 供局域网访问；控制 API 仍只接受本机请求")
    ap.add_argument("--open", action="store_true",
                    help="启动后自动打开浏览器总入口（lab.bat 默认传；已在跑时也用它再开页面）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])
    if args.selftest:
        return selftest()
    return serve(args.port, lan=args.lan, open_browser=args.open)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
