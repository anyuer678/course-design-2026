"""linkbox/stash.py —— 文本暂存：带过期时间的自毁便签（M2 起支持可选访问口令）。

课程要点延续（B32 的教训直接用在这里）：
    - 内容是用户输入，展示层必须转义（app.py 里用 html.escape），存储层只管存原文；
    - 对外 code 用密码学随机（new_code，40 bit 十六进制，不可枚举），路由空间独立
      （/s/ 前缀），与短链的 /l/ 不冲突；
    - 过期语义：访问时惰性删除——命中过期条目就删掉并返回"已过期"，
      库里不留僵尸行；没有后台清扫线程（教学简化，见 README 局限）；
    - 口令只存 PBKDF2-HMAC-SHA256（随机盐 + hmac.compare_digest 恒时比较），
      绝不存原文——口令校验是 B32 sec-lab"单向存储"知识点的产品化落地。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from pathlib import Path


def new_code(conn: sqlite3.Connection, table: str) -> str:
    """对外 code：密码学随机十六进制（40 bit），不可枚举、不可预测。
    2026-10-07 审查收口——旧版 encode_id(rowid) 顺序可猜，未设口令的
    条目等于向知道地址段的来访者裸奔。极小概率撞码：查表重试。"""
    for _ in range(5):
        code = secrets.token_hex(5)
        if conn.execute(f"SELECT 1 FROM {table} WHERE code = ?",
                        (code,)).fetchone() is None:
            return code
    raise RuntimeError("随机 code 连续撞表（概率事件，检查熵源）")

MAX_CONTENT = 100_000                         # 单条上限（字符）
MIN_TTL_HOURS, MAX_TTL_HOURS = 0.01, 8760.0   # 1 小时到 1 年
MAX_PASSCODE_LEN = 128                        # 口令上限（超出只会拖慢哈希，不增加强度）

# OWASP 口令存储口径：PBKDF2-HMAC-SHA256 2021 建议 210k 次（2023 更新为 600k）。
# 本机单用户教学产品取 210k：实测 124 ms/条（600k 为 338 ms），安全与测试耗时的折中，
# 此偏离已登记在项目 README。
PBKDF2_ITERATIONS = 210_000
SALT_LEN = 16                                 # os.urandom 字节数


class StashError(ValueError):
    """内容、TTL 或口令不合法（映射 400）。"""


class StashGone(Exception):
    """存在过但已过期（映射 410）。携带原内容供"过期通知"展示。"""

    def __init__(self, code: str, content: str):
        super().__init__(f"暂存 {code!r} 已过期")
        self.code = code
        self.content = content


def _passcode_digest(passcode: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passcode, salt, PBKDF2_ITERATIONS)


class StashRecord:
    __slots__ = ("code", "content", "created_at", "expires_at", "has_passcode")

    def __init__(self, code: str, content: str, created_at: float,
                 expires_at: float, has_passcode: bool = False):
        self.code = code
        self.content = content
        self.created_at = created_at
        self.expires_at = expires_at
        self.has_passcode = has_passcode


class StashStore:
    def __init__(self, path: str | Path = ":memory:"):
        Path(path).parent.mkdir(parents=True, exist_ok=True) if path != ":memory:" else None
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS stashes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )""")
        # M1 -> M2 迁移：老库没有口令两列，ALTER 加上（已存在则忽略）
        for col in ("pass_salt BLOB", "pass_hash BLOB"):
            try:
                self.conn.execute(f"ALTER TABLE stashes ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass                    # 列已存在：老库重复打开走到这里
        self.conn.commit()

    # ------------------------------------------------ 创建
    def create(self, content: str, *, ttl_hours: float = 24.0,
               now: float, passcode: str | None = None) -> StashRecord:
        if not isinstance(content, str) or not (0 < len(content) <= MAX_CONTENT):
            raise StashError(f"content 长度须在 1..{MAX_CONTENT} 字符")
        if not (MIN_TTL_HOURS <= ttl_hours <= MAX_TTL_HOURS):
            raise StashError(f"ttl_hours 须在 {MIN_TTL_HOURS}..{MAX_TTL_HOURS}")
        if passcode is not None:
            if not isinstance(passcode, str) or not (1 <= len(passcode) <= MAX_PASSCODE_LEN):
                raise StashError(f"passcode 须为 1..{MAX_PASSCODE_LEN} 字符的字符串")
            salt = os.urandom(SALT_LEN)
            digest = _passcode_digest(passcode.encode("utf-8"), salt)
        else:
            salt = digest = None
        # 与 B31 同款"id 即编码"：先拿 rowid，再编成 base62 回填
        cur = self.conn.execute(
            "INSERT INTO stashes (code, content, created_at, expires_at, "
            "pass_salt, pass_hash) VALUES (NULL, ?, ?, ?, ?, ?)",
            (content, now, now + ttl_hours * 3600, salt, digest))
        code = new_code(self.conn, "stashes")
        self.conn.execute("UPDATE stashes SET code = ? WHERE id = ?",
                          (code, cur.lastrowid))
        self.conn.commit()
        return StashRecord(code, content, now, now + ttl_hours * 3600,
                           has_passcode=digest is not None)

    # ------------------------------------------------ 查询（含惰性过期）
    def get(self, code: str, *, now: float) -> StashRecord | None:
        """返回记录；已过期 -> 删除并抛 StashGone（附原内容，供过期页展示）；
        不存在 -> None。口令材料不进记录——校验走 verify_passcode。"""
        row = self.conn.execute(
            "SELECT id, content, created_at, expires_at, pass_hash FROM stashes "
            "WHERE code = ?", (code,)).fetchone()
        if row is None:
            return None
        rid, content, created_at, expires_at, pass_hash = row
        if now >= expires_at:
            self.conn.execute("DELETE FROM stashes WHERE id = ?", (rid,))
            self.conn.commit()
            raise StashGone(code, content)
        return StashRecord(code, content, created_at, expires_at,
                           has_passcode=pass_hash is not None)

    def verify_passcode(self, code: str, candidate: str | None) -> bool:
        """恒时比较口令。记录不存在 / 未设口令 / 候选不匹配 -> False。"""
        row = self.conn.execute(
            "SELECT pass_salt, pass_hash FROM stashes WHERE code = ?",
            (code,)).fetchone()
        if row is None or row[0] is None or row[1] is None:
            return False
        salt, expected = row
        return hmac.compare_digest(
            _passcode_digest((candidate or "").encode("utf-8"), salt), expected)

    def delete(self, code: str) -> bool:
        cur = self.conn.execute("DELETE FROM stashes WHERE code = ?", (code,))
        self.conn.commit()
        return cur.rowcount > 0

    def sweep(self, *, now: float) -> int:
        """清掉全部已过期行，返回删了几条（M3：配合后台线程定时跑；
        惰性过期只清被访问的，这条把"没人访问的僵尸行"也收走）。"""
        cur = self.conn.execute("DELETE FROM stashes WHERE expires_at <= ?",
                                (now,))
        self.conn.commit()
        return cur.rowcount

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM stashes").fetchone()[0]
