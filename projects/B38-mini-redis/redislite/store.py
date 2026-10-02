"""redislite/store.py —— 字符串键空间：命令语义（语义表）+ 过期双策略

课程要点（对应 docs/case-study.md 第 3、6 节）：
    - 过期必须"两条腿走路"：**惰性删除**保证到期的键读不到；**主动采样**保证
      没人访问的过期键也不会长期占内存（随机采样 20 个、过期率 >25% 就再来一轮，
      用样本推断整库——不阻塞、不全扫）。
    - **时钟可注入**：过期语义的边界测试最怕 sleep；测试与演示给一个假墙钟，
      时间由测试推进，一切边界（deadline 当刻、负 EXPIRE、TTL -1/-2）都变成确定性断言。
    - 命令语义以 docs/case-study.md §6 的语义表为准：INCR 用 string2ll 口径的
      严格整数文法；错误文本逐字可断言（这是"行为对拍"的锚点）。
"""
from __future__ import annotations

import random
import time

INT64_MAX = 2 ** 63 - 1
INT64_MIN = -(2 ** 63)

#: 会被传播到从库的写类命令（case-study §8.1；SAVE/REPLICAOF/PSYNC 不传播）
WRITE_COMMANDS = {"SET", "DEL", "EXPIRE", "INCR"}


class CommandError(Exception):
    """命令级错误：message 是 `-` 后的完整错误文本（不含 `-`）。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def parse_int64(token: bytes) -> int:
    """string2ll 口径：可选负号 + 数字；拒绝 `+`、空白、前导零、`-0`、超出 int64。"""
    if not token:
        raise ValueError("empty")
    if token == b"0":
        return 0
    body = token[1:] if token[:1] == b"-" else token
    if not body or not body.isdigit():
        raise ValueError("not an integer")
    if body[:1] == b"0":
        raise ValueError("leading zero")
    value = int(body)
    if token[:1] == b"-":
        value = -value
    if not INT64_MIN <= value <= INT64_MAX:
        raise ValueError("out of int64 range")
    return value


class Store:
    def __init__(self, clock=time.time, active_sample: int = 20,
                 active_rounds: int = 4, rng_seed: int = 20261002,
                 passive_expire: bool = False, on_expire=None):
        self.clock = clock
        self.active_sample = active_sample
        self.active_rounds = active_rounds
        self._rng = random.Random(rng_seed)
        self.data: dict[bytes, bytes] = {}
        self.expires: dict[bytes, float] = {}
        self.stats = {"expired_lazy": 0, "expired_active": 0, "active_cycles": 0}
        # 从库模式（case-study §8.1）：读过期键表现为"不存在"但**不删除**；
        # 不跑主动周期；等主库传播 DEL。see docs/case-study.md
        self.passive_expire = passive_expire
        # 主库真正删除过期键时的回调（服务器据此向从库补发合成 DEL）
        self.on_expire = on_expire

    # ---------------------------------------------------------------- 过期
    def _check_expired(self, key: bytes) -> bool:
        """惰性：到期就删（顺带计数）。从库模式只回答"已过期"，不动数据。"""
        deadline = self.expires.get(key)
        if deadline is not None and deadline <= self.clock():
            if self.passive_expire:
                return True
            del self.expires[key]
            self.data.pop(key, None)
            self.stats["expired_lazy"] += 1
            if self.on_expire:
                self.on_expire(key)
            return True
        return False

    def active_expire_cycle(self) -> int:
        """主动采样一轮（可由服务器每 N 条命令调一次）：返回删除个数。从库不跑。"""
        if self.passive_expire:
            return 0
        deleted = 0
        self.stats["active_cycles"] += 1
        for _ in range(self.active_rounds):
            if not self.expires:
                break
            keys = sorted(self.expires)                # 排序：采样可复现
            sample = self._rng.sample(keys, min(self.active_sample, len(keys)))
            expired = [k for k in sample if self.expires[k] <= self.clock()]
            for key in expired:
                del self.expires[key]
                self.data.pop(key, None)
                if self.on_expire:
                    self.on_expire(key)
            deleted += len(expired)
            if len(expired) / len(sample) <= 0.25:     # 过期率低：这一轮收工
                break
        self.stats["expired_active"] += deleted
        return deleted

    # ---------------------------------------------------------------- 命令
    def cmd_set(self, key: bytes, value: bytes) -> None:
        self.data[key] = value
        self.expires.pop(key, None)                    # SET 清除过期时间（语义表）

    def cmd_get(self, key: bytes) -> bytes | None:
        if self._check_expired(key):
            return None
        return self.data.get(key)

    def cmd_del(self, keys: list[bytes]) -> int:
        count = 0
        for key in keys:
            self._check_expired(key)
            if key in self.data:
                del self.data[key]
                self.expires.pop(key, None)            # 一起清（曾被对账器抓出的残留）
                count += 1
        return count

    def cmd_expire(self, key: bytes, seconds: int) -> int:
        if self._check_expired(key) or key not in self.data:
            return 0
        if seconds <= 0:
            del self.data[key]                         # 非正数：立即删除（语义表）
            self.expires.pop(key, None)
            return 1
        self.expires[key] = self.clock() + seconds
        return 1

    def cmd_ttl(self, key: bytes) -> int:
        if self._check_expired(key) or key not in self.data:
            return -2
        deadline = self.expires.get(key)
        if deadline is None:
            return -1
        return int(deadline - self.clock())            # 向下取整（见偏离表第 2 条）

    def cmd_incr(self, key: bytes) -> int:
        current = self.cmd_get(key)
        if current is None:
            base = 0
        else:
            try:
                base = parse_int64(current)
            except ValueError as err:
                raise CommandError("ERR value is not an integer or out of range") from err
        if not INT64_MIN <= base + 1 <= INT64_MAX:
            raise CommandError("ERR increment or decrement would overflow")
        self.data[key] = str(base + 1).encode("ascii")  # 保留 TTL（真实 Redis 行为）
        return base + 1

    # ---------------------------------------------------------------- 路由
    def dispatch(self, args: list[bytes]) -> object:
        """执行一条命令；返回要编码的值（None→+OK 由调用方决定）。"""
        name = args[0].decode("utf-8", "replace")
        upper = name.upper()
        if upper == "PING":
            if len(args) == 1:
                return _Pong()
            if len(args) == 2:
                return args[1]
            raise self._arity("ping")
        if upper == "SET":
            if len(args) != 3:
                raise self._arity("set")
            self.cmd_set(args[1], args[2])
            return _Ok()
        if upper == "GET":
            if len(args) != 2:
                raise self._arity("get")
            return self.cmd_get(args[1])
        if upper == "DEL":
            if len(args) < 2:
                raise self._arity("del")
            return self.cmd_del(args[1:])
        if upper == "EXPIRE":
            if len(args) != 3:
                raise self._arity("expire")
            try:
                seconds = parse_int64(args[2])
            except ValueError as err:
                raise CommandError("ERR value is not an integer or out of range") from err
            return self.cmd_expire(args[1], seconds)
        if upper == "TTL":
            if len(args) != 2:
                raise self._arity("ttl")
            return self.cmd_ttl(args[1])
        if upper == "INCR":
            if len(args) != 2:
                raise self._arity("incr")
            return self.cmd_incr(args[1])
        if upper == "SAVE":
            if len(args) != 1:
                raise self._arity("save")
            return _Save()
        if upper == "PSYNC":
            if len(args) != 3:
                raise self._arity("psync")
            return _Psync()
        if upper == "REPLICAOF":
            if len(args) != 3:
                raise self._arity("replicaof")
            if args[1].upper() == b"NO" and args[2].upper() == b"ONE":
                return _Replicaof(host=None, port=None)
            try:
                port = parse_int64(args[2])
            except ValueError as err:
                raise CommandError("ERR Invalid master port") from err
            if not 1 <= port <= 65535:
                raise CommandError("ERR Invalid master port")
            return _Replicaof(host=args[1].decode("utf-8", "replace"), port=port)
        raise CommandError(f"ERR unknown command '{name}'")

    @staticmethod
    def _arity(name: str) -> CommandError:
        return CommandError(f"ERR wrong number of arguments for '{name}' command")

    # ---------------------------------------------------------------- 快照
    def export_state(self) -> list[tuple[bytes, bytes, float | None]]:
        """导出未过期键（(key, value, 绝对到期时刻|None)）——快照用。

        注意 `list(...)`：循环里的 `_check_expired` 会删键，
        直接迭代 `self.data.items()` 会 RuntimeError（复制的全量同步把这条炸出来过）。
        """
        out = []
        for key, value in list(self.data.items()):
            if self._check_expired(key):
                continue
            out.append((key, value, self.expires.get(key)))
        return sorted(out)

    def load_state(self, entries: list[tuple[bytes, bytes, float | None]]) -> int:
        """加载快照（覆盖现有数据）。已过期的条目直接丢弃——加载时不该复活过期键。"""
        self.data.clear()
        self.expires.clear()
        loaded = 0
        now = self.clock()
        for key, value, deadline in entries:
            if deadline is not None and deadline <= now:
                continue
            self.data[key] = value
            if deadline is not None:
                self.expires[key] = deadline
            loaded += 1
        return loaded


class _Ok:
    """SET 等的 `+OK` 返回值哨兵（避免和 PING 的 bulk 回显混淆）。"""


class _Pong:
    """无参 PING 的 `+PONG` 哨兵。"""


class _Save:
    """SAVE 命令的返回值哨兵（服务器据此落盘）。"""


class _Psync:
    """PSYNC 命令的哨兵（服务器据此回 FULLRESYNC + 快照并标记复制链接）。"""


class _Replicaof:
    """REPLICAOF 命令的哨兵（服务器据此配置/解除复制链路）。"""

    def __init__(self, host, port):
        self.host = host
        self.port = port
