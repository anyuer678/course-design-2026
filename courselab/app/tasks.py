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

# 完成口径：直接完成、已提交待批、已批阅，都算"做完了"
DONE_STATES = ("done", "submitted", "graded")
SUBMISSION_MAX = 2000
FEEDBACK_MAX = 500


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
    if cur and cur["status"] in DONE_STATES:
        raise TaskError("ALREADY_DONE", "这条已有完成/提交记录，不能再领取", 409)
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
    cur = _record(db, user_id, key)
    if cur and cur["status"] in ("submitted", "graded"):
        raise TaskError("ALREADY_SUBMITTED", "这条已提交或已批阅，不能再标记完成", 409)
    db.execute(
        "INSERT INTO task_records(task_key, user_id, course, status, note, updated_at)"
        " VALUES(?,?,?,?,?,?) ON CONFLICT(task_key, user_id)"
        " DO UPDATE SET status='done', note=excluded.note, updated_at=excluded.updated_at",
        (key, user_id, course, "done", (note or "")[:200], now_str()))
    return dict(_record(db, user_id, key))


def submit(db, user_id: int, course: str, key: str, text: str) -> dict:
    """学生提交作业（可覆盖重交；重交会清空原分数、回到待批阅）。"""
    _validate_key(db, course, key)
    text = (text or "").strip()
    if not (1 <= len(text) <= SUBMISSION_MAX):
        raise TaskError("BAD_SUBMISSION", f"作业内容需为 1-{SUBMISSION_MAX} 字")
    ts = now_str()
    db.execute(
        "INSERT INTO task_records(task_key, user_id, course, status, note, submission,"
        " submitted_at, updated_at)"
        " VALUES(?,?,?,'submitted','',?,?,?) ON CONFLICT(task_key, user_id) DO UPDATE SET"
        " status='submitted', submission=excluded.submission, submitted_at=excluded.submitted_at,"
        " grade=NULL, feedback='', graded_at=NULL, updated_at=excluded.updated_at",
        (key, user_id, course, text, ts, ts))
    return dict(_record(db, user_id, key))


def grade(db, course: str, key: str, student_id: int, score, feedback: str = "") -> dict:
    """教师批阅：对"待批阅"或"已批阅"的记录（重批可改分）；0-100 整数。"""
    _validate_key(db, course, key)
    if isinstance(score, bool) or not isinstance(score, int) or not (0 <= score <= 100):
        raise TaskError("BAD_GRADE", "分数需为 0-100 的整数")
    row = db.one("SELECT * FROM task_records WHERE task_key=? AND user_id=?", (key, student_id))
    if row is None:
        raise TaskError("NO_RECORD", "该学生没有这条任务的记录", 404)
    if row["status"] not in ("submitted", "graded"):
        raise TaskError("NOT_SUBMITTED", "这条记录还没有提交，无法批阅", 409)
    ts = now_str()
    db.execute(
        "UPDATE task_records SET status='graded', grade=?, feedback=?, graded_at=?, updated_at=?"
        " WHERE task_key=? AND user_id=?",
        (score, (feedback or "").strip()[:FEEDBACK_MAX], ts, ts, key, student_id))
    return dict(_record(db, student_id, key))


def submissions(db, course: str, key: str) -> list:
    """教师视角：某任务下所有"已提交/已批阅"的学生记录。"""
    _validate_key(db, course, key)
    rows = db.all(
        "SELECT r.user_id, r.status, r.submission, r.submitted_at, r.grade, r.feedback,"
        " r.graded_at, u.username, u.display_name FROM task_records r"
        " JOIN users u ON u.id = r.user_id"
        " WHERE r.task_key=? AND r.status IN ('submitted','graded')"
        " ORDER BY r.submitted_at, r.user_id", (key,))
    return [{"user_id": r["user_id"], "who": r["display_name"] or r["username"],
             "status": r["status"], "submission": r["submission"],
             "submitted_at": r["submitted_at"], "grade": r["grade"],
             "feedback": r["feedback"], "graded_at": r["graded_at"]} for r in rows]


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
        "SELECT task_key, course, status, note, submission, submitted_at, grade, feedback,"
        " graded_at, updated_at FROM task_records"
        " WHERE user_id=? ORDER BY updated_at DESC LIMIT 200", (user_id,))
    out = []
    for r in rows:
        out.append({
            "key": r["task_key"], "course": r["course"], "status": r["status"],
            "note": r["note"], "submission": r["submission"],
            "submitted_at": r["submitted_at"], "grade": r["grade"],
            "feedback": r["feedback"], "graded_at": r["graded_at"],
            "updated_at": r["updated_at"],
            "title": _title_for(db, r["task_key"]),
        })
    return out


def course_taskboard(db, user, cid: str) -> dict:
    """课程页任务板：内置 + 自定义 + 我的状态 + 人数统计 + 进度。"""
    user_id = user["id"] if user else None
    counts = {r["task_key"]: r["c"] for r in db.all(
        "SELECT task_key, COUNT(*) AS c FROM task_records WHERE course=?"
        " AND status IN ('done','submitted','graded') GROUP BY task_key", (cid,))}
    mine_rows = {}
    if user_id:
        mine_rows = {r["task_key"]: r for r in db.all(
            "SELECT task_key, status, submission, grade, feedback FROM task_records"
            " WHERE course=? AND user_id=?", (cid, user_id))}

    def mine_info(key):
        r = mine_rows.get(key)
        if r is None:
            return {}
        return {"my": r["status"], "submission": r["submission"],
                "grade": r["grade"], "feedback": r["feedback"]}

    card = courses.catalog()["cards"].get(cid, {})
    items = []
    for i, t in enumerate(card.get("tasks", [])):
        key = f"{cid}#{i}"
        items.append({"key": key, "text": (t.get("raw") or "").strip().replace("**", ""),
                      "from": t.get("from", ""), "done_count": counts.get(key, 0),
                      **mine_info(key)})
    custom = []
    for row in db.all("SELECT * FROM tasks WHERE course=? ORDER BY id", (cid,)):
        key = f"T{row['id']}"
        custom.append({"key": key, "title": row["title"], "body": row["body"],
                       "due_at": row["due_at"], "done_count": counts.get(key, 0),
                       **mine_info(key)})
    total = len(items) + len(custom)
    done = sum(1 for x in items + custom if x.get("my") in DONE_STATES)
    return {"items": items, "custom": custom,
            "progress": {"total": total, "done": done}}


# ------------------------------------------------------------------ 教师侧（F10/F11）

def teacher_course_stats(db, cid: str) -> dict:
    if courses.course_detail(cid) is None:
        raise TaskError("NO_COURSE", "课程不存在", 404)
    counts = {r["task_key"]: r for r in db.all(
        "SELECT task_key, SUM(status IN ('done','submitted','graded')) AS done,"
        " SUM(status='doing') AS doing, SUM(status='submitted') AS submitted,"
        " SUM(status='graded') AS graded, AVG(CASE WHEN grade IS NOT NULL THEN grade END) AS avg"
        " FROM task_records WHERE course=? GROUP BY task_key", (cid,))}

    def item_counts(key):
        c = counts.get(key)
        return {"doing": int(c["doing"]) if c else 0,
                "done": int(c["done"]) if c else 0,
                "submitted": int(c["submitted"]) if c else 0,
                "graded": int(c["graded"]) if c else 0}

    builtin_stats = []
    card = courses.catalog()["cards"].get(cid, {})
    for i, t in enumerate(card.get("tasks", [])):
        key = f"{cid}#{i}"
        builtin_stats.append({"key": key, "title": (t.get("raw") or "").strip().replace("**", ""),
                              **item_counts(key)})
    custom = []
    for row in db.all("SELECT * FROM tasks WHERE course=? ORDER BY id", (cid,)):
        key = f"T{row['id']}"
        custom.append({"id": row["id"], "title": row["title"], "body": row["body"],
                       "due_at": row["due_at"], **item_counts(key)})
    students = db.one("SELECT COUNT(DISTINCT user_id) AS n FROM task_records WHERE course=?",
                      (cid,))["n"]
    records = db.one("SELECT COUNT(*) AS n FROM task_records WHERE course=?", (cid,))["n"]
    lab_rank = [{"who": r["display_name"] or r["username"], "n": int(r["n"])}
                for r in db.all(
        "SELECT u.username, u.display_name, COUNT(*) AS n FROM lab_runs r"
        " JOIN users u ON u.id = r.user_id WHERE r.pid = ?"
        " GROUP BY r.user_id ORDER BY n DESC, u.id LIMIT 10", (cid,))]
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
            "custom": custom, "recent": recent, "lab_rank": lab_rank}


def export_grades(db, cid: str) -> list[dict]:
    """成绩册长表（C1）：课程下全部任务记录 JOIN 用户，教师导出 CSV 用。
    没交过的学生不在此表（长表只记发生过的动作）；课程不存在按 404 语义报。"""
    if courses.course_detail(cid) is None:
        raise TaskError("NO_COURSE", "课程不存在", 404)
    return db.all(
        "SELECT u.username, u.display_name, r.task_key, r.status, r.submitted_at,"
        " r.grade, r.feedback FROM task_records r"
        " JOIN users u ON u.id = r.user_id"
        " WHERE r.course = ? ORDER BY u.username, r.task_key", (cid,))


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
