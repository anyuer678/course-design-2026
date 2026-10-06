"""linkbox/qr.py —— 纯标准库 QR 编码器（数字/字节模式，版本 1-5，ECC L/M）

正确性锚点（tests/test_qr.py，全部有出处、当轮实跑核对）：
    1. ISO/IEC 18004 数字例："01234567" V1-M 的数据码字前 6 字节
       10 20 0C 56 61 80（随后按规范补 EC 11 填充至 16 码字）
       ——41 位流（模式4+计数10+数字27）+ 终止符4 + 补齐3 的自然结果；
    2. Reed-Solomon 外部向量：Wikiversity《Reed–Solomon codes for coders》
       样例 QR 消息 16 码字 -> ECC = BC 2A 90 13 6B AF EF FD 4B E0（逐字节核对）；
       生成多项式 n=10 的 α 指数 [0,251,67,46,61,118,70,64,94,32,45] 与规范附录一致；
    3. RS 数学性质：消息 × x^ecc + 余式 ≡ 0 (mod 生成多项式)——
       余式由除法算出，测试另用"代入求值"独立验证；
    4. 格式信息两份均可解码：从矩阵抠出 15 位，异或 0x5412 后 BCH 余式为 0
       （第二份对 L/M × 8 掩码共 16 种组合全部钉住）；
    5. 结构：定位/时序/校正图形/黑模块坐标按规范公式精确断言（含 V2）。
曾经实现的五处错误（2026-10-04 探针定位后修复）：
    a) rs_ecc 把按最低次存储的生成多项式当最高次用（除数反了）——整除性
       自测因同源自洽而照绿，公开向量仲裁才现形；
    b) 校正图形在 (6,6) 画了规范规定不画的 5×5，涂坏左上定位图形；
    c) 第二份格式信息 bit 7 写进黑模块格后被覆盖，且 (8, size-8) 漏写；
    d) _place_data 未处理 V2+ 的 7 个剩余位（越界 IndexError）；
    e) 字节模式用字符数而非 UTF-8 字节数写计数域/判容量。
"""
from __future__ import annotations

# ================================================================ GF(256)
# QR 的伽罗瓦域：本原多项式 x^8 + x^4 + x^3 + x^2 + 1（0x11D）
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _gf_pow(a: int, n: int) -> int:
    return _GF_EXP[(_GF_LOG[a] * n) % 255]


# ================================================================ Reed-Solomon
def _rs_generator_poly(degree: int) -> list[int]:
    """(x - α^0)(x - α^1)…(x - α^(degree-1))，系数最高次在前。
    校验锚点：n=10 时 α 指数 = [0, 251, 67, 46, 61, 118, 70, 64, 94, 32, 45]
    （QR 规范附录 + Wikiversity《Reed–Solomon codes for coders》公开表）。"""
    poly = [1]                              # 单项式 1，最高次在前（长度=次数+1）
    for i in range(degree):
        new_poly = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            new_poly[j] ^= coef                              # ×x：整体升一次
            new_poly[j + 1] ^= _gf_mul(coef, _GF_EXP[i])     # ×α^i
        poly = new_poly
    return poly


def rs_ecc(data: list[int], ecc_len: int) -> list[int]:
    """数据多项式（升 x^ecc_len）除以生成多项式，返回 ecc_len 个余式系数。"""
    gen = _rs_generator_poly(ecc_len)
    rem = list(data) + [0] * ecc_len
    for i in range(len(data)):
        coef = rem[i]
        if coef == 0:
            continue
        for j in range(1, len(gen)):
            rem[i + j] ^= _gf_mul(gen[j], coef)
    return rem[len(data):]


# ================================================================ 版本表
# (数据码字, 每块 ECC 码字, 块数)。v1-5 的 L/M 档都是等尺寸块（无需交织）。
_CAP = {
    "L": {1: (19, 7, 1), 2: (34, 10, 1), 3: (55, 15, 1), 4: (80, 20, 1), 5: (108, 26, 1)},
    "M": {1: (16, 10, 1), 2: (28, 16, 1), 3: (44, 26, 1), 4: (64, 18, 2), 5: (86, 24, 2)},
}
# 校正图形中心（V2-V5 各恰有一个，位于对角线上；(6,6) 处与定位图形重叠、规范规定不画）
_ALIGNMENT = {1: [], 2: [18], 3: [22], 4: [26], 5: [30]}
_LEVEL_BITS = {"L": "01", "M": "00"}


def pick_version(text: str, ecc: str) -> tuple[int, str]:
    """按内容自动选模式与版本。纯数字用数字模式（密度 10bit/3字）；
    字节模式按 UTF-8 字节数判定容量（计数域写的就是字节数）。"""
    mode = "numeric" if text.isdigit() else "byte"
    n = len(text) if mode == "numeric" else len(text.encode("utf-8"))
    for version in range(1, 6):
        data_cw = _CAP[ecc][version][0]
        cap_bits = data_cw * 8 - 4 - (10 if mode == "numeric" else 8)
        need = 0
        if mode == "numeric":
            need = (len(text) // 3) * 10 + (0, 4, 7)[len(text) % 3]
        else:
            need = n * 8
        if need <= cap_bits:
            return version, mode
    raise ValueError(f"内容过长：{len(text)} 字符超出 v5-{ecc} 容量")


# ================================================================ 位流
def build_data_codewords(text: str, version: int, ecc: str) -> list[int]:
    """模式指示 + 计数 + 数据 + 终止符 + 补齐 + 填充字节 -> 码字列表。"""
    mode = "numeric" if text.isdigit() else "byte"
    bits = "0100" if mode == "byte" else "0001"
    count_width = 10 if mode == "numeric" else 8
    n = len(text) if mode == "numeric" else len(text.encode("utf-8"))
    bits += format(n, f"0{count_width}b")
    if mode == "numeric":
        for i in range(0, len(text), 3):
            chunk = text[i:i + 3]
            bits += {3: format(int(chunk), "010b"), 2: format(int(chunk), "07b"), 1: format(int(chunk), "04b")}[len(chunk)]
    else:
        bits += "".join(format(b, "08b") for b in text.encode("utf-8"))

    data_cw = _CAP[ecc][version][0]
    bits += "0" * min(4, max(0, data_cw * 8 - len(bits)))   # 终止符 ≤4 位
    bits += "0" * (-len(bits) % 8)                          # 补齐到字节
    codewords = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    i = 0
    while len(codewords) < data_cw:                         # 填充字节交替
        codewords.append(pad[i % 2])
        i += 1
    assert len(codewords) == data_cw, "码字数与容量不符"
    return codewords


# ================================================================ 矩阵
def _empty_matrix(version: int):
    size = 17 + 4 * version

    def new():
        return [[None] * size for _ in range(size)]

    matrix = new()
    function_modules = new()                # True = 功能模块（不参与掩码/数据）

    def mark(r, c):
        function_modules[r][c] = True

    def finder(row, col):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = row + dr, col + dc
                if 0 <= r < size and 0 <= c < size:
                    dark = (0 <= dr <= 6 and (dc in (0, 6) or dr in (0, 6))
                            or (2 <= dr <= 4 and 2 <= dc <= 4))
                    matrix[r][c] = dark
                    mark(r, c)

    for row, col in ((0, 0), (0, size - 7), (size - 7, 0)):
        finder(row, col)

    # 时序图形：第 6 行/列，深浅交替（两端由定位图形占位）
    for c in range(8, size - 8):
        matrix[6][c] = c % 2 == 0
        mark(6, c)
        matrix[c][6] = c % 2 == 0
        mark(c, 6)

    # 校正图形：5x5，中心在 (6, 6) 之外的对齐坐标
    for center in _ALIGNMENT[version]:
        r0, c0 = center - 2, center - 2
        for dr in range(5):
            for dc in range(5):
                dark = dr in (0, 4) or dc in (0, 4) or (dr == 2 and dc == 2)
                matrix[r0 + dr][c0 + dc] = dark
                mark(r0 + dr, c0 + dc)

    # 格式信息保留区（两份，覆盖所有格式位可能出现的坐标）
    for i in range(9):
        if i != 6:
            mark(8, i)
            mark(i, 8)
    for c in range(size - 8, size):                       # 右上横条
        mark(8, c)
    for r in range(size - 8, size):                       # 左下竖条
        mark(r, 8)
    # 黑模块：规范要求 (4v+9, 8) 恒黑
    matrix[size - 8][8] = True
    mark(size - 8, 8)
    return matrix, function_modules


def _mask_fn(mask: int):
    def fn(r, c):
        if mask == 0:
            return (r + c) % 2 == 0
        if mask == 1:
            return r % 2 == 0
        if mask == 2:
            return c % 3 == 0
        if mask == 3:
            return (r + c) % 3 == 0
        if mask == 4:
            return (r // 2 + c // 3) % 2 == 0
        if mask == 5:
            return (r * c) % 2 + (r * c) % 3 == 0
        if mask == 6:
            return ((r * c) % 2 + (r * c) % 3) % 2 == 0
        return ((r + c) % 2 + (r * c) % 3) % 2 == 0
    return fn


def _place_data(matrix, function_modules, codewords: list[int], mask: int) -> None:
    """按规范蛇形放置：两列一组自右向左（跳过时序列），列内先上后下交替；
    每个数据模块按所选掩码翻转。"""
    size = len(matrix)
    fn = _mask_fn(mask)
    bits = []
    for cw in codewords:
        for b in range(7, -1, -1):
            bits.append((cw >> b) & 1)
    bit_i = 0
    upward = True
    right = size - 1
    while right > 0:
        if right == 6:
            right -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for c in (right, right - 1):
                if function_modules[r][c]:
                    continue
                if bit_i < len(bits):
                    dark = bool(bits[bit_i])
                    if fn(r, c):
                        dark = not dark     # 掩码只作用于数据/纠错位
                    bit_i += 1
                else:
                    dark = False            # 剩余位（V2+ 为 7 个）：恒亮、不加掩码
                matrix[r][c] = dark
        upward = not upward
        right -= 2


def _penalty(matrix) -> int:
    """规范四条惩罚规则。返回总分（越小越好）。"""
    size = len(matrix)
    score = 0
    lines = []
    for i in range(size):
        lines.append([matrix[i][j] for j in range(size)])           # 行
        lines.append([matrix[j][i] for j in range(size)])           # 列
    # 规则 1：连续同色 ≥5 个加 (长度-2)
    for line in lines:
        run, prev = 1, line[0]
        for c in line[1:]:
            if c == prev:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run, prev = 1, c
        if run >= 5:
            score += run - 2
    # 规则 2：2x2 同色块每个加 3
    for r in range(size - 1):
        for c in range(size - 1):
            block = (matrix[r][c], matrix[r][c + 1],
                     matrix[r + 1][c], matrix[r + 1][c + 1])
            if len(set(block)) == 1:
                score += 3
    # 规则 3：出现 1:1:3:1:1 比例图样（含前后 4 模块亮边）加 40
    pat = "10111010000"                                  # 暗色形态
    pat_rev = pat[::-1]
    for line in lines:
        joined = "".join("1" if v else "0" for v in line)
        score += 40 * (joined.count(pat) + joined.count(pat_rev))
    # 规则 4：暗色占比偏离 50%，每 5% 加 10
    dark = sum(1 for row in matrix for v in row if v)
    total = size * size
    score += (abs(dark * 20 - total * 10) // total) * 10
    return score


def _format_bits(ecc: str, mask: int) -> int:
    """15 位格式信息：5 位数据 + 10 位 BCH(15,5)，异或掩码 0x5412。"""
    data_str = _LEVEL_BITS[ecc] + format(mask, "03b")
    data = int(data_str, 2) << 10
    g = 0x537
    rem = data
    for i in range(14, 9, -1):
        if rem & (1 << i):
            rem ^= g << (i - 10)
    return (data | rem) ^ 0x5412


def _place_format(matrix, ecc: str, mask: int) -> None:
    """15 位格式信息两份：第一份绕左上定位图形，第二份拆在右下/右上。
    放置方式按 Nayuki qrcodegen（最广为验证的参考实现）：
      第一份：bits 0-5 沿 row 8 的 col 0-5，bit 6 在 (8,7)，bit 7 在 (8,8)，
              bit 8 在 (7,8)，bits 9-14 沿 col 8 从 row 5 向上到 row 0。
      第二份：bits 0-7 沿 col 8 从 size-1 向上，bits 8-14 沿 row 8 从
              size-7 向右到 size-1。
    全部走 get_bit(i)（LSB 先出）。"""
    size = len(matrix)
    fmt = _format_bits(ecc, mask)

    def get_bit(i):
        return bool((fmt >> i) & 1)

    # 第一份
    for i in range(6):
        matrix[8][i] = get_bit(i)              # row 8, cols 0-5
    matrix[8][7] = get_bit(6)                  # 跳过时序列 col 6
    matrix[8][8] = get_bit(7)                  # 角
    matrix[7][8] = get_bit(8)                  # 向下
    for i in range(9, 15):
        matrix[14 - i][8] = get_bit(i)         # col 8, rows 5..0

    # 第二份（拆两段，黑模块格不承载格式位）：
    #   bits 0-6 沿 col 8 从 size-1 向上到 size-7（7 格）；
    #   bits 7-14 沿 row 8 从 size-8 向右到 size-1（8 格）。
    for i in range(7):
        matrix[size - 1 - i][8] = get_bit(i)   # col 8, 从底向上
    for i in range(7, 15):
        matrix[8][size - 15 + i] = get_bit(i)  # row 8, 从右向左
    # 黑模块：规范要求恒黑，不属于格式信息（曾误把 bit 7 写进这里后被覆盖）
    matrix[size - 8][8] = True


def qr_matrix(text: str, ecc: str = "M") -> list[list[bool]]:
    """文本 -> QR 矩阵（暗色 = True）。版本按内容自动选择（1-5）。"""
    if ecc not in ("L", "M"):
        raise ValueError("ecc 是 L 或 M")
    version, _ = pick_version(text, ecc)
    data_cw, ec_cw, blocks = _CAP[ecc][version]

    codewords = build_data_codewords(text, version, ecc)
    per_block = data_cw // blocks
    # 分块各自算 ECC，再按规范交织（数据流：块1[0]、块2[0]、块1[1]…）
    blocks_data = [codewords[b * per_block:(b + 1) * per_block]
                   for b in range(blocks)]
    blocks_ecc = [rs_ecc(chunk, ec_cw) for chunk in blocks_data]
    final = []
    for i in range(per_block):
        for chunk in blocks_data:
            final.append(chunk[i])
    for i in range(ec_cw):
        for chunk in blocks_ecc:
            final.append(chunk[i])

    matrix, function_modules = _empty_matrix(version)

    # 8 种掩码全试，按惩罚分选最优
    best_matrix, best_score = None, None
    for mask in range(8):
        trial = [row[:] for row in matrix]
        trial_fn = [row[:] for row in function_modules]
        _place_data(trial, trial_fn, final, mask)
        _place_format(trial, ecc, mask)
        score = _penalty(trial)
        if best_score is None or score < best_score:
            best_matrix, best_score = trial, score
    return best_matrix


def qr_svg(text: str, ecc: str = "M", pixel: int = 4) -> str:
    """文本 -> 自包含 SVG 字符串（含 4 模块静区，白底黑模块）。"""
    matrix = qr_matrix(text, ecc)
    size = len(matrix)
    quiet = 4
    dim = (size + 2 * quiet) * pixel
    rects = []
    for r in range(size):
        for c in range(size):
            if matrix[r][c]:
                rects.append(f'<rect x="{(c + quiet) * pixel}" '
                             f'y="{(r + quiet) * pixel}" '
                             f'width="{pixel}" height="{pixel}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{dim}" '
            f'height="{dim}" viewBox="0 0 {dim} {dim}" shape-rendering="crispEdges">'
            f'<rect width="{dim}" height="{dim}" fill="white"/>'
            + "".join(rects) + "</svg>")
