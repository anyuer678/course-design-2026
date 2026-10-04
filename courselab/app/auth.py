"""账号与会话（F1 学生端 / F16 底座）：注册、登录、登出、PBKDF2、会话表、登录限流。

边界（沿用设计文档 §三 F1）：
- 口令 PBKDF2-HMAC-SHA256，盐 16B，迭代 120000，参数随用户存库；
- 会话 = 随机令牌 + 服务端会话表（可登出即失效），默认 12 小时；
- 登录失败限流：同"用户名+IP" 10 分钟内失败 5 次后 429。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta

from app.db import now_str

PWD_ITER = 120_000
SESSION_HOURS = 12
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
RATE_WINDOW = 600.0
RATE_LIMIT = 5

_fail_log: dict = {}     # "username|ip" -> [失败时间戳]


class AuthError(Exception):
    def __init__(self, code: str, message: str, http: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


# ------------------------------------------------------------------ 口令

def hash_password(password: str):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PWD_ITER)
    return salt.hex(), dk.hex(), PWD_ITER


def verify_password(password: str, salt_hex: str, hash_hex: str, iterations: int) -> bool:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             bytes.fromhex(salt_hex), iterations)
    return hmac.compare_digest(dk.hex(), hash_hex)


# ------------------------------------------------------------------ 校验

def validate_password(password: str) -> None:
    if len(password or "") < 8 or not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        raise AuthError("BAD_PASSWORD", "口令至少 8 位，且需同时包含字母与数字")


def validate_credentials(username: str, password: str) -> None:
    if not USERNAME_RE.match(username or ""):
        raise AuthError("BAD_USERNAME", "用户名需为 3-32 位字母/数字/下划线")
    validate_password(password)


# ------------------------------------------------------------------ 限流

def _key(username: str, ip: str) -> str:
    return f"{(username or '').lower()}|{ip}"


def check_rate(username: str, ip: str) -> None:
    now = time.time()
    lst = [t for t in _fail_log.get(_key(username, ip), []) if now - t < RATE_WINDOW]
    _fail_log[_key(username, ip)] = lst
    if len(lst) >= RATE_LIMIT:
        wait = int(RATE_WINDOW - (now - lst[0])) + 1
        raise AuthError("RATE_LIMITED", f"失败次数过多，请 {wait} 秒后再试", 429)


def record_failure(username: str, ip: str) -> None:
    _fail_log.setdefault(_key(username, ip), []).append(time.time())


def clear_failures(username: str, ip: str) -> None:
    _fail_log.pop(_key(username, ip), None)


# ------------------------------------------------------------------ 用户与会话

def _user_public(row) -> dict:
    return {
        "id": row["id"], "username": row["username"], "display_name": row["display_name"],
        "role": row["role"], "status": row["status"],
        "created_at": row["created_at"], "last_login": row["last_login"],
    }


def register(db, username: str, display_name: str, password: str, status: str = "active") -> dict:
    validate_credentials(username, password)
    display_name = (display_name or "").strip() or username
    if len(display_name) > 32:
        raise AuthError("BAD_DISPLAY_NAME", "昵称最长 32 个字符")
    if status not in ("active", "pending"):
        raise AuthError("BAD_STATUS", "注册状态只能是 active / pending")
    if db.one("SELECT id FROM users WHERE username = ?", (username,)):
        raise AuthError("USER_EXISTS", "用户名已被占用", 409)
    salt, hsh, it = hash_password(password)
    cur = db.execute(
        "INSERT INTO users(username, display_name, role, pwd_salt, pwd_hash, pwd_iter, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (username, display_name, "student", salt, hsh, it, status, now_str()))
    return _user_public(db.one("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)))


def create_session(db, user_id: int, ip: str = "", ua: str = "",
                   hours: float = SESSION_HOURS) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=hours)
    db.execute("INSERT INTO sessions(token, user_id, created_at, expires_at, ip, ua) VALUES(?,?,?,?,?,?)",
               (token, user_id, now_str(), expires.strftime("%Y-%m-%d %H:%M:%S"), ip, (ua or "")[:200]))
    return token


def login(db, username: str, password: str, ip: str = "", ua: str = "",
          hours: float = SESSION_HOURS) -> tuple:
    check_rate(username, ip)
    row = db.one("SELECT * FROM users WHERE username = ?", (username,))
    if row is None or not verify_password(password, row["pwd_salt"], row["pwd_hash"], row["pwd_iter"]):
        record_failure(username, ip)
        raise AuthError("BAD_CREDENTIALS", "用户名或口令不正确", 401)
    if row["status"] == "pending":
        raise AuthError("USER_PENDING", "账号待管理员审批（通过后即可登录）", 403)
    if row["status"] != "active":
        raise AuthError("USER_DISABLED", "账号已被封禁", 403)
    clear_failures(username, ip)
    token = create_session(db, row["id"], ip, ua, hours)
    db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now_str(), row["id"]))
    return _user_public(db.one("SELECT * FROM users WHERE id = ?", (row["id"],))), token


def change_password(db, user_id: int, old_password: str, new_password: str,
                    keep_token: str = "", ip: str = "") -> None:
    """改口令：旧口令校验（计入登录失败限流）；改后其他会话立即失效、当前会话保留。"""
    row = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        raise AuthError("NO_USER", "用户不存在", 404)
    check_rate(row["username"], ip)
    if not verify_password(old_password, row["pwd_salt"], row["pwd_hash"], row["pwd_iter"]):
        record_failure(row["username"], ip)
        raise AuthError("BAD_OLD_PASSWORD", "当前口令不正确")
    validate_password(new_password)
    salt, hsh, it = hash_password(new_password)
    db.execute("UPDATE users SET pwd_salt = ?, pwd_hash = ?, pwd_iter = ? WHERE id = ?",
               (salt, hsh, it, user_id))
    db.execute("DELETE FROM sessions WHERE user_id = ? AND token != ?", (user_id, keep_token or ""))
    clear_failures(row["username"], ip)


def logout(db, token: str) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))


def user_by_session(db, token: str):
    if not token:
        return None
    row = db.one(
        "SELECT u.id, u.username, u.display_name, u.role, u.status, u.created_at, u.last_login,"
        " s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?", (token,))
    if row is None:
        return None
    if row["expires_at"] <= now_str() or row["status"] != "active":
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    return _user_public(row)
