"""tests/test_durability.py —— B10 持久性工程化扩展自测（B41 候选①，页式快照 + fsync）

纪律（与本仓库其它轮一致）：
  1. 崩溃用**真子进程硬退**（os._exit）模拟，不是"同一进程里再开一个 Engine"——
     后者只能证明"文件被写过"，证明不了"提交返回时落了盘"；
  2. 坏页/坏头槽位用**逐字节翻转**构造，恢复层要么正确回退、要么响亮报错，
     不允许静默带病打开（负面自证）；
  3. LSN 边界（快照与 WAL 的交界窗口）用"把 WAL 文件留回去"来精确复现。
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minidb.engine import Engine                       # noqa: E402
from minidb.pager import (HEADER_REGION, PageFile,     # noqa: E402
                          PagerError, SLOT_BYTES)


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b10dur-{name}-"))
    if str(base.resolve()).lower().startswith(str(ROOT.parent.parent.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


def flip_byte(path: pathlib.Path, offset: int) -> None:
    with open(path, "r+b") as f:
        f.seek(offset)
        old = f.read(1)
        f.seek(offset)
        f.write(bytes([old[0] ^ 0xFF]))


CHILD = """
import os, sys
sys.path.insert(0, sys.argv[1])
from minidb.engine import Engine
db = sys.argv[2]
eng = Engine(db, durable=True)
eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
eng.execute("INSERT INTO t VALUES (1, 'committed'), (2, 'also')")
eng.execute("BEGIN")
eng.execute("INSERT INTO t VALUES (3, 'txn')")
eng.execute("COMMIT")
if os.environ.get("ALSO_UNCOMMITTED") == "1":
    eng.execute("BEGIN")
    eng.execute("INSERT INTO t VALUES (99, 'uncommitted')")
os._exit(0)          # 硬退：不析构、不 CHECKPOINT
"""


def run_child(db: pathlib.Path, uncommitted: bool = False) -> None:
    env = dict(os.environ)
    env["ALSO_UNCOMMITTED"] = "1" if uncommitted else "0"
    proc = subprocess.run([sys.executable, "-c", CHILD, str(ROOT), str(db)],
                          capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise AssertionError(f"子进程失败：{proc.returncode}\n{proc.stderr[-800:]}")


class TestPageFile(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp("pager")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / "db.pages"

    def test_roundtrip_small(self):
        pf = PageFile(self.path, page_size=256)
        stats = pf.commit(b"hello")
        self.assertEqual(stats["seq"], 1)
        self.assertEqual(stats["n_pages"], 1)
        payload, meta = pf.load()
        self.assertEqual(payload, b"hello")
        self.assertEqual(meta["seq"], 1)
        self.assertFalse(meta["fell_back"])

    def test_roundtrip_multi_page(self):
        payload = bytes(range(256)) * 12                  # 3072 字节
        pf = PageFile(self.path, page_size=256)
        stats = pf.commit(payload)
        self.assertEqual(stats["n_pages"], len(payload) // 248 + 1)
        back, _ = pf.load()
        self.assertEqual(back, payload)

    def test_slots_alternate(self):
        pf = PageFile(self.path, page_size=256)
        first = pf.commit(b"one")
        second = pf.commit(b"two")
        self.assertEqual((first["slot"], second["slot"]), (0, 1))
        payload, meta = pf.load()
        self.assertEqual((payload, meta["seq"], meta["slot"]), (b"two", 2, 1))
        slots, warnings = pf._read_slots()
        self.assertEqual([s["seq"] for s in slots], [2, 1])   # 两个槽位都能读

    def test_corrupt_newest_page_falls_back_to_previous_generation(self):
        pf = PageFile(self.path, page_size=256)
        pf.commit(b"generation-one")
        stats = pf.commit(b"generation-two")
        slots, _ = pf._read_slots()
        newest = slots[0]
        self.assertEqual(newest["seq"], stats["seq"])
        flip_byte(self.path, newest["gen_offset"] + 256 + 5)  # 打坏新代第一个数据页
        payload, meta = pf.load()
        self.assertEqual(payload, b"generation-one")
        self.assertTrue(meta["fell_back"])
        self.assertTrue(any("不可用" in w for w in meta["warnings"]))

    def test_corrupt_newest_slot_uses_other_slot(self):
        pf = PageFile(self.path, page_size=256)
        pf.commit(b"old")
        second = pf.commit(b"new")
        flip_byte(self.path, second["slot"] * SLOT_BYTES + 12)
        payload, meta = pf.load()
        self.assertEqual(payload, b"old")
        self.assertEqual(meta["seq"], 1)
        self.assertTrue(any("头槽位" in w for w in meta["warnings"]))

    def test_single_generation_corruption_raises(self):
        pf = PageFile(self.path, page_size=256)
        pf.commit(b"only")
        flip_byte(self.path, HEADER_REGION + 256 + 3)
        with self.assertRaises(PagerError):
            pf.load()                                     # 没有旧代可退：必须响亮报错

    def test_both_slots_corrupt_raises(self):
        pf = PageFile(self.path, page_size=256)
        pf.commit(b"x")
        flip_byte(self.path, 12)
        flip_byte(self.path, SLOT_BYTES + 12)
        with self.assertRaises(PagerError) as ctx:
            pf.load()
        self.assertIn("头槽位", str(ctx.exception))

    def test_zero_header_region_is_no_snapshot(self):
        self.path.write_bytes(b"\x00" * HEADER_REGION)    # 第一次提交中途崩溃的残留
        payload, meta = PageFile(self.path, page_size=256).load()
        self.assertIsNone(payload)                        # 视为"尚无快照"，由 WAL 重放追回
        self.assertTrue(meta["warnings"])

    def test_compaction_bounds_the_file(self):
        pf = PageFile(self.path, page_size=256, waste_factor=1.05)
        compacted = False
        for i in range(20):
            stats = pf.commit(f"payload-{i}".encode())
            compacted = compacted or stats["compacted"]
        self.assertTrue(compacted, "浪费超过倍数阈值时应触发压实")
        payload, meta = pf.load()
        self.assertEqual(payload, b"payload-19")
        self.assertLess(self.path.stat().st_size, HEADER_REGION + 256 * 4)

    def test_page_size_can_change_between_opens(self):
        PageFile(self.path, page_size=256).commit(b"tiny-pages")
        free = PageFile(self.path, page_size=4096)        # 用另一页长打开
        payload, _ = free.load()
        self.assertEqual(payload, b"tiny-pages")          # 读按代自描述
        free.commit(b"larger-pages-now")
        payload, meta = free.load()
        self.assertEqual((payload, meta["seq"]), (b"larger-pages-now", 2))


class TestEngineDurability(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp("eng")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = self.tmp / "db"

    def ids(self) -> list[int]:
        eng = Engine(self.db)
        eng.verbose = False
        return [r["id"] for r in eng.execute("SELECT id FROM t ORDER BY id")]

    def test_committed_rows_survive_hard_exit(self):
        run_child(self.db)                                # 子进程提交后立刻硬退
        self.assertEqual(self.ids(), [1, 2, 3])           # 已提交的一条不少

    def test_uncommitted_rows_lost_but_committed_kept(self):
        run_child(self.db, uncommitted=True)
        self.assertEqual(self.ids(), [1, 2, 3])           # 99 号未提交，必须不在

    def test_crash_between_head_switch_and_wal_clear_no_double_apply(self):
        eng = Engine(self.db)
        eng.verbose = False
        eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
        eng.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c')")
        eng.execute("CHECKPOINT")
        eng.execute("INSERT INTO t VALUES (4, 'd')")      # 只进 WAL
        wal_backup = (self.db.parent / "db.wal").read_bytes()

        eng2 = Engine(self.db)
        eng2.verbose = False
        eng2.execute("CHECKPOINT")                        # 新快照已包含 4 号（lsn 分界）
        (self.db.parent / "db.wal").write_bytes(wal_backup)   # 模拟："删 WAL"没来得及发生

        self.assertEqual(self.ids(), [1, 2, 3, 4])        # 重放按 lsn 跳过，不双放
        reopened = Engine(self.db)
        reopened.verbose = False
        reopened.execute("INSERT INTO t VALUES (5, 'e')")
        self.assertEqual(self.ids(), [1, 2, 3, 4, 5])     # 恢复后还能继续写

    def test_checkpoint_orders_fsync_then_removes_wal(self):
        eng = Engine(self.db)
        eng.verbose = False
        eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
        eng.execute("INSERT INTO t VALUES (1, 'a')")
        self.assertTrue((self.db.parent / "db.wal").exists())
        eng.execute("CHECKPOINT")
        self.assertFalse((self.db.parent / "db.wal").exists())    # 头落盘后才删 WAL
        stats = eng.last_checkpoint_stats
        self.assertGreaterEqual(stats["n_pages"], 1)
        self.assertGreaterEqual(stats["file_bytes"], HEADER_REGION)
        reopened = Engine(self.db)
        reopened.verbose = False
        self.assertEqual([r["id"] for r in reopened.execute("SELECT id FROM t")], [1])

    def test_wal_entries_carry_monotonic_lsn(self):
        eng = Engine(self.db)
        eng.verbose = False
        eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
        eng.execute("INSERT INTO t VALUES (1, 'a')")
        lines = (self.db.parent / "db.wal").read_text(encoding="utf-8").splitlines()
        lsns = [json.loads(line)["lsn"] for line in lines]
        self.assertEqual(lsns, sorted(lsns))
        self.assertEqual(len(set(lsns)), len(lsns))

    def test_durable_flag_off_still_reads_back_in_process(self):
        eng = Engine(self.db, durable=False)              # 对照臂：功能等价、不含 fsync
        eng.verbose = False
        eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
        eng.execute("INSERT INTO t VALUES (7, 'x')")
        reopened = Engine(self.db, durable=False)
        reopened.verbose = False
        self.assertEqual([r["id"] for r in reopened.execute("SELECT id FROM t")], [7])

    def test_engine_snapshot_uses_configured_page_size(self):
        eng = Engine(self.db, page_size=256)
        eng.verbose = False
        eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
        eng.execute("INSERT INTO t VALUES (1, 'a')")
        eng.execute("CHECKPOINT")
        reopened = Engine(self.db, page_size=256)
        reopened.verbose = False
        self.assertEqual([r["id"] for r in reopened.execute("SELECT id FROM t")], [1])
        slots, _ = PageFile(self.db, page_size=256)._read_slots()
        self.assertEqual(slots[0]["page_size"], 256)


if __name__ == "__main__":
    unittest.main()
