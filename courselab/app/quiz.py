"""随堂测验（轮五十）：选择题题库 + 判分 + 尝试记录。

- 题库 courselab/data/quiz.json：按课程 cid 组织；题目贴合 g2/cards.json
  的知识点表（出题出处写在 explain 里）；
- quiz_for(cid)：给学生拉的版本——**剥掉 answer 与 explain**，答案不过网；
- grade(cid, answers)：判分并落 quiz_attempts（成绩分析图的数据源，下一轮）；
- 未登录也能拉题（游客可体验），但只有登录用户会记分。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # courselab/
QUIZ_FILE = ROOT / "data" / "quiz.json"

_cache: dict = {"key": None, "data": None}


def load_bank() -> dict:
    key = QUIZ_FILE.stat().st_mtime
    if _cache["data"] is None or _cache["key"] != key:
        raw = json.loads(QUIZ_FILE.read_text(encoding="utf-8"))
        bank = {cid: qs for cid, qs in raw.items() if not cid.startswith("_")}
        _cache.update(key=key, data=bank)
    return _cache["data"]


def quiz_for(cid: str) -> dict | None:
    """学生版题目：剥答案。返回 {cid, count, questions:[{id,q,options}]} 或 None。"""
    qs = load_bank().get(cid)
    if not qs:
        return None
    questions = [{"id": i, "q": qz["q"], "options": qz["options"]}
                 for i, qz in enumerate(qs)]
    return {"cid": cid, "count": len(questions), "questions": questions}


def grade(db, user_id: int | None, cid: str, answers) -> dict | None:
    """判分。answers: {题号(可字符串): 选项下标}。未登录 user_id=None 不落库。"""
    qs = load_bank().get(cid)
    if not qs:
        return None
    detail, score = [], 0
    for i, qz in enumerate(qs):
        given = answers.get(str(i), answers.get(i))
        try:
            given = int(given) if given is not None else None
        except (TypeError, ValueError):
            given = None
        ok = given == qz["answer"]
        score += 1 if ok else 0
        detail.append({"id": i, "given": given, "answer": qz["answer"],
                       "ok": ok, "explain": qz["explain"]})
    total = len(qs)
    if user_id is not None:
        db.execute(                      # DB.execute 自动 commit
            "INSERT INTO quiz_attempts (user_id, cid, score, total, detail, created) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (user_id, cid, score, total,
             json.dumps(detail, ensure_ascii=False)))
    return {"score": score, "total": total, "detail": detail}


def stats(db, user_id: int) -> dict:
    """成绩分析（轮五十一）：按课程聚合 + 时间线。成绩 ECharts 的数据源。"""
    rows = [dict(zip(("cid", "score", "total", "created"), row))
            for row in db.execute(
                "SELECT cid, score, total, created FROM quiz_attempts "
                "WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()]
    by_course: dict = {}
    timeline = []
    for r in rows:
        pct = round(r["score"] / r["total"] * 100) if r["total"] else 0
        agg = by_course.setdefault(r["cid"], {"count": 0, "best": 0, "last": 0})
        agg["count"] += 1
        agg["best"] = max(agg["best"], pct)
        agg["last"] = pct
        timeline.append({"cid": r["cid"], "pct": pct, "created": r["created"]})
    # 课程名映射（courses.catalog 现算自仓库）
    names = {}
    try:
        from app import courses
        for p in courses.catalog()["projects"]:
            names[p["id"]] = p["course"]
    except OSError:
        pass
    per_course = [{"cid": cid, "course": names.get(cid, cid), **agg}
                  for cid, agg in by_course.items()]
    per_course.sort(key=lambda x: -x["best"])
    return {"count": len(rows), "per_course": per_course, "timeline": timeline}


def my_attempts(db, user_id: int, cid: str | None = None, limit: int = 20) -> list[dict]:
    """我的测验记录（成绩分析图的数据源，下一轮）。"""
    sql = ("SELECT cid, score, total, created FROM quiz_attempts "
           "WHERE user_id = ?" + (" AND cid = ?" if cid else "") +
           " ORDER BY id DESC LIMIT ?")
    params = (user_id, cid, limit) if cid else (user_id, limit)
    return [dict(zip(("cid", "score", "total", "created"), row))
            for row in db.execute(sql, params).fetchall()]
