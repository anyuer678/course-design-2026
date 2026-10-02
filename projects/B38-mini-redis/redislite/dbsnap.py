"""redislite/dbsnap.py —— 简化快照：版本魔数 + 校验和 + 原子写

课程要点（对应 docs/case-study.md 第 5 节）：
    - RDB 是"某一刻的全量镜像"：加载快、两次快照之间的写入会丢。我们不追求
      二进制兼容（格式是自定的），但把**工程要点**做全：
        版本行（拒绝未来/未知格式）、长度前缀（二进制安全）、
        校验和（坏一个字节必须报错而不是带病加载）、
        **原子写**（临时文件 + os.replace——崩在写一半不产生半个快照）。
    - 过期时刻存**绝对墙钟**：重启后仍然有效（配合 store 的墙钟语义）。
"""
from __future__ import annotations

import hashlib
import os
import pathlib

MAGIC = b"REDISLITE1"


class SnapshotError(Exception):
    """快照文件坏了/版本不对：message 是一句人话（不吞错、不带病启动）。"""


def _encode(entries: list[tuple[bytes, bytes, float | None]]) -> bytes:
    parts = [MAGIC, b"\n", str(len(entries)).encode("ascii"), b"\n"]
    for key, value, deadline in entries:
        parts.append(str(len(key)).encode("ascii"))
        parts.append(b"\n")
        parts.append(key)
        parts.append(str(len(value)).encode("ascii"))
        parts.append(b"\n")
        parts.append(value)
        if deadline is None:
            parts.append(b"0\n")
        else:
            parts.append(b"1\n")
            parts.append(repr(float(deadline)).encode("ascii"))
            parts.append(b"\n")
    payload = b"".join(parts)
    digest = hashlib.sha256(payload).hexdigest().encode("ascii")
    return payload + b"SHA256 " + digest + b"\n"


def save_snapshot(path, entries: list[tuple[bytes, bytes, float | None]]) -> int:
    """原子写：同目录临时文件 + fsync + os.replace。返回文件字节数。"""
    path = pathlib.Path(path)
    payload = _encode(entries)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return len(payload)


def load_snapshot(path) -> list[tuple[bytes, bytes, float | None]]:
    """读快照；版本/结构/校验和任何一项不过就抛 SnapshotError（带人话）。"""
    path = pathlib.Path(path)
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    if not lines or lines[0] != MAGIC:
        raise SnapshotError(f"不是 REDISLITE 快照（魔数不符）：{path}")
    # 找校验行：最后一行形如 b"SHA256 <64hex>"，之前是 payload
    if len(lines) < 3 or not lines[-2].startswith(b"SHA256 "):
        raise SnapshotError(f"快照缺少校验行：{path}")
    digest = lines[-2][7:]
    payload = raw[: len(raw) - len(lines[-2]) - 1]
    if hashlib.sha256(payload).hexdigest().encode("ascii") != digest:
        raise SnapshotError(f"快照校验和不符（文件被改坏过？）：{path}")
    # 解析 payload（此时已确认完整）
    body = payload[len(MAGIC) + 1:]
    try:
        count_line, rest = body.split(b"\n", 1)
        count = int(count_line)
    except ValueError as err:
        raise SnapshotError(f"快照头部坏了：{path}") from err
    entries: list[tuple[bytes, bytes, float | None]] = []
    for _ in range(count):
        try:
            klen_line, rest = rest.split(b"\n", 1)
            klen = int(klen_line)
            key, rest = rest[:klen], rest[klen:]
            vlen_line, rest = rest.split(b"\n", 1)
            vlen = int(vlen_line)
            value, rest = rest[:vlen], rest[vlen:]
            flag, rest = rest.split(b"\n", 1)
            if flag == b"0":
                deadline = None
            elif flag == b"1":
                dline, rest = rest.split(b"\n", 1)
                deadline = float(dline)
            else:
                raise ValueError("bad deadline flag")
        except (ValueError, IndexError) as err:
            raise SnapshotError(f"快照条目结构坏了：{path}") from err
        entries.append((key, value, deadline))
    if rest:
        raise SnapshotError(f"快照尾部有多余字节：{path}")
    return entries
