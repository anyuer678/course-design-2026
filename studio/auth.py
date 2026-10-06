"""studio/auth.py —— 门户登录：密钥与会话口令的落盘管理。

口径（单用户自托管产品，用户就是机主本人）：
    - 用户名固定 "owner"；
    - 初始口令首次启动自动生成（secrets.token_urlsafe），写入 data/password.txt，
      文件里同时写一行说明指向本文件——机主看 README/控制台都能找到；
    - 会话签名密钥 data/secret.key 落盘：门户重启不会把人踢下线；
    - data/ 整个目录进 .gitignore（口令与密钥不进仓库，PLAN §6 的红线）。
"""
from __future__ import annotations

import hmac
import secrets
from pathlib import Path

USERNAME = "owner"
_MIN_LEN = 8

_PASSWORD_NOTE = (
    "# Studio 门户登录口令（自动生成，可改）。用户名固定为 owner。\n"
    "# 改口令：门户页面右上角，或 POST /api/password。\n"
    "# 本目录（studio/data/）已进 .gitignore，不要提交。\n")


class Auth:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.secret = self._load_secret()
        self.generation = self._load_generation()
        self.password = self._load_password()

    # ------------------------------------------------ 密钥（会话签名）
    def _load_secret(self) -> bytes:
        path = self.dir / "secret.key"
        if path.is_file():
            data = path.read_text(encoding="ascii").strip()
            if len(data) >= 64:
                return bytes.fromhex(data)
        secret = secrets.token_bytes(32)
        path.write_text(secret.hex() + "\n", encoding="ascii")
        return secret

    # ------------------------------------------------ 世代（改口令 → 旧会话全失效）
    def _load_generation(self) -> int:
        path = self.dir / "generation.txt"
        if path.is_file():
            try:
                return int(path.read_text(encoding="ascii").strip())
            except ValueError:
                pass
        return 1

    def bump_generation(self) -> int:
        """口令变更后调用：旧世代会话（gen 不匹配）全部失效。"""
        self.generation += 1
        (self.dir / "generation.txt").write_text(f"{self.generation}\n",
                                                 encoding="ascii")
        return self.generation

    # ------------------------------------------------ 口令
    def _load_password(self) -> str:
        path = self.dir / "password.txt"
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
        password = secrets.token_urlsafe(9)          # ~12 字符，72 bit 熵
        path.write_text(_PASSWORD_NOTE + password + "\n", encoding="utf-8")
        return password

    def verify(self, password: str) -> bool:
        if not isinstance(password, str) or not password:
            return False
        return hmac.compare_digest(password.encode("utf-8"),
                                   self.password.encode("utf-8"))

    def set_password(self, new: str) -> None:
        if not isinstance(new, str) or len(new) < _MIN_LEN:
            raise ValueError(f"新口令至少 {_MIN_LEN} 个字符")
        self.password = new
        (self.dir / "password.txt").write_text(
            _PASSWORD_NOTE + new + "\n", encoding="utf-8")
