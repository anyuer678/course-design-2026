"""通知与公告（F8）：管理员发平台公告、教师发本课通知；未读计数供导航角标。

可见性规则（写死，文档同步）：
- audience='all'：所有登录用户可见；
- audience=课程 id：管理员可见；该课绑定教师可见；**在该课有记录**的用户（做过任务或跑过实验）可见。
"""
from __future__ import annotations

from app.db import now_str


class NoticeError(Exception):
    def __init__(self, code: str, message: str, http: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


def _visible_rows(db, user) -> list:
    rows = db.all(
        "SELECT n.*, u.display_name, u.username FROM notices n JOIN users u ON u.id = n.created_by"
        " ORDER BY n.id DESC LIMIT 200")

    def visible(n) -> bool:
        if n["audience"] == "all":
            return True
        if user["role"] == "admin":
            return True
        if user["role"] == "teacher":
            m = db.one("SELECT teacher_id FROM course_meta WHERE course = ?", (n["audience"],))
            if m and m["teacher_id"] == user["id"]:
                return True
        hit = db.one("SELECT 1 FROM task_records WHERE user_id = ? AND course = ? LIMIT 1",
                     (user["id"], n["audience"]))
        if hit:
            return True
        return bool(db.one("SELECT 1 FROM lab_runs WHERE user_id = ? AND pid = ? LIMIT 1",
                           (user["id"], n["audience"])))

    return [r for r in rows if visible(r)]


def list_for(db, user) -> list:
    rows = _visible_rows(db, user)
    read = {r["notice_id"] for r in db.all(
        "SELECT notice_id FROM notice_reads WHERE user_id = ?", (user["id"],))}
    return [{
        "id": r["id"], "title": r["title"], "body": r["body"], "audience": r["audience"],
        "created_at": r["created_at"], "by": r["display_name"] or r["username"],
        "read": r["id"] in read,
    } for r in rows]


def unread_count(db, user) -> int:
    if user is None:
        return 0
    rows = _visible_rows(db, user)
    if not rows:
        return 0
    read = {r["notice_id"] for r in db.all(
        "SELECT notice_id FROM notice_reads WHERE user_id = ?", (user["id"],))}
    return sum(1 for r in rows if r["id"] not in read)


def mark_read(db, user, notice_id: int) -> None:
    visible_ids = {r["id"] for r in _visible_rows(db, user)}
    if notice_id not in visible_ids:
        raise NoticeError("NO_NOTICE", "公告不存在或不可见", 404)
    db.execute(
        "INSERT INTO notice_reads(notice_id, user_id, read_at) VALUES(?,?,?)"
        " ON CONFLICT(notice_id, user_id) DO NOTHING",
        (notice_id, user["id"], now_str()))


def mark_all_read(db, user) -> int:
    ids = [r["id"] for r in _visible_rows(db, user)]
    for nid in ids:
        db.execute(
            "INSERT INTO notice_reads(notice_id, user_id, read_at) VALUES(?,?,?)"
            " ON CONFLICT(notice_id, user_id) DO NOTHING",
            (nid, user["id"], now_str()))
    return len(ids)


def publish(db, user_id: int, title: str, body: str, audience: str) -> dict:
    title = (title or "").strip()
    if not (1 <= len(title) <= 100):
        raise NoticeError("BAD_TITLE", "标题需为 1-100 个字符")
    audience = (audience or "all").strip() or "all"
    cur = db.execute(
        "INSERT INTO notices(title, body, audience, created_by, created_at) VALUES(?,?,?,?,?)",
        (title, (body or "").strip()[:2000], audience, user_id, now_str()))
    return dict(db.one("SELECT * FROM notices WHERE id = ?", (cur.lastrowid,)))
