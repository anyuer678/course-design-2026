"""linkbox/files.py —— 文件暂存：手机↔电脑互传的落盘版暂存（轮八真功能）。

与 stash.py 同一套语义，三处不同：
    - 内容是**二进制**：元数据进 SQLite（files 表），字节落盘
      <数据目录>/files/<code>.bin——文件名只是展示元数据，取件路径永远
      是 /f/<code>，路径穿越在结构上不可能（B31/B32 的老教训）；
    - 上限是字节不是字符：MAX_FILE_BYTES（32 MiB）；传输层 max_body 由
      server.py 按它放宽（netlab 默认 1 MiB 是为 JSON 设计的）；
    - 下载头 Content-Disposition: attachment——文件永远当附件下载，
      不给浏览器当页面渲染（XSS 的最后一道闸）。
口令/过期/清扫语义与 stash 完全一致：PBKDF2 恒时比较、惰性过期、
sweep(now) 供后台线程定时跑。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from .stash import new_code

MAX_FILE_BYTES = 32 * 1024 * 1024             # 单文件上限（32 MiB）
MIN_TTL_HOURS, MAX_TTL_HOURS = 0.01, 8760.0   # 与 stash 同口径
MAX_PASSCODE_LEN = 128
MAX_NAME_LEN = 120
PBKDF2_ITERATIONS = 210_000                   # 与 stash 同参数（偏离已登记 README）
SALT_LEN = 16

_NAME_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')
DEFAULT_NAME = "file.bin"


class FileError(ValueError):
    """文件、TTL、文件名或口令不合法（映射 400）。"""


class FileGone(Exception):
    """存在过但已过期（映射 410）。"""

    def __init__(self, code: str):
        super().__init__(f"文件 {code!r} 已过期")
        self.code = code


def safe_name(name: str | None) -> str:
    """文件名只当展示元数据：去路径、去控制符与 Windows 保留字符、限长。
    不合法就退回 file.bin——绝不参与取件路径。"""
    base = (name or "").replace("\\", "/").split("/")[-1].strip().lstrip(".")
    base = _NAME_BAD.sub("_", base).strip()
    return (base or DEFAULT_NAME)[:MAX_NAME_LEN]


def content_disposition(name: str) -> str:
    """RFC 6266/5987：ASCII 回退 + UTF-8 扩展（中文文件名不乱码）。"""
    ascii_fb = name.encode("ascii", "ignore").decode("ascii").strip() or "download"
    return f"attachment; filename=\"{ascii_fb}\"; filename*=UTF-8''{quote(name)}"


def content_disposition_inline(name: str) -> str:
    """预览版 disposition：inline + 同样的双编码文件名。"""
    ascii_fb = name.encode("ascii", "ignore").decode("ascii").strip() or "file"
    return f"inline; filename=\"{ascii_fb}\"; filename*=UTF-8''{quote(name)}"


# 在线预览白名单（2026-10-12 升级动作②）：只放"渲染成图/文档也不可能有脚本"
# 的类型。HTML/HTM/XML **故意不在表里**——它们 inline 渲染就是存储型 XSS 的门；
# SVG 虽可携带 <script>，但预览响应带 CSP sandbox 头（见 app.py），脚本必然不执行。
PREVIEW_CONTENT_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".svg": "image/svg+xml", ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
    ".csv": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8",
}


def preview_content_type(name: str) -> str | None:
    """按文件名扩展查预览类型；不在白名单返回 None（映射 415）。"""
    base = name.rsplit(".", 1)
    if len(base) != 2:
        return None
    return PREVIEW_CONTENT_TYPES.get("." + base[1].lower())


def _passcode_digest(passcode: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passcode, salt, PBKDF2_ITERATIONS)


class FileRecord:
    __slots__ = ("code", "name", "size", "created_at", "expires_at", "has_passcode")

    def __init__(self, code: str, name: str, size: int, created_at: float,
                 expires_at: float, has_passcode: bool = False):
        self.code = code
        self.name = name
        self.size = size
        self.created_at = created_at
        self.expires_at = expires_at
        self.has_passcode = has_passcode


class FileStore:
    def __init__(self, path: str | Path = ":memory:"):
        if path == ":memory:":
            self._mem: dict[str, bytes] = {}
            self._blobs: Path | None = None
        else:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._blobs = path.parent / "files"
            self._blobs.mkdir(parents=True, exist_ok=True)
            self._mem = {}
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                name TEXT NOT NULL,
                size INTEGER NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )""")
        for col in ("pass_salt BLOB", "pass_hash BLOB"):
            try:
                self.conn.execute(f"ALTER TABLE files ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass                    # 列已存在：老库重复打开走到这里
        self.conn.commit()

    # ------------------------------------------------ 内部：字节读写
    def _write_blob(self, code: str, data: bytes) -> None:
        if self._blobs is None:
            self._mem[code] = data
        else:
            (self._blobs / f"{code}.bin").write_bytes(data)

    def _read_blob(self, code: str) -> bytes:
        if self._blobs is None:
            return self._mem.get(code, b"")
        p = self._blobs / f"{code}.bin"
        return p.read_bytes() if p.exists() else b""

    def _drop_blob(self, code: str) -> None:
        if self._blobs is None:
            self._mem.pop(code, None)
        else:
            (self._blobs / f"{code}.bin").unlink(missing_ok=True)

    # ------------------------------------------------ 创建
    def create(self, data: bytes, name: str | None, *, ttl_hours: float = 24.0,
               now: float, passcode: str | None = None) -> FileRecord:
        if not isinstance(data, (bytes, bytearray)) or not (0 < len(data) <= MAX_FILE_BYTES):
            raise FileError(f"文件大小须在 1..{MAX_FILE_BYTES} 字节")
        if not (MIN_TTL_HOURS <= ttl_hours <= MAX_TTL_HOURS):
            raise FileError(f"ttl_hours 须在 {MIN_TTL_HOURS}..{MAX_TTL_HOURS}")
        if passcode is not None:
            if not isinstance(passcode, str) or not (1 <= len(passcode) <= MAX_PASSCODE_LEN):
                raise FileError(f"passcode 须为 1..{MAX_PASSCODE_LEN} 字符的字符串")
            salt = os.urandom(SALT_LEN)
            digest = _passcode_digest(passcode.encode("utf-8"), salt)
        else:
            salt = digest = None
        clean = safe_name(name)
        cur = self.conn.execute(
            "INSERT INTO files (code, name, size, created_at, expires_at, "
            "pass_salt, pass_hash) VALUES (NULL, ?, ?, ?, ?, ?, ?)",
            (clean, len(data), now, now + ttl_hours * 3600, salt, digest))
        code = new_code(self.conn, "files")
        self.conn.execute("UPDATE files SET code = ? WHERE id = ?", (code, cur.lastrowid))
        self.conn.commit()
        self._write_blob(code, bytes(data))
        return FileRecord(code, clean, len(data), now, now + ttl_hours * 3600,
                          has_passcode=digest is not None)

    # ------------------------------------------------ 查询（含惰性过期）
    def get(self, code: str, *, now: float) -> FileRecord | None:
        """返回记录；已过期 -> 删行+删盘并抛 FileGone；不存在 -> None。"""
        row = self.conn.execute(
            "SELECT id, name, size, created_at, expires_at, pass_hash FROM files "
            "WHERE code = ?", (code,)).fetchone()
        if row is None:
            return None
        rid, name, size, created_at, expires_at, pass_hash = row
        if now >= expires_at:
            self.conn.execute("DELETE FROM files WHERE id = ?", (rid,))
            self.conn.commit()
            self._drop_blob(code)
            raise FileGone(code)
        return FileRecord(code, name, size, created_at, expires_at,
                          has_passcode=pass_hash is not None)

    def read(self, code: str) -> bytes:
        return self._read_blob(code)

    def verify_passcode(self, code: str, candidate: str | None) -> bool:
        row = self.conn.execute(
            "SELECT pass_salt, pass_hash FROM files WHERE code = ?",
            (code,)).fetchone()
        if row is None or row[0] is None or row[1] is None:
            return False
        salt, expected = row
        return hmac.compare_digest(
            _passcode_digest((candidate or "").encode("utf-8"), salt), expected)

    def delete(self, code: str) -> bool:
        cur = self.conn.execute("DELETE FROM files WHERE code = ?", (code,))
        self.conn.commit()
        if cur.rowcount > 0:
            self._drop_blob(code)
            return True
        return False

    def sweep(self, *, now: float) -> int:
        """清掉全部已过期行（连带删盘），返回删了几条。"""
        gone = self.conn.execute(
            "SELECT code FROM files WHERE expires_at <= ?", (now,)).fetchall()
        if not gone:
            return 0
        self.conn.execute("DELETE FROM files WHERE expires_at <= ?", (now,))
        self.conn.commit()
        for (code,) in gone:
            self._drop_blob(code)
        return len(gone)

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
