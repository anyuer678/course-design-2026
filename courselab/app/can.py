"""权限判定（唯一源）。

角色矩阵来自 docs/PLAN.md §三；页面与接口只读这里的判定结果，不复制规则。
target 预留给"教师只能管自己的课"这类对象级判定（M5 接课程绑定后才需要）。
"""
from __future__ import annotations

_MATRIX = {
    "view": {"guest", "student", "teacher", "admin"},
    "lab_run": {"student", "teacher", "admin"},
    "task_claim": {"student", "teacher", "admin"},
    "manage_course": {"teacher", "admin"},
    "admin": {"admin"},
}


def role_of(user) -> str:
    role = (user or {}).get("role", "guest") if user else "guest"
    return role if role in ("guest", "student", "teacher", "admin") else "student"


def can(user, action: str, target=None) -> bool:
    return role_of(user) in _MATRIX.get(action, set())
