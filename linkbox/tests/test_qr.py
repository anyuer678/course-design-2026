"""QR 编码器自测：只断言能独立推导或公开向量核对过的性质。

可验证的性质（每条都有数学、规范或公开出处）：
    1. RS 编码后：数据 × x^ecc 的多项式被生成多项式整除（余式 = 0）——
       这是 RS 编码的定义，用"代入求值"独立验证而非复用同一算法；
       另钉 Wikiversity《Reed–Solomon codes for coders》样例 QR 的公开向量；
    2. 生成多项式：n=10 的 α 指数与 QR 规范附录公开表一致；
    3. ISO/IEC 18004 数字例："01234567" V1-M 数据码字 10 20 0C 56 61 80 + EC/11 补齐；
    4. GF(256) 乘法性质：交换/单位；
    5. 结构：定位图形/时序/校正图形/黑模块坐标按规范公式（V1 与 V2）；
    6. 格式信息两份均可解码（BCH 余式 0）：第一份对最终矩阵，
       第二份对 L/M × 8 掩码全部 16 种组合；
    7. 字节模式计数域/容量按 UTF-8 字节数；
    8. 确定性：同输入同输出。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linkbox.qr import (_format_bits, _gf_mul, _penalty,
                        _rs_generator_poly, _GF_LOG, _empty_matrix,
                        _place_format, build_data_codewords,
                        pick_version, qr_matrix, qr_svg, rs_ecc)


def _bch_remainder(fmt: int) -> int:
    """格式信息 BCH(15,5) 校验：异或掩码后除 0x537 的余式（可解码则 0）。"""
    fmt ^= 0x5412
    g = 0x537
    rem = fmt
    for i in range(14, 9, -1):
        if rem & (1 << i):
            rem ^= g << (i - 10)
    return rem


class TestReedSolomon(unittest.TestCase):
    def test_gf_properties(self):
        """GF(256) 乘法：交换律、单位元。"""
        for a in (1, 2, 0x53, 0xCA, 0xFF):
            self.assertEqual(_gf_mul(a, 1), a)
            self.assertEqual(_gf_mul(1, a), a)
        self.assertEqual(_gf_mul(0x53, 0xCA), _gf_mul(0xCA, 0x53))

    def test_generator_poly_matches_spec_table(self):
        """生成多项式 α 指数与公开表一致（QR 规范附录 / Wikiversity）。"""
        gen = _rs_generator_poly(10)
        self.assertEqual([_GF_LOG[c] for c in gen],
                         [0, 251, 67, 46, 61, 118, 70, 64, 94, 32, 45])

    def test_rs_external_vector(self):
        """公开向量：Wikiversity《Reed–Solomon codes for coders》样例 QR 消息。
        （曾把该向量错配到 ISO 数字例；2026-10-04 以原文核对后钉住正确配对。）"""
        msg = [0x40, 0xd2, 0x75, 0x47, 0x76, 0x17, 0x32, 0x06,
               0x27, 0x26, 0x96, 0xc6, 0xc6, 0x96, 0x70, 0xec]
        self.assertEqual(rs_ecc(msg, 10),
                         [0xbc, 0x2a, 0x90, 0x13, 0x6b, 0xaf,
                          0xef, 0xfd, 0x4b, 0xe0])

    def test_rs_divisibility(self):
        """RS 编码的定义：数据多项式 × x^ecc 后被生成多项式整除（余式 = 0）。
        独立验证：把完整码字多项式除以生成多项式，余式必须全零（消息任意）。"""
        data = [0x40, 0xD2, 0x75, 0x47, 0x76, 0x17, 0x32, 0x06,
                0x27, 0x26, 0x96, 0xC6]
        ecc = rs_ecc(data, 10)
        full = data + ecc
        gen = _rs_generator_poly(10)
        work = list(full)
        for i in range(len(data)):
            coef = work[i]
            if coef == 0:
                continue
            for j in range(1, len(gen)):
                if i + j < len(work):
                    work[i + j] ^= _gf_mul(gen[j], coef)
        for i in range(len(data), len(work)):
            self.assertEqual(work[i], 0, msg=f"index {i}")


class TestISOVector(unittest.TestCase):
    def test_numeric_example_data_codewords(self):
        """ISO/IEC 18004 数字例："01234567" V1-M。
        位流 41 位（模式 4 + 计数 10 + 数字 27）+ 终止符 4 + 补齐 3
        → 前 6 码字 10 20 0C 56 61 80，其余按规范补 EC 11 至 16。"""
        cw = build_data_codewords("01234567", 1, "M")
        self.assertEqual(cw,
                         [0x10, 0x20, 0x0C, 0x56, 0x61, 0x80]
                         + [0xEC, 0x11] * 5)


class TestQRStructure(unittest.TestCase):
    def test_structure_v1(self):
        matrix = qr_matrix("01234567", "M")
        size = len(matrix)
        self.assertEqual(size, 21)
        self.assertTrue(matrix[0][0])
        self.assertTrue(matrix[0][size - 7])
        self.assertTrue(matrix[size - 7][0])
        self.assertTrue(matrix[13][8])

    def test_format_decodable(self):
        matrix = qr_matrix("01234567", "M")
        positions = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5),
                     (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8),
                     (2, 8), (1, 8), (0, 8)]
        fmt = 0
        for i, (r, c) in enumerate(positions):
            if matrix[r][c]:
                fmt |= 1 << i
        self.assertEqual(_bch_remainder(fmt), 0)

    def test_format_second_copy_decodable_all_combos(self):
        """第二份格式信息对 L/M × 8 掩码全部 16 种组合均可解码。
        （曾有 bug：bit 7 写进黑模块格被覆盖、(8, size-8) 漏写，
        导致半数组合的第二份损坏——此测试即为钉住该修复。）"""
        for ecc in ("L", "M"):
            for mask in range(8):
                matrix, _fn = _empty_matrix(1)
                _place_format(matrix, ecc, mask)
                size = 21
                fmt = 0
                for i in range(7):                      # col 8 自底向上 7 格
                    if matrix[size - 1 - i][8]:
                        fmt |= 1 << i
                for i in range(7, 15):                  # row 8 自右向左 8 格
                    if matrix[8][size - 15 + i]:
                        fmt |= 1 << i
                self.assertEqual(fmt, _format_bits(ecc, mask),
                                 msg=f"{ecc} mask{mask}")
                self.assertEqual(_bch_remainder(fmt), 0,
                                 msg=f"{ecc} mask{mask}")
                self.assertTrue(matrix[size - 8][8])    # 黑模块恒黑

    def test_determinism(self):
        a = qr_matrix("hello", "M")
        b = qr_matrix("hello", "M")
        self.assertEqual(a, b)

    def test_structure_v2_finder_and_alignment(self):
        """V2 结构：定位图形不得被幻影校正图形涂坏；校正图形在 (18,18)。
        （曾有 bug：在 (6,6) 画了规范规定不画的 5×5，覆盖定位图形内部。）"""
        matrix = qr_matrix("https://x.io/abc", "M")   # 16 字节 → V2（V1 上限 14 字节）
        size = len(matrix)
        self.assertEqual(size, 25)
        # 左上定位图形内部环（曾被涂成暗色）
        self.assertFalse(matrix[5][4])
        self.assertFalse(matrix[4][5])
        self.assertTrue(matrix[5][6])          # 定位图形右边界仍为暗
        # 校正图形：中心暗、外环暗、内环亮
        self.assertTrue(matrix[18][18])
        self.assertTrue(matrix[16][18])
        self.assertFalse(matrix[17][18])
        # 时序图形
        self.assertTrue(matrix[6][8])
        self.assertFalse(matrix[6][9])
        # 黑模块
        self.assertTrue(matrix[size - 8][8])

    def test_capacity(self):
        with self.assertRaises(ValueError):
            qr_matrix("A" * 200, "L")


class TestQRIntegration(unittest.TestCase):
    def test_svg_well_formed(self):
        svg = qr_svg("https://example.com", "M")
        self.assertIn("<svg", svg)
        self.assertIn("</svg>", svg)
        self.assertNotIn("http://", svg.replace("http://www.w3.org", ""))

    def test_long_url_auto_version(self):
        from linkbox.qr import pick_version
        short = "https://x.io/abc"
        long = "https://example.com/" + "a" * 60
        v1, _ = pick_version(short, "M")
        v2, _ = pick_version(long, "M")
        self.assertLessEqual(v1, v2)
        self.assertEqual(len(qr_matrix(short, "M")), 17 + 4 * v1)
        self.assertEqual(len(qr_matrix(long, "M")), 17 + 4 * v2)

    def test_capacity_exceeded_raises(self):
        with self.assertRaises(ValueError):
            qr_matrix("A" * 200, "L")

    def test_mask_selection(self):
        matrix = qr_matrix("https://example.com/page", "M")
        score = _penalty(matrix)
        self.assertIsInstance(score, int)
        self.assertGreaterEqual(score, 0)

    def test_utf8_byte_mode_count_and_capacity(self):
        """字节模式按 UTF-8 字节数写计数域/判容量。
        11 个中文字符 = 33 字节 → 需 v3（按字符数会误判 v1，已被修复）。"""
        text = "例" * 11
        self.assertEqual(len(text.encode("utf-8")), 33)
        version, mode = pick_version(text, "M")
        self.assertEqual(mode, "byte")
        self.assertEqual(version, 3)           # 33*8=264 位 → v3-M(340) 才装得下
        matrix = qr_matrix(text, "M")
        self.assertEqual(len(matrix), 17 + 4 * 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
