"""sec32/traversal.py —— 路径穿越：静态文件服务的边界是"算出来的"还是"字符串比出来的"。

课程概念：
    Web 服务器把一个**用户可控的字符串**当成"相对 root 的路径"去打开文件。
    危险的不是字符串里有点点，而是"字符串 → 真实位置"这一步由谁决定：
    如果决定权在文件系统（`join` 之后直接 `open`），`..` 就会被**解析**成父目录；
    如果决定权在程序（先解析、再判定、后打开），越界就发生在打开之前，可以拦住。

三种写法，全部实测（判定列是**执行出来的**，不是我猜的）：
    `serve_join`      最原始的 `root / user` 直接读 ⇒ 越界。
    `serve_blacklist` 只拦 `".." in user` 字符串 ⇒ 漏掉百分号编码、绝对路径、
                      Windows 反斜杠分隔符——黑名单的经典失败方式。
    `serve_prefix`    解析之后用 `str(p).startswith(str(root))` 比前缀 ⇒
                      **兄弟目录** `static_evil` 的绝对路径以 `static` 开头，
                      前缀检查通过，文件在 root 之外。这一条是真实代码里最常见的错法。
    `serve_guarded`   修复版：解码一次并拒绝残留编码 ⇒ 拒绝 NUL/控制字符 ⇒
                      拒绝绝对形式（前导分隔符、盘符、UNC）⇒ 按两种分隔符切段并拒绝
                      `..` ⇒ `resolve()` 之后要求 `is_relative_to(root)`。

Windows 特有的坑（本机实测，写在 CASES 表里，不靠 Linux 教程的结论）：
    尾点/尾空格会被 OS **忽略**（`ok.txt.` 打开的是 `ok.txt`），所以"字符串不同就是不同文件"
    在 Windows 上不成立；`is_relative_to` 在 Windows 上**大小写无关**，所以大小写变换
    打不穿它；`os.symlink` 在本机不需要管理员权限就能建，软链指向 root 外时
    `resolve()` 会把链跟出去 ⇒ 判定失败 ⇒ 被拦（代价：不能用软链把 root 外的资源发布出来）。
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import urllib.parse


class TraversalError(ValueError):
    """拒绝某个路径请求。`reason` 会原样进入判定表，所以每条都要能解释为什么拒。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
        self.verdict = "REJECTED"


SEPARATORS = ("/", "\\")
OUTSIDE_SENTINEL = "OUTSIDE-SECRET"
INSIDE_SENTINEL = "PUBLIC"


def make_tree(base: pathlib.Path | None = None) -> dict:
    """搭一个可复现的小目录树：root 里有公开文件和一个指向 root 外的软链（能建的话）。

    返回 {"root": …, "outside_file": …, "sibling_root": …, "symlink": … or None}。
    """
    base = base or pathlib.Path(tempfile.mkdtemp(prefix="b32-traversal-"))
    root = base / "static"
    root.mkdir(parents=True, exist_ok=True)
    (root / "ok.txt").write_text(INSIDE_SENTINEL, encoding="utf-8")
    (root / "sub").mkdir(exist_ok=True)
    (root / "sub" / "deep.txt").write_text(INSIDE_SENTINEL + "-DEEP", encoding="utf-8")
    outside = base / "outside.txt"
    outside.write_text(OUTSIDE_SENTINEL, encoding="utf-8")
    sibling = base / "static_evil"
    sibling.mkdir(exist_ok=True)
    (sibling / "s.txt").write_text(OUTSIDE_SENTINEL + "-SIBLING", encoding="utf-8")
    link = None
    try:
        link = root / "linkdir"
        os.symlink(str(base), str(link), target_is_directory=True)
    except OSError:
        link = None
    return {"base": base, "root": root, "outside_file": outside,
            "sibling_root": sibling, "symlink": link}


# ---------------------------------------------------------------- 漏洞写法
def serve_join(root: pathlib.Path, user_path: str) -> str:
    """最原始：join 完直接读。`..` 由文件系统解析。"""
    return (root / user_path).read_text(encoding="utf-8")


def serve_blacklist(root: pathlib.Path, user_path: str) -> str:
    """黑名单只盯字面 `..`。"""
    if ".." in user_path:
        raise TraversalError("黑名单命中：字符串里含有 ..")
    return (root / user_path).read_text(encoding="utf-8")


def serve_prefix(root: pathlib.Path, user_path: str) -> str:
    """解析了，但用**字符串前缀**判定归属——兄弟目录 `static_evil` 以 `static` 开头。"""
    target = (root / user_path).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise TraversalError("前缀检查未通过")
    return target.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 修复写法
def decode_once(user_path: str) -> str:
    """解码**恰好一次**；若结果里仍有百分号编码残留就拒绝。

    为什么要拒绝而不是再解一次：解两次是"双重编码"的入口（`%252e%252e%252f`），
    而"解几次"取决于上游有没有已经解过——这是**假设**，不是保证。
    这里选择拒绝，并让 CASES 表把标准库的实际解码行为记成参照数据。
    """
    decoded = urllib.parse.unquote(user_path, errors="strict")
    if urllib.parse.unquote(decoded) != decoded:
        raise TraversalError("解码后仍有百分号编码残留（疑似双重编码）")
    return decoded


def _reject_nul_and_control(text: str) -> None:
    for i, ch in enumerate(text):
        if ch == "\x00":
            raise TraversalError(f"第 {i + 1} 个字符是 NUL；Python 的 open 会直接抛错")
        if ord(ch) < 32:
            raise TraversalError(f"第 {i + 1} 个字符是控制字符 U+{ord(ch):04X}")


def _reject_absolute(text: str) -> None:
    if text.startswith(SEPARATORS) or text.startswith("//"):
        raise TraversalError("绝对路径：前导分隔符")
    if len(text) >= 2 and text[1] == ":":
        raise TraversalError(f"绝对路径：带盘符 {text[:2]!r}")
    if text.startswith("\\\\"):
        raise TraversalError("绝对路径：UNC 共享名")


def _segments(text: str) -> list[str]:
    parts = []
    for chunk in text.replace("\\", "/").split("/"):
        if chunk in ("", "."):
            continue
        if chunk == "..":
            raise TraversalError("切段后出现 .. 段")
        parts.append(chunk)
    if not parts:
        raise TraversalError("切段后没有留下任何路径成分")
    return parts


def _reject_win_normalization(parts: list[str]) -> None:
    """Windows 会吃掉尾点与尾空格，所以"看起来不同"的两个字符串指向同一个文件。

    这不是越界，而是**判定与执行不一致**：任何按字符串做的白名单都会被它绕过，
    因此这里直接拒绝这类成分。
    """
    for name in parts:
        if name.endswith((".", " ")):
            raise TraversalError(f"成分 {name!r} 以尾点/尾空格结尾（Windows 会忽略）")


def serve_guarded(root: pathlib.Path, user_path: str) -> str:
    """修复版：先判定，后打开；判定用的是解析后的真实位置。"""
    _reject_nul_and_control(user_path)
    text = decode_once(user_path)
    _reject_nul_and_control(text)
    _reject_absolute(text)
    parts = _segments(text)
    _reject_win_normalization(parts)
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root.resolve()):
        raise TraversalError(f"resolve 之后落在 root 之外：{target}")
    if not target.is_file():
        err = TraversalError("目标不是普通文件（或不存在）")
        err.verdict = "NOT_FOUND"
        raise err
    return target.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 判定表
def classify(handler, root: pathlib.Path, user_path: str) -> dict:
    """真跑一次，把结果分成 ESCAPED / SERVED_INSIDE / REJECTED / NOT_FOUND / ERROR。

    分类依据是**返回内容里有没有越界哨兵**，不是异常名字——
    读到了 root 外的东西才算越界，抛错只是它的一种表现形式。
    """
    try:
        body = handler(root, user_path)
    except TraversalError as exc:
        return {"verdict": exc.verdict, "detail": exc.reason}
    except (ValueError, OSError) as exc:
        return {"verdict": "ERROR", "detail": f"{type(exc).__name__}: {exc}"}
    if OUTSIDE_SENTINEL in body:
        return {"verdict": "ESCAPED", "detail": body}
    return {"verdict": "SERVED_INSIDE", "detail": body}


# 载荷表。判定列是**本机实测**跑出来的，不是查资料查来的。
# `{outside}` 与 `{sibling}` 由临时目录现场填进去——绝对路径载荷必须指向真实存在的位置。
CASES = [
    ("正常文件", "ok.txt"),
    ("正常子目录", "sub/deep.txt"),
    ("相对穿越", "../outside.txt"),
    ("反斜杠穿越", "..\\outside.txt"),
    ("多级穿越", "sub/../../outside.txt"),
    ("百分号编码的点", "%2e%2e/outside.txt"),
    ("百分号编码的斜杠", "..%2foutside.txt"),
    ("双重编码", "%252e%252e%252foutside.txt"),
    ("绝对路径（指向 root 外）", "{outside}"),
    ("兄弟目录绝对路径（前缀检查的靶）", "{sibling}"),
    ("NUL 截断", "ok.txt\x00.txt"),
    ("尾点（Windows 会忽略）", "ok.txt."),
    ("大小写变形", "OK.TXT"),
    ("软链越界", "linkdir/outside.txt"),
    ("URL 编码的空格名", "ok%20.txt"),
]

HANDLERS = (("join", serve_join), ("blacklist", serve_blacklist),
            ("prefix", serve_prefix), ("guarded", serve_guarded))


def build_case_rows(tree: dict) -> list[dict]:
    """把 CASES 逐条喂给四种写法，产出判定表。"""
    root, outside, sibling = tree["root"], tree["outside_file"], tree["sibling_root"]
    can_symlink = tree["symlink"] is not None
    rows = []
    for name, template in CASES:
        payload = template.format(outside=str(outside),
                                  sibling=str(sibling / "s.txt"))
        if name == "软链越界" and not can_symlink:
            rows.append({"name": name, "payload": payload,
                         "skipped": "本机建不出软链（权限或文件系统限制）"})
            continue
        row = {"name": name, "payload": payload}
        for label, handler in HANDLERS:
            row[label] = classify(handler, root, payload)
        rows.append(row)
    return rows


def stdlib_reference() -> dict:
    """标准库在这些载荷上的**实际行为**，作为分歧表的参照列（不是我的判断）。"""
    return {
        "unquote_2e2e2f": urllib.parse.unquote("%2e%2e%2f"),
        "unquote_double_252e": urllib.parse.unquote("%252e%252e%252f"),
        "unquote_twice_252e": urllib.parse.unquote(
            urllib.parse.unquote("%252e%252e%252f")),
        "unquote_overlong_c0af": repr(urllib.parse.unquote("%c0%af")),
        "unquote_fullwidth_solidus": repr(urllib.parse.unquote("%EF%BC%8F")),
        "path_plus_absolute": str(pathlib.Path("C:/web/static") / "C:/other/x.txt"),
        "is_relative_to_case_flip": pathlib.Path(
            str(pathlib.Path.cwd()).upper()).is_relative_to(pathlib.Path.cwd()),
        "plus_in_unquote": urllib.parse.unquote("a+b"),
        "unquote_plus": urllib.parse.unquote_plus("a+b"),
    }
