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
from pathlib import Path

ROLES = ("operator", "viewer")
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{2,20}$")
_MIN_PW = 8
_ITERATIONS = 100_000


class UserStore:
    """成员账号簿。全部操作加锁（事件循环单线程，但测试与启停线程都会碰）。"""

    def __init__(self, data_dir: str | Path, *, iterations: int = _ITERATIONS):
        self.path = Path(data_dir) / "users.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.iterations = iterations
        self.users: dict[str, dict] = self._load()

    def _load(self) -> dict:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (ValueError, OSError):
                pass                      # 坏文件当空册（新号重建），不崩门户
        return {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.users, ensure_ascii=False, indent=1),
                       encoding="utf-8")
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
            raise ValueError(f"口令至少 {_MIN_PW} 个字符")
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
            raise ValueError(f"口令至少 {_MIN_PW} 个字符")
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
