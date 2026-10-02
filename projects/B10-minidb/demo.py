"""B10-minidb 演示：一条 SELECT/INSERT 从解析到落盘的全过程。

run.bat 会自动跑；想单看某一段：python demo.py
演示数据库写在临时目录里，跑完即删，不污染仓库。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minidb.engine import Engine          # noqa: E402
from minidb.sqlparser import SqlError     # noqa: E402


def show(title: str, rows) -> None:
    print(f"\n-- {title}")
    if not rows:
        print("   (空)")
        return
    cols = list(rows[0].keys())
    widths = [max(len(str(c)), *(len(str(r[c])) for r in rows)) for c in cols]
    print("   " + " | ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
    for r in rows:
        print("   " + " | ".join(str(r[c]).ljust(w) for c, w in zip(cols, widths)))


def step(n: int, title: str) -> None:
    print(f"\n{'=' * 62}\n[{n}] {title}\n{'=' * 62}")


# --------------------------------------------------------------- 1
def demo_crud(path: str) -> None:
    step(1, "建表 / 增删改查（数据只在内存，改动先写 WAL）")
    eng = Engine(path)
    eng.execute("CREATE TABLE users (id INTEGER, name TEXT, age INTEGER,"
                " score REAL, PRIMARY KEY (id))")
    eng.execute("CREATE TABLE orders (oid INTEGER, uid INTEGER, amount REAL,"
                " PRIMARY KEY (oid))")
    eng.execute("INSERT INTO users VALUES (1, 'alice', 30, 92.5),"
                " (2, 'bob', 17, 60.0), (3, 'carol', 25, 78.0),"
                " (4, 'dave', NULL, NULL)")
    eng.execute("INSERT INTO orders VALUES (100, 1, 30.0), (101, 1, 20.0),"
                " (102, 2, 5.0), (103, 99, 999.0)")
    show("SELECT * FROM users", eng.execute("SELECT * FROM users ORDER BY id"))
    show("WHERE age >= 18 ORDER BY score DESC",
         eng.execute("SELECT name, age, score FROM users WHERE age >= 18"
                     " ORDER BY score DESC"))
    print(f"\n   UPDATE users SET score = 100 WHERE id = 3  -> 改了 "
          f"{eng.execute('UPDATE users SET score = 100 WHERE id = 3')} 行")
    print(f"   DELETE FROM users WHERE age < 18           -> 删了 "
          f"{eng.execute('DELETE FROM users WHERE age < 18')} 行")
    show("删除之后", eng.execute("SELECT id, name FROM users ORDER BY id"))


# --------------------------------------------------------------- 2
def demo_plan(path: str) -> None:
    step(2, "计划器：同一条 WHERE，走主键索引还是全表扫描")
    eng = Engine(path)
    for sql in ["SELECT name FROM users WHERE id = 3",
                "SELECT name FROM users WHERE id >= 1 AND id < 4",
                "SELECT name FROM users WHERE age > 20"]:
        print(f"\n   {sql}")
        eng.verbose = True
        rows = eng.execute(sql)
        eng.verbose = False
        show("结果", rows)
    print("\n   只有主键上的等值/范围能变成索引扫描；其它列没有二级索引，只能全表扫。")


# --------------------------------------------------------------- 3
def demo_constraints(path: str) -> None:
    step(3, "约束与三值逻辑：这些语句必须失败或不选出行")
    eng = Engine(path)
    for sql in ["INSERT INTO users VALUES (1, 'dup', 20, 20.0)",
                "UPDATE users SET id = 3 WHERE id = 1",
                "INSERT INTO users VALUES (9, 'x', 1)",
                "SELECT name FROM users WHERE age = NULL",
                "SELECT name FROM users WHERE age IS NULL",
                "SELECT name FROM users WHERE NOT age > 20"]:
        try:
            res = eng.execute(sql)
        except SqlError as e:
            print(f"\n   {sql}\n   -> 拒绝：{e}")
            continue
        n = len(res) if isinstance(res, list) else res
        note = "（与 NULL 比较是 UNKNOWN；只有 IS NULL 能选出它）" if n == 0 else ""
        print(f"\n   {sql}\n   -> 不报错，影响/返回 {n} 行{note}")
    print("\n   多行 INSERT 里只要有一行撞主键，整条语句都不生效（语句是原子的）：")
    try:
        eng.execute("INSERT INTO users VALUES (7, 'ok', 1, 1.0), (1, 'dup', 2, 2.0)")
    except SqlError as e:
        print(f"   {e}  -> id=7 也没有被写进去")
    show("确认", eng.execute("SELECT id, name FROM users WHERE id = 7"))


# --------------------------------------------------------------- 4
def demo_join(path: str) -> None:
    step(4, "INNER JOIN：内表主键点查 vs 全表扫描")
    eng = Engine(path)
    print("\n   FROM orders JOIN users ON users.id = orders.uid   （内表主键命中）")
    eng.verbose = True
    show("结果", eng.execute(
        "SELECT orders.uid AS uid, users.name AS uname, orders.amount AS amount"
        " FROM orders JOIN users ON users.id = orders.uid ORDER BY orders.oid"))
    eng.verbose = False
    print("\n   FROM users JOIN orders ON orders.uid = users.id    （内表无索引可用）")
    eng.verbose = True
    eng.execute("SELECT users.id, orders.oid FROM users JOIN orders"
                " ON orders.uid = users.id ORDER BY orders.oid")
    eng.verbose = False
    print("\n   两种计划的结果集相同（孤儿订单 uid=99 与无订单用户都会被 INNER 掉）：")
    a = eng.execute("SELECT users.name, orders.oid FROM orders JOIN users"
                    " ON users.id = orders.uid ORDER BY orders.oid")
    b = eng.execute("SELECT users.name, orders.oid FROM users JOIN orders"
                    " ON orders.uid = users.id ORDER BY orders.oid")
    print(f"   {a == b}  ({len(a)} 行)")
    print("\n   多表下裸列名有歧义时要写限定名：")
    try:
        eng.execute("SELECT id FROM users JOIN users AS u2 ON u2.id = users.id")
    except SqlError as e:
        print(f"   -> {e}")


# --------------------------------------------------------------- 5
def demo_txn(path: str) -> None:
    step(5, "事务：回滚只丢未提交内容，提交才进 WAL")
    eng = Engine(path)
    before = eng.execute("SELECT id, name FROM users ORDER BY id")
    eng.execute("BEGIN")
    eng.execute("INSERT INTO users VALUES (500, 'txn-insert', 1, 1.0)")
    eng.execute("DELETE FROM users WHERE id = 1")
    show("事务内看到的", eng.execute("SELECT id, name FROM users ORDER BY id"))
    eng.execute("ROLLBACK")
    show("ROLLBACK 之后", eng.execute("SELECT id, name FROM users ORDER BY id"))
    print(f"   与事务开始前一致：{before == eng.execute('SELECT id, name FROM users ORDER BY id')}")
    print("\n   事务进行中禁止 CHECKPOINT（快照会把未提交数据永久落盘）：")
    eng.execute("BEGIN")
    try:
        eng.execute("CHECKPOINT")
    except SqlError as e:
        print(f"   -> {e}")
    eng.execute("ROLLBACK")


# --------------------------------------------------------------- 6
def demo_recovery(path: str) -> None:
    step(6, "崩溃恢复：重启后从快照 + WAL 重建，撕裂的最后一行被丢掉")
    eng = Engine(path)
    eng.execute("INSERT INTO users VALUES (900, '已提交', 1, 1.0)")
    print(f"\n   WAL 里已有 {len(eng.wal)} 条记录；快照文件存在："
          f"{os.path.exists(path)}")
    # 模拟进程在写最后一条日志时被杀死：只落了一半
    with open(path + ".wal", "a", encoding="utf-8", newline="\n") as f:
        f.write('{"op": "insert", "table": "users", "rows": [[901, "半条记录"')
    print("   已向日志尾部写入半条记录（模拟崩溃）")
    del eng

    reopened = Engine(path)
    show("重启后 id >= 900 的行（半条记录被丢弃，库仍能打开）",
         reopened.execute("SELECT id, name FROM users WHERE id >= 900"))
    print("\n   CHECKPOINT 之后 WAL 清空，状态全进快照：")
    reopened.execute("CHECKPOINT")
    print(f"   WAL 文件还在吗：{os.path.exists(path + '.wal')}；"
          f"内存日志条数：{len(reopened.wal)}")
    show("CHECKPOINT 后重启", Engine(path).execute("SELECT id, name FROM users"
                                                   " WHERE id >= 900"))


# --------------------------------------------------------------- 7
CHILD_SQL = """
import os, sys
sys.path.insert(0, sys.argv[1])
from minidb.engine import Engine
eng = Engine(sys.argv[2], durable=True)
eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
eng.execute("INSERT INTO t VALUES (1, 'auto-commit')")
eng.execute("BEGIN")
eng.execute("INSERT INTO t VALUES (2, 'in-txn'), (3, 'also')")
eng.execute("COMMIT")
os._exit(0)          # 硬退：不析构、不 CHECKPOINT
"""


def demo_durability(root: str) -> None:
    step(7, "持久性工程化：提交即 fsync、页式快照、坏页回退（B41 候选①）")

    # ---- 提交即持久：子进程硬退后逐条对账
    crash_db = os.path.join(root, "crash_db")
    proc = subprocess.run([sys.executable, "-c", CHILD_SQL,
                           os.path.dirname(os.path.abspath(__file__)), crash_db],
                          capture_output=True, text=True)
    print(f"   子进程写入并提交后立刻 os._exit（退出码 {proc.returncode}，不 CHECKPOINT）")
    eng = Engine(crash_db)
    rows = eng.execute("SELECT id, v FROM t ORDER BY id")
    show("重启后逐条对账（已提交的一条不少）", rows)

    # ---- fsync 的代价（本机实测）
    def timed_inserts(durable: bool) -> float:
        db = os.path.join(root, "bench_%s" % ("on" if durable else "off"))
        e = Engine(db, durable=durable)
        e.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
        t0 = time.perf_counter()
        for i in range(100):
            e.execute(f"INSERT INTO t VALUES ({i}, 'x')")
        return (time.perf_counter() - t0) * 1000

    on_ms = timed_inserts(True)
    off_ms = timed_inserts(False)
    print(f"\n   100 次自动提交 INSERT：durable(每次 fsync) {on_ms:>8.3f} ms  |  "
          f"非 durable {off_ms:>8.3f} ms  （差 {on_ms - off_ms:>8.3f} ms，本机介质实测）")

    # ---- 页大小对照表（文件体积/页数确定性；耗时实测）
    print("\n   页大小对照（同一份数据 CHECKPOINT 一次）：")
    print("   " + "页大小".ljust(10) + "文件字节".ljust(12) + "数据页".ljust(8) + "耗时[实测]")
    for ps in (512, 4096, 16384):
        db = os.path.join(root, f"ps_{ps}")
        e = Engine(db, page_size=ps)
        e.execute("CREATE TABLE big (id INTEGER, v TEXT, PRIMARY KEY id)")
        for i in range(400):
            e.execute(f"INSERT INTO big VALUES ({i}, 'row-{i:04d}')")
        t0 = time.perf_counter()
        e.execute("CHECKPOINT")
        ms = (time.perf_counter() - t0) * 1000
        stats = e.last_checkpoint_stats
        print("   " + str(ps).ljust(10) + str(stats["file_bytes"]).ljust(12)
              + str(stats["n_pages"]).ljust(8) + f"{ms:>8.3f} ms")

    # ---- 坏页回退：打坏最新代的一个数据页，读必须回退旧代并留证据
    from minidb.pager import PageFile
    db = os.path.join(root, "fallback")
    pf = PageFile(db, page_size=4096)
    pf.commit(b"generation-one")
    stats = pf.commit(b"generation-two")
    slots, _ = pf._read_slots()
    with open(db, "r+b") as f:
        f.seek(slots[0]["gen_offset"] + slots[0]["page_size"] + 7)
        old = f.read(1)
        f.seek(slots[0]["gen_offset"] + slots[0]["page_size"] + 7)
        f.write(bytes([old[0] ^ 0xFF]))
    payload, meta = pf.load()
    print(f"\n   打坏最新代（seq={stats['seq']}）一个数据页后重新打开：")
    print(f"   回退到 seq={meta['seq']}，拿到 {payload!r}；警告：{meta['warnings'][0]}")


def main() -> int:
    d = tempfile.mkdtemp(prefix="b10demo")
    path = os.path.join(d, "db")
    try:
        demo_crud(path)
        demo_plan(path)
        demo_constraints(path)
        demo_join(path)
        demo_txn(path)
        demo_recovery(path)
        demo_durability(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"\n{'=' * 62}\n演示结束（临时库已删除）。跑自测：python tests\\test_minidb.py\n{'=' * 62}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
