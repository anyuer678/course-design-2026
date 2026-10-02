"""B10-minidb 自测。

压轴策略：**与 sqlite3（真数据库）对拍**——
同一批随机 SQL 分别打到 mini 引擎和 sqlite 内存库上，结果必须一致。
加 B+ 树单元测试（对拍有序列表）、WAL 崩溃恢复、事务回滚。
"""
import os
import contextlib
import io
import random
import sqlite3
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minidb.btree import BPlusTree
from minidb.engine import Engine
from minidb.sqlparser import SqlError, parse, tokenize

DDL = [
    "CREATE TABLE users (id INTEGER, name TEXT, age INTEGER, score REAL, PRIMARY KEY id)",
    "CREATE TABLE orders (oid INTEGER, uid INTEGER, amount REAL, PRIMARY KEY oid)",
]


class TestBPlusTree(unittest.TestCase):
    def test_insert_search_range(self):
        rng = random.Random(42)
        for round in range(20):
            t = BPlusTree(order=4)               # 小阶数 -> 频繁分裂，压测结构
            keys = rng.sample(range(10000), 800)
            ref = {}
            for k in keys:
                v = k * 10
                t.insert(k, v)
                ref[k] = v
            # 全量有序
            self.assertEqual([k for k, _ in t.items()], sorted(keys))
            # 精确查找
            for k in keys:
                self.assertEqual(t.search(k), ref[k])
            self.assertIsNone(t.search(999999))
            # 范围扫描 vs 有序过滤
            lo, hi = rng.randint(0, 5000), rng.randint(5000, 10000)
            want = sorted((k, ref[k]) for k in keys if lo <= k <= hi)
            self.assertEqual(t.range_scan(lo, hi), want)

    def test_delete(self):
        rng = random.Random(7)
        t = BPlusTree(order=4)
        keys = rng.sample(range(5000), 600)
        for k in keys:
            t.insert(k, k)
        removed = keys[:300]
        for k in removed:
            self.assertTrue(t.delete(k))
        left = sorted(set(keys) - set(removed))
        self.assertEqual([k for k, _ in t.items()], left)
        for k in removed:
            self.assertIsNone(t.search(k))
            self.assertFalse(t.delete(k))        # 二次删除 = 不存在
        # 范围扫描仍正确
        got = t.range_scan(left[0], left[-1])
        self.assertEqual([k for k, _ in got], left)

    def test_overwrite(self):
        t = BPlusTree()
        t.insert(5, "old")
        t.insert(5, "new")
        self.assertEqual(t.search(5), "new")
        self.assertEqual(len(t.items()), 1)


class TestSqlParser(unittest.TestCase):
    def test_tokenize_parse(self):
        stmt = parse("SELECT name, score FROM users WHERE age >= 18 AND name != 'bob' "
                     "ORDER BY score DESC, name LIMIT 5")
        self.assertEqual(stmt[0], "select")
        self.assertEqual(stmt[2], ["name", "score"])
        self.assertEqual(stmt[4], [("score", True), ("name", False)])
        self.assertEqual(stmt[5], 5)

    def test_errors(self):
        for bad in ["SELECT FROM t", "INSERT INTO t VALUES (1,", "FROB t"]:
            with self.assertRaises(SqlError):
                parse(bad)


class TestEngineBasics(unittest.TestCase):
    def setUp(self):
        self.eng = Engine()
        self.eng.verbose = False
        for ddl in DDL:
            self.eng.execute(ddl)

    def test_crud(self):
        self.eng.execute("INSERT INTO users VALUES (1, 'alice', 30, 9.5)")
        self.eng.execute("INSERT INTO users VALUES (2, 'bob', 17, 6.0)")
        self.eng.execute("INSERT INTO users VALUES (3, 'carol', 25, 8.0)")

        rows = self.eng.execute("SELECT * FROM users ORDER BY id")
        self.assertEqual([r["name"] for r in rows], ["alice", "bob", "carol"])

        rows = self.eng.execute(
            "SELECT name FROM users WHERE age >= 18 ORDER BY score DESC")
        self.assertEqual([r["name"] for r in rows], ["alice", "carol"])

        rows = self.eng.execute("SELECT name FROM users ORDER BY age LIMIT 1")
        self.assertEqual(rows[0]["name"], "bob")

        self.eng.execute("UPDATE users SET score = 10.0 WHERE id = 3")
        rows = self.eng.execute("SELECT score FROM users WHERE id = 3")
        self.assertEqual(rows[0]["score"], 10.0)

        n = self.eng.execute("DELETE FROM users WHERE age < 18")
        self.assertEqual(n, 1)
        rows = self.eng.execute("SELECT * FROM users")
        self.assertEqual(len(rows), 2)

    def test_pk_index(self):
        eng = self.eng
        eng.execute("INSERT INTO users VALUES (10, 'x', 1, 1.0)")
        self.assertIsNotNone(eng.tables["users"].index.search(10))
        # 重复主键被拒
        with self.assertRaises(SqlError):
            eng.execute("INSERT INTO users VALUES (10, 'y', 2, 2.0)")
        # WHERE 主键 = 值 -> 走索引
        eng.verbose = True
        rows = eng.execute("SELECT name FROM users WHERE id = 10")
        eng.verbose = False
        self.assertEqual(rows[0]["name"], "x")

    def test_null_and_not(self):
        eng = self.eng
        eng.execute("INSERT INTO users VALUES (1, 'a', NULL, NULL)")
        rows = eng.execute("SELECT * FROM users WHERE age IS NULL")
        self.assertEqual(len(rows), 1)
        rows = eng.execute("SELECT * FROM users WHERE NOT age > 0")
        self.assertEqual(len(rows), 0)       # NULL 比较 -> UNKNOWN -> 不选


class TestWALAndTxn(unittest.TestCase):
    def test_persistence_and_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db")
            eng = Engine(path)
            eng.verbose = False
            for ddl in DDL:
                eng.execute(ddl)
            eng.execute("INSERT INTO users VALUES (1, 'a', 1, 1.0)")
            eng.execute("INSERT INTO users VALUES (2, 'b', 2, 2.0)")
            # 此时没有 CHECKPOINT：状态全部在 WAL 里
            eng2 = Engine(path)              # 模拟崩溃重启
            eng2.verbose = False
            rows = eng2.execute("SELECT * FROM users ORDER BY id")
            self.assertEqual([r["id"] for r in rows], [1, 2])

            # CHECKPOINT 之后 WAL 清空、快照生效
            eng2.execute("CHECKPOINT")
            self.assertFalse(os.path.exists(path + ".wal"))
            eng3 = Engine(path)
            eng3.verbose = False
            self.assertEqual(len(eng3.execute("SELECT * FROM users")), 2)

    def test_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db")
            eng = Engine(path)
            eng.verbose = False
            eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
            eng.execute("INSERT INTO t VALUES (1, 'keep')")
            eng.execute("BEGIN")
            eng.execute("INSERT INTO t VALUES (2, 'lost')")
            eng.execute("DELETE FROM t WHERE id = 1")
            eng.execute("ROLLBACK")
            rows = eng.execute("SELECT * FROM t")
            self.assertEqual([r["id"] for r in rows], [1])   # 事务内的改动全部消失
            # 提交的事务才进 WAL
            eng.execute("BEGIN")
            eng.execute("INSERT INTO t VALUES (3, 'kept')")
            eng.execute("COMMIT")
            eng2 = Engine(path)
            eng2.verbose = False
            self.assertEqual([r["id"] for r in eng2.execute("SELECT * FROM t")], [1, 3])


class TestAgainstSqlite(unittest.TestCase):
    """对拍：同一批随机 SQL -> mini 引擎 vs sqlite3 内存库，结果逐行相同。"""

    def setUp(self):
        self.mini = Engine()
        self.mini.verbose = False
        self.sql = sqlite3.connect(":memory:")
        self.sql.execute("CREATE TABLE u (id INTEGER PRIMARY KEY, name TEXT, "
                         "age INTEGER, score REAL)")
        self.mini.execute("CREATE TABLE u (id INTEGER, name TEXT, age INTEGER, "
                          "score REAL, PRIMARY KEY id)")

    def run_both(self, sql, want_rows=True):
        mini_out = self.mini.execute(sql)
        cur = self.sql.execute(sql)
        sqlite_out = cur.fetchall() if cur.description else None
        if want_rows and sqlite_out is not None:
            mini_rows = [tuple(r.values()) for r in mini_out]
            self.assertEqual(mini_rows, sqlite_out, msg=sql)
        return mini_out, sqlite_out

    def test_random_battery(self):
        rng = random.Random(2026)
        names = ["alice", "bob", "carol", "dave", "eve"]
        # 插入
        for i in range(200):
            age = rng.choice([rng.randint(10, 60), None])
            self.run_both(
                f"INSERT INTO u VALUES ({i}, '{names[i % 5]}', "
                f"{age if age is not None else 'NULL'}, "
                f"{round(rng.uniform(0, 100), 2)})")
        self.assertEqual(self.mini.execute("SELECT * FROM u"),
                         self.mini.execute("SELECT * FROM u"))  # sanity

        # 随机查询/更新/删除对拍
        queries = []
        conds = ["age > 30", "age <= 25", "name = 'alice'", "name != 'bob'",
                 "score >= 50.0", "age IS NULL", "age IS NOT NULL AND score < 60",
                 "name = 'carol' OR age > 50", "age = NULL", "age > NULL",
                 "age IS NULL OR score > 30", "NOT (age > 20 AND score < 80)"]
        for step in range(300):
            pick = rng.random()
            if pick < 0.5:
                cond = rng.choice(conds)
                order = rng.choice(["", " ORDER BY age, id",
                                    " ORDER BY score DESC, id", " ORDER BY name, id"])
                limit = rng.choice(["", " LIMIT 10", " LIMIT 3"])
                sql = f"SELECT id, name FROM u WHERE {cond}{order}{limit}"
                self.run_both(sql)
            elif pick < 0.7:
                i = rng.randint(0, 199)
                sql = f"UPDATE u SET score = {round(rng.uniform(0, 100), 2)} WHERE id = {i}"
                self.run_both(sql, want_rows=False)
            elif pick < 0.85:
                i = rng.randint(0, 199)
                sql = f"DELETE FROM u WHERE id = {i}"
                self.run_both(sql, want_rows=False)
            else:
                self.run_both("SELECT * FROM u ORDER BY id")
        # 收尾：两库全量状态一致
        self.run_both("SELECT * FROM u ORDER BY id")


class TestSemantics(unittest.TestCase):
    """语义边界：这些案例都是修 bug 前真实挂掉的写法。"""

    def new(self, ddl=DDL[0]):
        eng = Engine()
        eng.verbose = False
        eng.execute(ddl)
        return eng

    def test_negative_literal(self):
        eng = self.new()
        eng.execute("INSERT INTO users VALUES (-5, 'neg', 1, 1.0)")
        self.assertEqual([r["name"] for r in eng.execute(
            "SELECT name FROM users WHERE id = -5")], ["neg"])
        self.assertEqual([r["name"] for r in eng.execute(
            "SELECT name FROM users WHERE id < -1")], ["neg"])
        self.assertEqual(eng.execute("SELECT name FROM users WHERE id > -1"), [])

    def test_text_pk_range_scan(self):
        # 主键是 TEXT 时，无界一侧不能用 ±inf 占位：str 与 float 比较直接 TypeError
        eng = self.new("CREATE TABLE t (k TEXT, v INTEGER, PRIMARY KEY (k))")
        for k in "abcde":
            eng.execute(f"INSERT INTO t VALUES ('{k}', 1)")
        self.assertEqual(sorted(r["k"] for r in eng.execute(
            "SELECT k FROM t WHERE k >= 'c'")), ["c", "d", "e"])
        self.assertEqual([r["k"] for r in eng.execute(
            "SELECT k FROM t WHERE k < 'b'")], ["a"])
        self.assertEqual([r["k"] for r in eng.execute(
            "SELECT k FROM t WHERE k = 'd'")], ["d"])

    def test_three_valued_logic_table(self):
        eng = self.new()
        eng.execute("INSERT INTO users VALUES (1, 'n', NULL, 1.0)")   # age 为 NULL
        # UNKNOWN 单看两边都不选
        self.assertEqual(eng.execute("SELECT * FROM users WHERE age > 0"), [])
        self.assertEqual(eng.execute("SELECT * FROM users WHERE NOT age > 0"), [])
        # UNKNOWN OR TRUE = TRUE；UNKNOWN AND FALSE = FALSE
        self.assertEqual(len(eng.execute(
            "SELECT * FROM users WHERE age > 0 OR score = 1.0")), 1)
        self.assertEqual(eng.execute(
            "SELECT * FROM users WHERE age > 0 AND score = 99.0"), [])
        # UNKNOWN OR FALSE = UNKNOWN -> 不选
        self.assertEqual(eng.execute(
            "SELECT * FROM users WHERE age > 0 OR score = 99.0"), [])
        # = NULL 不是 IS NULL：它是 UNKNOWN，什么都选不出来
        self.assertEqual(eng.execute("SELECT * FROM users WHERE age = NULL"), [])
        self.assertEqual(eng.execute("SELECT * FROM users WHERE age != NULL"), [])
        self.assertEqual(eng.execute("SELECT * FROM users WHERE age > NULL"), [])
        self.assertEqual(len(eng.execute("SELECT * FROM users WHERE age IS NULL")), 1)
        self.assertEqual(eng.execute("SELECT * FROM users WHERE age IS NOT NULL"), [])

    def test_bad_column_and_arity(self):
        eng = self.new()
        for bad in ["SELECT nope FROM users",
                    "INSERT INTO users VALUES (1, 'a')",
                    "SELECT id FROM users WHERE nope = 1",
                    "SELECT id FROM nope",
                    "SELECT users.id, orders.oid FROM users, orders"]:
            with self.assertRaises(SqlError, msg=bad):
                eng.execute(bad)
        self.assertEqual(eng.execute("SELECT * FROM users"), [])   # 失败不留半行

    def test_select_star_keys(self):
        eng = self.new()
        eng.execute("INSERT INTO users VALUES (1, 'a', 10, 1.0)")
        row = eng.execute("SELECT * FROM users")[0]
        # 内部行同时带 "表.列" 和裸列名，投影不能把它们都吐出来
        self.assertEqual(list(row.keys()), ["id", "name", "age", "score"])


class TestStatementAtomicity(unittest.TestCase):
    def new(self):
        eng = Engine()
        eng.verbose = False
        eng.execute(DDL[0])
        return eng

    def test_multi_row_insert_is_all_or_nothing(self):
        eng = self.new()
        eng.execute("INSERT INTO users VALUES (1, 'a', 1, 1.0)")
        with self.assertRaises(SqlError):
            # 一条语句里第二行撞主键
            eng.execute("INSERT INTO users VALUES (2, 'b', 2, 2.0), (1, 'dup', 3, 3.0)")
        self.assertEqual([r["id"] for r in eng.execute("SELECT id FROM users")], [1])
        # next_rowid 也不能被白消耗，否则删除后会出现空洞
        self.assertEqual(eng.tables["users"].next_rowid, 2)

    def test_update_conflicting_pk_rejected(self):
        eng = self.new()
        eng.execute("INSERT INTO users VALUES (1, 'a', 10, 1.0)")
        eng.execute("INSERT INTO users VALUES (2, 'b', 20, 2.0)")
        with self.assertRaises(SqlError):
            eng.execute("UPDATE users SET id = 2 WHERE id = 1")
        self.assertEqual([(r["id"], r["name"]) for r in
                          eng.execute("SELECT id, name FROM users ORDER BY id")],
                         [(1, "a"), (2, "b")])
        # 失败的语句不能进 WAL，否则重启后会"复活"
        self.assertEqual(len(eng.wal), 3)          # create + 2 条 insert

    def test_update_pk_keeps_index_consistent(self):
        eng = self.new()
        eng.execute("INSERT INTO users VALUES (1, 'a', 10, 1.0)")
        eng.execute("INSERT INTO users VALUES (2, 'b', 20, 2.0)")
        eng.execute("UPDATE users SET id = 5 WHERE id = 1")
        self.assertEqual([r["name"] for r in eng.execute(
            "SELECT name FROM users WHERE id = 5")], ["a"])
        self.assertEqual(eng.execute("SELECT name FROM users WHERE id = 1"), [])
        self.assertIsNone(eng.tables["users"].index.search(1))
        self.assertIsNotNone(eng.tables["users"].index.search(5))
        # 索引扫描和全表扫描必须给同一个答案
        self.assertEqual([r["name"] for r in eng.execute(
            "SELECT name FROM users WHERE id = 5")],
            [r["name"] for r in eng.execute(
                "SELECT name FROM users WHERE id = 5 AND name IS NOT NULL")])

    def test_delete_then_reinsert_pk(self):
        eng = self.new()
        eng.execute("INSERT INTO users VALUES (1, 'a', 1, 1.0)")
        eng.execute("DELETE FROM users WHERE id = 1")
        eng.execute("INSERT INTO users VALUES (1, 'b', 2, 2.0)")   # 索引槽位要真的放掉
        self.assertEqual([r["name"] for r in eng.execute(
            "SELECT name FROM users WHERE id = 1")], ["b"])

    def test_failure_inside_txn_does_not_abort_it(self):
        """语句原子、事务不原子：一条语句失败只回滚它自己，事务还能继续。"""
        eng = self.new()
        eng.execute("INSERT INTO users VALUES (1, 'a', 1, 1.0)")
        eng.execute("BEGIN")
        eng.execute("INSERT INTO users VALUES (7, 'ok', 7, 7.0)")
        with self.assertRaises(SqlError):
            eng.execute("INSERT INTO users VALUES (1, 'dup', 1, 1.0)")
        eng.execute("COMMIT")
        self.assertEqual(sorted(r["id"] for r in eng.execute("SELECT id FROM users")),
                         [1, 7])

    def test_index_plan_matches_full_scan(self):
        """同一份数据，有主键（走索引）和无主键（只能全表扫）结果必须一致。"""
        rng = random.Random(11)
        keyed = Engine(); keyed.verbose = False
        keyed.execute(DDL[0])
        plain = Engine(); plain.verbose = False
        plain.execute("CREATE TABLE users (id INTEGER, name TEXT, age INTEGER, score REAL)")
        conds = ["id = 7", "id > 90", "id <= 5", "id >= 50 AND id < 80",
                 "id > 20 AND id < 40", "age > 100 OR name = 'n0'", "id != 3"]
        for i in range(120):
            row = (i, f"n{i}", rng.randint(10, 60), round(rng.uniform(0, 100), 2))
            for eng in (keyed, plain):
                eng.execute(f"INSERT INTO users VALUES {row}")
        for cond in conds:
            sql = f"SELECT id, name FROM users WHERE {cond} ORDER BY id"
            self.assertEqual(keyed.execute(sql), plain.execute(sql), msg=cond)
        # 主键等值确实走了索引（计划打印是给用户看的，也要能验证）
        buf = io.StringIO()
        keyed.verbose = True
        with contextlib.redirect_stdout(buf):
            keyed.execute("SELECT id FROM users WHERE id = 7")
        keyed.verbose = False
        self.assertIn("索引", buf.getvalue())


class TestTransactionsAndRecovery(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_checkpoint_in_txn_is_refused(self):
        eng = Engine(self.path)
        eng.verbose = False
        eng.execute(DDL[0])
        eng.execute("BEGIN")
        eng.execute("INSERT INTO users VALUES (1, 'uncommitted', 1, 1.0)")
        with self.assertRaises(SqlError):
            eng.execute("CHECKPOINT")     # 否则会落下未提交数据
        eng.execute("ROLLBACK")
        reopened = Engine(self.path)
        reopened.verbose = False
        self.assertEqual(reopened.execute("SELECT * FROM users"), [])

    def test_rollback_covers_txn_ddl(self):
        eng = Engine(self.path)
        eng.verbose = False
        eng.execute("CREATE TABLE keep (id INTEGER, PRIMARY KEY id)")
        eng.execute("BEGIN")
        eng.execute("CREATE TABLE tmp (id INTEGER, PRIMARY KEY id)")
        eng.execute("ROLLBACK")
        self.assertNotIn("tmp", eng.tables)          # 内存里不能留
        self.assertIn("keep", eng.tables)
        reopened = Engine(self.path)
        reopened.verbose = False
        self.assertNotIn("tmp", reopened.tables)     # 磁盘里也不能留

    def test_rollback_restores_next_rowid(self):
        eng = Engine(self.path)
        eng.verbose = False
        eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
        eng.execute("INSERT INTO t VALUES (1, 'a')")
        eng.execute("BEGIN")
        eng.execute("INSERT INTO t VALUES (2, 'b')")
        eng.execute("ROLLBACK")
        eng.execute("INSERT INTO t VALUES (2, 'c')")     # rowid 回收后才能干净重来
        self.assertEqual([r["v"] for r in eng.execute("SELECT * FROM t ORDER BY id")],
                         ["a", "c"])

    def test_torn_wal_tail_is_dropped_not_fatal(self):
        eng = Engine(self.path)
        eng.verbose = False
        eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
        eng.execute("INSERT INTO t VALUES (1, 'ok')")
        # 模拟崩溃：最后一条日志只写了一半
        with open(self.path + ".wal", "a", encoding="utf-8", newline="\n") as f:
            f.write('{"op": "insert", "table": "t", "rows": [[2, "torn"')
        reopened = Engine(self.path)
        reopened.verbose = False
        self.assertEqual([r["id"] for r in reopened.execute("SELECT id FROM t")], [1])
        with open(self.path + ".wal", encoding="utf-8", newline="") as f:
            self.assertEqual(f.read().count("\n"), 2)   # 撕裂行已从文件里去掉
        # 恢复后还能继续写，且新记录不会被上一次的截断破坏
        reopened.execute("INSERT INTO t VALUES (3, 'after')")
        again = Engine(self.path)
        again.verbose = False
        self.assertEqual(sorted(r["id"] for r in again.execute("SELECT id FROM t")),
                         [1, 3])

    def test_rollback_restores_index(self):
        eng = Engine(self.path)
        eng.verbose = False
        eng.execute("CREATE TABLE t (id INTEGER, v TEXT, PRIMARY KEY id)")
        eng.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
        eng.execute("BEGIN")
        eng.execute("UPDATE t SET id = 5 WHERE id = 1")
        eng.execute("DELETE FROM t WHERE id = 2")
        eng.execute("ROLLBACK")
        self.assertEqual([(r["id"], r["v"]) for r in
                          eng.execute("SELECT id, v FROM t ORDER BY id")],
                         [(1, "a"), (2, "b")])
        # 回滚后索引必须同步还原：旧键还查得到，改出来的新键不能残留
        self.assertIsNotNone(eng.tables["t"].index.search(1))
        self.assertIsNotNone(eng.tables["t"].index.search(2))
        self.assertIsNone(eng.tables["t"].index.search(5))
        self.assertEqual([r["v"] for r in eng.execute("SELECT v FROM t WHERE id = 1")],
                         ["a"])

    def read_rows(self):
        eng = Engine(self.path)
        eng.verbose = False
        return [(r["id"], r["v"], r["n"]) for r in
                eng.execute("SELECT id, v, n FROM t ORDER BY id")]

    def test_writes_survive_restarts_around_checkpoint(self):
        """快照 + WAL 混合恢复：CHECKPOINT 前后的写入都要能回来。"""
        eng = Engine(self.path)
        eng.verbose = False
        eng.execute("CREATE TABLE t (id INTEGER, v TEXT, n INTEGER, PRIMARY KEY id)")
        eng.execute("INSERT INTO t VALUES (1, 'a', 10), (2, 'b', 20), (3, 'c', 30)")
        eng.execute("UPDATE t SET n = 99 WHERE id = 2")
        eng.execute("DELETE FROM t WHERE id = 3")
        eng.execute("CHECKPOINT")                               # 以上进快照
        eng.execute("INSERT INTO t VALUES (4, 'd', 40)")
        eng.execute("UPDATE t SET v = 'zz' WHERE id = 4")        # 以上留在 WAL
        want = [(1, "a", 10), (2, "b", 99), (4, "zz", 40)]
        for _ in range(2):                                       # 反复重启要稳定
            self.assertEqual(self.read_rows(), want)
        reopened = Engine(self.path)
        reopened.verbose = False
        reopened.execute("INSERT INTO t VALUES (5, 'e', 50)")
        want.append((5, "e", 50))
        self.assertEqual(self.read_rows(), want)                 # 新写入也能接上
        self.assertEqual([r["id"] for r in reopened.execute(
            "SELECT id FROM t WHERE id = 5")], [5])              # 索引重建过

    def test_corrupt_middle_of_wal_refuses_to_open(self):
        with open(self.path + ".wal", "w", encoding="utf-8", newline="\n") as f:
            f.write('{"op": "create", "table": "t", "cols": [["id", "INTEGER"]],'
                    ' "pk": "id"}\n')
            f.write('{"op": "garbage"\n')            # 中间就坏了
            f.write('{"op": "create", "table": "t2", "cols": [["id", "INTEGER"]],'
                    ' "pk": "id"}\n')
        with self.assertRaises(SqlError):
            Engine(self.path)          # 不能静默跳过：那会丢数据


class TestJoin(unittest.TestCase):
    def setUp(self):
        self.eng = Engine()
        self.eng.verbose = False
        self.eng.execute("CREATE TABLE u (id INTEGER, name TEXT, PRIMARY KEY (id))")
        self.eng.execute("CREATE TABLE o (oid INTEGER, uid INTEGER, amount REAL,"
                         " PRIMARY KEY (oid))")
        for i, n in enumerate(["alice", "bob", "carol"], start=1):
            self.eng.execute(f"INSERT INTO u VALUES ({i}, '{n}')")
        # uid=99 是孤儿订单，id=3 是没有订单的用户：INNER JOIN 都该丢掉
        self.eng.execute("INSERT INTO o VALUES (100, 1, 10.0),"
                         " (101, 2, 20.0), (102, 1, 5.0), (103, 99, 99.0)")

    def test_inner_join_basic(self):
        rows = self.eng.execute(
            "SELECT u.name AS nm, o.amount AS amt FROM u JOIN o ON o.uid = u.id"
            " ORDER BY o.oid")
        self.assertEqual([(r["nm"], r["amt"]) for r in rows],
                         [("alice", 10.0), ("bob", 20.0), ("alice", 5.0)])

    def test_alias_and_qualification(self):
        rows = self.eng.execute(
            "SELECT x.name AS nm FROM u AS x INNER JOIN o AS y ON y.uid = x.id"
            " WHERE y.amount > 6 ORDER BY y.oid, x.id")
        self.assertEqual([r["nm"] for r in rows], ["alice", "bob"])
        # 同一张表连两次：裸列名有歧义，必须写限定名
        with self.assertRaises(SqlError):
            self.eng.execute("SELECT id FROM u JOIN u AS b ON b.id = u.id")
        rows = self.eng.execute(
            "SELECT u.id, b.name FROM u JOIN u AS b ON b.id = u.id ORDER BY u.id")
        # 多表结果的键是限定名，否则两表的同名列会互相覆盖
        self.assertEqual([(r["u.id"], r["b.name"]) for r in rows],
                         [(1, "alice"), (2, "bob"), (3, "carol")])

    def test_empty_and_no_match(self):
        self.assertEqual(self.eng.execute(
            "SELECT u.name FROM u JOIN o ON o.uid = u.id WHERE u.id = 3"), [])
        empty = Engine()
        empty.verbose = False
        empty.execute("CREATE TABLE u (id INTEGER, name TEXT, PRIMARY KEY (id))")
        empty.execute("CREATE TABLE o (oid INTEGER, uid INTEGER, amount REAL,"
                      " PRIMARY KEY (oid))")
        self.assertEqual(empty.execute("SELECT u.name FROM u JOIN o ON o.uid = u.id"),
                         [])
        self.assertEqual(empty.execute("SELECT o.oid FROM u JOIN o ON o.uid = u.id"),
                         [])

    def test_index_nested_loop_vs_full_scan(self):
        """ON 的左右写法决定内表能否走主键点查；两种计划的结果必须一致。"""
        def run(sql):
            buf = io.StringIO()
            self.eng.verbose = True
            with contextlib.redirect_stdout(buf):
                rows = self.eng.execute(sql)
            self.eng.verbose = False
            return rows, buf.getvalue()

        indexed, plan_a = run("SELECT u.name AS nm, o.amount AS amt"
                              " FROM o JOIN u ON u.id = o.uid ORDER BY o.oid")
        scanned, plan_b = run("SELECT o.oid, u.name FROM u JOIN o ON o.uid = u.id"
                              " ORDER BY o.oid")
        self.assertIn("按内表主键点查", plan_a)
        self.assertIn("内表全表扫描", plan_b)
        self.assertEqual([(r["nm"], r["amt"]) for r in indexed],
                         [("alice", 10.0), ("bob", 20.0), ("alice", 5.0)])
        self.assertEqual(len(indexed), len(scanned))
        # 三表连接：orders -> users（两次，用别名区分）
        rows = self.eng.execute(
            "SELECT a.name AS an, b.name AS bn FROM o JOIN u AS a ON a.id = o.uid"
            " JOIN u AS b ON b.id = o.uid ORDER BY o.oid")
        self.assertEqual([(r["an"], r["bn"]) for r in rows],
                         [("alice", "alice"), ("bob", "bob"), ("alice", "alice")])

    def test_null_and_orphan_join_keys(self):
        self.eng.execute("INSERT INTO o VALUES (104, NULL, 7.0)")   # 外键为 NULL
        a = self.eng.execute("SELECT u.name, o.oid FROM o JOIN u ON u.id = o.uid"
                             " ORDER BY o.oid")
        b = self.eng.execute("SELECT u.name, o.oid FROM u JOIN o ON o.uid = u.id"
                             " ORDER BY o.oid")
        self.assertEqual(len(a), 3)              # NULL 和 uid=99 都匹配不到用户
        self.assertEqual(a, b)

    def test_select_star_on_join_is_qualified(self):
        rows = self.eng.execute("SELECT * FROM u JOIN o ON u.id = o.uid ORDER BY o.oid")
        self.assertEqual(list(rows[0].keys()),
                         ["u.id", "u.name", "o.oid", "o.uid", "o.amount"])
        self.assertEqual(rows[0]["u.name"], "alice")


class TestJoinAgainstSqlite(unittest.TestCase):
    """JOIN 与 sqlite 对拍：同一份数据、同一条 SQL，逐行一致。"""

    def setUp(self):
        self.mini = Engine()
        self.mini.verbose = False
        self.mini.execute("CREATE TABLE u (id INTEGER, name TEXT, PRIMARY KEY (id))")
        self.mini.execute("CREATE TABLE o (oid INTEGER, uid INTEGER, amount REAL,"
                          " PRIMARY KEY (oid))")
        self.sql = sqlite3.connect(":memory:")
        self.sql.execute("CREATE TABLE u (id INTEGER PRIMARY KEY, name TEXT)")
        self.sql.execute("CREATE TABLE o (oid INTEGER PRIMARY KEY, uid INTEGER,"
                         " amount REAL)")
        rng = random.Random(5)
        for i in range(1, 12):
            self.mini.execute(f"INSERT INTO u VALUES ({i}, 'n{i}')")
            self.sql.execute(f"INSERT INTO u VALUES ({i}, 'n{i}')")
        oid = 100
        for uid in [1, 1, 2, 5, 5, 5, 11, 99, 3]:
            amount = round(rng.uniform(1, 99), 2)
            self.mini.execute(f"INSERT INTO o VALUES ({oid}, {uid}, {amount})")
            self.sql.execute(f"INSERT INTO o VALUES ({oid}, {uid}, {amount})")
            oid += 1

    def run_both(self, sql):
        mini_rows = [tuple(r.values()) for r in self.mini.execute(sql)]
        sqlite_rows = self.sql.execute(sql).fetchall()
        self.assertEqual(mini_rows, sqlite_rows, msg=sql)

    def test_join_queries(self):
        for sql in [
            "SELECT u.name, o.amount FROM u JOIN o ON o.uid = u.id ORDER BY o.oid",
            "SELECT u.name, o.amount FROM u INNER JOIN o ON u.id = o.uid"
            " WHERE o.amount > 50 ORDER BY o.amount DESC, u.id",
            "SELECT o.oid, u.name FROM o JOIN u ON u.id = o.uid"
            " WHERE u.name = 'n5' ORDER BY o.oid",
            # ORDER BY 必须写到能定序为止，否则并列行的先后两库可能不同（假失败）
            "SELECT u.id, o.oid FROM u JOIN o ON o.uid = u.id"
            " ORDER BY u.id, o.oid LIMIT 4",
            "SELECT u.name FROM u JOIN o ON o.uid = u.id WHERE u.id = 9",   # 无订单
        ]:
            self.run_both(sql)


if __name__ == "__main__":
    unittest.main(verbosity=2)
