"""sec32/creds.py —— 口令存储：三种存法、一份现算的破解成本表、可预测令牌。

课程概念：
    服务器**不需要知道口令**，它只需要能判断"这次输入的口令派生出的东西，
    和上次派生出的东西是否相同"。所以口令存储的正确形态是**单向派生**，
    而且这个派生必须**贵**——贵在攻击者那边，不是贵在自己登录那一下。

三口径对照（同一份口令、同一台机器、实测吞吐）：
    plain   明文：一旦库被拖走，危害 = 100%，且横向能看出两人用了同一口令。
    md5     无盐快摘要：库被拖走后可**离线**跑字典；单核吞吐就是攻击者的速度上限，
            所以"快"在这里是缺陷不是优点。相同口令 → 相同摘要（彩虹表与横向比较）。
    pbkdf2  加盐 + 迭代次数：每个用户不同盐 => 同一口令也得到不同摘要；
            迭代次数把一次验证的成本放大 N 倍 => 离线字典的成本同步放大 N 倍。

三个容易写错的细节，本模块都用实测钉住：
    1. **比较必须走 `hmac.compare_digest`**。普通 `==` 会在第一个不同字节提前返回；
       这个"快一点"是可以被外部计时的（时序侧信道）。本实验测的是**代码写法**，
       不假装能在 Python 层量出可靠的纳秒级差异——测不出来就写"未验证"。
    2. **盐要随机且唯一**，但盐**不是秘密**，它和摘要一起存。
    3. **重置令牌属于另一类问题**：它不需要"派生成本"，需要的是**不可预测**。
       用 `random`（线性同余、可复现）发令牌，等于把秘密交给了种子。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import random
import secrets
import time

PBKDF2_ALGO = "sha256"
DEFAULT_ITERS = 120_000            # 教学取值；真实项目应按目标硬件标定并写清依据
SALT_BYTES = 16
DK_BYTES = 32

# 现算成本表用的迭代档位（覆盖三个数量级，斜率应当接近线性）
ITER_LADDER = (1_000, 10_000, 100_000)


# ---------------------------------------------------------------- 三口径
def store_plain(password: str) -> dict:
    """明文存储：能跑，但库一泄露就全完。"""
    return {"scheme": "plain", "stored": password}


def recover_plain(record: dict) -> str:
    """明文的定义性缺陷：**可以被还原**。这一行就是危害本身。"""
    return record["stored"]


def store_md5(password: str) -> dict:
    """无盐快摘要：不可还原，但可离线字典攻击，且同口令同摘要。"""
    return {"scheme": "md5", "stored": hashlib.md5(
        password.encode("utf-8"), usedforsecurity=False).hexdigest()}


def verify_md5(record: dict, password: str) -> bool:
    return hmac.compare_digest(record["stored"], hashlib.md5(
        password.encode("utf-8"), usedforsecurity=False).hexdigest())


def store_pbkdf2(password: str, iters: int = DEFAULT_ITERS,
                 salt: bytes | None = None) -> dict:
    """加盐 + 迭代。`salt` 参数只为**对拍/可复现**而暴露，正常调用不传。"""
    salt = salt if salt is not None else os.urandom(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(PBKDF2_ALGO, password.encode("utf-8"), salt,
                             iters, dklen=DK_BYTES)
    return {"scheme": "pbkdf2", "salt": salt.hex(), "iters": iters,
            "stored": dk.hex()}


def derive(record: dict, password: str) -> bytes:
    return hashlib.pbkdf2_hmac(PBKDF2_ALGO, password.encode("utf-8"),
                               bytes.fromhex(record["salt"]),
                               record["iters"], dklen=DK_BYTES)


def verify_pbkdf2(record: dict, password: str) -> bool:
    """比较走 `hmac.compare_digest`（常量时间写法），不走 `==`。"""
    return hmac.compare_digest(bytes.fromhex(record["stored"]),
                               derive(record, password))


# ---------------------------------------------------------------- 度量
def hash_rate(algo: str, iters: int | None = None, budget: float = 0.05) -> float:
    """实测这台机器上"每秒能算多少次派生"。

    `budget` 是至少占用的秒数：单次计时噪声太大，所以按批次数到覆盖 budget 再取均值。
    返回**次/秒**。这只是单核 Python 的数量级，不是 GPU 的数字，README 里写清了边界。
    """
    password, salt = b"correct horse", b"0123456789abcdef"
    if algo == "md5":
        op = lambda: hashlib.md5(password, usedforsecurity=False).digest()
    elif algo == "sha256":
        op = lambda: hashlib.sha256(password).digest()
    elif algo == "pbkdf2":
        op = lambda: hashlib.pbkdf2_hmac(PBKDF2_ALGO, password, salt, iters)
    else:
        raise ValueError(f"未知算法：{algo}")
    op()                                     # 预热，避开首次调用的导入成本
    best_rate = 0.0
    batch = 8
    while True:
        start = time.perf_counter()
        for _ in range(batch):
            op()
        elapsed = time.perf_counter() - start
        best_rate = max(best_rate, batch / elapsed) if elapsed > 0 else best_rate
        if elapsed >= budget:
            return best_rate
        batch = max(batch * 2, int(batch * budget / elapsed) + 1) if elapsed else batch * 2


def cost_table() -> dict:
    """三口径 + 迭代阶梯的现算成本表。"""
    md5_rate = hash_rate("md5")
    sha_rate = hash_rate("sha256")
    ladder = {iters: hash_rate("pbkdf2", iters) for iters in ITER_LADDER}
    pbkdf2_rate = hash_rate("pbkdf2", DEFAULT_ITERS)
    return {"md5_per_sec": md5_rate, "sha256_per_sec": sha_rate,
            "pbkdf2_ladder": ladder, "pbkdf2_default_per_sec": pbkdf2_rate,
            "slowdown_vs_md5": md5_rate / pbkdf2_rate}


def dictionary_hours(words: int, per_sec: float) -> float:
    """把"字典大小 ÷ 每秒次数"换算成小时——数量级论证，不是保证。"""
    return words / per_sec / 3600


# ---------------------------------------------------------------- 盐的作用
def salt_effect(password: str, iters: int = 1_000) -> dict:
    """同一口令，两个用户各存一次：无盐 => 摘要相同（可横向比对、可彩虹表）；
    加盐 => 摘要不同（攻击者必须**逐用户**跑字典）。"""
    a = store_pbkdf2(password, iters=iters)
    b = store_pbkdf2(password, iters=iters)
    return {"md5_same": store_md5(password)["stored"] == store_md5(password)["stored"],
            "pbkdf2_same": a["stored"] == b["stored"],
            "salt_a": a["salt"], "salt_b": b["salt"],
            "salt_differs": a["salt"] != b["salt"],
            "verify_a": verify_pbkdf2(a, password),
            "verify_b_wrong": verify_pbkdf2(b, password + "!")}


# ---------------------------------------------------------------- 令牌可预测性
def token_with_random(n: int = 4, seed: int | None = None) -> list[str]:
    """反面教材：用 `random` 生成"看起来随机"的重置令牌。

    `random` 是 Mersenne Twister，**已知种子即可复现**。这里允许传 seed 正是为了
    让测试能证明"复现得出同一串"。
    """
    rng = random.Random(seed)
    return [f"{rng.getrandbits(128):032x}" for _ in range(n)]


def token_with_secrets(n: int = 4) -> list[str]:
    """修复版：`secrets` 走 OS 的 CSPRNG（`token_urlsafe` 默认 32 字节 ≈ 256 bit）。"""
    return [secrets.token_urlsafe(32) for _ in range(n)]


def token_entropy(n: int = 4) -> dict:
    """两种令牌的**实测**可比性质：长度、字符集、以及"同种子能否复现"。"""
    r1 = token_with_random(n, seed=20261002)
    r2 = token_with_random(n, seed=20261002)
    s1, s2 = token_with_secrets(n), token_with_secrets(n)
    return {"random_reproducible": r1 == r2,
            "random_length": len(r1[0]),
            "secrets_reproducible": s1 == s2,
            "secrets_length": len(s1[0]),
            "secrets_unique": len(set(s1 + s2)) == 2 * n,
            "random_bits_per_token": 128,
            "secrets_bits_per_token": 256}
