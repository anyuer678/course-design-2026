"""管理端（F12-F15）：用户治理 / 课程治理（发布·排序·教师绑定）/ 实验审计 / 看板聚合。

课程治理是"平台态覆盖层"：仓库现算的内容不动，course_meta 只记发布/排序/绑定教师，
以及教师维护的补充简介/大纲（F9；与仓库内容并列展示、标明来源，不覆盖现算层）。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from app import courses
from app.db import now_str

ROLES = ("student", "teacher", "admin")
STATUSES = ("active", "banned")
SUMMARY_MAX = 120
OUTLINE_MAX = 2000
_UNSET = object()


class AdminError(Exception):
    def __init__(self, code: str, message: str, http: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


# ------------------------------------------------------------------ 课程治理

def _meta_rows(db) -> dict:
    return {r["course"]: r for r in db.all("SELECT * FROM course_meta")}


def public_course_list(db) -> dict:
    """门户课程目录：未发布的隐藏；按 sort 升序（稳定：同 sort 保持仓库原序）。"""
    cat = courses.course_list()
    meta = _meta_rows(db)
    items = []
    for c in cat["courses"]:
        m = meta.get(c["id"])
        if m and not m["published"]:
            continue
        items.append({**c, "_sort": m["sort"] if m else 0})
    items.sort(key=lambda x: x["_sort"])
    for x in items:
        x.pop("_sort", None)
    return {"ok": True, "count": len(items), "cards": cat["cards"], "courses": items}


def course_visible(db, cid: str) -> bool:
    m = _meta_rows(db).get(cid)
    return not (m and not m["published"])


def course_rows(db) -> list:
    """管理端课程表：全部课程 + 治理状态。"""
    cat = courses.catalog()
    meta = _meta_rows(db)
    teachers = {r["id"]: (r["display_name"] or r["username"]) for r in db.all(
        "SELECT id, username, display_name FROM users WHERE role IN ('teacher','admin')")}
    out = []
    for p in cat["projects"]:
        m = meta.get(p["id"])
        tid = m["teacher_id"] if m else None
        out.append({"id": p["id"], "course": p["course"],
                    "published": bool(m["published"]) if m else True,
                    "sort": m["sort"] if m else 0,
                    "teacher_id": tid, "teacher": teachers.get(tid)})
    return out


def set_course_meta(db, cid: str, actor_id: int = 0, published=None, sort=None,
                    teacher_id=_UNSET, summary=None, outline=None) -> dict:
    if courses.course_detail(cid) is None:
        raise AdminError("NO_COURSE", "课程不存在", 404)
    # 类型校验（判定唯一源）：畸形输入一律 4xx，不把异常打穿到请求线程
    if published is not None and not isinstance(published, bool):
        raise AdminError("BAD_PUBLISHED", "published 必须是 true/false")
    if summary is not None and not isinstance(summary, str):
        raise AdminError("BAD_SUMMARY", "补充简介必须是文本")
    if outline is not None and not isinstance(outline, str):
        raise AdminError("BAD_OUTLINE", "大纲必须是文本")
    row = _meta_rows(db).get(cid)
    pub = (row["published"] if row else 1) if published is None else (1 if published else 0)
    srt = (row["sort"] if row else 0) if sort is None else int(sort)
    if teacher_id is _UNSET:
        tid = row["teacher_id"] if row else None
    elif teacher_id in (None, "", 0):
        tid = None
    else:
        try:
            tid = int(teacher_id)
        except (TypeError, ValueError):
            raise AdminError("BAD_TEACHER_ID", "绑定教师编号必须是整数")
    summ = ((row["summary"] if row else "") or "") if summary is None else summary.strip()
    outl = ((row["outline"] if row else "") or "") if outline is None else outline.strip()
    if len(summ) > SUMMARY_MAX:
        raise AdminError("BAD_SUMMARY", f"补充简介最长 {SUMMARY_MAX} 字")
    if len(outl) > OUTLINE_MAX:
        raise AdminError("BAD_OUTLINE", f"大纲最长 {OUTLINE_MAX} 字")
    if tid is not None:
        t = db.one("SELECT role FROM users WHERE id = ?", (tid,))
        if t is None or t["role"] not in ("teacher", "admin"):
            raise AdminError("BAD_TEACHER", "绑定对象必须是教师或管理员")
    db.execute(
        "INSERT INTO course_meta(course, published, sort, teacher_id, summary, outline)"
        " VALUES(?,?,?,?,?,?)"
        " ON CONFLICT(course) DO UPDATE SET published=excluded.published,"
        " sort=excluded.sort, teacher_id=excluded.teacher_id,"
        " summary=excluded.summary, outline=excluded.outline",
        (cid, pub, srt, tid, summ, outl))
    audit(db, actor_id, "course_meta", cid,
          f"published={int(pub)} sort={srt} teacher_id={tid}"
          f" summary={len(summ)}字 outline={len(outl)}字")
    return {"course": cid, "published": bool(pub), "sort": srt, "teacher_id": tid,
            "summary": summ, "outline": outl}


def course_meta_public(db, cid: str) -> dict:
    """课程详情附带的平台态：发布状态 + 教师维护的补充简介/大纲（注明来源教师名）。"""
    m = _meta_rows(db).get(cid)
    teacher = None
    if m and m["teacher_id"]:
        t = db.one("SELECT username, display_name FROM users WHERE id = ?", (m["teacher_id"],))
        if t:
            teacher = t["display_name"] or t["username"]
    return {"published": bool(m["published"]) if m else True,
            "summary": ((m["summary"] if m else "") or ""),
            "outline": ((m["outline"] if m else "") or ""),
            "teacher": teacher}


def teacher_can_manage(db, user, cid: str) -> bool:
    if user is None:
        return False
    if user["role"] == "admin":
        return True
    if user["role"] != "teacher":
        return False
    m = _meta_rows(db).get(cid)
    return bool(m and m["teacher_id"] == user["id"])


def teacher_courses(db, user) -> list:
    """教师台可选课程：管理员=全部；教师=绑定给自己的。"""
    cat = courses.catalog()
    meta = _meta_rows(db)
    out = []
    for p in cat["projects"]:
        m = meta.get(p["id"])
        if user["role"] == "admin" or (m and m["teacher_id"] == user["id"]):
            out.append({"id": p["id"], "course": p["course"]})
    return out


# ------------------------------------------------------------------ 用户治理

def users_list(db) -> list:
    rows = db.all(
        "SELECT id, username, display_name, role, status, created_at, last_login"
        " FROM users ORDER BY id LIMIT 500")
    return [dict(r) for r in rows]


def _target_user(db, target_id: int):
    row = db.one("SELECT * FROM users WHERE id = ?", (target_id,))
    if row is None:
        raise AdminError("NO_USER", "用户不存在", 404)
    return row


def _public(row) -> dict:
    return {k: row[k] for k in
            ("id", "username", "display_name", "role", "status", "created_at", "last_login")}


def audit(db, actor_id: int, action: str, target: str = "", detail: str = "") -> None:
    db.execute("INSERT INTO admin_audit(ts, actor_id, action, target, detail) VALUES(?,?,?,?,?)",
               (now_str(), actor_id, action, target, detail[:300]))


def audit_list(db, limit: int = 100) -> list:
    rows = db.all(
        "SELECT a.ts, a.action, a.target, a.detail, u.username, u.display_name"
        " FROM admin_audit a JOIN users u ON u.id = a.actor_id"
        " ORDER BY a.id DESC LIMIT ?", (limit,))
    return [{"ts": r["ts"], "who": r["display_name"] or r["username"],
             "action": r["action"], "target": r["target"], "detail": r["detail"]}
            for r in rows]


def set_user_role(db, actor_id: int, target_id: int, role: str) -> dict:
    if role not in ROLES:
        raise AdminError("BAD_ROLE", "角色只能是 student / teacher / admin")
    if target_id == actor_id:
        raise AdminError("SELF", "不能改自己的角色（防止把自己锁在门外）")
    target = _target_user(db, target_id)
    db.execute("UPDATE users SET role = ? WHERE id = ?", (role, target_id))
    audit(db, actor_id, "user_role", target["username"], f"{target['role']} -> {role}")
    return _public(_target_user(db, target_id))


def set_user_status(db, actor_id: int, target_id: int, status: str) -> dict:
    if status not in STATUSES:
        raise AdminError("BAD_STATUS", "状态只能是 active / banned")
    if target_id == actor_id:
        raise AdminError("SELF", "不能封禁自己")
    target = _target_user(db, target_id)
    db.execute("UPDATE users SET status = ? WHERE id = ?", (status, target_id))
    if status == "banned":
        db.execute("DELETE FROM sessions WHERE user_id = ?", (target_id,))   # 封禁即下线
    audit(db, actor_id, "user_status", target["username"], f"{target['status']} -> {status}")
    return _public(_target_user(db, target_id))


# ------------------------------------------------------------------ 审计与看板

def labs_audit(db, limit: int = 50) -> list:
    rows = db.all(
        "SELECT r.id, r.pid, r.action, r.kind, r.started_at, r.finished_at,"
        " r.exit_code, u.username, u.display_name"
        " FROM lab_runs r JOIN users u ON u.id = r.user_id"
        " ORDER BY r.started_at DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        out.append({**{k: r[k] for k in r.keys()},
                    "who": r["display_name"] or r["username"]})
        out[-1].pop("username", None)
    return out


def overview(db) -> dict:
    today = time.strftime("%Y-%m-%d")
    users = db.one("SELECT COUNT(*) AS n FROM users")["n"]
    teachers = db.one("SELECT COUNT(*) AS n FROM users WHERE role='teacher'")["n"]
    labs_total = db.one("SELECT COUNT(*) AS n FROM lab_runs")["n"]
    labs_today = db.one("SELECT COUNT(*) AS n FROM lab_runs WHERE substr(started_at,1,10)=?",
                        (today,))["n"]
    tasks_done = db.one("SELECT COUNT(*) AS n FROM task_records WHERE status='done'")["n"]
    tasks_doing = db.one("SELECT COUNT(*) AS n FROM task_records WHERE status='doing'")["n"]
    # 最近 7 天实验数
    days = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    by_day = {r["d"]: r["n"] for r in db.all(
        "SELECT substr(started_at,1,10) AS d, COUNT(*) AS n FROM lab_runs GROUP BY d")}
    daily_labs = [{"date": d, "label": d[5:], "n": by_day.get(d, 0)} for d in days]
    active_users = db.one(
        "SELECT COUNT(DISTINCT user_id) AS n FROM ("
        " SELECT user_id FROM lab_runs WHERE substr(started_at,1,10)>=?"
        " UNION SELECT user_id FROM task_records WHERE substr(updated_at,1,10)>=?)",
        (days[0], days[0]))["n"]
    day7 = db.one("SELECT COUNT(*) AS n FROM lab_runs WHERE substr(started_at,1,10)>=?",
                  (days[0],))["n"]
    vt = db.one("SELECT n FROM visits WHERE day=?", (today,))
    visits_today = int(vt["n"]) if vt else 0
    visits_7d = int(db.one("SELECT COALESCE(SUM(n),0) AS n FROM visits WHERE day>=?",
                           (days[0],))["n"])
    return {"ok": True, "users": int(users), "teachers": int(teachers),
            "labs_total": int(labs_total), "labs_today": int(labs_today),
            "labs_7d": int(day7),
            "visits_today": visits_today, "visits_7d": visits_7d,
            "tasks_done": int(tasks_done), "tasks_doing": int(tasks_doing),
            "active_users_7d": int(active_users), "daily_labs": daily_labs}
