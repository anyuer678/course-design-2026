"""demo.py —— B4 集合论与代数实验台，六段演示。数字全部运行时现算，不抄文档。

  1) 数论底座：扩展欧几里得（两实现互拍）、快速幂 vs 内建 pow、欧拉函数双实现对拍
  2) 快速幂的账：平方-乘乘法次数 vs 朴素累乘——"快多少倍"是数出来的
  3) CRT：孙子算经"物不知数" + 300 组随机系统对暴力搜索
  4) 教学 RSA：密钥生成 → 加密 → 解密回读（含文本），并当面演示三条红线
  5) 群运算表：Z_7*、Z_8*（Klein 四元群）、S_3（非交换）、四张坏表被拒绝的理由
  6) 集合论：幂集/笛卡尔积计数、容斥公式 vs 暴力并集、双射枚举对账 n!

本演示固定种子、不打印耗时，两遍运行应逐字相同。
"""
from __future__ import annotations

import math
import pathlib
import random
import sys
from itertools import permutations

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from algebra import groups as G          # noqa: E402
from algebra import numbertheory as NT   # noqa: E402
from algebra import rsa as R             # noqa: E402
from algebra import sets as S            # noqa: E402

LINE = "=" * 78


def section(no: int, title: str) -> None:
    print(f"\n{LINE}\n  {no}) {title}\n{LINE}")


def main() -> int:
    print("B4 集合论与代数实验台 —— 数论底座 + 教学 RSA + 群运算表判定 + 集合论小工具")

    # ------------------------------------------------------------------ 1
    section(1, "数论底座：扩展欧几里得 / 快速幂 / 欧拉函数（全部对拍）")
    g, x, y = NT.egcd(240, 46)
    g2, x2, y2 = NT.egcd_iter(240, 46)
    print(f"  egcd(240,46) = ({g}, {x}, {y})；递归与迭代两版一致：{ (g, x, y) == (g2, x2, y2) }")
    print(f"  裴蜀等式验算：240·({x}) + 46·({y}) = {240 * x + 46 * y} = gcd")
    rng = random.Random(20261002)
    fails = 0
    for _ in range(2000):
        a, e, m = rng.randint(-9999, 9999), rng.randint(0, 500), rng.randint(1, 9999)
        if NT.mod_pow(a, e, m) != pow(a, e, m):
            fails += 1
    print(f"  mod_pow vs 内建 pow：2000 组随机 (a, e, m) 对拍，{fails} 处不一致")
    phi_line = "、".join(f"φ({n})={NT.phi(n)}" for n in (1, 2, 9, 97, 100))
    print(f"  {phi_line}")
    sieve_ok = all(NT.phi_sieve(400)[n - 1] == NT.phi(n) for n in range(1, 401))
    ident_ok = all(sum(NT.phi(d) for d in range(1, n + 1) if n % d == 0) == n
                   for n in range(1, 201))
    print(f"  筛法 φ 与分解 φ 对拍 1..400：{'全一致' if sieve_ok else '有不一致！'}"
          f"；恒等式 Σφ(d)=n 对 1..200：{'成立' if ident_ok else '不成立！'}")

    # ------------------------------------------------------------------ 2
    section(2, "快速幂的账：平方-乘 vs 朴素累乘（乘法次数实测）")
    e = (1 << 20) + 37
    stats: dict = {}
    value = NT.mod_pow(3, e, 1_000_000_007, stats=stats)
    fast = stats.get("multiplications", 0) + stats.get("squarings", 0)
    print(f"  3^(2^20+37) mod p = {value}")
    print(f"  平方-乘：{stats.get('squarings', 0)} 次平方 + {stats.get('multiplications', 0)} 次乘法"
          f" = 共 {fast} 次模乘；朴素累乘要 {e} 次 —— 差 {e // fast} 倍")
    print(f"  （指数二进制的位数 = {e.bit_length()}，快速幂的复杂度就是 O(log e)）")

    # ------------------------------------------------------------------ 3
    section(3, "CRT：孙子算经\"物不知数\" + 随机系统对暴力搜索")
    x23 = NT.crt([2, 3, 2], [3, 5, 7])
    print(f"  物不知数（3,5,7 的排列）：解 = {x23}"
          f"（验算：{x23}%3={x23 % 3}, {x23}%5={x23 % 5}, {x23}%7={x23 % 7}）")
    rng = random.Random(7)
    primes = [p for p in NT.sieve(30) if p >= 3]
    bad = 0
    for _ in range(300):
        ms = rng.sample(primes, 3)
        rs = [rng.randrange(m) for m in ms]
        got = NT.crt(rs, ms)
        prod = ms[0] * ms[1] * ms[2]
        brute = next(v for v in range(prod) if all(v % m == r % m for r, m in zip(rs, ms)))
        if got != brute:
            bad += 1
    print(f"  300 组随机 3 模系统对暴力搜索：{bad} 处不一致"
          f"（每组都在 [0, ∏m) 里逐数试出来的答案）")

    # ------------------------------------------------------------------ 4
    section(4, "教学 RSA：生成 → 加密 → 解密回读（红线当面说）")
    key = R.generate_keypair(seed=42)
    print(f"  p={key.p} q={key.q} n={key.n} φ={key.phi} e={key.e} d={key.d}（seed=42，可复现）")
    print(f"  验算：e·d mod φ = {(key.e * key.d) % key.phi}")
    m = 65
    c = R.encrypt(key, m)
    print(f"  加密 m={m} → c={c}；解密 → {R.decrypt(key, c)}（回读{'一致' if R.decrypt(key, c) == m else '不一致！'}）")
    text = "RSA 回读"
    blocks = R.encrypt_text(key, text)
    print(f"  文本 {text!r} → {len(blocks)} 个密文块（逐字节） → 回读 {R.decrypt_text(key, blocks)!r}")
    print(f"  **红线演示**：同一明文两次加密都是 {R.encrypt(key, m)}——教科书 RSA 是确定性的；")
    print(f"  本实现用小素数、无填充、无签名，仅供教学，不用于真实秘密保护。")

    # ------------------------------------------------------------------ 5
    section(5, "群运算表：真群、Klein 群、非交换群、四张坏表")
    for n in (5, 7):
        units, table = G.mul_units_table(n)
        rep = G.check_group(table)
        print(f"  Z_{n}* 元素 {units}：是群={rep.ok}，阿贝尔={G.is_abelian(table)}"
              f"（结合律检查 {rep.n}**3={rep.n ** 3} 组三元）")
    units8, table8 = G.mul_units_table(8)
    rep8 = G.check_group(table8)
    print(f"  Z_8* = {units8}：是群={rep8.ok}，阿贝尔={G.is_abelian(table8)}"
          f"，每元自乘 = 1：{all((u * u) % 8 == 1 for u in units8)}（Klein 四元群）")
    perms = list(permutations(range(3)))
    idx = {p: i for i, p in enumerate(perms)}
    s3 = [[idx[tuple(p[q[i]] for i in range(3))] for q in perms] for p in perms]
    w = G.abelian_witness(s3)
    print(f"  S_3（3 元置换复合）：是群={G.check_group(s3).ok}，阿贝尔={G.is_abelian(s3)}"
          f"；交换律反例：(置换 {w[0]}, {w[1]}) 两边得 {w[2]} vs {w[3]}")
    bad_tables = [
        ("不封闭", [[0, 1], [1, 2]]),
        ("没有单位元", [[0, 0], [0, 0]]),
        ("缺逆元", [[0, 1, 2], [1, 0, 2], [2, 2, 2]]),
        ("不结合（模 3 减法）", [[0, 2, 1], [1, 0, 2], [2, 1, 0]]),
    ]
    for label, table in bad_tables:
        reason = G.check_group(table).explain()[0]
        print(f"  坏表·{label}：被拒绝 —— {reason}")

    # ------------------------------------------------------------------ 6
    section(6, "集合论：幂集、笛卡尔积、容斥、双射枚举")
    A = frozenset({1, 2, 3})
    ps = S.power_set(A)
    print(f"  |P({{1,2,3}})| = {len(ps)} = 2**3；含空集={frozenset() in ps}，含全集={A in ps}")
    prod = S.cartesian(frozenset({1, 2}), frozenset("xyz"))
    print(f"  |{{1,2}} × {{x,y,z}}| = {len(prod)} = 2×3")
    rng = random.Random(11)
    bad = 0
    for _ in range(300):
        k = rng.randrange(2, 5)
        family = [frozenset(rng.sample(range(20), rng.randrange(0, 8))) for _ in range(k)]
        if S.inclusion_exclusion(family) != len(frozenset().union(*family)):
            bad += 1
    print(f"  容斥公式 vs 暴力并集：300 组 2~4 个集合，{bad} 处不一致")
    D = frozenset({0, 1, 2})
    bij = sum(
        1
        for a in range(3) for b in range(3) for c in range(3)
        if S.check_function({(0, a), (1, b), (2, c)}, D, D).bijective
    )
    print(f"  3→3 全部 27 个映射里双射 = {bij} 个 = 3!（穷举出来的阶乘）")

    print("\n" + LINE)
    print("完成：6 段演示全部跑通。演示固定种子、无耗时输出，两遍运行应逐字相同。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
