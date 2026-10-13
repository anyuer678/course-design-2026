"""studio/auth.py —— 门户登录：密钥与会话口令的落盘管理。

口径（轮四十二翻新：owner 口令哈希化，password.txt 降级为一次性信封）：
    - 用户名固定 "owner"；**口令 pbkdf2 哈希存 data/owner.json**（盐 16B、
      120k 迭代）——磁盘上不再有长期明文凭据；
    - 首次启动自动生成随机口令（secrets.token_urlsafe），明文只出现一次：
      写入 data/password.txt 作为"开机信封"，owner 在账户页改口令后该文件
      被改写为失效说明（全注释行，明文从磁盘消失）；
    - 会话签名密钥 data/secret.key 落盘：门户重启不会把人踢下线；
    - data/ 整个目录进 .gitignore（口令与密钥不进仓库，PLAN §6 的红线）；
    - owner 忘口令：删 data/owner.json 重启门户即重新生成信封（自托管单机
      的如实找回口径——机主有文件系统权限，任何"找回"都等价于这条路）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from pathlib import Path

USERNAME = "owner"
_MIN_LEN = 8
_PWD_ITER = 120_000

_PASSWORD_NOTE = (
    "# Studio 门户登录口令（自动生成，可改）。用户名固定为 owner。\n"
    "# 改口令：门户页面右上角，或 POST /api/password。\n"
    "# 本目录（studio/data/）已进 .gitignore，不要提交。\n")

_ENVELOPE_SPENT = (
    "# 口令已通过门户修改，本文件不再是凭据来源（明文已从磁盘消失）。\n"
    "# 忘记口令：删除 data/owner.json 后重启门户，会重新生成初始信封。\n")


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PWD_ITER).hex()


class Auth:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.secret = self._load_secret()
        self.generation = self._load_generation()
        self._record = self._load_record()      # {"salt","hash","iter"}（owner.json）
        self.password = self._envelope()        # 明文信封（改口令后为 None）

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

    # ------------------------------------------------ owner 口令（哈希 + 信封）
    def _owner_path(self) -> Path:
        return self.dir / "owner.json"

    def _load_record(self) -> dict:
        """owner 哈希记录；没有就生成初始口令：哈希入 owner.json、明文写信封。"""
        path = self._owner_path()
        if path.is_file():
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(rec, dict) and "salt" in rec and "hash" in rec:
                    return rec
            except (ValueError, OSError):
                pass                              # 坏文件按首次启动重生成
        password = secrets.token_urlsafe(9)       # ~12 字符，72 bit 熵
        salt = secrets.token_bytes(16)
        record = {"salt": salt.hex(), "hash": _hash(password, salt),
                  "iter": _PWD_ITER}
        path.write_text(json.dumps(record), encoding="utf-8")
        (self.dir / "password.txt").write_text(
            _PASSWORD_NOTE + password + "\n", encoding="utf-8")
        return record

    def _envelope(self) -> str | None:
        """password.txt 里若还有明文口令（信封未拆），返回它；已失效返回 None。"""
        path = self.dir / "password.txt"
        if not path.is_file():
            return None
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        if not lines:
            return None                           # 信封已拆（改口令后）
        return lines[-1]

    @property
    def envelope_active(self) -> bool:
        """初始口令信封是否还没拆（true = 机主仍在用自动生成的初始口令）。"""
        return self.password is not None

    def verify(self, password: str) -> bool:
        if not isinstance(password, str) or not password:
            return False
        salt = bytes.fromhex(self._record["salt"])
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                  salt, int(self._record.get("iter", _PWD_ITER)))
        return hmac.compare_digest(got.hex(), self._record["hash"])

    def set_password(self, new: str) -> None:
        if not isinstance(new, str) or len(new) < _MIN_LEN:
            raise ValueError(f"新口令至少 {_MIN_LEN} 个字符")
        salt = secrets.token_bytes(16)
        self._record = {"salt": salt.hex(), "hash": _hash(new, salt),
                        "iter": _PWD_ITER}
        self._owner_path().write_text(json.dumps(self._record), encoding="utf-8")
        # 信封拆封：磁盘上明文消失（失效说明全注释行——脚本取末行拿到空集即知失效）。
        # 内存缓存保留当前口令（演示/测试用）——磁盘不再有长期明文凭据即达标。
        (self.dir / "password.txt").write_text(_ENVELOPE_SPENT, encoding="utf-8")
        self.password = new
