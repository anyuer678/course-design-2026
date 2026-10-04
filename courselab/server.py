"""courselab/server.py —— 课程工坊（CourseLab）服务端。

M1+M2：账号与会话（注册/登录/登出/PBKDF2/限流）+ 课程目录 / 课程工作区 / 项目页（含演示）。
零第三方依赖；默认只绑回环；课程与项目内容现算自仓库（app/courses.py 是唯一出处）；
权限判定只有 app/can.py 一份。

用法：
    python courselab/server.py                # http://127.0.0.1:7900/
    python courselab/server.py --port 7930    # 换端口
    python courselab/server.py --db path.db   # 换库（默认 courselab/data/app.db）
    python courselab/server.py --selftest     # 自检（临时库，不碰正式数据）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from app import auth, can, courses, labs
from app.db import DB

ROOT = Path(__file__).resolve().parent          # courselab/
REPO = ROOT.parent                              # 课设仓库根（内容源）
WEB = ROOT / "web"
DEFAULT_DB = ROOT / "data" / "app.db"

JSON_TYPE = "application/json; charset=utf-8"
COOKIE_NAME = "cl_session"


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    server_version = "CourseLab/0.2"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    # ---------------------------------------------------------- 基础工具
    def log_message(self, fmt, *args):
        sys.stderr.write("[courselab] %s\n" % (fmt % args))

    @property
    def db(self) -> DB:
        return self.server.db            # type: ignore[attr-defined]

    @property
    def labs(self) -> labs.Labs:
        return self.server.labs          # type: ignore[attr-defined]

    def send_json(self, obj, code: int = 200, set_cookie: str | None = None):
        body = _json_bytes(obj)
        self.send_response(code)
        self.send_header("Content-Type", JSON_TYPE)
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_error_json(self, code: int, message: str, err_code: str = ""):
        self.send_json({"ok": False, "error": message, "code": err_code}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        from http.cookies import SimpleCookie
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            return None
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def current_user(self):
        return auth.user_by_session(self.db, self._token())

    def _origin_ok(self) -> bool:
        """同源基线（CSRF）：带 Origin 的请求只放行本机同源。"""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return origin in (f"http://{host}", f"https://{host}")

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else ""

    # ---------------------------------------------------------- GET
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            return self.send_json({"ok": True, "app": "courselab", "version": "0.2"})

        if path == "/api/me":
            user = self.current_user()
            return self.send_json({
                "ok": True, "user": user,
                "can": {"lab_run": can.can(user, "lab_run"),
                        "manage_course": can.can(user, "manage_course"),
                        "admin": can.can(user, "admin")},
            })

        if path == "/api/courses":
            try:
                return self.send_json(courses.course_list())
            except (OSError, ValueError) as exc:
                return self.send_error_json(500, f"课程目录读取失败：{exc}")

        if path.startswith("/api/courses/"):
            cid = unquote(path[len("/api/courses/"):]).strip("/")
            detail = courses.course_detail(cid)
            if detail is None:
                return self.send_error_json(404, "课程不存在", "NO_COURSE")
            user = self.current_user()
            detail["can"] = {"lab_run": can.can(user, "lab_run", cid)}
            detail["lab"] = labs.describe(cid)
            return self.send_json({"ok": True, "course": detail})

        if path == "/api/labs/active":
            if self.current_user() is None:
                return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
            return self.send_json(self.labs.active())

        if path == "/api/labs/runs/mine":
            user = self.current_user()
            if user is None:
                return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
            return self.send_json({"ok": True, "runs": self.labs.mine(user["id"])})

        if path.startswith("/api/labs/runs/"):
            user = self.current_user()
            if user is None:
                return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
            if path.endswith("/log"):
                run_id = unquote(path[len("/api/labs/runs/"):-len("/log")]).strip("/")
                meta = self.labs.status(run_id)
                if meta is None:
                    return self.send_error_json(404, "没有这个运行记录", "NO_RUN")
                if not self._can_view_run(user, meta):
                    return self.send_error_json(403, "只能看自己的实验日志", "FORBIDDEN")
                return self._sse(self.labs.stream(run_id))
            run_id = unquote(path[len("/api/labs/runs/"):]).strip("/")
            meta = self.labs.status(run_id)
            if meta is None:
                return self.send_error_json(404, "没有这个运行记录", "NO_RUN")
            if not self._can_view_run(user, meta):
                return self.send_error_json(403, "只能看自己的实验记录", "FORBIDDEN")
            return self.send_json({"ok": True, "run": meta})

        if path.startswith("/repo/"):
            return self._serve_repo(unquote(path[len("/repo/"):]))

        return super().do_GET()

    def _serve_repo(self, rel: str):
        """内容源代理：只允许仓库内真实文件（解析后再判前缀，防目录穿越）。"""
        root = REPO.resolve()
        target = (REPO / rel).resolve()
        if not str(target).startswith(str(root)) or not target.is_file():
            return self.send_error_json(404, "not found")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(target)))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _can_view_run(self, user, meta) -> bool:
        return user["id"] == meta["user_id"] or can.can(user, "manage_course")

    def _sse(self, gen):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for event, data in gen:
                chunk = "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------------------------------------------------------- POST
    def do_POST(self):
        path = urlparse(self.path).path
        if not self._origin_ok():
            return self.send_error_json(403, "跨源请求被拒绝", "BAD_ORIGIN")
        data = self._body()
        try:
            if path == "/api/auth/register":
                return self._register(data)
            if path == "/api/auth/login":
                return self._login(data)
            if path == "/api/auth/logout":
                return self._logout()
            if path == "/api/labs/run":
                return self._lab_run(data)
            if path.startswith("/api/labs/runs/") and path.endswith("/stop"):
                return self._lab_stop(path)
        except (auth.AuthError, labs.LabsError) as exc:
            return self.send_error_json(exc.http, exc.message, exc.code)
        return self.send_error_json(404, "unknown api")

    def _lab_run(self, data):
        user = self.current_user()
        if user is None:
            return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
        if not can.can(user, "lab_run"):
            return self.send_error_json(403, "没有实验权限", "FORBIDDEN")
        out = self.labs.start(user, str(data.get("project") or ""),
                              str(data.get("action") or ""))
        return self.send_json(out)

    def _lab_stop(self, path):
        user = self.current_user()
        if user is None:
            return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
        run_id = unquote(path[len("/api/labs/runs/"):-len("/stop")]).strip("/")
        meta = self.labs.status(run_id)
        if meta is None:
            return self.send_error_json(404, "没有这个运行记录", "NO_RUN")
        if not self._can_view_run(user, meta):
            return self.send_error_json(403, "只能停自己的实验", "FORBIDDEN")
        return self.send_json(self.labs.stop(run_id))

    def _register(self, data):
        user = auth.register(self.db, str(data.get("username") or "").strip(),
                             str(data.get("display_name") or "").strip(),
                             str(data.get("password") or ""))
        token = auth.create_session(self.db, user["id"], self._client_ip(),
                                    self.headers.get("User-Agent", ""))
        return self.send_json({"ok": True, "user": user},
                              set_cookie=self._cookie(token))

    def _login(self, data):
        user, token = auth.login(self.db, str(data.get("username") or "").strip(),
                                 str(data.get("password") or ""),
                                 self._client_ip(), self.headers.get("User-Agent", ""))
        return self.send_json({"ok": True, "user": user},
                              set_cookie=self._cookie(token))

    def _logout(self):
        auth.logout(self.db, self._token())
        return self.send_json({"ok": True}, set_cookie=f"{COOKIE_NAME}=; Path=/; Max-Age=0")

    def _cookie(self, token: str) -> str:
        return f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={auth.SESSION_HOURS * 3600}"


def serve(port: int, db: DB, open_browser: bool = False) -> int:
    engine = labs.Labs(REPO, db)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.db = db            # type: ignore[attr-defined]
    httpd.labs = engine      # type: ignore[attr-defined]
    print(f"课程工坊已启动：http://127.0.0.1:{port}/（数据：{db.path}；Ctrl+C 结束）")
    if open_browser:
        url = f"http://127.0.0.1:{port}/"
        print(f"    浏览器将在 2 秒后自动打开：{url}")
        import webbrowser
        threading.Timer(2.0, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


# ---------------------------------------------------------------- 自检

def selftest(port: int = 7901) -> int:
    ok = True

    def check(label, cond, extra=""):
        nonlocal ok
        print(("[PASS] " if cond else "[FAIL] ") + label + (f"  {extra}" if extra else ""))
        ok = ok and bool(cond)

    tmp = tempfile.TemporaryDirectory(prefix="courselab-test-")
    db = DB(Path(tmp.name) / "app.db")
    t = threading.Thread(target=serve, args=(port, db), daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    t0 = time.time()
    while time.time() - t0 < 10:
        try:
            urllib.request.urlopen(base + "/health", timeout=1).read()
            break
        except OSError:
            time.sleep(0.1)

    def get(path, cookie=None):
        req = urllib.request.Request(base + path)
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8")), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8")), e.headers

    def post(path, obj, cookie=None, origin=None):
        req = urllib.request.Request(base + path, _json_bytes(obj),
                                     {"Content-Type": "application/json"})
        if cookie:
            req.add_header("Cookie", cookie)
        if origin:
            req.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8")), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8")), e.headers

    def cookie_of(headers) -> str:
        raw = headers.get("Set-Cookie") or ""
        return raw.split(";")[0]

    # -- 基础与内容（M0 保持）
    status, health, _ = get("/health")
    check("health 就绪", status == 200 and health.get("app") == "courselab")

    status, data, _ = get("/api/courses")
    check("课程目录现算（33 门）", data.get("ok") and data.get("count") >= 33, f"{data.get('count')} 门")
    with_summary = sum(1 for c in data["courses"] if c.get("summary"))
    check("摘要现算（≥20 门有真实一句话；缺的页面有兜底文案）", with_summary >= 20, f"{with_summary} 门")

    status, data, _ = get("/api/courses/B11-net-lab")
    c = data.get("course", {})
    check("课程工作区：B11 详情含知识点/任务/材料/实验动作",
          data.get("ok") and len(c.get("knowledge", [])) >= 1 and len(c.get("tasks", [])) >= 1
          and any(m["kind"] == "file" for m in c.get("materials", []))
          and any(a["id"] == "serve_start" for a in c.get("lab", {}).get("actions", [])))
    status, data, _ = get("/api/courses/no-such-course")
    check("未知课程 404", status == 404)

    # -- 账号（M1）
    status, data, hdrs = post("/api/auth/register",
                              {"username": "stu_a", "display_name": "甲同学", "password": "pw123456"})
    check("注册成功且角色=student", status == 200 and data["user"]["role"] == "student")
    status, data, _ = post("/api/auth/register",
                           {"username": "stu_a", "display_name": "重复", "password": "pw123456"})
    check("重复用户名 409", status == 409 and data["code"] == "USER_EXISTS")
    status, data, _ = post("/api/auth/register",
                           {"username": "ab", "display_name": "短", "password": "pw123456"})
    check("非法用户名 400", status == 400)
    status, data, _ = post("/api/auth/register",
                           {"username": "stu_b", "display_name": "弱口令", "password": "abcdefgh"})
    check("弱口令（无数字）400", status == 400 and data["code"] == "BAD_PASSWORD")

    status, data, hdrs = post("/api/auth/login", {"username": "stu_a", "password": "pw123456"})
    cookie = cookie_of(hdrs)
    check("登录成功并下发会话 Cookie", status == 200 and cookie.startswith("cl_session="), cookie[:24])

    status, data, _ = get("/api/me", cookie=cookie)
    check("带会话 /api/me 返回本人与 can()",
          data.get("user", {}).get("username") == "stu_a" and data["can"]["lab_run"] is True
          and data["can"]["admin"] is False)
    status, data, _ = get("/api/me")
    check("匿名 /api/me user=null 且 lab_run 拒绝", data.get("user") is None and data["can"]["lab_run"] is False)

    status, data, _ = post("/api/auth/login", {"username": "stu_a", "password": "wrong-pass1"})
    check("错误口令 401", status == 401)

    for i in range(5):
        post("/api/auth/login", {"username": "stu_rate", "password": "bad-pass1"})
    status, data, _ = post("/api/auth/login", {"username": "stu_rate", "password": "bad-pass1"})
    check("失败 5 次后限流 429", status == 429 and data["code"] == "RATE_LIMITED")

    status, data, _ = post("/api/auth/logout", {}, cookie=cookie)
    check("登出成功", status == 200)
    status, data, _ = get("/api/me", cookie=cookie)
    check("登出后旧会话失效", data.get("user") is None)

    status, data, _ = post("/api/auth/login", {"username": "stu_a", "password": "pw123456"},
                           origin="http://evil.example")
    check("跨源 POST 被拒（同源基线）", status == 403 and data["code"] == "BAD_ORIGIN")

    # -- 在线实验（M3）
    status, data, _ = post("/api/labs/run", {"project": "B3-logic-lab", "action": "demo"})
    check("匿名发起实验被拒 401", status == 401 and data["code"] == "LOGIN_REQUIRED")

    status, data, hdrs = post("/api/auth/login", {"username": "stu_a", "password": "pw123456"})
    cookie = cookie_of(hdrs)
    check("重新登录（实验阶段）", status == 200 and cookie.startswith("cl_session="))

    status, data, _ = post("/api/labs/run", {"project": "B3-logic-lab", "action": "demo"},
                           cookie=cookie)
    rid = data.get("run_id")
    check("学生发起 demo 实验", status == 200 and bool(rid), str(data)[:80])

    st, t0 = {}, time.time()
    while time.time() - t0 < 60:
        _, d2, _ = get(f"/api/labs/runs/{rid}", cookie=cookie)
        st = d2.get("run") or {}
        if st and st.get("running") is False:
            break
        time.sleep(0.4)
    check("demo 跑完且 exit=0", st.get("running") is False and st.get("exit") == 0, str(st))

    req = urllib.request.Request(base + f"/api/labs/runs/{rid}/log")
    req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req, timeout=10) as r:
        sse = r.read().decode("utf-8", "replace")
    check("SSE 日志流（回放含 log 与 done 事件）",
          "event: log" in sse and "event: done" in sse, f"{len(sse)}B")

    status, data, _ = get("/api/labs/runs/mine", cookie=cookie)
    check("我的实验记录含本次运行", any(x["id"] == rid for x in data.get("runs", [])))

    s1, d1, _ = post("/api/labs/run", {"project": "B2-datastruct-lab", "action": "run"}, cookie=cookie)
    s2, d2, _ = post("/api/labs/run", {"project": "B1-cpp-ministl", "action": "run"}, cookie=cookie)
    s3, d3, _ = post("/api/labs/run", {"project": "B3-logic-lab", "action": "demo"}, cookie=cookie)
    check("并发限额：第 3 个被拒 429", s1 == 200 and s2 == 200 and s3 == 429,
          f"{s1}/{s2}/{s3} {d3.get('code')}")
    st1, _, _ = post(f"/api/labs/runs/{d1['run_id']}/stop", {}, cookie=cookie)
    st2, _, _ = post(f"/api/labs/runs/{d2['run_id']}/stop", {}, cookie=cookie)
    check("强停两个运行中任务（整树杀）", st1 == 200 and st2 == 200)
    t0 = time.time()
    gone = False
    while time.time() - t0 < 8:
        _, da, _ = get("/api/labs/active", cookie=cookie)
        if not da.get("running"):
            gone = True
            break
        time.sleep(0.4)
    check("停止后运行列表清空", gone)

    s, d, _ = post("/api/labs/run", {"project": "B31-shorturl", "action": "serve_start"},
                   cookie=cookie)
    check("启动真实服务 B31（:8312）", s == 200 and d.get("port") == 8312, str(d)[:80])
    if s == 200:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8312/", timeout=5) as r:
                page = r.read(120)
            check("服务页面可打开（「打开」目标）", r.status == 200 and len(page) > 20)
        finally:
            s3, _, _ = post(f"/api/labs/runs/{d['run_id']}/stop", {}, cookie=cookie)
        check("停止服务", s3 == 200)

    # -- 权限矩阵单元（负面为主）
    stu = {"role": "student"}
    check("can()：学生不可 admin / 可 lab_run；教师可 manage_course",
          not can.can(stu, "admin") and can.can(stu, "lab_run")
          and can.can({"role": "teacher"}, "manage_course")
          and not can.can(None, "lab_run") and can.can(None, "view"))

    # -- 页面与内容源
    bat = (ROOT / "run.bat").read_bytes()
    check("run.bat 纯 ASCII + CRLF + 空设备写 nul（无 /dev/null——本机 C:\\dev 会吞掉）",
          all(b < 128 for b in bat) and b"/dev/null" not in bat and b">nul" in bat
          and bat.count(b"\n") == bat.count(b"\r\n"))

    for page in ("/", "/login.html", "/register.html",
                 "/course.html", "/project.html", "/me.html"):
        with urllib.request.urlopen(base + page, timeout=5) as r:
            body = r.read()
        check(f"页面 {page} 200", r.status == 200 and len(body) > 300)

    with urllib.request.urlopen(base + "/repo/projects/B13-tinylang/web/showcase.html", timeout=10) as r:
        body = r.read(400)
        check("项目演示页经 /repo/ 可打开", r.status == 200 and len(body) > 50)

    # 目录穿越：指向"仓库外真实存在的文件"（自检临时库），必须被 404 挡住
    rel = os.path.relpath(str(Path(tmp.name) / "app.db"), str(REPO)).replace("\\", "/")
    status, data, _ = get("/repo/" + rel)
    check("目录穿越（仓库外真实文件）被拒", status == 404)

    print("CourseLab 自检：" + ("PASS" if ok else "FAIL"))
    db.close()
    return 0 if ok else 1


# ---------------------------------------------------------------- 入口

def main(argv) -> int:
    ap = argparse.ArgumentParser(description="课程工坊 CourseLab（课程项目平台）")
    ap.add_argument("--port", type=int, default=7900)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 路径（默认 courselab/data/app.db）")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])
    if args.selftest:
        return selftest()
    db = DB(Path(args.db))
    return serve(args.port, db, open_browser=args.open)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
