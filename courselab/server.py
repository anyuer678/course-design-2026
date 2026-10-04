"""courselab/server.py —— 课程工坊（CourseLab）服务骨架。

M0：标准库 ThreadingHTTPServer + 自研路由表 + JSON API + 静态托管 + 内容源代理 + 自检。
边界（沿用课设仓库 lab.py 的纪律）：默认只绑回环；零第三方依赖；客户端带不了任意命令。
课程/项目数据现算自仓库（showcase/manifest.json 是唯一出处）。

用法：
    python courselab/server.py              # 起在 127.0.0.1:7900
    python courselab/server.py --port 7930  # 换端口
    python courselab/server.py --selftest   # 自检：health / 课程目录 / 首页 / 项目页
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # courselab/
REPO = ROOT.parent                              # 课设仓库根（内容源）
WEB = ROOT / "web"
MANIFEST = REPO / "showcase" / "manifest.json"

JSON_TYPE = "application/json; charset=utf-8"


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def courses_payload() -> dict:
    """课程目录现算：manifest.json 是唯一出处，平台不维护第二份。"""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = [{
        "id": p["id"],
        "course": p["course"],
        "title": p["title"],
        "batch": str(p["batch"]),
        "status": p["status"],
        "page": p.get("page"),
    } for p in data["projects"]]
    return {"ok": True, "count": len(items), "courses": items}


class Handler(SimpleHTTPRequestHandler):
    server_version = "CourseLab/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[courselab] %s\n" % (fmt % args))

    def send_json(self, obj, code: int = 200):
        body = _json_bytes(obj)
        self.send_response(code)
        self.send_header("Content-Type", JSON_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import unquote, urlparse
        path = urlparse(self.path).path
        if path == "/health":
            return self.send_json({"ok": True, "app": "courselab", "version": "0.1"})
        if path == "/api/courses":
            try:
                return self.send_json(courses_payload())
            except (OSError, ValueError) as exc:
                return self.send_json({"ok": False, "error": "课程目录读取失败：%s" % exc}, 500)
        if path.startswith("/repo/"):
            return self._serve_repo(unquote(path[len("/repo/"):]))
        return super().do_GET()

    def _serve_repo(self, rel: str):
        """内容源代理：只允许仓库内真实文件（解析后再判前缀，防目录穿越）。"""
        root = REPO.resolve()
        target = (REPO / rel).resolve()
        if not str(target).startswith(str(root)) or not target.is_file():
            return self.send_json({"ok": False, "error": "not found"}, 404)
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(target)))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def serve(port: int) -> int:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"课程工坊已启动：http://127.0.0.1:{port}/（Ctrl+C 结束）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def selftest(port: int = 7901) -> int:
    ok = True

    def check(label, cond, extra=""):
        nonlocal ok
        print(("[PASS] " if cond else "[FAIL] ") + label + (f"  {extra}" if extra else ""))
        ok = ok and bool(cond)

    t = threading.Thread(target=serve, args=(port,), daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    t0 = time.time()
    while time.time() - t0 < 10:
        try:
            urllib.request.urlopen(base + "/health", timeout=1).read()
            break
        except OSError:
            time.sleep(0.1)

    with urllib.request.urlopen(base + "/health", timeout=5) as r:
        health = json.loads(r.read().decode("utf-8"))
    check("health 就绪", health.get("ok") and health.get("app") == "courselab")

    with urllib.request.urlopen(base + "/api/courses", timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
    check("课程目录现算（33 个项目）", data.get("ok") and data.get("count", 0) >= 33,
          f"{data.get('count')} 项")

    with urllib.request.urlopen(base + "/", timeout=5) as r:
        page = r.read().decode("utf-8", "replace")
        check("首页 200 且含平台名", r.status == 200 and "CourseLab" in page)

    first = next((c for c in data.get("courses", []) if c.get("page")), None)
    if first:
        with urllib.request.urlopen(base + "/repo/" + first["page"], timeout=10) as r:
            body = r.read(400)
        check(f"项目页经 /repo/ 可打开（{first['id']}）", r.status == 200 and len(body) > 50)

    print("CourseLab 自检：" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="课程工坊 CourseLab（课程项目平台）")
    ap.add_argument("--port", type=int, default=7900)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])
    if args.selftest:
        return selftest()
    return serve(args.port)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
