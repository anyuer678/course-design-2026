"""algebra/rsa.py —— 教学 RSA：密钥生成、加密、解密（回读）

课程要点（集合论与代数）：
    - RSA 的三行数学：n = p·q、φ(n) = (p-1)(q-1)、e·d ≡ 1 (mod φ(n))。
      "为什么能解密"是欧拉定理：m^(ed) = m^(1+kφ) ≡ m (mod n)——前一半是本模块，
      后一半在 numbertheory；
    - 加密解密都用**快速幂**（numbertheory.mod_pow），密钥生成用**模逆**（mod_inverse）——
      数论底座不是摆设，是每一行都在用的零件；
    - **回读**（round-trip）：encrypt 之后必须能 decrypt 回原文——这是测试钉住的第一条，
      随机消息批量回读；
    - 三条红线必须当面说清（README 与演示里都写）：**教学实现，不用于真实秘密保护**：
        ① 小素数当钥匙（本模块的素数池来自筛法，几十位就到头）；
        ② 教科书 RSA 是**确定性**的（同一明文 → 同一密文，演示里专门打印两次加密相同）；
        ③ 无填充/无签名/无侧信道防护（OAEP、签名属于 PLAN 选做项，明确没做）。
"""
from __future__ import annotations

from dataclasses import dataclass
import random

from algebra.numbertheory import first_primes, gcd, mod_inverse, mod_pow


@dataclass(frozen=True)
class RSAKey:
    """教学密钥对：两个素数、公开指数 e、私密指数 d。"""
    p: int
    q: int
    e: int
    d: int

    @property
    def n(self) -> int:
        return self.p * self.q

    @property
    def phi(self) -> int:
        return (self.p - 1) * (self.q - 1)


# 候选公开指数：从小到大挑第一个与 φ 互素的（教学版不追 F4=65537 的工程理由，
# 但把这个优先级写在这儿——真实系统为何偏爱 65537 见 README 的练习）
E_CANDIDATES = (65537, 257, 17, 5, 3)


def generate_keypair(seed: int = 42, prime_pool: int = 200,
                     min_n: int = 1000) -> RSAKey:
    """从筛法素数池里确定性挑两个素数（同 seed 同结果，演示可复现）。

    min_n 用来保证 n 比"按字节加密"所需的门限大（字节值 ≤ 255）。
    """
    pool = [p for p in first_primes(prime_pool) if p > 3]
    rng = random.Random(seed)
    while True:
        p = rng.choice(pool)
        q = rng.choice(pool)
        if p == q or p * q < min_n:
            continue
        phi_n = (p - 1) * (q - 1)
        for e in E_CANDIDATES:
            if gcd(e, phi_n) == 1:
                return RSAKey(p=p, q=q, e=e, d=mod_inverse(e, phi_n))


def encrypt(key: RSAKey, message: int) -> int:
    """c = m^e mod n；要求 0 ≤ m < n（越界抛错——"消息太长"要当场说，不是悄悄截断）。"""
    if not 0 <= message < key.n:
        raise ValueError(f"消息必须落在 [0, {key.n})：m={message}")
    return mod_pow(message, key.e, key.n)


def decrypt(key: RSAKey, ciphertext: int) -> int:
    """m = c^d mod n；要求 0 ≤ c < n。"""
    if not 0 <= ciphertext < key.n:
        raise ValueError(f"密文必须落在 [0, {key.n})：c={ciphertext}")
    return mod_pow(ciphertext, key.d, key.n)


def encrypt_text(key: RSAKey, text: str) -> list[int]:
    """按 UTF-8 字节逐个加密（教学口径：每个字节值的密文 = 字节值^e mod n）。

    分组/填充属真实工程做法，这里明确不做；要求 n > 255，否则单字节都可能越界。
    """
    if key.n <= 255:
        raise ValueError(f"n={key.n} 太小，无法逐字节加密——先用 min_n 生成更大的钥匙")
    return [encrypt(key, b) for b in text.encode("utf-8")]


def decrypt_text(key: RSAKey, blocks: list[int]) -> str:
    """回读：逐块解密并还原 UTF-8 文本。"""
    data = bytes(decrypt(key, c) for c in blocks)
    return data.decode("utf-8")


def verify_roundtrip(key: RSAKey, message: int) -> bool:
    return decrypt(key, encrypt(key, message)) == message
