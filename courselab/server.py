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
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from app import admin, auth, can, courses, labs, notices, tasks
from app.db import DB, now_str

ROOT = Path(__file__).resolve().parent          # courselab/
REPO = ROOT.parent                              # 课设仓库根（内容源）
WEB = ROOT / "web"
DEFAULT_DB = ROOT / "data" / "app.db"

JSON_TYPE = "application/json; charset=utf-8"
COOKIE_NAME = "cl_session"

DEFAULT_CFG = {
    "bind": "127.0.0.1",        # 部署到局域网/公网时改 0.0.0.0（配合注册审批与备份）
    "port": 7900,
    "data_dir": "data",         # 相对 courselab/ 或绝对路径（放库与未来上传）
    "max_labs": 2,              # 在线实验并发上限
    "task_timeout": 600,        # 单个实验超时（秒），到点整树杀
    "session_hours": 12,        # 会话时长
    "registration": "open",     # open=注册即用；approval=注册后待管理员审批
    "public_mode": False,       # 公网部署提醒开关（只影响启动提示，不改边界）
}


def load_config(path=None) -> dict:
    """读 config.json（默认 courselab/config.json，存在才读）；未知键与非法值直接拒绝启动。"""
    cfg = dict(DEFAULT_CFG)
    p = Path(path) if path else (ROOT / "config.json")
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise SystemExit(f"[!] {p.name} 不是合法 JSON：{exc}")
        if not isinstance(data, dict):
            raise SystemExit(f"[!] {p.name} 顶层必须是对象")
        unknown = sorted(k for k in data if k not in DEFAULT_CFG)
        if unknown:
            raise SystemExit(f"[!] {p.name} 有不认识的键：{unknown}")
        if data.get("registration") not in (None, "open", "approval"):
            raise SystemExit("[!] registration 只能是 open 或 approval")
        cfg.update(data)
    return cfg


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


_LOG_RE = re.compile(r"^app-(\d{4}-\d{2}-\d{2})\.log$")


def prune_logs(log_dir, keep_days: int = 14) -> int:
    """删除文件名日期早于 keep_days 天的 app-*.log（F18：日志保留 14 天）。"""
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - keep_days * 86400))
    removed = 0
    for f in Path(log_dir).glob("app-*.log"):
        m = _LOG_RE.match(f.name)
        if m and m.group(1) < cutoff:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def count_visit(db) -> None:
    """页面访问计数（F15）：只计 / 与 *.html 页面，不计资源与 API。"""
    day = time.strftime("%Y-%m-%d")
    db.execute("INSERT INTO visits(day, n) VALUES(?, 1)"
               " ON CONFLICT(day) DO UPDATE SET n = n + 1", (day,))


class Handler(SimpleHTTPRequestHandler):
    server_version = "CourseLab/0.2"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    # ---------------------------------------------------------- 基础工具
    def log_message(self, fmt, *args):
        line = fmt % args
        sys.stderr.write("[courselab] %s\n" % line)
        log_dir = getattr(self.server, "log_dir", None)
        if log_dir is None:
            return
        try:
            with open(log_dir / ("app-%s.log" % time.strftime("%Y-%m-%d")),
                      "a", encoding="utf-8") as fh:
                fh.write("%s [courselab] %s\n" % (time.strftime("%H:%M:%S"), line))
        except OSError:
            pass

    @property
    def db(self) -> DB:
        return self.server.db            # type: ignore[attr-defined]

    @property
    def labs(self) -> labs.Labs:
        return self.server.labs          # type: ignore[attr-defined]

    @property
    def cfg(self) -> dict:
        return self.server.cfg           # type: ignore[attr-defined]

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
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            n = 0
        n = max(0, min(n, 1 << 20))     # 畸形/超长 Content-Length 不当异常路径
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
        from urllib.parse import parse_qs
        u = urlparse(self.path)
        path = u.path
        query = parse_qs(u.query)

        if path == "/health":
            return self.send_json({"ok": True, "app": "courselab", "version": "0.2"})

        if path in ("/teacher", "/teacher/"):
            self.send_response(302)
            self.send_header("Location", "/teacher.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path in ("/admin", "/admin/"):
            self.send_response(302)
            self.send_header("Location", "/admin.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path == "/api/me":
            user = self.current_user()
            return self.send_json({
                "ok": True, "user": user,
                "unread": notices.unread_count(self.db, user),
                "can": {"lab_run": can.can(user, "lab_run"),
                        "manage_course": can.can(user, "manage_course"),
                        "admin": can.can(user, "admin")},
            })

        if path == "/api/notices":
            user = self.current_user()
            if user is None:
                return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
            items = notices.list_for(self.db, user)
            return self.send_json({"ok": True, "notices": items,
                                   "unread": sum(1 for x in items if not x["read"])})

        if path == "/api/courses":
            try:
                return self.send_json(admin.public_course_list(self.db))
            except (OSError, ValueError) as exc:
                return self.send_error_json(500, f"课程目录读取失败：{exc}")

        if path.startswith("/api/courses/"):
            cid = unquote(path[len("/api/courses/"):]).strip("/")
            user = self.current_user()
            if not admin.course_visible(self.db, cid) and not can.can(user, "admin"):
                return self.send_error_json(404, "课程不存在", "NO_COURSE")
            detail = courses.course_detail(cid)
            if detail is None:
                return self.send_error_json(404, "课程不存在", "NO_COURSE")
            detail["can"] = {"lab_run": can.can(user, "lab_run", cid)}
            detail["lab"] = labs.describe(cid)
            detail["taskboard"] = tasks.course_taskboard(self.db, user, cid)
            detail["meta"] = admin.course_meta_public(self.db, cid)
            return self.send_json({"ok": True, "course": detail})

        if path == "/api/tasks/mine":
            user = self.current_user()
            if user is None:
                return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
            return self.send_json({"ok": True, "tasks": tasks.my_records(self.db, user["id"])})

        if path == "/api/teacher/courses":
            user = self.current_user()
            if user is None:
                return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
            if not can.can(user, "manage_course"):
                return self.send_error_json(403, "需要教师权限", "FORBIDDEN")
            return self.send_json({"ok": True, "courses": admin.teacher_courses(self.db, user)})

        if path == "/api/teacher/course":
            user = self.current_user()
            if user is None:
                return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
            cid = (query.get("course") or [""])[0]
            if not admin.teacher_can_manage(self.db, user, cid):
                return self.send_error_json(403, "该课未绑定给你（联系管理员在管理端绑定）", "FORBIDDEN")
            try:
                return self.send_json(tasks.teacher_course_stats(self.db, cid))
            except tasks.TaskError as exc:
                return self.send_error_json(exc.http, exc.message, exc.code)

        if path.startswith("/api/admin/"):
            user = self.current_user()
            if user is None:
                return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
            if not can.can(user, "admin"):
                return self.send_error_json(403, "需要管理员权限", "FORBIDDEN")
            if path == "/api/admin/overview":
                return self.send_json(admin.overview(self.db))
            if path == "/api/admin/users":
                return self.send_json({"ok": True, "users": admin.users_list(self.db)})
            if path == "/api/admin/courses":
                return self.send_json({"ok": True, "courses": admin.course_rows(self.db)})
            if path == "/api/admin/labs":
                return self.send_json({"ok": True, "recent": admin.labs_audit(self.db),
                                       "active": self.labs.active()["running"]})
            if path == "/api/admin/audit":
                return self.send_json({"ok": True, "events": admin.audit_list(self.db)})
            return self.send_error_json(404, "unknown api")

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

        if self.command == "GET" and (path == "/" or (path.endswith(".html")
                                                      and (WEB / path.lstrip("/")).is_file())):
            count_visit(self.db)
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
            if path == "/api/auth/password":
                return self._change_password(data)
            if path == "/api/labs/run":
                return self._lab_run(data)
            if path.startswith("/api/labs/runs/") and path.endswith("/stop"):
                return self._lab_stop(path)
            if path == "/api/tasks/claim":
                return self._task_action(data, "claim")
            if path == "/api/tasks/done":
                return self._task_action(data, "done")
            if path == "/api/teacher/tasks":
                return self._teacher_create(data)
            if path.startswith("/api/teacher/tasks/") and path.endswith("/delete"):
                return self._teacher_delete(path)
            if path == "/api/teacher/course/meta":
                return self._teacher_course_meta(data)
            if path == "/api/notices":
                return self._notice_publish(data)
            if path == "/api/notices/read-all":
                user = self.current_user()
                if user is None:
                    return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
                return self.send_json({"ok": True, "marked": notices.mark_all_read(self.db, user)})
            if path.startswith("/api/notices/") and path.endswith("/read"):
                user = self.current_user()
                if user is None:
                    return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
                raw = path[len("/api/notices/"):-len("/read")].strip("/")
                try:
                    notice_id = int(raw)
                except ValueError:
                    return self.send_error_json(400, "公告编号不合法")
                notices.mark_read(self.db, user, notice_id)
                return self.send_json({"ok": True})
            if path.startswith("/api/admin/users/") and path.endswith(("/role", "/status")):
                return self._admin_user(path, data)
            if path.startswith("/api/admin/courses/") and path.endswith("/meta"):
                return self._admin_course(path, data)
        except (admin.AdminError, auth.AuthError, labs.LabsError, notices.NoticeError,
                tasks.TaskError) as exc:
            return self.send_error_json(exc.http, exc.message, exc.code)
        return self.send_error_json(404, "unknown api")

    def _notice_publish(self, data):
        user = self.current_user()
        if user is None:
            return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
        audience = str(data.get("audience") or "all").strip() or "all"
        if audience == "all":
            if not can.can(user, "admin"):
                return self.send_error_json(403, "只有管理员能发全员公告", "FORBIDDEN")
        else:
            if courses.course_detail(audience) is None:
                return self.send_error_json(400, "公告对象课程不存在", "NO_COURSE")
            if not admin.teacher_can_manage(self.db, user, audience):
                return self.send_error_json(403, "只能给自己负责的课程发公告", "FORBIDDEN")
        row = notices.publish(self.db, user["id"], str(data.get("title") or ""),
                              str(data.get("body") or ""), audience)
        admin.audit(self.db, user["id"], "notice_publish", audience, row["title"])
        return self.send_json({"ok": True, "notice": row})

    def _task_action(self, data, kind):
        user = self.current_user()
        if user is None:
            return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
        if not can.can(user, "task_claim"):
            return self.send_error_json(403, "没有任务权限", "FORBIDDEN")
        course = str(data.get("course") or "")
        key = str(data.get("key") or "")
        if kind == "claim":
            rec = tasks.claim(self.db, user["id"], course, key)
        else:
            rec = tasks.complete(self.db, user["id"], course, key, str(data.get("note") or ""))
        return self.send_json({"ok": True, "record": rec})

    def _teacher_create(self, data):
        user = self.current_user()
        if user is None:
            return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
        course = str(data.get("course") or "")
        if not admin.teacher_can_manage(self.db, user, course):
            return self.send_error_json(403, "该课未绑定给你（联系管理员在管理端绑定）", "FORBIDDEN")
        row = tasks.teacher_create(self.db, user["id"], course,
                                   str(data.get("title") or ""), str(data.get("body") or ""),
                                   str(data.get("due_at") or ""))
        return self.send_json({"ok": True, "task": row})

    def _teacher_delete(self, path):
        user = self.current_user()
        if user is None:
            return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
        raw = path[len("/api/teacher/tasks/"):-len("/delete")].strip("/")
        try:
            task_id = int(raw)
        except ValueError:
            return self.send_error_json(400, "任务编号不合法")
        row = self.db.one("SELECT course FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            return self.send_error_json(404, "任务不存在", "NO_TASK")
        if not admin.teacher_can_manage(self.db, user, row["course"]):
            return self.send_error_json(403, "该课未绑定给你（联系管理员在管理端绑定）", "FORBIDDEN")
        tasks.teacher_delete(self.db, task_id)
        return self.send_json({"ok": True})

    def _admin_user(self, path, data):
        user = self.current_user()
        if user is None:
            return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
        if not can.can(user, "admin"):
            return self.send_error_json(403, "需要管理员权限", "FORBIDDEN")
        is_role = path.endswith("/role")
        tail = "/role" if is_role else "/status"
        raw = path[len("/api/admin/users/"):-len(tail)].strip("/")
        try:
            target_id = int(raw)
        except ValueError:
            return self.send_error_json(400, "用户编号不合法")
        if is_role:
            row = admin.set_user_role(self.db, user["id"], target_id, str(data.get("role") or ""))
        else:
            row = admin.set_user_status(self.db, user["id"], target_id,
                                        str(data.get("status") or ""))
        return self.send_json({"ok": True, "user": row})

    def _admin_course(self, path, data):
        user = self.current_user()
        if user is None:
            return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
        if not can.can(user, "admin"):
            return self.send_error_json(403, "需要管理员权限", "FORBIDDEN")
        cid = unquote(path[len("/api/admin/courses/"):-len("/meta")]).strip("/")
        kwargs = {}
        if "published" in data:
            kwargs["published"] = data.get("published")
        if "sort" in data:
            try:
                kwargs["sort"] = int(data.get("sort") or 0)
            except (TypeError, ValueError):
                return self.send_error_json(400, "排序值必须是整数")
        if "teacher_id" in data:
            kwargs["teacher_id"] = data.get("teacher_id")
        if "summary" in data:
            kwargs["summary"] = data.get("summary")
        if "outline" in data:
            kwargs["outline"] = data.get("outline")
        row = admin.set_course_meta(self.db, cid, user["id"], **kwargs)
        return self.send_json({"ok": True, "meta": row})

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
        status = "pending" if self.cfg.get("registration") == "approval" else "active"
        user = auth.register(self.db, str(data.get("username") or "").strip(),
                             str(data.get("display_name") or "").strip(),
                             str(data.get("password") or ""), status=status)
        if status == "pending":
            return self.send_json({"ok": True, "user": user,
                                   "notice": "注册成功，等待管理员审批后即可登录"})
        token = auth.create_session(self.db, user["id"], self._client_ip(),
                                    self.headers.get("User-Agent", ""),
                                    self._hours())
        return self.send_json({"ok": True, "user": user},
                              set_cookie=self._cookie(token))

    def _login(self, data):
        user, token = auth.login(self.db, str(data.get("username") or "").strip(),
                                 str(data.get("password") or ""),
                                 self._client_ip(), self.headers.get("User-Agent", ""),
                                 self._hours())
        return self.send_json({"ok": True, "user": user},
                              set_cookie=self._cookie(token))

    def _hours(self):
        try:
            return float(self.cfg.get("session_hours", 12))
        except (TypeError, ValueError):
            return 12.0

    def _logout(self):
        auth.logout(self.db, self._token())
        return self.send_json({"ok": True}, set_cookie=f"{COOKIE_NAME}=; Path=/; Max-Age=0")

    def _change_password(self, data):
        user = self.current_user()
        if user is None:
            return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
        auth.change_password(self.db, user["id"],
                             str(data.get("old_password") or ""),
                             str(data.get("new_password") or ""),
                             keep_token=self._token(), ip=self._client_ip())
        return self.send_json({"ok": True, "notice": "口令已更新；其他已登录的会话已失效"})

    def _teacher_course_meta(self, data):
        user = self.current_user()
        if user is None:
            return self.send_error_json(401, "请先登录", "LOGIN_REQUIRED")
        cid = str(data.get("course") or "").strip()
        if not admin.teacher_can_manage(self.db, user, cid):
            return self.send_error_json(403, "只能维护绑定给自己的课程", "FORBIDDEN")
        kwargs = {}
        if "published" in data:
            kwargs["published"] = data.get("published")
        if "summary" in data:
            kwargs["summary"] = data.get("summary")
        if "outline" in data:
            kwargs["outline"] = data.get("outline")
        if not kwargs:
            return self.send_error_json(400, "没有要修改的字段", "EMPTY")
        row = admin.set_course_meta(self.db, cid, user["id"], **kwargs)
        return self.send_json({"ok": True, "meta": row})

    def _cookie(self, token: str) -> str:
        return (f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; "
                f"Max-Age={int(self._hours() * 3600)}")


def serve(port: int, db: DB, cfg: dict | None = None, open_browser: bool = False) -> int:
    cfg = dict(cfg or DEFAULT_CFG)
    engine = labs.Labs(REPO, db, max_labs=int(cfg.get("max_labs", 2)),
                       task_timeout=float(cfg.get("task_timeout", 600)))
    bind = str(cfg.get("bind", "127.0.0.1"))
    httpd = ThreadingHTTPServer((bind, port), Handler)
    httpd.db = db            # type: ignore[attr-defined]
    httpd.labs = engine      # type: ignore[attr-defined]
    httpd.cfg = cfg          # type: ignore[attr-defined]
    swept = auth.sweep_sessions(db)
    if swept:
        print(f"    启动清扫：删除过期会话 {swept} 条")
    log_dir = Path(db.path).parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        httpd.log_dir = log_dir  # type: ignore[attr-defined]
        prune_logs(log_dir)
        log_note = f"日志：{log_dir}，保留 14 天"
    except OSError:
        httpd.log_dir = None     # type: ignore[attr-defined]
        log_note = "日志：目录不可写，仅控制台"
    print(f"课程工坊已启动：http://127.0.0.1:{port}/（数据：{db.path}；{log_note}；Ctrl+C 结束）")
    if bind != "127.0.0.1":
        print(f"    监听 {bind}:{port}——局域网/公网可访问；注册模式：{cfg.get('registration')}")
        if cfg.get("public_mode"):
            print("    公网模式提醒：注册建议切 approval、定期备份 data 目录、实验并发保持小值（见 docs/DEPLOY.md）。")
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

    tmp = tempfile.TemporaryDirectory(prefix="courselab-test-",
                                      ignore_cleanup_errors=True)
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

    # -- 练习任务（M4）
    status, data, _ = post("/api/tasks/claim", {"course": "B11-net-lab", "key": "B11-net-lab#0"})
    check("匿名领取任务被拒 401", status == 401)

    status, data, _ = post("/api/tasks/claim", {"course": "B11-net-lab", "key": "B11-net-lab#0"},
                           cookie=cookie)
    check("领取内置任务 -> doing", status == 200 and data["record"]["status"] == "doing")
    status, data, _ = post("/api/tasks/done",
                           {"course": "B11-net-lab", "key": "B11-net-lab#0", "note": "十分钟搞定"},
                           cookie=cookie)
    check("完成任务（带备注）-> done", status == 200 and data["record"]["status"] == "done")
    status, data, _ = post("/api/tasks/claim", {"course": "B11-net-lab", "key": "B11-net-lab#0"},
                           cookie=cookie)
    check("已完成再领取 409", status == 409 and data["code"] == "ALREADY_DONE")
    status, data, _ = post("/api/tasks/done", {"course": "B11-net-lab", "key": "B11-net-lab#99"},
                           cookie=cookie)
    check("越界任务编号 400", status == 400)

    status, data, _ = get("/api/tasks/mine", cookie=cookie)
    check("我的任务含刚完成的内置任务",
          any(x["key"] == "B11-net-lab#0" and x["status"] == "done" and "十分钟" in x["note"]
              for x in data["tasks"]))
    status, data, _ = get("/api/courses/B11-net-lab", cookie=cookie)
    tb = data["course"]["taskboard"]
    check("课程任务板：进度含我的完成 + 人数统计",
          tb["progress"]["done"] >= 1
          and any(x["my"] == "done" and x["done_count"] >= 1 for x in tb["items"]))

    post("/api/auth/register", {"username": "teach_a", "display_name": "乙老师",
                                "password": "pw123456"})
    db.execute("UPDATE users SET role='teacher' WHERE username='teach_a'")
    teach_a_id = db.one("SELECT id FROM users WHERE username='teach_a'")["id"]
    # 教师绑定（M5 起教师只能管绑定给自己的课；这里直接建绑定做测试准备）
    db.execute("INSERT INTO course_meta(course, published, sort, teacher_id)"
               " VALUES('B11-net-lab', 1, 0, ?)", (teach_a_id,))
    status, data, h2 = post("/api/auth/login", {"username": "teach_a", "password": "pw123456"})
    tcookie = cookie_of(h2)
    check("教师账号就绪（注册 + 提升 + 绑定 B11）", status == 200)

    status, data, _ = post("/api/teacher/tasks", {"course": "B3-logic-lab", "title": "越权试探"},
                           cookie=tcookie)
    check("教师管未绑定的课 403（绑定即权限）", status == 403)

    status, data, _ = post("/api/teacher/tasks",
                           {"course": "B11-net-lab", "title": "自测：补一个边界用例",
                            "body": "给 kv 路由加空键的用例"}, cookie=tcookie)
    check("教师布置自定义任务", status == 200 and data["task"]["id"])
    tid = data["task"]["id"]

    status, data, _ = post("/api/tasks/claim", {"course": "B11-net-lab", "key": f"T{tid}"},
                           cookie=cookie)
    check("学生领取自定义任务", status == 200 and data["record"]["status"] == "doing")
    status, data, _ = post("/api/teacher/tasks", {"course": "B11-net-lab", "title": "x"},
                           cookie=cookie)
    check("学生调教师接口 403", status == 403)

    status, data, _ = get("/api/teacher/course?course=B11-net-lab", cookie=tcookie)
    check("本课统计：总数/内置统计/最近动态齐全",
          status == 200 and data["totals"]["records"] >= 2 and data["totals"]["done"] >= 1
          and len(data["builtin_stats"]) >= 1 and len(data["recent"]) >= 2)

    status, data, _ = post(f"/api/teacher/tasks/{tid}/delete", {}, cookie=tcookie)
    check("教师删除自定义任务", status == 200)
    status, data, _ = get("/api/tasks/mine", cookie=cookie)
    check("删除后学生记录同步消失", all(x["key"] != f"T{tid}" for x in data["tasks"]))

    # -- 管理端（M5）
    status, data, _ = get("/api/admin/overview", cookie=cookie)
    check("学生访问管理端 403", status == 403)
    post("/api/auth/register", {"username": "admin_a", "display_name": "丙管理员",
                                "password": "pw123456"})
    db.execute("UPDATE users SET role='admin' WHERE username='admin_a'")
    status, data, h3 = post("/api/auth/login", {"username": "admin_a", "password": "pw123456"})
    acookie = cookie_of(h3)
    check("管理员账号就绪", status == 200 and data["user"]["role"] == "admin")

    status, data, _ = get("/api/admin/overview", cookie=acookie)
    check("看板聚合（用户/实验/任务/七日曲线）",
          status == 200 and data["users"] >= 3 and data["labs_total"] >= 1
          and len(data["daily_labs"]) == 7)
    status, data, _ = get("/api/admin/users", cookie=acookie)
    check("用户列表", status == 200 and len(data["users"]) >= 3)
    status, data, _ = get("/api/admin/labs", cookie=acookie)
    check("实验审计（含历史运行）", status == 200 and len(data["recent"]) >= 1)

    stu_a_id = db.one("SELECT id FROM users WHERE username='stu_a'")["id"]
    status, data, _ = post(f"/api/admin/users/{stu_a_id}/role", {"role": "teacher"},
                           cookie=acookie)
    check("改角色 student->teacher", status == 200 and data["user"]["role"] == "teacher")
    status, data, _ = post(f"/api/admin/users/{stu_a_id}/role", {"role": "student"},
                           cookie=acookie)
    check("改回 student", status == 200 and data["user"]["role"] == "student")
    admin_id = db.one("SELECT id FROM users WHERE username='admin_a'")["id"]
    status, data, _ = post(f"/api/admin/users/{admin_id}/status", {"status": "banned"},
                           cookie=acookie)
    check("管理员自封被拒（防锁死）", status == 400 and data["code"] == "SELF")

    post("/api/auth/register", {"username": "stu_ban", "display_name": "封禁样例",
                                "password": "pw123456"})
    status, data, hb = post("/api/auth/login", {"username": "stu_ban", "password": "pw123456"})
    ban_cookie = cookie_of(hb)
    ban_id = db.one("SELECT id FROM users WHERE username='stu_ban'")["id"]
    status, data, _ = post(f"/api/admin/users/{ban_id}/status", {"status": "banned"},
                           cookie=acookie)
    check("封禁用户", status == 200 and data["user"]["status"] == "banned")
    status, data, _ = get("/api/me", cookie=ban_cookie)
    check("封禁即下线（存量会话失效）", data.get("user") is None)
    status, data, _ = post("/api/auth/login", {"username": "stu_ban", "password": "pw123456"})
    check("封禁后登录被拒 403", status == 403 and data["code"] == "USER_DISABLED")
    post(f"/api/admin/users/{ban_id}/status", {"status": "active"}, cookie=acookie)

    status, data, _ = post("/api/admin/courses/B31-shorturl/meta", {"published": False},
                           cookie=acookie)
    check("下架课程", status == 200 and data["meta"]["published"] is False)
    status, data, _ = get("/api/courses")
    check("下架后学生目录隐藏", all(c["id"] != "B31-shorturl" for c in data["courses"]))
    status, data, _ = get("/api/courses/B31-shorturl", cookie=cookie)
    check("下架后详情对学生 404", status == 404)
    status, data, _ = post("/api/admin/courses/B31-shorturl/meta",
                           {"published": True, "sort": 999}, cookie=acookie)
    check("重新上架并排序", status == 200 and data["meta"]["sort"] == 999)
    status, data, _ = get("/api/courses")
    check("排序生效（排到最后）", data["courses"][-1]["id"] == "B31-shorturl")

    status, data, _ = post("/api/admin/courses/B31-shorturl/meta",
                           {"teacher_id": teach_a_id}, cookie=acookie)
    check("绑定 B31 给教师", status == 200 and data["meta"]["teacher_id"] == teach_a_id)
    status, data, _ = get("/api/teacher/course?course=B31-shorturl", cookie=tcookie)
    check("绑定后可管（教师读 B31 统计）", status == 200 and data["course"] == "B31-shorturl")
    status, data, _ = get("/api/teacher/courses", cookie=tcookie)
    check("教师台课程列表=绑定的课",
          status == 200 and {c["id"] for c in data["courses"]} == {"B11-net-lab", "B31-shorturl"})
    post("/api/admin/courses/B31-shorturl/meta", {"teacher_id": None}, cookie=acookie)
    status, data, _ = get("/api/teacher/course?course=B31-shorturl", cookie=tcookie)
    check("解绑后教师 403", status == 403)

    # -- 部署与运维（M6）
    cfg_path = Path(tmp.name) / "cfg.json"
    cfg_path.write_text(json.dumps({"port": 7999, "max_labs": 5,
                                    "registration": "approval"}), encoding="utf-8")
    cfg = load_config(str(cfg_path))
    check("配置加载（config.json 覆盖默认，缺省项保留）",
          cfg["port"] == 7999 and cfg["max_labs"] == 5
          and cfg["registration"] == "approval" and cfg["bind"] == "127.0.0.1")
    bad_cfg = Path(tmp.name) / "bad.json"
    bad_cfg.write_text("{not json", encoding="utf-8")
    try:
        load_config(str(bad_cfg))
        bad_rejected = False
    except SystemExit:
        bad_rejected = True
    check("坏配置拒绝启动（非法 JSON）", bad_rejected)
    check("并发上限可配置（Labs 参数生效）",
          labs.Labs(REPO, db, max_labs=5).active()["limit"] == 5)

    pu = auth.register(db, "stu_pending", "待审样例", "pw123456", status="pending")
    check("审批模式注册 -> pending", pu["status"] == "pending")
    try:
        auth.login(db, "stu_pending", "pw123456")
        pending_blocked = False
    except auth.AuthError as exc:
        pending_blocked = (exc.code == "USER_PENDING")
    check("pending 用户登录被拒（USER_PENDING）", pending_blocked)
    status, data, _ = post(f"/api/admin/users/{pu['id']}/status", {"status": "active"},
                           cookie=acookie)
    check("管理员审批通过（pending -> active）",
          status == 200 and data["user"]["status"] == "active")
    status, data, _ = post("/api/auth/login", {"username": "stu_pending", "password": "pw123456"})
    check("审批通过后可登录", status == 200)

    tdb_path = Path(tmp.name) / "tool.db"
    tdb = DB(tdb_path)
    tdb.execute("INSERT INTO users(username, display_name, role, pwd_salt, pwd_hash, pwd_iter,"
                " created_at) VALUES('u1','样例','student','s','h',1,'2026-01-01')")
    tdb.close()
    out_dir = Path(tmp.name) / "bk"
    tool_env = dict(os.environ, PYTHONUTF8="1")
    r1 = subprocess.run([sys.executable, str(ROOT / "tools" / "backup.py"),
                         "--db", str(tdb_path), "--out", str(out_dir)],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=tool_env)
    backups = sorted(out_dir.glob("app-*.db")) if out_dir.is_dir() else []
    check("备份工具：VACUUM INTO + 校验", r1.returncode == 0 and len(backups) == 1,
          " / ".join((r1.stdout or "").strip().splitlines()[-1:]))
    r2 = subprocess.run([sys.executable, str(ROOT / "tools" / "restore.py"),
                         "--from", str(backups[0]) if backups else "missing",
                         "--db", str(Path(tmp.name) / "restored.db")],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=tool_env)
    check("恢复工具：复制 + 校验行数", r2.returncode == 0,
          " / ".join((r2.stdout or "").strip().splitlines()[-1:]))
    r3 = subprocess.run([sys.executable, str(ROOT / "tools" / "bench.py"),
                         "--url", base, "--n", "40", "--c", "4"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=tool_env)
    check("压测工具跑通（40 请求 / 4 并发）", r3.returncode == 0,
          " / ".join((r3.stdout or "").strip().splitlines()[-1:]))

    # -- 通知公告（F8）+ 管理动作审计（收官补全）
    status, data, _ = get("/api/notices")
    check("匿名看公告 401", status == 401)
    status, data, _ = post("/api/notices",
                           {"title": "平台公告：本周维护", "body": "周五 22:00 停机演练",
                            "audience": "all"}, cookie=acookie)
    check("管理员发全员公告", status == 200 and data["notice"]["id"])
    nid = data["notice"]["id"] if status == 200 else 0
    status, data, _ = get("/api/me", cookie=cookie)
    check("学生未读 +1（/api/me unread）", data.get("unread", 0) >= 1)
    status, data, _ = get("/api/notices", cookie=cookie)
    check("公告列表含未读条目", any(x["id"] == nid and not x["read"] for x in data["notices"]))
    status, data, _ = post(f"/api/notices/{nid}/read", {}, cookie=cookie)
    check("标记已读", status == 200)
    status, data, _ = get("/api/me", cookie=cookie)
    check("已读后未读归零", data.get("unread") == 0)

    status, data, _ = post("/api/notices", {"title": "B11 作业提醒", "body": "下周交",
                                            "audience": "B11-net-lab"}, cookie=tcookie)
    check("教师发本课公告（绑定课）", status == 200)
    status, data, _ = post("/api/notices", {"title": "越权", "audience": "B3-logic-lab"},
                           cookie=tcookie)
    check("教师发未绑定课公告 403", status == 403)
    status, data, _ = post("/api/notices", {"title": "越权2", "audience": "all"}, cookie=tcookie)
    check("教师发全员公告 403", status == 403)
    status, data, _ = post("/api/notices", {"title": "学生乱发", "audience": "all"},
                           cookie=cookie)
    check("学生发公告 403", status == 403)
    status, data, _ = get("/api/notices", cookie=cookie)
    check("学生对有记录的课程可见该课公告",
          any(x["title"] == "B11 作业提醒" for x in data["notices"]))

    status, data, _ = get("/api/admin/audit", cookie=acookie)
    acts = {x["action"] for x in data.get("events", [])}
    check("管理动作审计（角色/状态/课程/公告四类留痕）",
          {"user_role", "user_status", "course_meta", "notice_publish"} <= acts,
          str(sorted(acts)))

    # -- F7 修改口令 + F9 课程维护（M8 补全）
    post("/api/auth/register",
         {"username": "stu_pw", "display_name": "改密同学", "password": "pw123456"})
    _, _, hp1 = post("/api/auth/login", {"username": "stu_pw", "password": "pw123456"})
    cp1 = cookie_of(hp1)
    _, _, hp2 = post("/api/auth/login", {"username": "stu_pw", "password": "pw123456"})
    cp2 = cookie_of(hp2)
    status, data, _ = post("/api/auth/password",
                           {"old_password": "pw123456", "new_password": "newpw12345"})
    check("匿名改口令 401", status == 401)
    status, data, _ = post("/api/auth/password",
                           {"old_password": "wrong-old1", "new_password": "newpw12345"},
                           cookie=cp1)
    check("当前口令不对 400（BAD_OLD_PASSWORD）",
          status == 400 and data["code"] == "BAD_OLD_PASSWORD")
    status, data, _ = post("/api/auth/password",
                           {"old_password": "pw123456", "new_password": "abcdefgh"},
                           cookie=cp1)
    check("新口令太弱 400（BAD_PASSWORD）", status == 400 and data["code"] == "BAD_PASSWORD")
    status, data, _ = post("/api/auth/password",
                           {"old_password": "pw123456", "new_password": "newpw12345"},
                           cookie=cp1)
    check("修改口令成功", status == 200)
    status, data, _ = get("/api/me", cookie=cp1)
    check("当前会话保留", status == 200 and (data.get("user") or {}).get("username") == "stu_pw")
    status, data, _ = get("/api/me", cookie=cp2)
    check("其他会话即时失效", status == 200 and data.get("user") is None)
    status, data, _ = post("/api/auth/login", {"username": "stu_pw", "password": "pw123456"})
    check("旧口令登录被拒 401", status == 401)
    status, data, _ = post("/api/auth/login", {"username": "stu_pw", "password": "newpw12345"})
    check("新口令登录成功", status == 200)

    status, data, _ = post("/api/teacher/course/meta",
                           {"course": "B3-logic-lab", "summary": "越权试试"}, cookie=tcookie)
    check("教师维护未绑定课 403", status == 403)
    status, data, _ = post("/api/teacher/course/meta",
                           {"course": "B11-net-lab",
                            "summary": "本课补充：先跑通 demo，再交实验报告",
                            "outline": "第 1 周 环境与演示\n第 2 周 HTTP 子集解析\n第 3 周 对拍与边界"},
                           cookie=tcookie)
    check("教师维护绑定课（补充简介 + 大纲）",
          status == 200 and data["meta"]["summary"].startswith("本课补充"))
    status, data, _ = get("/api/courses/B11-net-lab")
    m = (data.get("course") or {}).get("meta") or {}
    check("课程详情回读维护内容（标明来源教师）",
          m.get("summary", "").startswith("本课补充") and "第 2 周" in m.get("outline", "")
          and m.get("teacher"))
    status, data, _ = post("/api/teacher/course/meta",
                           {"course": "B11-net-lab", "summary": "x" * 121}, cookie=tcookie)
    check("补充简介超长 400（BAD_SUMMARY）", status == 400 and data["code"] == "BAD_SUMMARY")
    status, data, _ = post("/api/teacher/course/meta", {"course": "B11-net-lab"}, cookie=tcookie)
    check("空修改 400", status == 400)
    status, data, _ = post("/api/teacher/course/meta",
                           {"course": "B11-net-lab", "summary": "学生乱改"}, cookie=cookie)
    check("学生维护课程 403", status == 403)
    status, data, _ = post("/api/teacher/course/meta",
                           {"course": "B11-net-lab", "published": False}, cookie=tcookie)
    check("教师下架本课", status == 200 and data["meta"]["published"] is False)
    status, data, _ = get("/api/courses")
    check("下架后学生目录隐藏", all(c["id"] != "B11-net-lab" for c in data["courses"]))
    status, data, _ = get("/api/courses/B11-net-lab", cookie=cookie)
    check("下架后学生详情 404", status == 404)
    status, data, _ = post("/api/teacher/course/meta",
                           {"course": "B11-net-lab", "published": True}, cookie=tcookie)
    check("教师重新上架", status == 200 and data["meta"]["published"] is True)
    status, data, _ = get("/api/admin/audit", cookie=acookie)
    evs = [x for x in data.get("events", [])
           if x["action"] == "course_meta" and x["target"] == "B11-net-lab"]
    check("教师维护动作同样留痕（summary= 在 detail）",
          any("summary=" in x["detail"] for x in evs))
    status, data, _ = post("/api/admin/courses/B11-net-lab/meta",
                           {"summary": "管理员补写：面向全平台"}, cookie=acookie)
    check("管理端 meta 接口也接受 summary/outline", status == 200
          and data["meta"]["summary"] == "管理员补写：面向全平台")

    # -- 健壮性：畸形输入必须 4xx（探针抓出 teacher_id 非整数曾 500 崩线程）（M10）
    status, data, _ = post("/api/admin/courses/B11-net-lab/meta",
                           {"teacher_id": "abc"}, cookie=acookie)
    check("绑定教师编号非整数 400（修复前崩请求线程）",
          status == 400 and data["code"] == "BAD_TEACHER_ID")
    status, data, _ = post("/api/admin/courses/B11-net-lab/meta",
                           {"published": []}, cookie=acookie)
    check("published 非布尔 400", status == 400 and data["code"] == "BAD_PUBLISHED")
    status, data, _ = post("/api/admin/courses/B11-net-lab/meta",
                           {"summary": []}, cookie=acookie)
    check("summary 非文本 400", status == 400 and data["code"] == "BAD_SUMMARY")
    status, data, _ = post("/api/teacher/course/meta",
                           {"course": "B11-net-lab", "published": "xx"}, cookie=tcookie)
    check("教师端 published 非布尔 400", status == 400)
    sk = socket.create_connection(("127.0.0.1", port), timeout=5)
    sk.sendall(b"POST /api/auth/login HTTP/1.1\r\nHost: probe\r\n"
               b"Content-Length: abc\r\nContent-Type: application/json\r\n\r\n")
    resp = sk.recv(200)
    sk.close()
    line1 = resp.split(b"\r\n", 1)[0]
    check("畸形 Content-Length 不崩（按空 body 处理 → 401）", b" 401" in line1,
          line1.decode("latin-1"))

    # -- 访问量（F15）+ 日志保留（F18）+ 本课实验排行（F11）（M9 对账补全）
    log_dir = Path(tmp.name) / "logs"
    logs = sorted(log_dir.glob("app-*.log")) if log_dir.is_dir() else []
    check("访问日志落盘（数据目录 logs/app-日期.log）",
          bool(logs) and "[courselab]" in logs[-1].read_text(encoding="utf-8"))
    old_log = log_dir / "app-2000-01-01.log"
    old_log.write_text("old", encoding="utf-8")
    removed = prune_logs(log_dir, keep_days=14)
    check("日志保留策略（超 14 天自动清理）",
          removed >= 1 and not old_log.exists() and bool(logs) and logs[-1].exists())
    status, data, _ = get("/api/admin/overview", cookie=acookie)
    v0 = int(data.get("visits_today", 0))
    urllib.request.urlopen(base + "/", timeout=5).read()
    urllib.request.urlopen(base + "/me.html", timeout=5).read()
    status, data, _ = get("/api/admin/overview", cookie=acookie)
    v1 = int(data.get("visits_today", 0))
    check("访问计数：匿名访问 2 个页面 +2", v1 == v0 + 2, f"{v0} -> {v1}")
    get("/api/courses")
    get("/api/me")
    status, data, _ = get("/api/admin/overview", cookie=acookie)
    check("API 请求与资源不计入访问量", int(data.get("visits_today", 0)) == v1)
    stu_id = db.one("SELECT id FROM users WHERE username='stu_a'")["id"]
    db.execute("INSERT INTO lab_runs(id, user_id, pid, action, kind, started_at, finished_at,"
               " exit_code, log_tail) VALUES('rank1', ?, 'B11-net-lab', 'demo', 'task', ?, ?, 0, '')",
               (stu_id, now_str(), now_str()))
    status, data, _ = get("/api/teacher/course?course=B11-net-lab", cookie=tcookie)
    check("本课实验排行按人聚合（Top 10；夹具 1 条）",
          status == 200 and data.get("lab_rank") and data["lab_rank"][0]["n"] >= 1)

    # -- 竞态与清理：服务就绪判定 + 会话过期清扫（M11）
    hold = socket.socket()
    hold.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    hold.bind(("127.0.0.1", 8313))
    hold.listen(1)

    class _FadingProc:
        """端口可连、自己的进程随后死掉——复现"连上别人端口即宣告就绪"的竞态窗口。"""

        def __init__(self):
            self.t0 = time.time()

        def poll(self):
            return None if time.time() - self.t0 < 0.25 else 1

    probe_engine = labs.Labs(REPO, db, max_labs=1)
    try:
        probe_engine._wait_port({"proc": _FadingProc(), "port": 8313, "stopped": False})
        got = "OK(误报)"
    except labs.LabsError as exc:
        got = exc.code
    finally:
        hold.close()
    check("就绪判定不误报：端口可连但自己的进程随后退出 → SERVE_FAILED", got == "SERVE_FAILED", got)
    owner = db.one("SELECT id FROM users WHERE username='stu_a'")["id"]
    db.execute("INSERT INTO sessions(token, user_id, created_at, expires_at)"
               " VALUES('expired_tok', ?, '2000-01-01 00:00:00', '2000-01-02 00:00:00')",
               (owner,))
    db.execute("INSERT INTO sessions(token, user_id, created_at, expires_at)"
               " VALUES('live_tok', ?, '2000-01-01 00:00:00', '2999-01-01 00:00:00')",
               (owner,))
    swept = auth.sweep_sessions(db)
    left = {r["token"] for r in db.all("SELECT token FROM sessions")}
    check("启动会话清扫：过期删除、有效保留",
          swept >= 1 and "expired_tok" not in left and "live_tok" in left)

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

    for page in ("/", "/login.html", "/register.html", "/course.html", "/project.html",
                 "/me.html", "/tasks.html", "/notices.html", "/teacher.html", "/admin.html"):
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

def _db_path(cfg: dict) -> Path:
    d = Path(str(cfg.get("data_dir", "data")))
    return (d if d.is_absolute() else ROOT / d) / "app.db"


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="课程工坊 CourseLab（课程项目平台）")
    ap.add_argument("--config", default=None, help="配置文件（默认 courselab/config.json，存在才读）")
    ap.add_argument("--host", default=None, help="覆盖配置的 bind（如 0.0.0.0 供局域网访问）")
    ap.add_argument("--port", type=int, default=None, help="覆盖配置的 port（默认 7900）")
    ap.add_argument("--db", default=None, help="直接指定 SQLite 路径（默认 <data_dir>/app.db）")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--promote", nargs=2, metavar=("USERNAME", "ROLE"),
                    help="把已注册用户提升为 teacher/admin 后退出（角色管理工具）")
    args = ap.parse_args(argv[1:])
    if args.selftest:
        return selftest()
    cfg = load_config(args.config)
    if args.host:
        cfg["bind"] = args.host
    if args.port is not None:
        cfg["port"] = args.port
    db_path = Path(args.db) if args.db else _db_path(cfg)
    if args.promote:
        username, role = args.promote
        if role not in ("teacher", "admin"):
            print("[!] ROLE 只能是 teacher 或 admin")
            return 2
        db = DB(db_path)
        row = db.one("SELECT id FROM users WHERE username = ?", (username,))
        if row is None:
            print(f"[!] 没有用户 {username}——先在平台注册这个账号，再提升")
            db.close()
            return 1
        db.execute("UPDATE users SET role = ? WHERE id = ?", (role, row["id"]))
        print(f"已把 {username} 设为 {role}（立即生效）")
        db.close()
        return 0
    db = DB(db_path)
    return serve(int(cfg["port"]), db, cfg, open_browser=args.open)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
