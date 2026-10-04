"""练习任务闭环（F6/F10/F11）。

两类任务、一套记录：
- 内置任务：内容源 = g2 卡片（pid 的 tasks 列表），key = "pid#编号"，**不落库**；
- 教师任务：教师布置，存 tasks 表，key = "T<id>"；
- 记录：task_records（(task_key, user_id) 主键，status=doing/done，note 可选）。
"""
from __future__ import annotations

import re

from app import courses
from app.db import now_str

_TKEY = re.compile(r"^(.+)#(\d+)$")
_CKEY = re.compile(r"^T(\d+)$")


class TaskError(Exception):
    def __init__(self, code: str, message: str, http: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


def builtin_keys(cid: str) -> list:
    card = courses.catalog()["cards"].get(cid, {})
    return [f"{cid}#{i}" for i in range(len(card.get("tasks", [])))]


def _card_task(cid: str, idx: int):
    card = courses.catalog()["cards"].get(cid, {})
    tasks = card.get("tasks", [])
    if 0 <= idx < len(tasks):
        return tasks[idx]
    return None


def _custom_row(db, task_id: int):
    return db.one("SELECT * FROM tasks WHERE id = ?", (task_id,))


def _validate_key(db, course: str, key: str):
    """返回 (title, due_at)；非法抛 TaskError。"""
    m = _TKEY.match(key)
    if m and m.group(1) == course:
        task = _card_task(course, int(m.group(2)))
        if task is None:
            raise TaskError("BAD_KEY", "内置任务编号越界")
        return task.get("raw", ""), None
    m2 = _CKEY.match(key)
    if m2:
        row = _custom_row(db, int(m2.group(1)))
        if row is None or row["course"] != course:
            raise TaskError("NO_TASK", "任务不存在或不属于该课程")
        return row["title"], row["due_at"]
    raise TaskError("BAD_KEY", "任务编号不合法")


def _record(db, user_id: int, key: str):
    return db.one("SELECT * FROM task_records WHERE task_key=? AND user_id=?", (key, user_id))


def claim(db, user_id: int, course: str, key: str) -> dict:
    _validate_key(db, course, key)
    cur = _record(db, user_id, key)
    if cur and cur["status"] == "done":
        raise TaskError("ALREADY_DONE", "这条已完成，不能再领取", 409)
    if cur and cur["status"] == "doing":
        return dict(cur)
    db.execute(
        "INSERT INTO task_records(task_key, user_id, course, status, note, updated_at)"
        " VALUES(?,?,?,?,?,?) ON CONFLICT(task_key, user_id)"
        " DO UPDATE SET status='doing', updated_at=excluded.updated_at",
        (key, user_id, course, "doing", "", now_str()))
    return dict(_record(db, user_id, key))


def complete(db, user_id: int, course: str, key: str, note: str = "") -> dict:
    _validate_key(db, course, key)
    db.execute(
        "INSERT INTO task_records(task_key, user_id, course, status, note, updated_at)"
        " VALUES(?,?,?,?,?,?) ON CONFLICT(task_key, user_id)"
        " DO UPDATE SET status='done', note=excluded.note, updated_at=excluded.updated_at",
        (key, user_id, course, "done", (note or "")[:200], now_str()))
    return dict(_record(db, user_id, key))


def _title_for(db, key: str) -> str:
    m2 = _CKEY.match(key)
    if m2:
        row = _custom_row(db, int(m2.group(1)))
        return row["title"] if row else "（任务已删除）"
    m = _TKEY.match(key)
    if m:
        task = _card_task(m.group(1), int(m.group(2)))
        return (task.get("raw", "") if task else "（任务不存在）")
    return key


def my_records(db, user_id: int) -> list:
    rows = db.all(
        "SELECT task_key, course, status, note, updated_at FROM task_records"
        " WHERE user_id=? ORDER BY updated_at DESC LIMIT 200", (user_id,))
    out = []
    for r in rows:
        out.append({
            "key": r["task_key"], "course": r["course"], "status": r["status"],
            "note": r["note"], "updated_at": r["updated_at"],
            "title": _title_for(db, r["task_key"]),
        })
    return out


def course_taskboard(db, user, cid: str) -> dict:
    """课程页任务板：内置 + 自定义 + 我的状态 + 人数统计 + 进度。"""
    user_id = user["id"] if user else None
    counts = {r["task_key"]: r["c"] for r in db.all(
        "SELECT task_key, COUNT(*) AS c FROM task_records WHERE course=? AND status='done'"
        " GROUP BY task_key", (cid,))}
    mine = {}
    if user_id:
        mine = {r["task_key"]: r["status"] for r in db.all(
            "SELECT task_key, status FROM task_records WHERE course=? AND user_id=?", (cid, user_id))}

    card = courses.catalog()["cards"].get(cid, {})
    items = []
    for i, t in enumerate(card.get("tasks", [])):
        key = f"{cid}#{i}"
        items.append({"key": key, "text": (t.get("raw") or "").strip().replace("**", ""),
                      "from": t.get("from", ""), "my": mine.get(key),
                      "done_count": counts.get(key, 0)})
    custom = []
    for row in db.all("SELECT * FROM tasks WHERE course=? ORDER BY id", (cid,)):
        key = f"T{row['id']}"
        custom.append({"key": key, "title": row["title"], "body": row["body"],
                       "due_at": row["due_at"], "my": mine.get(key),
                       "done_count": counts.get(key, 0)})
    total = len(items) + len(custom)
    done = sum(1 for x in items + custom if x["my"] == "done")
    return {"items": items, "custom": custom,
            "progress": {"total": total, "done": done}}


# ------------------------------------------------------------------ 教师侧（F10/F11）

def teacher_course_stats(db, cid: str) -> dict:
    if courses.course_detail(cid) is None:
        raise TaskError("NO_COURSE", "课程不存在", 404)
    counts = {r["task_key"]: r for r in db.all(
        "SELECT task_key, SUM(status='done') AS done, SUM(status='doing') AS doing"
        " FROM task_records WHERE course=? GROUP BY task_key", (cid,))}
    builtin_stats = []
    card = courses.catalog()["cards"].get(cid, {})
    for i, t in enumerate(card.get("tasks", [])):
        key = f"{cid}#{i}"
        c = counts.get(key)
        builtin_stats.append({"key": key, "title": (t.get("raw") or "").strip().replace("**", ""),
                              "doing": int(c["doing"]) if c else 0,
                              "done": int(c["done"]) if c else 0})
    custom = []
    for row in db.all("SELECT * FROM tasks WHERE course=? ORDER BY id", (cid,)):
        key = f"T{row['id']}"
        c = counts.get(key)
        custom.append({"id": row["id"], "title": row["title"], "body": row["body"],
                       "due_at": row["due_at"],
                       "doing": int(c["doing"]) if c else 0,
                       "done": int(c["done"]) if c else 0})
    students = db.one("SELECT COUNT(DISTINCT user_id) AS n FROM task_records WHERE course=?",
                      (cid,))["n"]
    records = db.one("SELECT COUNT(*) AS n FROM task_records WHERE course=?", (cid,))["n"]
    recent = []
    for r in db.all(
            "SELECT r.task_key, r.status, r.updated_at, u.username, u.display_name"
            " FROM task_records r JOIN users u ON u.id = r.user_id"
            " WHERE r.course=? ORDER BY r.updated_at DESC LIMIT 20", (cid,)):
        recent.append({"who": r["display_name"] or r["username"], "status": r["status"],
                       "updated_at": r["updated_at"], "title": _title_for(db, r["task_key"])})
    totals = {"done": sum(x["done"] for x in builtin_stats + custom),
              "doing": sum(x["doing"] for x in builtin_stats + custom),
              "students": int(students), "records": int(records)}
    return {"ok": True, "course": cid, "totals": totals, "builtin_stats": builtin_stats,
            "custom": custom, "recent": recent}


def teacher_create(db, user_id: int, course: str, title: str, body: str, due_at: str) -> dict:
    if courses.course_detail(course) is None:
        raise TaskError("NO_COURSE", "课程不存在", 404)
    title = (title or "").strip()
    if not (1 <= len(title) <= 100):
        raise TaskError("BAD_TITLE", "标题需为 1-100 个字符")
    due_at = (due_at or "").strip()
    if due_at and not re.match(r"^\d{4}-\d{2}-\d{2}$", due_at):
        raise TaskError("BAD_DUE", "截止日期格式应为 YYYY-MM-DD")
    cur = db.execute(
        "INSERT INTO tasks(course, title, body, due_at, created_by, created_at) VALUES(?,?,?,?,?,?)",
        (course, title, (body or "").strip()[:500], due_at or None, user_id, now_str()))
    return dict(_custom_row(db, cur.lastrowid))


def teacher_delete(db, task_id: int) -> None:
    row = _custom_row(db, task_id)
    if row is None:
        raise TaskError("NO_TASK", "任务不存在", 404)
    db.execute("DELETE FROM task_records WHERE task_key=?", (f"T{task_id}",))
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
