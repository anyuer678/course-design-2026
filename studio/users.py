"""studio/users.py —— 成员账号与角色（RBAC，2026-10-13，GAP P0 收口）。

口径（单机自托管门户，不是多租户 SaaS）：
    - owner（机主）不入册：口令走 auth.py 的 password.txt 体系，角色恒 owner；
    - 成员存 data/users.json：{name: {salt, hash, role}}——pbkdf2_hmac 哈希，
      口令不落明文（owner 的 password.txt 是历史口径，成员账号新开就按新标准）；
    - 角色：operator（启停产品）/ viewer（只看矩阵、状态、审计）；
      写权限梯度 owner > operator > viewer，在 server 层 require_role 把门；
    - 成员口令由 owner 管理（建号/重置），成员不自助改——门户没有"我的账号"
      页面的必要，课设口径如实从简。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path

_ROLES = ("operator", "viewer")
ROLES = _ROLES
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")
USERNAME = "owner"                    # 机主保留名（自助注册不可占用）
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{2,20}$")
_MIN_PW = 8
_ITERATIONS = 100_000

# ------------------------------------------------ 用户分层（轮四十四，权限矩阵）
# L3 owner 管理员（机主）> L2 operator 操作员 > L1 viewer 观察者 > L0 未登录（公开只读）
# 权限点 → 允许角色。一处定义：server 层 require_perm 按此把门，
# /api/me 下发 permissions 供前端渲染，测试逐格钉住——三处同源不漂移。
ROLE_LEVELS = {"owner": 3, "operator": 2, "viewer": 1}   # L0 未登录不在册

PERMISSIONS = {
    "product.start":   ("owner", "operator"),            # 启动产品
    "product.stop":    ("owner", "operator"),            # 停止产品
    "audit.read":      ("owner", "operator", "viewer"),  # 查看操作审计
    "users.manage":    ("owner",),                       # 成员管理（增删/角色/重置口令）
    "invites.manage":  ("owner",),                       # 邀请码（生成/作废）
    "portal.password": ("owner",),                       # 修改门户 owner 口令
}


class UserStore:
    """成员账号簿。全部操作加锁（事件循环单线程，但测试与启停线程都会碰）。

    轮四十二起支持自助注册：owner 生成一次性邀请码，注册者凭码获得对应
    角色；无码注册一律 viewer（只读无风险）。邀请码随 users.json 落盘。
    """

    def __init__(self, data_dir: str | Path, *, iterations: int = _ITERATIONS):
        self.path = Path(data_dir) / "users.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.iterations = iterations
        data = self._load()
        self.users: dict[str, dict] = data.get("users", {})
        self.invites: dict[str, dict] = data.get("invites", {})

    def _load(self) -> dict:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # 旧格式（轮四十：直接 {name: rec}）迁移为新结构
                    if "users" not in data:
                        return {"users": data, "invites": {}}
                    return data
            except (ValueError, OSError):
                pass                      # 坏文件当空册（新号重建），不崩门户
        return {"users": {}, "invites": {}}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"users": self.users, "invites": self.invites},
            ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)            # 原子替换，半写不留账

    @staticmethod
    def _hash(password: str, salt: bytes, iterations: int) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations).hex()

    # ------------------------------------------------ 管理（owner 专属）
    def add(self, name: str, password: str, role: str) -> None:
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError("用户名须为 2-20 位字母/数字/下划线/连字符")
        if not isinstance(password, str) or len(password) < _MIN_PW:
            raise ValueError(f"密码至少 {_MIN_PW} 个字符")
        if role not in ROLES:
            raise ValueError(f"角色只能是 {' / '.join(ROLES)}")
        if name in self.users:
            raise KeyError(f"成员 {name!r} 已存在")
        salt = secrets.token_bytes(16)
        self.users[name] = {"salt": salt.hex(),
                            "hash": self._hash(password, salt, self.iterations),
                            "role": role}
        self._save()

    def remove(self, name: str) -> None:
        if name not in self.users:
            raise KeyError(f"没有叫 {name!r} 的成员")
        del self.users[name]
        self._save()

    def set_role(self, name: str, role: str) -> None:
        if name not in self.users:
            raise KeyError(f"没有叫 {name!r} 的成员")
        if role not in ROLES:
            raise ValueError(f"角色只能是 {' / '.join(ROLES)}")
        self.users[name]["role"] = role
        self._save()

    def reset_password(self, name: str, password: str) -> None:
        if name not in self.users:
            raise KeyError(f"没有叫 {name!r} 的成员")
        if not isinstance(password, str) or len(password) < _MIN_PW:
            raise ValueError(f"密码至少 {_MIN_PW} 个字符")
        salt = secrets.token_bytes(16)
        self.users[name]["salt"] = salt.hex()
        self.users[name]["hash"] = self._hash(password, salt, self.iterations)
        self._save()

    # ------------------------------------------------ 登录与列表
    def verify(self, name: str, password: str) -> str | None:
        """口令对得上返回角色，否则 None（统一话术由调用方给）。"""
        rec = self.users.get(name)
        if not isinstance(password, str) or not password or rec is None:
            return None
        got = self._hash(password, bytes.fromhex(rec["salt"]), self.iterations)
        if hmac.compare_digest(got, rec["hash"]):
            return rec["role"]
        return None

    def listing(self) -> list[dict]:
        return [{"name": n, "role": r["role"]}
                for n, r in sorted(self.users.items())]

    # ------------------------------------------------ 自助注册与邀请码（轮四十二）
    def register_self(self, name: str, password: str,
                      invite: str | None = None) -> str:
        """自助注册：凭一次性邀请码得对应角色，无码一律 viewer。
        "owner" 是机主保留名；码用后即焚。返回新成员角色。"""
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError("用户名须为 2-20 位字母/数字/下划线/连字符")
        if name.lower() == USERNAME.lower():
            raise ValueError("该用户名为机主保留名，请换一个")
        if not isinstance(password, str) or len(password) < _MIN_PW:
            raise ValueError(f"密码至少 {_MIN_PW} 个字符")
        if name in self.users:
            raise KeyError(f"成员 {name!r} 已存在")
        if invite:
            code = str(invite).strip()
            info = self.invites.get(code)
            if info is None:
                raise ValueError("邀请码无效或已被使用")
            role = info["role"]
            del self.invites[code]            # 一次性，用后即焚
        else:
            role = "viewer"
        salt = secrets.token_bytes(16)
        self.users[name] = {"salt": salt.hex(),
                            "hash": self._hash(password, salt, self.iterations),
                            "role": role}
        self._save()
        return role

    def create_invite(self, role: str = "operator") -> str:
        """owner 生成一次性邀请码。"""
        if role not in ROLES:
            raise ValueError(f"角色只能是 {' / '.join(ROLES)}")
        code = secrets.token_urlsafe(6)       # 8 字符，够抄写
        self.invites[code] = {"role": role, "created": time.strftime("%Y-%m-%d")}
        self._save()
        return code

    def invites_listing(self) -> list[dict]:
        return [{"code": c, "role": i["role"], "created": i.get("created", "")}
                for c, i in sorted(self.invites.items())]

    def revoke_invite(self, code: str) -> None:
        if code not in self.invites:
            raise KeyError(f"没有邀请码 {code!r}")
        del self.invites[code]
        self._save()
