"""studio/audit.py —— 门户操作审计（M2，2026-10-07）：启停动作落 SQLite。

口径：
    - 只记"管理动作"（产品的 start/stop），目录浏览与状态查询不记（只读无副作用）；
    - 拒绝也如实入账（already_online / not_ours / planned）——审计的价值恰恰在
      "有人想做什么而没做成"；
    - 纯幂等空操作（stop 一个本来就离线的产品）不记，避免账面噪音；
    - SQLite 连接只被 webframe 的事件循环线程使用（webframe 单线程），仍配锁：
      审计要在任何线程模型下都不出账。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    action  TEXT NOT NULL,
    pid     TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail  TEXT NOT NULL DEFAULT ''
);
"""

_KEYS = ("ts", "action", "pid", "outcome", "detail")


class AuditLog:
    """追加写的操作账本。record 只进不出；tail 倒序取最近的。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def record(self, action: str, pid: str, outcome: str, detail: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log (ts, action, pid, outcome, detail) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), action, pid, outcome, str(detail)[:300]))
            self._conn.commit()

    def tail(self, limit: int = 200) -> list[dict]:
        limit = max(1, min(1000, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, action, pid, outcome, detail FROM audit_log "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(_KEYS, row)) for row in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM audit_log").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
                self._conn.close()
            except sqlite3.Error:
                pass
