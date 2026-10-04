"""linkbox/stash.py —— 文本暂存：带过期时间的自毁便签。

课程要点延续（B32 的教训直接用在这里）：
    - 内容是用户输入，展示层必须转义（app.py 里用 html.escape），存储层只管存原文；
    - id 用 B31 同款 base62（encode_id(rowid)），路由空间独立（/s/ 前缀），
      与短链的 /l/ 不冲突；
    - 过期语义：访问时惰性删除——命中过期条目就删掉并返回"已过期"，
      库里不留僵尸行；没有后台清扫线程（教学简化，见 README 局限）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from b31.codec import encode_id

MAX_CONTENT = 100_000                         # 单条上限（字符）
MIN_TTL_HOURS, MAX_TTL_HOURS = 0.01, 8760.0   # 1 小时到 1 年


class StashError(ValueError):
    """内容或 TTL 不合法（映射 400）。"""


class StashGone(Exception):
    """存在过但已过期（映射 410）。携带原内容供"过期通知"展示。"""

    def __init__(self, code: str, content: str):
        super().__init__(f"暂存 {code!r} 已过期")
        self.code = code
        self.content = content


class StashRecord:
    __slots__ = ("code", "content", "created_at", "expires_at")

    def __init__(self, code: str, content: str, created_at: float,
                 expires_at: float):
        self.code = code
        self.content = content
        self.created_at = created_at
        self.expires_at = expires_at


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
        self.conn.commit()

    # ------------------------------------------------ 创建
    def create(self, content: str, *, ttl_hours: float = 24.0,
               now: float) -> StashRecord:
        if not isinstance(content, str) or not (0 < len(content) <= MAX_CONTENT):
            raise StashError(f"content 长度须在 1..{MAX_CONTENT} 字符")
        if not (MIN_TTL_HOURS <= ttl_hours <= MAX_TTL_HOURS):
            raise StashError(f"ttl_hours 须在 {MIN_TTL_HOURS}..{MAX_TTL_HOURS}")
        # 与 B31 同款"id 即编码"：先拿 rowid，再编成 base62 回填
        cur = self.conn.execute(
            "INSERT INTO stashes (code, content, created_at, expires_at) "
            "VALUES (NULL, ?, ?, ?)", (content, now, now + ttl_hours * 3600))
        code = encode_id(cur.lastrowid)
        self.conn.execute("UPDATE stashes SET code = ? WHERE id = ?",
                          (code, cur.lastrowid))
        self.conn.commit()
        return StashRecord(code, content, now, now + ttl_hours * 3600)

    # ------------------------------------------------ 查询（含惰性过期）
    def get(self, code: str, *, now: float) -> StashRecord | None:
        """返回记录；已过期 -> 删除并抛 StashGone（附原内容，供过期页展示）；
        不存在 -> None。"""
        row = self.conn.execute(
            "SELECT id, content, created_at, expires_at FROM stashes "
            "WHERE code = ?", (code,)).fetchone()
        if row is None:
            return None
        rid, content, created_at, expires_at = row
        if now >= expires_at:
            self.conn.execute("DELETE FROM stashes WHERE id = ?", (rid,))
            self.conn.commit()
            raise StashGone(code, content)
        return StashRecord(code, content, created_at, expires_at)

    def delete(self, code: str) -> bool:
        cur = self.conn.execute("DELETE FROM stashes WHERE code = ?", (code,))
        self.conn.commit()
        return cur.rowcount > 0

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM stashes").fetchone()[0]
