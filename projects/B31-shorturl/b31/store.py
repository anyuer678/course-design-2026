"""b31/store.py —— SQLite 仓储：短码 → 目标，外加命中计数。

三件事值得单独写一层，而不是散在 handler 里：

* **短码从哪来**：不自定义随机串，而是给每条链接一个自增 id，再把 id 编成 base62。
  这样"编码"和"唯一性"是同一件事，不需要重试撞库，也不需要锁。
  代价是可枚举（`/l/1`、`/l/2` 都在），教学实现里把它写进局限，不当成就。
* **计数不能算错**：命中数用一条 `UPDATE ... SET hits = hits + 1` 完成，
  读—改—写在数据库里是一次动作。若在 Python 里先读再加再写，两个请求就会互相覆盖。
* **只写参数化 SQL**：短码是用户输入，任何字符串拼接都会把 `' OR 1=1--` 变成语法的一部分。

时间戳由调用方传入（`now`），测试里才能不用 sleep 就断言"最后一次访问时间更新了"。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .codec import MAX_CODE_LEN, encode_id, is_code_shape

MAX_LINKS = 5000                       # 单表容量上限：到了就拒绝新建，而不是悄悄淘汰旧数据
MAX_CODE_PROBES = 64                   # 取号最多试这么多次（别名占满了名字空间就该报错了）
MAX_LIST = 200
CLICK_KINDS = ("link", "stash", "file")   # 访问流水的三类对象（LinkBox 产品层语义）
CLICK_RETAIN_DAYS = 90                 # 流水保留窗口：统计只用近期，老流水无价值还占库
CLICK_MAX_ROWS = 50000                 # 流水行数硬上限：防高频访问把库撑爆
CLICK_MAX_DAYS = 90                    # 统计查询最多回看天数


class ConflictError(Exception):
    """别名已存在。带上占用者，好让调用方给出"这条是谁的"这种可操作的错误。"""

    def __init__(self, code: str, target: str):
        super().__init__(f"短码 {code!r} 已被占用")
        self.code = code
        self.target = target


class AliasError(ValueError):
    """别名形状不对。"""


class CapacityError(ValueError):
    """链接数到上限：这是资源问题，不该和"用户写错了"混成同一种错误。"""


@dataclass
class Link:
    code: str
    target: str
    created_at: float
    hits: int
    last_visit: float | None

    def as_dict(self) -> dict:
        return {"code": self.code, "target": self.target, "created_at": self.created_at,
                "hits": self.hits, "last_visit": self.last_visit}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sequences (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS links (
    id         INTEGER PRIMARY KEY,
    code       TEXT NOT NULL UNIQUE,          -- BINARY 排序：'Ab' 与 'ab' 是两条链接
    target     TEXT NOT NULL,
    created_at REAL NOT NULL,
    hits       INTEGER NOT NULL DEFAULT 0,
    last_visit REAL
);
CREATE INDEX IF NOT EXISTS links_created ON links(created_at DESC);
CREATE TABLE IF NOT EXISTS clicks (
    kind TEXT NOT NULL,                -- 'link' / 'stash' / 'file'（LinkBox 三类对象）
    code TEXT NOT NULL,
    ts   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS clicks_ts ON clicks(ts);
"""


class Store:
    def __init__(self, path=":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # 单线程服务器 + 一个连接就够；isolation_level=None 让我们自己掌控事务，
        # 不然 Python 的隐式 BEGIN 会在最奇怪的时候插入。
        #
        # check_same_thread=False 是必需的：连接在主线程建，而请求在事件循环线程里处理。
        # 但"允许跨线程"不等于"随便并发"：create() 里的 BEGIN/COMMIT 跨了好几条语句，
        # 两个线程交错执行就会互相把对方的事务一起提交或回滚。
        # 所以外面加一把锁，把"一次逻辑操作"钉成一段——数据库自带序列化，
        # 可它不知道哪几条语句属于同一个业务动作，我们知道。
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self.db.close()

    # ------------------------------------------------------------------ 写入

    def count(self) -> int:
        with self._lock:
            return self.db.execute("SELECT COUNT(*) FROM links").fetchone()[0]

    def create(self, target: str, *, alias: str | None = None, now: float | None = None) -> Link:
        now = time.time() if now is None else now
        if alias is not None and not is_code_shape(alias):
            raise AliasError(f"别名 {alias!r} 不合法：只能用 base62 字母表、长度 1..{MAX_CODE_LEN}")
        with self._lock:
            if self.count() >= MAX_LINKS:
                raise CapacityError(f"链接数已到上限 {MAX_LINKS}，先删旧的")
            self.db.execute("BEGIN IMMEDIATE")
            try:
                if alias is None:
                    code = self._take_free_code()
                else:
                    code = alias
                    exists = self.db.execute(
                        "SELECT target FROM links WHERE code = ?", (code,)).fetchone()
                    if exists is not None:
                        self.db.execute("ROLLBACK")
                        raise ConflictError(code, exists[0])
                self.db.execute(
                    "INSERT INTO links(code, target, created_at, hits) VALUES(?, ?, ?, 0)",
                    (code, target, now))
                self.db.execute("COMMIT")
            except Exception:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise
            return Link(code=code, target=target, created_at=now, hits=0, last_visit=None)

    def _take_free_code(self) -> str:
        """取号直到拿到一个没被占用的短码。

        别名和自动码共用一个名字空间：用户先建了别名 `1`，自增 id 走到 1 时
        就会撞上它。这时候不能把 409 抛给一个"根本没挑过短码"的请求——
        跳过已占用的号，冲突只在用户明确指定别名时才可能发生。
        """
        for _ in range(MAX_CODE_PROBES):
            row = self.db.execute(
                "INSERT INTO sequences(name, value) VALUES('link', 1) "
                "ON CONFLICT(name) DO UPDATE SET value = value + 1 RETURNING value").fetchone()
            code = encode_id(row[0])
            if self.db.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone() is None:
                return code
        raise CapacityError(f"连续 {MAX_CODE_PROBES} 次取号都撞上别名，先清理别名再建")

    def visit(self, code: str, *, now: float | None = None) -> Link:
        """命中一次：计数与时间戳一条语句更新，并落一条点击流水（趋势统计的数据源）。
        找不到就抛 KeyError（由路由层翻译成 404）。"""
        now = time.time() if now is None else now
        with self._lock:
            row = self.db.execute(
                "UPDATE links SET hits = hits + 1, last_visit = ? WHERE code = ? "
                "RETURNING target, created_at, hits, last_visit", (now, code)).fetchone()
            if row is None:
                raise KeyError(code)
            self._log_click("link", code, now)
        return Link(code=code, target=row[0], created_at=row[1], hits=row[2], last_visit=row[3])

    # ------------------------------------------------------------- 点击流水（LinkBox 趋势统计）
    @staticmethod
    def _window_since(days: int) -> float:
        """统计窗口下界：今天 00:00 往回推 (days-1) 天——与 click_series 的
        localtime 分日同一锚点。不能用 time.time()-(days-1)*86400：days=1 时
        下界=此刻，今天早些时候的访问会全部漏掉（实测抓过）。"""
        import datetime as _dt
        midnight = _dt.datetime.combine(_dt.date.today(),
                                        _dt.time.min).timestamp()
        return midnight - (days - 1) * 86400.0
    def _log_click(self, kind: str, code: str, now: float) -> None:
        """入账一条访问流水 + 低频治理（过期裁剪 + 行数上限）。
        调用方必须已持有 _lock。治理的两条 DELETE 都走 ts 索引/主键，本地库无压力。"""
        self.db.execute("INSERT INTO clicks(kind, code, ts) VALUES(?, ?, ?)",
                        (kind, code, now))
        # 裁剪参照必须是真实墙钟而不是调用方注入的 now：注入时钟是给"数据时间戳"
        # 用的（测试不必 sleep），而"保留最近 90 天"是相对真实现在的治理规则——
        # 若拿注入 now 当参照，测试注入过去时间戳时阈值跟着回到过去，老流水永远清不掉。
        self.db.execute("DELETE FROM clicks WHERE ts < ?",
                        (time.time() - CLICK_RETAIN_DAYS * 86400.0,))
        self.db.execute(
            "DELETE FROM clicks WHERE rowid IN "
            "(SELECT rowid FROM clicks ORDER BY ts DESC LIMIT -1 OFFSET ?)",
            (CLICK_MAX_ROWS,))

    def log_click(self, kind: str, code: str, *, now: float | None = None) -> None:
        """产品层入账入口：暂存/文件的"打开"不走 Store.visit，从这里补一条流水。
        kind 不在三类对象里就拒绝——流水表列没有约束，脏数据只能靠入口挡。"""
        if kind not in CLICK_KINDS:
            raise ValueError(f"未知流水类型 {kind!r}，只接受 {CLICK_KINDS}")
        now = time.time() if now is None else now
        with self._lock:
            self._log_click(kind, code, now)

    def click_series(self, days: int = 14, kind: str | None = None) -> list:
        """近 N 天逐日访问数（本地时区分日），缺的日子补零——前端画折线不用再算。"""
        days = max(1, min(int(days), CLICK_MAX_DAYS))
        since = self._window_since(days)
        where, params = "ts >= ?", [since]
        if kind is not None:
            if kind not in CLICK_KINDS:
                raise ValueError(f"未知流水类型 {kind!r}，只接受 {CLICK_KINDS}")
            where += " AND kind = ?"
            params.append(kind)
        with self._lock:
            rows = self.db.execute(
                f"SELECT date(ts, 'unixepoch', 'localtime') AS d, COUNT(*) "
                f"FROM clicks WHERE {where} GROUP BY d", params).fetchall()
        by_date = {r["d"]: r[1] for r in rows}
        # 分日锚点取"今天 00:00 往回推"——与 SQL 的 localtime 分日同一套时区口径
        import datetime as _dt
        today = _dt.date.today()
        out = []
        for i in range(days - 1, -1, -1):
            key = (today - _dt.timedelta(days=i)).isoformat()
            out.append({"date": key, "count": by_date.get(key, 0)})
        return out

    def click_top(self, days: int = 14, limit: int = 8, kind: str | None = None) -> list:
        """近 N 天访问最多的对象排行（kind+code 维度，暂存/文件与短链同台）。"""
        days = max(1, min(int(days), CLICK_MAX_DAYS))
        limit = max(1, min(int(limit), MAX_LIST))
        since = self._window_since(days)
        where, params = "ts >= ?", [since]
        if kind is not None:
            if kind not in CLICK_KINDS:
                raise ValueError(f"未知流水类型 {kind!r}，只接受 {CLICK_KINDS}")
            where += " AND kind = ?"
            params.append(kind)
        with self._lock:
            rows = self.db.execute(
                f"SELECT kind, code, COUNT(*) AS n FROM clicks WHERE {where} "
                f"GROUP BY kind, code ORDER BY n DESC, code ASC LIMIT ?",
                params + [limit]).fetchall()
        return [{"kind": r["kind"], "code": r["code"], "count": r["n"]} for r in rows]

    def clicks_total(self, days: int = 14, kind: str | None = None) -> int:
        """近 N 天访问总数（流水口径；与 links.hits 累计口径不同，别混用）。"""
        days = max(1, min(int(days), CLICK_MAX_DAYS))
        since = self._window_since(days)
        where, params = "ts >= ?", [since]
        if kind is not None:
            if kind not in CLICK_KINDS:
                raise ValueError(f"未知流水类型 {kind!r}，只接受 {CLICK_KINDS}")
            where += " AND kind = ?"
            params.append(kind)
        with self._lock:
            row = self.db.execute(f"SELECT COUNT(*) FROM clicks WHERE {where}", params).fetchone()
        return row[0]

    # ------------------------------------------------------------------ 读取

    def lookup(self, code: str) -> Link | None:
        with self._lock:
            row = self.db.execute(
                "SELECT code, target, created_at, hits, last_visit FROM links WHERE code = ?",
                (code,)).fetchone()
        return None if row is None else Link(*tuple(row))

    def delete(self, code: str) -> bool:
        """删除一条短链（LinkBox L3 管理能力新增，B31 原有只读账面不变）。
        返回是否真删了——不存在的码返回 False，由路由层翻译成 404。"""
        with self._lock:
            cur = self.db.execute("DELETE FROM links WHERE code = ?", (code,))
        return cur.rowcount > 0

    def recent(self, limit: int = 20) -> list:
        limit = max(1, min(int(limit), MAX_LIST))
        with self._lock:
            rows = self.db.execute(
                "SELECT code, target, created_at, hits, last_visit FROM links "
                "ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return [Link(*tuple(r)) for r in rows]

    def top(self, limit: int = 5) -> list:
        limit = max(1, min(int(limit), MAX_LIST))
        with self._lock:
            rows = self.db.execute(
                "SELECT code, target, created_at, hits, last_visit FROM links "
                "ORDER BY hits DESC, created_at ASC LIMIT ?", (limit,)).fetchall()
        return [Link(*tuple(r)) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            row = self.db.execute(
                "SELECT COUNT(*) AS links, COALESCE(SUM(hits), 0) AS hits, "
                "COALESCE(MAX(hits), 0) AS best FROM links").fetchone()
        return {"links": row["links"], "total_hits": row["hits"], "best_hits": row["best"],
                "limit": MAX_LINKS}
