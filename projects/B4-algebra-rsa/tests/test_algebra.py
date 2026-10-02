"""tests/test_algebra.py —— B4 的单元测试。

纪律（和本仓库其它项目一致）：
  1. 期望值来自**手算或独立参照**：裴蜀系数手推、`pow(a,e,m)` 当快速幂的参照、
     筛法 φ 与分解 φ 互拍、CRT 对拍暴力搜索、群判定器直接验真群与手写的坏表；
  2. 随机全部**固定种子**，失败可复现；
  3. 本套件纯内存，不建临时文件。
"""
from __future__ import annotations

import math
import pathlib
import random
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algebra import groups as G                     # noqa: E402
from algebra import numbertheory as NT              # noqa: E402
from algebra import rsa as R                        # noqa: E402
from algebra import sets as S                       # noqa: E402


class TestEgcd(unittest.TestCase):
    def test_hand_value(self):
        g, x, y = NT.egcd(240, 46)
        self.assertEqual((g, x, y), (2, -9, 47))
        self.assertEqual(240 * x + 46 * y, 2)

    def test_recursive_and_iterative_agree(self):
        # 两套独立实现互拍（含负数与零；(0,0) 统一为 (0,0,0)）
        for a in range(-30, 31):
            for b in range(-30, 31):
                self.assertEqual(NT.egcd(a, b), NT.egcd_iter(a, b), msg=f"a={a} b={b}")

    def test_bezout_identity_and_gcd(self):
        for a in range(-25, 26):
            for b in range(-25, 26):
                g, x, y = NT.egcd_iter(a, b)
                self.assertEqual(a * x + b * y, g, msg=f"a={a} b={b}")
                self.assertEqual(g, math.gcd(a, b), msg=f"a={a} b={b}")

    def test_gcd_edges(self):
        self.assertEqual(NT.gcd(0, 0), 0)
        self.assertEqual(NT.gcd(0, 5), 5)
        self.assertEqual(NT.gcd(-4, 6), 2)
        self.assertEqual(NT.gcd(4, -6), 2)

    def test_mod_inverse_hand(self):
        self.assertEqual(NT.mod_inverse(3, 11), 4)      # 3·4=12≡1
        self.assertEqual(NT.mod_inverse(7, 40), 23)     # 7·23=161=4·40+1
        self.assertEqual(NT.mod_inverse(1, 7), 1)

    def test_mod_inverse_refuses_non_coprime(self):
        with self.assertRaises(ValueError):
            NT.mod_inverse(6, 9)
        with self.assertRaises(ValueError):
            NT.mod_inverse(4, 8)
        with self.assertRaises(ValueError):
            NT.mod_inverse(3, 0)                        # 模数非正

    def test_mod_inverse_vs_brute(self):
        # 参照：逐个试 0..m-1 找 a·x ≡ 1
        for m in range(2, 60):
            for a in range(-m, m + 1):
                if math.gcd(a, m) != 1:
                    continue
                inv = NT.mod_inverse(a, m)
                self.assertEqual((a * inv) % m, 1, msg=f"a={a} m={m}")


class TestModPow(unittest.TestCase):
    def test_hand_values(self):
        self.assertEqual(NT.mod_pow(2, 10, 1000), 24)
        self.assertEqual(NT.mod_pow(3, 0, 7), 1)
        self.assertEqual(NT.mod_pow(5, 1, 7), 5)
        self.assertEqual(NT.mod_pow(7, 5, 1), 0)        # mod 1 → 恒 0
        self.assertEqual(NT.mod_pow(-2, 3, 5), 2)       # (-8) mod 5 = 2
        self.assertEqual(NT.mod_pow(12345, 0, 2), 1)

    def test_against_builtin_pow(self):
        # 独立参照：Python 内建 pow(a, e, m)，3000 组固定种子
        rng = random.Random(20261002)
        for _ in range(3000):
            a = rng.randint(-10_000, 10_000)
            e = rng.randint(0, 600)
            m = rng.randint(1, 10_000)
            self.assertEqual(NT.mod_pow(a, e, m), pow(a, e, m), msg=f"{a}^{e} mod {m}")

    def test_stats_exact_counts(self):
        # 平方-乘的账：平方 = bit_length-1 次；乘法 = 指数二进制里 1 的个数
        for e in (0, 1, 2, 3, 5, 8, 31, 32, 100, 255, 256, 999):
            stats: dict = {}
            NT.mod_pow(7, e, 1000, stats=stats)
            self.assertEqual(stats.get("squarings", 0), max(e.bit_length() - 1, 0), msg=f"e={e}")
            self.assertEqual(stats.get("multiplications", 0), bin(e).count("1"), msg=f"e={e}")

    def test_rejects_negative_exp_and_bad_mod(self):
        with self.assertRaises(ValueError):
            NT.mod_pow(2, -1, 7)
        with self.assertRaises(ValueError):
            NT.mod_pow(2, 3, 0)


class TestPhi(unittest.TestCase):
    def test_hand_values(self):
        self.assertEqual(NT.phi(1), 1)
        self.assertEqual(NT.phi(2), 1)
        self.assertEqual(NT.phi(9), 6)
        self.assertEqual(NT.phi(97), 96)                # 素数
        self.assertEqual(NT.phi(100), 40)
        with self.assertRaises(ValueError):
            NT.phi(0)

    def test_sieve_matches_factorization(self):
        # 两套独立实现（筛法 vs 分解）逐数对拍
        values = NT.phi_sieve(300)
        self.assertEqual(len(values), 300)
        for i, v in enumerate(values):
            self.assertEqual(v, NT.phi(i + 1), msg=f"n={i + 1}")

    def test_divisor_sum_identity(self):
        # 经典恒等式：Σ_{d|n} φ(d) = n（对 n ≤ 200 逐数手算对账）
        for n in range(1, 201):
            total = sum(NT.phi(d) for d in range(1, n + 1) if n % d == 0)
            self.assertEqual(total, n, msg=f"n={n}")

    def test_multiplicative_on_coprimes(self):
        for a in range(1, 51):
            for b in range(1, 51):
                if math.gcd(a, b) == 1:
                    self.assertEqual(NT.phi(a * b), NT.phi(a) * NT.phi(b),
                                     msg=f"a={a} b={b}")


class TestCrt(unittest.TestCase):
    def test_hand_values(self):
        # 孙子算经"物不知数"：3、5、7 的排列解得 23
        self.assertEqual(NT.crt([2, 3, 2], [3, 5, 7]), 23)
        self.assertEqual(NT.crt([1, 2, 3], [2, 3, 5]), 23)
        self.assertEqual(NT.crt([5], [7]), 5)           # 单个同余式

    def test_random_systems_vs_brute_force(self):
        # 参照：在 [0, ∏m) 里暴力找第一个满足所有同余式的 x
        rng = random.Random(7)
        primes = [p for p in NT.sieve(30) if p >= 3]    # 3,5,7,11,13,17,19,23,29
        for _ in range(300):
            ms = rng.sample(primes, 3)
            rs = [rng.randrange(m) for m in ms]
            x = NT.crt(rs, ms)
            prod = ms[0] * ms[1] * ms[2]
            for r, m in zip(rs, ms):
                self.assertEqual(x % m, r % m, msg=f"{rs} {ms}")
            brute = next(y for y in range(prod)
                         if all(y % m == r % m for r, m in zip(rs, ms)))
            self.assertEqual(x, brute, msg=f"{rs} {ms}")

    def test_refuses_non_coprime(self):
        with self.assertRaises(ValueError):
            NT.crt([1, 1], [4, 6])                      # gcd(4,6)=2
        with self.assertRaises(ValueError):
            NT.crt([], [])

    def test_solver_wrapper(self):
        sysm = NT.CrtSystem(residues=(2, 3, 2), moduli=(3, 5, 7))
        self.assertEqual(sysm.solve(), 23)


class TestPrimes(unittest.TestCase):
    def test_sieve_hand(self):
        self.assertEqual(NT.sieve(29), [2, 3, 5, 7, 11, 13, 17, 19, 23, 29])
        self.assertEqual(NT.sieve(1), [])
        self.assertEqual(len(NT.sieve(100)), 25)        # π(100)=25，教材常数

    def test_is_prime_matches_sieve(self):
        expected = set(NT.sieve(2000))
        for n in range(0, 2001):
            self.assertEqual(NT.is_prime(n), n in expected, msg=f"n={n}")

    def test_first_primes(self):
        self.assertEqual(NT.first_primes(10), [2, 3, 5, 7, 11, 13, 17, 19, 23, 29])
        self.assertEqual(NT.first_primes(1), [2])
        with self.assertRaises(ValueError):
            NT.first_primes(0)


class TestRSA(unittest.TestCase):
    def setUp(self):
        self.key = R.generate_keypair(seed=42)

    def test_key_properties(self):
        k = self.key
        self.assertTrue(NT.is_prime(k.p) and NT.is_prime(k.q))
        self.assertNotEqual(k.p, k.q)
        self.assertEqual(k.n, k.p * k.q)
        self.assertEqual(k.phi, (k.p - 1) * (k.q - 1))
        self.assertEqual((k.e * k.d) % k.phi, 1, msg="e·d ≡ 1 (mod φ)")

    def test_deterministic_keygen(self):
        self.assertEqual(R.generate_keypair(seed=42), self.key)
        self.assertNotEqual(R.generate_keypair(seed=1).n, R.generate_keypair(seed=2).n)

    def test_roundtrip_many_messages(self):
        k = self.key
        rng = random.Random(2026)
        for _ in range(200):
            m = rng.randrange(k.n)
            self.assertEqual(R.decrypt(k, R.encrypt(k, m)), m, msg=f"m={m}")
        for m in (0, 1, k.n - 1):                       # 边界
            self.assertTrue(R.verify_roundtrip(k, m), msg=f"m={m}")

    def test_text_roundtrip(self):
        text = "RSA 教学演示：回读（round-trip）"
        blocks = R.encrypt_text(self.key, text)
        self.assertTrue(all(0 <= c < self.key.n for c in blocks))
        self.assertEqual(R.decrypt_text(self.key, blocks), text)

    def test_text_needs_big_enough_n(self):
        small = R.RSAKey(p=3, q=5, e=3, d=3)            # n=15 < 255
        with self.assertRaises(ValueError):
            R.encrypt_text(small, "x")

    def test_message_bounds(self):
        k = self.key
        with self.assertRaises(ValueError):
            R.encrypt(k, k.n)
        with self.assertRaises(ValueError):
            R.encrypt(k, -1)
        with self.assertRaises(ValueError):
            R.decrypt(k, k.n)

    def test_textbook_rsa_is_deterministic(self):
        # 这不是缺点声明，是**当面演示**：同一明文两次加密密文相同
        # （真实系统用随机填充破坏它，本教学版没有——README 红线）
        m = 42
        self.assertEqual(R.encrypt(self.key, m), R.encrypt(self.key, m))


class TestGroups(unittest.TestCase):
    def test_zn_addition_always_group(self):
        for n in range(1, 13):
            _, table = G.add_table(n)
            report = G.check_group(table)
            self.assertTrue(report.ok, msg=f"Z_{n} 加法：{report.explain()}")
            self.assertTrue(G.is_abelian(table), msg=f"Z_{n}")

    def test_units_multiplicative_groups(self):
        for n in (3, 4, 5, 7, 8, 11, 12):
            units, table = G.mul_units_table(n)
            self.assertTrue(G.check_group(table).ok, msg=f"Z_{n}*")
            self.assertTrue(G.is_abelian(table), msg=f"Z_{n}*")

    def test_z8_units_is_klein(self):
        units, table = G.mul_units_table(8)
        self.assertEqual(units, [1, 3, 5, 7])           # 手算：与 8 互素的剩余类
        self.assertTrue(all((x * x) % 8 == 1 for x in units))
        # Klein 四元群：每个非单位元阶为 2，最大阶 = 2（不是循环群）
        e = 0                                            # 单位元 1 的编号是 0
        def order(i: int) -> int:
            cur, k = i, 1
            while cur != e:
                cur = table[cur][i]
                k += 1
            return k
        self.assertEqual(max(order(i) for i in range(1, len(units))), 2)

    def test_bad_tables_are_rejected_with_reasons(self):
        # ① 不封闭：出现了元素编号 2（表只有 0/1）
        rep = G.check_group([[0, 1], [1, 2]])
        self.assertFalse(rep.ok)
        self.assertFalse(rep.closure_ok)
        self.assertIn("不封闭", " ".join(rep.explain()))
        # ② 全零表：结合成立、没有单位元
        rep = G.check_group([[0, 0], [0, 0]])
        self.assertFalse(rep.ok)
        self.assertTrue(rep.assoc_ok)
        self.assertIsNone(rep.identity)
        # ③ 有单位元但元素 2 没有逆
        rep = G.check_group([[0, 1, 2], [1, 0, 2], [2, 2, 2]])
        self.assertFalse(rep.ok)
        self.assertEqual(rep.identity, 0)
        self.assertEqual(rep.inverses_missing, [2])
        # ④ 不结合：模 3 减法（封闭、但没有单位元也不结合）
        rep = G.check_group([[0, 2, 1], [1, 0, 2], [2, 1, 0]])
        self.assertFalse(rep.assoc_ok)
        self.assertIsNotNone(rep.assoc_witness)
        i, j, k, left, right = rep.assoc_witness
        self.assertNotEqual(left, right)
        self.assertIn("不结合", " ".join(rep.explain()))

    def test_explain_mentions_cube_count(self):
        _, table = G.add_table(5)
        text = " ".join(G.check_group(table).explain())
        self.assertIn("125", text)                       # n3=125 组三元被检查过

    def test_abelian_witness(self):
        # 交换的例子：Z_3 加法（witness 必须是 None）
        table = [[0, 1, 2], [1, 2, 0], [2, 0, 1]]
        self.assertIsNone(G.abelian_witness(table))
        # 非交换的例子：S_3（3 个元素的全体置换，按复合运算）——最小的非交换群，
        # 桌子就有：判定器必须既认它是群、又抓出它不交换
        from itertools import permutations
        perms = list(permutations(range(3)))
        index = {p: i for i, p in enumerate(perms)}
        def compose(p, q):                    # (poq)(x) = p(q(x))
            return tuple(p[q[x]] for x in range(3))
        s3 = [[index[compose(p, q)] for q in perms] for p in perms]
        report = G.check_group(s3)
        self.assertTrue(report.ok, msg=f"S_3 应是群：{report.explain()}")
        self.assertFalse(G.is_abelian(s3))
        witness = G.abelian_witness(s3)
        self.assertIsNotNone(witness)
        i, j, ij, ji = witness
        self.assertNotEqual(ij, ji)

    def test_shape_validation(self):
        with self.assertRaises(ValueError):
            G.check_group([])
        with self.assertRaises(ValueError):
            G.check_group([[0, 1], [1]])
        with self.assertRaises(ValueError):
            G.mul_units_table(1)
        with self.assertRaises(ValueError):
            G.add_table(0)


class TestSets(unittest.TestCase):
    def test_de_morgan(self):
        U = frozenset(range(10))
        A = frozenset({1, 2, 3, 4})
        B = frozenset({3, 4, 5, 6})
        self.assertEqual(S.difference(U, S.union(A, B)),
                         S.intersection(S.difference(U, A), S.difference(U, B)))
        self.assertEqual(S.difference(U, S.intersection(A, B)),
                         S.union(S.difference(U, A), S.difference(U, B)))

    def test_cardinality_formula(self):
        rng = random.Random(9)
        for _ in range(300):
            A = frozenset(rng.sample(range(30), rng.randrange(0, 15)))
            B = frozenset(rng.sample(range(30), rng.randrange(0, 15)))
            self.assertEqual(len(S.union(A, B)),
                             len(A) + len(B) - len(S.intersection(A, B)))

    def test_power_set(self):
        ps = S.power_set(frozenset({1, 2, 3}))
        self.assertEqual(len(ps), 8)                    # 23
        self.assertIn(frozenset(), ps)
        self.assertIn(frozenset({1, 2, 3}), ps)
        self.assertTrue(all(isinstance(x, frozenset) for x in ps))
        self.assertEqual(S.power_set(frozenset()), [frozenset()])
        ps4 = S.power_set(frozenset({1, 2, 3, 4}))
        self.assertEqual(len(ps4), 16)

    def test_cartesian(self):
        A = frozenset({1, 2})
        B = frozenset({"x", "y", "z"})
        prod = S.cartesian(A, B)
        self.assertEqual(len(prod), 6)                  # 2×3
        self.assertIn((1, "x"), prod)
        self.assertNotIn((1, "w"), prod)
        self.assertEqual(len(S.cartesian(frozenset(), B)), 0)
        self.assertEqual(len(S.cartesian(frozenset({1}), frozenset({1}))), 1)

    def test_inclusion_exclusion_vs_brute(self):
        rng = random.Random(11)
        for _ in range(300):
            k = rng.randrange(2, 5)
            family = [frozenset(rng.sample(range(20), rng.randrange(0, 8)))
                      for _ in range(k)]
            brute = len(frozenset().union(*family))
            self.assertEqual(S.inclusion_exclusion(family), brute, msg=f"{family}")

    def test_function_checks(self):
        D = frozenset({1, 2, 3})
        C = frozenset({1, 2, 3})
        rep = S.check_function({(1, 2), (2, 3), (3, 1)}, D, C)
        self.assertTrue(rep.bijective)
        rep = S.check_function({(1, 1), (1, 2), (2, 3), (3, 3)}, D, C)
        self.assertFalse(rep.is_function)
        self.assertTrue(any("多个输出" in r for r in rep.reasons))
        rep = S.check_function({(1, 1)}, D, C)
        self.assertFalse(rep.is_function)
        self.assertTrue(any("无定义" in r for r in rep.reasons))
        rep = S.check_function({(1, 9)}, frozenset({1}), C)
        self.assertFalse(rep.is_function)
        self.assertTrue(any("不在 D×C" in r for r in rep.reasons))
        rep = S.check_function({(1, 1), (2, 1), (3, 3)}, D, C)
        self.assertTrue(rep.is_function)
        self.assertFalse(rep.injective)
        self.assertFalse(rep.surjective)
        rep = S.check_function({(1, 1), (2, 2)}, frozenset({1, 2}), C)
        self.assertTrue(rep.injective)
        self.assertFalse(rep.surjective)                # 3 没有原像
        self.assertFalse(rep.bijective)

    def test_bijection_count_is_factorial(self):
        # 3→3 的全部 27 个"函数对"枚举：其中双射恰好 3! = 6 个（手算对账）
        D = frozenset({0, 1, 2})
        count = 0
        for a in range(3):
            for b in range(3):
                for c in range(3):
                    rep = S.check_function({(0, a), (1, b), (2, c)}, D, D)
                    if rep.bijective:
                        count += 1
        self.assertEqual(count, 6)


if __name__ == "__main__":
    unittest.main()
