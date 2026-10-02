"""algebra/numbertheory.py —— 数论底座：扩展欧几里得、快速幂、欧拉函数、CRT、素数

课程要点（集合论与代数）：
    - 扩展欧几里得把 `gcd(a,b)` 连同**裴蜀系数** (x, y) 一起算出来：`a·x + b·y = g`。
      它一个定理喂三个用途：最大公因数、模逆（g=1 时 x 就是逆）、CRT 的构造；
    - 快速幂是**平方-乘**：按指数的二进制位走，乘法次数 ~2·log2(e) 而不是 e——演示里把
      两个计数都打出来对照（`mod_pow(..., stats=...)` 记账）；
    - 欧拉函数 φ(n) 用**因子分解**算（φ = n·∏(1-1/p)），另配一个**筛法**实现：
      两套独立算法对拍（本仓库纪律：谁也别信自己）；
    - CRT（中国剩余定理）的构造就是反复用模逆把两个同余式合成一个——
      "物不知数"（3,5,7 → 23）在测试里是被手算钉住的；
    - 全部函数都只依赖 Python 标准库；`pow(a, e, m)` 在本仓库里当**独立参照**用
      （stdlib 的实现与我们的平方-乘互不共享代码）。

边界口径（测试盯着）：
    - `mod_inverse(a, m)`：a 与 m 不互素时**抛错**，不返回垃圾；
    - `crt(residues, moduli)`：模数必须两两互素，否则抛错；
    - `phi(1) = 1`（约定写法，写清楚比默认强）；
    - `is_prime` 用试除：教学版正确但慢，大数素性测试（Miller–Rabin）是 PLAN 的选做项，没做。
"""
from __future__ import annotations

from dataclasses import dataclass


def egcd(a: int, b: int) -> tuple[int, int, int]:
    """递归版扩展欧几里得：返回 (g, x, y) 使 a·x + b·y = g = gcd(a, b)。"""
    if b == 0:
        return (abs(a), 1 if a >= 0 else -1, 0) if a != 0 else (0, 0, 0)
    g, x, y = egcd(b, a % b)
    return g, y, x - (a // b) * y


def egcd_iter(a: int, b: int) -> tuple[int, int, int]:
    """迭代版（独立实现，用于交叉对拍）：先跑欧几里得记商，再回代求系数。"""
    old_r, r = a, b
    old_s, s = 1, 0
    old_t, t = 0, 1
    while r != 0:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_s, s = s, old_s - q * s
        old_t, t = t, old_t - q * t
    if old_r == 0:                   # 与递归版同约定：(0, 0) → (0, 0, 0)
        return 0, 0, 0
    if old_r < 0:                    # 统一到正的最大公因数
        old_r, old_s, old_t = -old_r, -old_s, -old_t
    return old_r, old_s, old_t


def gcd(a: int, b: int) -> int:
    return egcd_iter(a, b)[0]


def mod_inverse(a: int, m: int) -> int:
    """a 在模 m 下的乘法逆元；不互素就抛错（返回垃圾是最坏的选择）。"""
    if m <= 0:
        raise ValueError(f"模数必须为正：m={m}")
    g, x, _ = egcd_iter(a % m, m)
    if g != 1:
        raise ValueError(f"{a} 与 {m} 不互素（gcd={g}），没有模逆")
    return x % m


def mod_pow(base: int, exp: int, mod: int, stats: dict | None = None) -> int:
    """平方-乘快速幂：base^exp mod mod（exp ≥ 0；mod ≥ 1）。

    stats 传 dict 时，把 "multiplications" 与 "squarings" 累加进去——
    演示里的"快多少倍"就是数出来的，不是喊出来的。
    """
    if exp < 0:
        raise ValueError(f"不支持负指数（先自己取模逆）：exp={exp}")
    if mod <= 0:
        raise ValueError(f"模数必须为正：mod={mod}")
    if mod == 1:
        return 0
    result = 1
    b = base % mod
    e = exp
    while e > 0:
        if e & 1:
            result = (result * b) % mod
            if stats is not None:
                stats["multiplications"] = stats.get("multiplications", 0) + 1
        e >>= 1
        if e > 0:
            b = (b * b) % mod
            if stats is not None:
                stats["squarings"] = stats.get("squarings", 0) + 1
    return result


def factorize(n: int) -> list[tuple[int, int]]:
    """试除分解：返回 [(p, e), ...]（p 升序）。教学版：慢但直白。"""
    if n <= 0:
        raise ValueError(f"只分解正整数：n={n}")
    factors = []
    d = 2
    while d * d <= n:
        if n % d == 0:
            e = 0
            while n % d == 0:
                n //= d
                e += 1
            factors.append((d, e))
        d += 1 if d == 2 else 2      # 跳过偶数
    if n > 1:
        factors.append((n, 1))
    return factors


def phi(n: int) -> int:
    """欧拉函数：φ(1) = 1（约定）；n ≥ 1。按分解算 φ = n·∏(1-1/p)。"""
    if n < 1:
        raise ValueError(f"φ 只定义在正整数上：n={n}")
    result = n
    for p, _ in factorize(n):
        result = result // p * (p - 1)
    return result


def phi_sieve(limit: int) -> list[int]:
    """筛法算 φ(1..limit)。独立实现，专门用来和 `phi` 对拍。"""
    if limit < 1:
        raise ValueError(f"limit 必须 ≥ 1：{limit}")
    values = list(range(limit + 1))
    for p in range(2, limit + 1):
        if values[p] == p:           # p 是素数
            for k in range(p, limit + 1, p):
                values[k] = values[k] // p * (p - 1)
    return values[1:]


def crt(residues: list[int], moduli: list[int]) -> int:
    """中国剩余定理：求 x 使 x ≡ residues[i] (mod moduli[i])，返回最小非负解。

    构造法：逐个合并 (x ≡ r0 mod m0) 与 (x ≡ r1 mod m1)：
        t ≡ (r1 - x) · m0^-1 (mod m1)，x ← x + t·m0，m ← m0·m1。
    """
    if len(residues) != len(moduli):
        raise ValueError("residues 与 moduli 长度不一致")
    if not residues:
        raise ValueError("至少给一个同余式")
    x, m = residues[0] % moduli[0], moduli[0]
    for r, mi in zip(residues[1:], moduli[1:]):
        try:
            inv = mod_inverse(m % mi, mi)
        except ValueError as err:
            raise ValueError(f"模数必须两两互素：{m} 与 {mi} —— {err}") from err
        t = ((r - x) * inv) % mi
        x = x + t * m
        m *= mi
    return x % m


def is_prime(n: int) -> bool:
    """试除素性判定（教学版：正确、慢；Miller–Rabin 是 PLAN 选做项，没做）。"""
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    d = 3
    while d * d <= n:
        if n % d == 0:
            return False
        d += 2
    return True


def sieve(limit: int) -> list[int]:
    """埃氏筛：返回 ≤ limit 的全部素数。"""
    if limit < 2:
        return []
    flags = bytearray([1]) * (limit + 1)
    flags[0] = flags[1] = 0
    for p in range(2, int(limit ** 0.5) + 1):
        if flags[p]:
            flags[p * p::p] = bytearray(len(flags[p * p::p]))
    return [i for i in range(2, limit + 1) if flags[i]]


def first_primes(count: int) -> list[int]:
    """前 count 个素数（教学 RSA 的素数池）。"""
    if count < 1:
        raise ValueError(f"count 必须 ≥ 1：{count}")
    limit = 32
    while True:
        found = sieve(limit)
        if len(found) >= count:
            return found[:count]
        limit *= 2


@dataclass(frozen=True)
class CrtSystem:
    """同余式组的一个小包装：把"两两互素"的校验与解一起带上。"""
    residues: tuple[int, ...]
    moduli: tuple[int, ...]

    def solve(self) -> int:
        return crt(list(self.residues), list(self.moduli))
