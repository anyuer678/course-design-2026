"""CourseLab 平台态数据层：SQLite 连接 + 建表 + 线程安全封装。

原则：课程/项目内容现算自仓库（app/courses.py），本库只存平台自己的状态。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'student',
  pwd_salt TEXT NOT NULL,
  pwd_hash TEXT NOT NULL,
  pwd_iter INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  last_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  ip TEXT,
  ua TEXT
);
CREATE TABLE IF NOT EXISTS lab_runs (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  pid TEXT NOT NULL,
  action TEXT NOT NULL,
  kind TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  exit_code INTEGER,
  log_tail TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  course TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT DEFAULT '',
  due_at TEXT,
  created_by INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_records (
  task_key TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  course TEXT NOT NULL,
  status TEXT NOT NULL,
  note TEXT DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (task_key, user_id)
);
CREATE TABLE IF NOT EXISTS course_meta (
  course TEXT PRIMARY KEY,
  published INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0,
  teacher_id INTEGER
);
"""


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class DB:
    """单连接 + 一把锁：ThreadingHTTPServer 并发的写法下够用且简单。"""

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lk = threading.Lock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def execute(self, sql: str, args=()):
        with self._lk:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def one(self, sql: str, args=()):
        with self._lk:
            return self.conn.execute(sql, args).fetchone()

    def all(self, sql: str, args=()):
        with self._lk:
            return self.conn.execute(sql, args).fetchall()

    def close(self) -> None:
        with self._lk:
            self.conn.close()
