"""minidb/pager.py —— 页式快照文件：固定页、逐页校验和、双头槽位、代追加、回退

课程要点（数据库系统原理 · 持久性工程化，B41 候选①的落地）：
    - **页是存储的计量单位**：文件切成固定大小页，快照负载按页存放；页尾 8 字节
      （长度 + crc32）让"撕裂/坏页"当场可检——不检测就等着把损坏当数据读出来；
    - **双头槽位（固定偏移 0 / 4096）**：每次提交把新"代指针"写进非活动槽，
      写完 fsync——只要两个槽之一完好，就知道最近一次**完整提交**在哪；
    - **代（generation）追加不覆盖**：新快照永远写到文件末尾的新页上，
      旧代物理完好 → 新代页坏了可以**回退**到旧代（再由 WAL 重放追平）；
    - **写序**：数据页 → fsync → 头槽位 → fsync。任何一步崩溃，文件都停在一个
      自洽状态上；回收空间用**压实**（重写小文件 + 原子替换）。

文件布局：
    [0, 4096)       头槽位 A（JSON + crc，定长 4096，与 page_size 无关）
    [4096, 8192)    头槽位 B
    [8192, ...)     代的追加区：每个代 = 1 个代头页 + k 个数据页（页长 = page_size）
"""
from __future__ import annotations

import json
import os
import pathlib
import struct
import zlib

SLOT_BYTES = 4096                 # 头槽位固定 4 KiB（与数据页大小解耦）
HEADER_REGION = SLOT_BYTES * 2
SLOT_MAGIC = "MDBP"
GEN_MAGIC = "MDBG"
VERSION = 1
DEFAULT_PAGE_SIZE = 4096
_TRAILER = struct.Struct("<II")   # 数据页尾部：真实长度 + crc32


class PagerError(Exception):
    """页文件损坏/不完整：message 是一句人话（不静默、不吞错）。"""


def _crc(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _encode_record(obj: dict, total_bytes: int) -> bytes:
    """JSON 内容 + 换行 + 8 位十六进制 crc，补零到定长。"""
    content = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    blob = content + b"\n" + f"{_crc(content):08x}".encode("ascii")
    if len(blob) > total_bytes:
        raise PagerError(f"记录装不下：{len(blob)} > {total_bytes} 字节")
    return blob + b"\x00" * (total_bytes - len(blob))


def _decode_record(page: bytes) -> dict | None:
    """定长页 → dict；魔数/格式/crc 任一不过返回 None（调用方决定报错还是回退）。"""
    content, _, rest = page.partition(b"\n")
    if not content or len(rest) < 8:
        return None
    try:
        crc_hex = rest[:8].decode("ascii")
        obj = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if f"{_crc(content):08x}" != crc_hex:
        return None
    return obj


def _align_up(value: int, unit: int) -> int:
    return (value + unit - 1) // unit * unit


def _pages_for(payload_len: int, page_size: int) -> int:
    """负载需要的页数：每页 8 字节留给 trailer，所以按**容量**（页长-8）算。"""
    return max(1, (payload_len + page_size - 9) // (page_size - 8))


class PageFile:
    def __init__(self, path, page_size: int = DEFAULT_PAGE_SIZE,
                 waste_factor: float = 4.0):
        if page_size < 256:
            raise ValueError("page_size 至少 256（代头记录要装得下一页）")
        self.path = pathlib.Path(path)
        self.page_size = page_size
        self.waste_factor = waste_factor

    # ---------------------------------------------------------------- 读
    def _read_slots(self) -> tuple[list[dict], list[str]]:
        valid, warnings = [], []
        if not self.path.exists():
            return valid, warnings
        with open(self.path, "rb") as f:
            for idx in (0, 1):
                f.seek(idx * SLOT_BYTES)
                page = f.read(SLOT_BYTES)
                if len(page) < SLOT_BYTES:
                    warnings.append(f"头槽位 {idx} 缺失（文件不足 8192 字节）")
                    continue
                slot = _decode_record(page)
                if slot is None or slot.get("magic") != SLOT_MAGIC \
                        or slot.get("version") != VERSION:
                    warnings.append(f"头槽位 {idx} 无效（魔数/版本/crc 不符）")
                    continue
                valid.append({"slot": idx, **slot})
        valid.sort(key=lambda s: s["seq"], reverse=True)
        return valid, warnings

    def _read_generation(self, gen_offset: int, page_size: int, seq: int) -> bytes:
        if page_size < 64 or gen_offset < HEADER_REGION \
                or gen_offset % page_size != 0:
            raise PagerError(f"代指针不合法（offset={gen_offset}, page_size={page_size}）")
        with open(self.path, "rb") as f:
            f.seek(gen_offset)
            head_page = f.read(page_size)
            if len(head_page) < page_size:
                raise PagerError("代头页不完整")
            head = _decode_record(head_page)
            if head is None or head.get("magic") != GEN_MAGIC:
                raise PagerError("代头页 crc/魔数不符")
            if head.get("seq") != seq:
                raise PagerError(f"代头序 {head.get('seq')} 与指针 {seq} 不符")
            chunks = []
            for i in range(head["n_pages"]):
                page = f.read(head["page_size"])
                if len(page) < head["page_size"]:
                    raise PagerError(f"数据页 {i} 不完整（文件被截断？）")
                length, chunk_crc = _TRAILER.unpack(page[-8:])
                capacity = head["page_size"] - 8
                if length > capacity:
                    raise PagerError(f"数据页 {i} 长度域非法：{length}")
                chunk = page[:length]
                if _crc(chunk) != chunk_crc:
                    raise PagerError(f"数据页 {i} crc 不符（坏页）")
                chunks.append(chunk)
        payload = b"".join(chunks)
        if len(payload) != head["payload_len"]:
            raise PagerError(f"负载长度不符：{len(payload)} != {head['payload_len']}")
        if _crc(payload) != head["payload_crc"]:
            raise PagerError("负载整体 crc 不符")
        return payload

    def load(self) -> tuple[bytes | None, dict]:
        """读**最近一个完好代**的负载。返回 (payload|None, meta)。

        新代坏页 → 回退旧代（meta["fell_back"]=True，warnings 记录原因）；
        两代都不可用 → PagerError（拒绝带病打开）。
        """
        valid, warnings = self._read_slots()
        if not valid:
            if not self.path.exists():
                return None, {"seq": None, "warnings": [], "fell_back": False}
            # 头区全零 = 第一次提交还没完成：视为"没有快照"（已提交的都在 WAL 里，
            # 由调用方重放追回——这正是写前日志的意义）；非零却无效 = 真损坏，报错
            with open(self.path, "rb") as f:
                header_region = f.read(HEADER_REGION)
            if header_region == b"\x00" * HEADER_REGION:
                return None, {"seq": None, "warnings": ["头区全零（尚无已提交快照）"],
                              "fell_back": False}
            raise PagerError("页文件存在但两个头槽位都无效：" + "；".join(warnings))
        newest_seq = None
        for cand in valid:
            if newest_seq is None:
                newest_seq = cand["seq"]
            try:
                payload = self._read_generation(cand["gen_offset"],
                                                cand["page_size"], cand["seq"])
            except (PagerError, KeyError) as err:
                warnings.append(f"seq={cand['seq']} 的代不可用：{err}")
                continue
            return payload, {"seq": cand["seq"], "slot": cand["slot"],
                             "warnings": warnings,
                             "fell_back": cand["seq"] != newest_seq}
        raise PagerError("所有可读头槽位指向的代都无法恢复：" + "；".join(warnings))

    # ---------------------------------------------------------------- 写
    def _ensure_file(self) -> None:
        if not self.path.exists():
            with open(self.path, "wb") as f:
                f.write(b"\x00" * HEADER_REGION)

    def commit(self, payload: bytes) -> dict:
        """追加一个新代 + 切换头槽位（数据 fsync → 头 fsync）。"""
        self._ensure_file()
        valid, _ = self._read_slots()
        seq = (valid[0]["seq"] if valid else 0) + 1
        slot = 1 - valid[0]["slot"] if valid else 0
        file_size = self.path.stat().st_size
        gen_offset = _align_up(file_size, self.page_size)
        n_pages = _pages_for(len(payload), self.page_size)
        head = {"magic": GEN_MAGIC, "seq": seq, "page_size": self.page_size,
                "n_pages": n_pages, "payload_len": len(payload),
                "payload_crc": _crc(payload)}
        with open(self.path, "r+b") as f:
            if gen_offset > file_size:                  # 换页长时从 EOF 补零对齐
                f.seek(file_size)
                f.write(b"\x00" * (gen_offset - file_size))
            else:
                f.seek(gen_offset)
            f.write(_encode_record(head, self.page_size))
            for i in range(n_pages):
                chunk = payload[i * (self.page_size - 8):(i + 1) * (self.page_size - 8)]
                page = chunk + b"\x00" * (self.page_size - 8 - len(chunk)) \
                    + _TRAILER.pack(len(chunk), _crc(chunk))
                f.write(page)
            f.flush()
            os.fsync(f.fileno())                            # 数据先落盘
            f.seek(slot * SLOT_BYTES)
            f.write(_encode_record({"magic": SLOT_MAGIC, "version": VERSION,
                                    "seq": seq, "gen_offset": gen_offset,
                                    "page_size": self.page_size}, SLOT_BYTES))
            f.flush()
            os.fsync(f.fileno())                            # 头切换再落盘
        stats = {"seq": seq, "slot": slot, "n_pages": n_pages,
                 "data_bytes": n_pages * self.page_size,
                 "file_bytes": self.path.stat().st_size, "compacted": False}
        live_bytes = HEADER_REGION + (1 + n_pages) * self.page_size
        if stats["file_bytes"] > live_bytes * self.waste_factor:
            stats.update(self._compact(payload))
        return stats

    def _compact(self, payload: bytes) -> dict:
        """把"仅一个最新代"的小文件原子替换回来（旧代至此不可再回退——声明在案）。"""
        tmp = self.path.with_name(self.path.name + ".compact")
        fresh = PageFile(tmp, self.page_size, self.waste_factor)
        fresh._ensure_file()
        head = {"magic": GEN_MAGIC, "seq": 1, "page_size": self.page_size,
                "n_pages": _pages_for(len(payload), self.page_size),
                "payload_len": len(payload), "payload_crc": _crc(payload)}
        with open(tmp, "r+b") as f:
            f.seek(HEADER_REGION)
            f.write(_encode_record(head, self.page_size))
            for i in range(head["n_pages"]):
                chunk = payload[i * (self.page_size - 8):(i + 1) * (self.page_size - 8)]
                page = chunk + b"\x00" * (self.page_size - 8 - len(chunk)) \
                    + _TRAILER.pack(len(chunk), _crc(chunk))
                f.write(page)
            f.flush()
            os.fsync(f.fileno())
            f.seek(0)
            f.write(_encode_record({"magic": SLOT_MAGIC, "version": VERSION,
                                    "seq": 1, "gen_offset": HEADER_REGION,
                                    "page_size": self.page_size}, SLOT_BYTES))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        return {"compacted": True, "file_bytes": self.path.stat().st_size}
