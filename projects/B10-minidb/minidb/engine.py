"""minidb/engine.py —— 执行器 + 存储 + B+树索引 + WAL 持久化 + 事务

存储结构：
    Table { columns, pk, rows: dict[rowid -> tuple], index: BPlusTree, next_rowid }
    主键索引：BPlusTree[pk值] = rowid。WHERE pk = x / 范围 走索引扫描，
    其余条件走全表扫描（计划器只做"用不用索引"一个决策——够说明原理）。

持久化 = WAL（write-ahead log，预写日志）+ 页式快照（B41 候选①，2026-10-02）：
    每条**已提交**的写语句先以 JSON 行（带 lsn 序号）追加进 .wal 文件，
    **durable 模式下 flush+fsync 之后**才算提交成功，然后才改内存——
    "提交返回=已落盘"。启动时回放 WAL 重建内存状态。
    WAL 最后一行若是撕裂的（崩溃时只写了一半），丢弃该行：这是 WAL 的
    "最后一次提交可能丢失"标准语义，不能让整个库打不开。
    CHECKPOINT 把全量状态经 **minidb/pager.py** 写成一个**页式快照**：
    固定页 + 逐页 crc + 双头槽位 + 代追加（新代不覆盖旧代，坏页可回退），
    数据页 fsync 后才切换头槽位，头落盘后才删除 WAL（写前次序）。
    快照带 lsn，恢复时只重放 lsn > 快照 lsn 的日志——快照与 WAL 的交界
    不怕"换了头还没删 WAL"的崩溃（重放会跳过已进快照的记录）。

语句原子性：一条语句要么全做要么全不做。INSERT/UPDATE 先把所有行校验完、
    确认没有主键冲突，才开始改内存和写 WAL（否则中途报错会留下半条语句）。
"""
from __future__ import annotations

import json
import os

from .btree import BPlusTree
from .pager import DEFAULT_PAGE_SIZE, PageFile
from .sqlparser import SqlError, parse


class Table:
    def __init__(self, columns: list[tuple[str, str]], pk: str | None):
        self.columns = columns                  # [(name, type)]
        self.col_names = [c for c, _ in columns]
        self.pk = pk
        self.rows: dict[int, tuple] = {}        # rowid -> 值元组
        self.index = BPlusTree(order=8)         # pk -> rowid
        self.next_rowid = 1


class Engine:
    def __init__(self, path=None, durable: bool = True,
                 page_size: int = DEFAULT_PAGE_SIZE):
        self.path = str(path) if path is not None else None   # 接受 str 或 os.PathLike
        self.durable = durable                  # True=提交 flush+fsync（默认，见 README 对照）
        self.page_size = page_size
        self.tables: dict[str, Table] = {}
        self.wal: list[dict] = []               # 尚未 CHECKPOINT 的日志（内存视图）
        self.in_txn = False
        self.txn_log: list[dict] = []           # 事务里暂存的写语句
        self.txn_snapshot: dict | None = None   # BEGIN 时的完整状态（回滚用）
        self.next_lsn = 1                       # 日志序号（快照里带走，恢复用）
        self.snapshot_lsn = -1                  # 最后一次进快照的 lsn
        self.last_checkpoint_stats: dict | None = None
        self.last_load_meta: dict | None = None
        if self.path and (os.path.exists(self.path) or os.path.exists(self.path + ".wal")):
            self._load()                        # 恢复：快照 + WAL 都要找

    # ================================================== 表与行
    def _new_table(self, cols, pk) -> Table:
        return Table(cols, pk)

    # ================================================== 执行入口
    def execute(self, sql: str):
        stmt = parse(sql)
        return self._run(stmt, sql)

    def _run(self, stmt, sql: str):
        kind = stmt[0]

        if kind == "create":
            _, table, cols, pk = stmt
            if table in self.tables:
                raise SqlError(f"表已存在: {table}")
            self.tables[table] = self._new_table(cols, pk)
            self._log({"op": "create", "table": table, "cols": cols, "pk": pk}, sql)
            return None

        if kind == "insert":
            _, table, rows = stmt
            t = self._table(table)
            self._check_insert(t, rows)                 # 先校验，保证语句原子
            for row in rows:
                rid = t.next_rowid
                t.next_rowid += 1
                t.rows[rid] = tuple(row)
                if t.pk is not None and row[t.col_names.index(t.pk)] is not None:
                    t.index.insert(row[t.col_names.index(t.pk)], rid)
            self._log({"op": "insert", "table": table, "rows": rows}, sql)
            return len(rows)

        if kind == "select":
            _, base, cols, where, order, limit = stmt[:6]
            joins = stmt[6] if len(stmt) > 6 else []
            labels = stmt[7] if len(stmt) > 7 else []
            srcs, on_conds = self._sources(base, joins)
            colkey = self._col_map(srcs)
            # 先整体校验列名：扫到一半才报错等于白干，而且错误信息更难看
            to_check = ([] if cols == ["*"] else cols) + [c for c, _ in order]
            to_check += self._columns(where)
            for cond in on_conds:
                to_check += self._columns(cond)
            for col in to_check:
                self._check_col(colkey, col)
            out = self._joined_rows(srcs, on_conds, where, colkey)
            # 多键排序：从最后一个键往前逐次稳定排序（经典 minor→major 技巧）
            for col, desc in reversed(order):
                out.sort(key=lambda r: self._sort_key(self._get(colkey, r, col)),
                         reverse=desc)
            if limit is not None:
                out = out[:limit]
            # 投影：内部行同时带 "别名.列" 和裸列名，必须按清单挑出来
            return [{k: self._get(colkey, r, n)
                     for k, n in self._projection(srcs, cols, labels)} for r in out]

        if kind == "delete":
            _, table, where = stmt
            t = self._table(table)
            victims = []
            for rid, row in t.rows.items():
                full = dict(zip(t.col_names, row))
                if where is None or self._eval(where, full):
                    victims.append(rid)
            for rid in victims:
                row = t.rows.pop(rid)
                if t.pk is not None and row[t.col_names.index(t.pk)] is not None:
                    t.index.delete(row[t.col_names.index(t.pk)])
            self._log({"op": "delete", "table": table, "rowids": victims}, sql)
            return len(victims)

        if kind == "update":
            _, table, sets, where = stmt
            t = self._table(table)
            for col, _ in sets:
                if col not in t.col_names:
                    raise SqlError(f"列不存在: {col}")
            # 先算出全部改动并检查主键冲突，再统一落地（原子性）
            changes = []
            for rid, row in t.rows.items():
                full = dict(zip(t.col_names, row))
                if where is None or self._eval(where, full):
                    new_row = list(row)
                    for col, val_expr in sets:
                        new_row[t.col_names.index(col)] = self._eval(val_expr, full)
                    new = tuple(new_row)
                    if t.pk is not None:
                        i = t.col_names.index(t.pk)
                        if new[i] != row[i] and new[i] is not None:
                            other = t.index.search(new[i])
                            if other is not None and other != rid:
                                raise SqlError(f"主键重复: {new[i]}")
                    changes.append((rid, row, new))
            for rid, old, new in changes:
                t.rows[rid] = new
                if t.pk is not None:
                    i = t.col_names.index(t.pk)
                    if old[i] is not None:
                        t.index.delete(old[i])
                    if new[i] is not None:
                        t.index.insert(new[i], rid)
            # WAL 记录整表镜像（简化取舍：工程实现应记前后镜像或物理页）
            self._log({"op": "update", "table": table, "rows": self._dump_rows(t)},
                      sql)
            return len(changes)

        if kind == "begin":
            if self.in_txn:
                raise SqlError("已在事务中")
            self.in_txn = True
            self.txn_log = []
            self.txn_snapshot = self._snapshot()
            return None

        if kind == "commit":
            if not self.in_txn:
                raise SqlError("没有活动事务")
            # 组提交：事务里所有语句一次 fsync（最后一条 append 时同步）
            for i, entry in enumerate(self.txn_log):
                self._append_wal(entry, sync=(i == len(self.txn_log) - 1))
            self.in_txn = False
            self.txn_log = []
            self.txn_snapshot = None
            return None

        if kind == "rollback":
            if not self.in_txn:
                raise SqlError("没有活动事务")
            self._restore(self.txn_snapshot)
            self.in_txn = False
            self.txn_log = []
            self.txn_snapshot = None
            return None

        if kind == "checkpoint":
            if self.in_txn:
                # 快照写的是"当前内存"，而事务未提交的改动已经在内存里——
                # 不在这里挡住，未提交数据就会被永久落盘，ROLLBACK 形同作废
                raise SqlError("事务进行中不能 CHECKPOINT（会落下未提交数据）")
            self._write_snapshot()
            return None

        raise SqlError(f"未知语句类型 {kind}")

    # ================================================== 计划器与表达式
    verbose = False

    def _table(self, name: str) -> Table:
        if name not in self.tables:
            raise SqlError(f"表不存在: {name}")
        return self.tables[name]

    def _check_insert(self, t: Table, rows) -> None:
        """插入前的整体校验：列数、主键重复（含同一条语句内部重复）。"""
        for row in rows:
            if len(row) != len(t.col_names):
                raise SqlError(f"列数不匹配: {len(row)} != {len(t.col_names)}")
        if t.pk is None:
            return
        i = t.col_names.index(t.pk)
        seen = set()
        for row in rows:
            key = row[i]
            if key is None:
                continue                    # 主键为 NULL 不建索引（教学简化，见 README 局限）
            if key in seen or t.index.search(key) is not None:
                raise SqlError(f"主键重复: {key}")
            seen.add(key)

    # ---------------------------------------------- FROM / JOIN
    def _sources(self, base, joins):
        """FROM 子句 -> ([(别名, Table)], [ON 条件])。别名缺省用表名。"""
        srcs = []
        for name, alias in [base] + [(j[0], j[1]) for j in joins]:
            key = alias or name
            if any(k == key for k, _ in srcs):
                raise SqlError(f"表别名重复: {key}")
            srcs.append((key, self._table(name)))
        return srcs, [j[2] for j in joins]

    @staticmethod
    def _col_map(srcs):
        """列名 -> 行里的键。行里真正的键是 "别名.列名"，所以：
        限定名永远不歧义；裸列名只在不冲突时可用，多表同名时置 None 报歧义。"""
        colkey = {}
        for alias, t in srcs:
            for c in t.col_names:
                key = f"{alias}.{c}"
                colkey[key] = key
                if c not in colkey:
                    colkey[c] = key
                elif colkey[c] != key:
                    colkey[c] = None                  # 歧义：留给 _check_col 报清楚
        return colkey

    @staticmethod
    def _columns(node):
        """表达式树里出现的所有列名（执行前统一校验，报错比逐行求值友好）。"""
        if not isinstance(node, tuple):
            return []
        if node[0] == "col":
            return [node[1]]
        return [c for child in node[1:] if isinstance(child, tuple)
                for c in Engine._columns(child)]

    @staticmethod
    def _projection(srcs, cols, labels):
        """SELECT 列表 -> [(输出键, 取值键)]。
        内部行同时带 "别名.列" 和裸列名，直接吐给调用方会让每列重复两遍，
        所以投影必须给出显式清单。
        单表输出裸列名（和 sqlite 的 cursor.description 一致）；
        多表输出限定名（否则两张表的同名列会互相覆盖）；AS 别名优先。"""
        if cols != ["*"]:
            return [(lab or c, c) for lab, c in zip(labels, cols)]
        names = [c if len(srcs) == 1 else f"{a}.{c}"
                 for a, t in srcs for c in t.col_names]
        return [(n, n) for n in names]

    @staticmethod
    def _check_col(colkey, name: str) -> None:
        if colkey.get(name):
            return
        raise SqlError(f"列不存在或存在歧义: {name}（多表时用 表名.列名）")

    @staticmethod
    def _get(colkey, row: dict, name: str):
        key = colkey.get(name)
        if key is None or key not in row:
            raise SqlError(f"列不可用: {name}")
        return row[key]

    @staticmethod
    def _merge(t: Table, alias: str, row: tuple, colkey) -> dict:
        out = {}
        for c, v in zip(t.col_names, row):
            key = f"{alias}.{c}"
            out[key] = v
            if colkey.get(c) == key:
                out[c] = v                            # 不歧义的列再存一个裸名，方便写 SQL
        return out

    def _joined_rows(self, srcs, on_conds, where, colkey):
        """执行 FROM/JOIN/WHERE。
        无 JOIN：单表扫描（可能走索引）。
        有 JOIN：嵌套循环；ON 里能拆出"内表主键 = 左侧值"时改走索引点查——
        这就是索引嵌套循环连接（index nested-loop join）。"""
        alias0, t0 = srcs[0]
        if len(srcs) == 1:
            used_index, pairs = self._plan(t0, where)
            out = []
            for _, row in pairs:
                r = self._merge(t0, alias0, row, colkey)
                if where is None or self._truthy3(self._eval(where, r)):
                    out.append(r)
            if self.verbose:
                print(f"  [计划] {alias0}: " + ("主键索引扫描" if used_index else "全表扫描"))
            return out
        acc = [self._merge(t0, alias0, row, colkey) for row in t0.rows.values()]
        for i, (alias, t) in enumerate(srcs[1:]):
            cond = on_conds[i]              # 第 i 个 JOIN 只对应自己那条 ON
            lookup = self._join_lookup(t, alias, cond, colkey)
            if self.verbose:
                print(f"  [计划] JOIN {alias}: " +
                      ("按内表主键点查" if lookup else "内表全表扫描"))
            out = []
            for left in acc:
                for right in self._inner_rows(t, lookup, left):
                    merged = {**left, **self._merge(t, alias, right, colkey)}
                    # 点查只保证"主键等于那一个值"，等式两边同值仍要在这里判定
                    if self._truthy3(self._eval(cond, merged)):
                        out.append(merged)
            acc = out
            if self.verbose:
                print(f"  [计划] JOIN {alias}: 输出 {len(out)} 行")
        return [r for r in acc
                if where is None or self._truthy3(self._eval(where, r))]

    @staticmethod
    def _join_lookup(t: Table, alias: str, cond, colkey):
        """索引嵌套循环的判定：ON 形如"内表主键 = 另一列"时，内表可按主键点查。
        返回另一列在行里的取值键；返回 None 表示只能用全表扫。
        两侧都要判归属：只看列名会把别的表的主键误认成内表的。"""
        if cond[0] != "cmp" or cond[1] != "=" or cond[2][0] != "col" or cond[3][0] != "col":
            return None
        for mine, theirs in ((cond[2], cond[3]), (cond[3], cond[2])):
            prefix, _, bare = mine[1].rpartition(".")
            if prefix and prefix != alias:
                continue                    # 这一侧属于别的表
            if bare != t.pk:
                continue                    # 不是内表主键，点查用不上
            key = colkey.get(theirs[1])
            if key:
                return key
        return None

    def _inner_rows(self, t: Table, lookup, left: dict):
        if lookup is None:
            return list(t.rows.values())
        key = left.get(lookup)
        if key is None:
            return []                       # 与 NULL 比较 -> 没有匹配行
        rid = t.index.search(key)
        return [t.rows[rid]] if rid in t.rows else []

    def _plan(self, t: Table, where):
        """极简计划器：WHERE 是 主键=值 或 主键范围 -> 索引扫描；否则全表。"""
        if t.pk is not None and where is not None:
            hit = self._index_range(t, where)
            if hit is not None:
                lo, hi = hit
                pairs = t.index.range_scan(lo, hi)
                return True, [(rid, t.rows[rid]) for _, rid in pairs if rid in t.rows]
        return False, list(t.rows.items())

    @staticmethod
    def _index_range(t: Table, where):
        """从 WHERE 提取主键的范围 [lo, hi]；提取不出返回 None。
        None 表示该侧无界——不能用 ±inf 占位：主键是 TEXT 时和浮点比较会直接 TypeError。"""
        if where is None or t.pk is None:
            return None
        lo, hi = None, None

        def walk(node):
            nonlocal lo, hi
            if node[0] == "and":
                walk(node[1])
                walk(node[2])
                return
            if node[0] == "cmp" and node[2][0] == "col" \
                    and node[2][1].rpartition(".")[2] == t.pk \
                    and node[3][0] == "lit" and node[3][1] is not None:
                op, val = node[1], node[3][1]
                if op == "=":
                    lo, hi = _narrow_max(lo, val), _narrow_min(hi, val)
                elif op == ">":
                    lo = _narrow_max(lo, _after(val))
                elif op == ">=":
                    lo = _narrow_max(lo, val)
                elif op == "<":
                    hi = _narrow_min(hi, _before(val))
                elif op == "<=":
                    hi = _narrow_min(hi, val)

        walk(where)
        if lo is None and hi is None:
            return None
        return (lo, hi)

    def _eval(self, node, row: dict):
        """求表达式值。返回 None 表示 SQL 的 UNKNOWN（三值逻辑）。"""
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "null":
            return None
        if kind == "col":
            if node[1] not in row:
                raise SqlError(f"列不存在或不可用: {node[1]}")
            return row[node[1]]
        if kind == "not":
            v = self._eval(node[1], row)
            return None if v is None else not v          # NOT UNKNOWN = UNKNOWN
        if kind == "and":
            left = self._truthy3(self._eval(node[1], row))
            if left is False:
                return False                              # 短路：FALSE AND x = FALSE
            right = self._truthy3(self._eval(node[2], row))
            if right is False:
                return False                              # UNKNOWN AND FALSE 仍是 FALSE
            return None if (left is None or right is None) else True
        if kind == "or":
            left = self._truthy3(self._eval(node[1], row))
            if left is True:
                return True                               # 短路：TRUE OR x = TRUE
            right = self._truthy3(self._eval(node[2], row))
            if right is True:
                return True                               # UNKNOWN OR TRUE 仍是 TRUE
            return None if (left is None or right is None) else False
        if kind == "is_null":               # 只有 IS [NOT] NULL 返回 TRUE/FALSE
            return self._eval(node[1], row) is None
        if kind == "is_not_null":
            return self._eval(node[1], row) is not None
        if kind == "cmp":
            op = node[1]
            left = self._eval(node[2], row)
            right = self._eval(node[3], row)
            # 注意：`age = NULL` 不是 IS NULL，它得 UNKNOWN（sqlite 同款）
            if left is None or right is None:
                return None                 # 与 NULL 比较 = UNKNOWN（不是 FALSE！）
            if op == "=":
                return left == right
            if op == "!=":
                return left != right
            try:
                if op == "<":
                    return left < right
                if op == "<=":
                    return left <= right
                if op == ">":
                    return left > right
                if op == ">=":
                    return left >= right
            except TypeError:
                raise SqlError(f"无法比较 {left!r} 和 {right!r}")
        raise SqlError(f"未知表达式节点 {node!r}")

    @staticmethod
    def _truthy3(v):
        """True/False 保持，UNKNOWN(None) 保持——供 AND/OR 判定用。"""
        return v

    @staticmethod
    def _sort_key(v):
        # None 排最前（sqlite 同款）；数字与字符串各自成区
        if v is None:
            return (0, 0)
        if isinstance(v, (int, float)):
            return (1, v)
        return (2, str(v))

    # ================================================== WAL 与快照
    def _log(self, entry: dict, sql: str) -> None:
        entry["sql"] = sql
        entry["lsn"] = self.next_lsn            # 预留序号（回滚浪费序号无妨，单调即可）
        self.next_lsn += 1
        if self.in_txn:
            self.txn_log.append(entry)           # 事务里先攒着，COMMIT 才落 WAL
        else:
            self._append_wal(entry)

    def _append_wal(self, entry: dict, sync: bool = True) -> None:
        self.wal.append(entry)
        if self.path:
            # newline="\n"：WAL 一律按 LF 写，跨平台字节数与行数一致
            with open(self.path + ".wal", "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
                if self.durable and sync:
                    os.fsync(f.fileno())         # 提交语义：fsync 返回才算"落了盘"

    def _write_snapshot(self) -> None:
        if not self.path:
            return
        state = {"tables": {}}
        for name, t in self.tables.items():
            state["tables"][name] = {
                "cols": t.columns, "pk": t.pk, "next_rowid": t.next_rowid,
                "rows": {str(r): list(v) for r, v in t.rows.items()},
            }
        state["lsn"] = self.next_lsn - 1         # 本快照包含到哪条日志（恢复据此分界）
        payload = json.dumps(state, ensure_ascii=False).encode("utf-8")
        stats = PageFile(self.path, page_size=self.page_size).commit(payload)
        self.last_checkpoint_stats = stats
        self.snapshot_lsn = state["lsn"]
        self.wal = []
        if os.path.exists(self.path + ".wal"):
            # 顺序就是写前规则：数据页 fsync → 头槽位 fsync → 才允许删 WAL。
            # 若在"换头"与"删 WAL"之间崩溃，恢复时重放会按 lsn 跳过已进快照的记录。
            os.remove(self.path + ".wal")

    def _load(self) -> None:
        """启动恢复：先加载页式快照（可回退旧代），再回放 lsn 大于快照的 WAL。"""
        if os.path.exists(self.path):
            payload, meta = PageFile(self.path, page_size=self.page_size).load()
            self.last_load_meta = meta
            if payload is not None:
                state = json.loads(payload)
                for name, td in state["tables"].items():
                    t = self._new_table([tuple(c) for c in td["cols"]], td["pk"])
                    t.next_rowid = td["next_rowid"]
                    for rid, row in td["rows"].items():
                        rid = int(rid)
                        t.rows[rid] = tuple(row)
                        if t.pk is not None:
                            key = row[t.col_names.index(t.pk)]
                            if key is not None:
                                t.index.insert(key, rid)
                    self.tables[name] = t
                self.snapshot_lsn = state.get("lsn", -1)
        self.next_lsn = max(self.next_lsn, self.snapshot_lsn + 1)
        if os.path.exists(self.path + ".wal"):
            with open(self.path + ".wal", encoding="utf-8", newline="") as f:
                lines = f.readlines()
            for n, line in enumerate(lines):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    if n == len(lines) - 1 and not line.endswith("\n"):
                        # 崩溃时最后一条日志只写到一半：丢掉它，库照样能开
                        self._truncate_wal(lines[:n])
                        break
                    raise SqlError(f"WAL 第 {n + 1} 行损坏（不是文件尾部，无法安全恢复）")
                lsn = entry.get("lsn", self.snapshot_lsn + 1)  # 老格式无 lsn：按须回放处理
                if lsn <= self.snapshot_lsn:
                    continue                     # 已包含在快照里（换头后未删 WAL 的窗口）
                self.wal.append(entry)
                self._replay(entry)
                self.next_lsn = max(self.next_lsn, lsn + 1)

    def _truncate_wal(self, keep_lines: list[str]) -> None:
        """改写 WAL 只留下完好前缀。
        别用 f.truncate(字符数)：Windows 上写文件时 "\n" 存成 "\r\n"，
        文本模式读回来的行数不等于字节数，按字节截断会砍进最后一条正常记录。"""
        with open(self.path + ".wal", "w", encoding="utf-8", newline="") as f:
            f.write("".join(keep_lines))

    def _replay(self, entry: dict) -> None:
        """崩溃恢复时重放写语句（不含 sql 文本，重放结构化操作）。"""
        op = entry["op"]
        if op == "create":
            self.tables[entry["table"]] = self._new_table(
                [tuple(c) for c in entry["cols"]], entry["pk"])
        elif op == "insert":
            t = self.tables[entry["table"]]
            for row in entry["rows"]:
                rid = t.next_rowid
                t.next_rowid += 1
                t.rows[rid] = tuple(row)
                if t.pk is not None:
                    key = row[t.col_names.index(t.pk)]
                    if key is not None:
                        t.index.insert(key, rid)
        elif op == "delete":
            t = self.tables[entry["table"]]
            for rid in entry["rowids"]:
                if rid in t.rows:
                    row = t.rows.pop(rid)
                    if t.pk is not None:
                        key = row[t.col_names.index(t.pk)]
                        if key is not None:
                            t.index.delete(key)
        elif op == "update":
            # update 记录的是整表镜像（工程上应记前后镜像或物理页），
            # 所以重放只需覆盖行并重建索引。
            self._set_rows(self.tables[entry["table"]], entry["rows"])

    @staticmethod
    def _set_rows(t: Table, rows: dict) -> None:
        """用 {rowid: 值元组} 覆盖表内容并重建主键索引。"""
        t.rows = {int(r): tuple(v) for r, v in rows.items()}
        t.index = BPlusTree(order=8)
        if t.pk is not None:
            i = t.col_names.index(t.pk)
            for rid, row in t.rows.items():
                if row[i] is not None:
                    t.index.insert(row[i], rid)

    def _dump_rows(self, t: Table) -> dict:
        return {str(r): list(v) for r, v in t.rows.items()}

    def _snapshot(self) -> dict:
        """BEGIN 时的完整状态：行数据 + 表结构 + 行号计数器。
        只存行数据的话，事务里 CREATE/DROP 的表回滚不掉，内存会和磁盘分叉。"""
        state = {}
        for name, t in self.tables.items():
            state[name] = {"cols": t.columns, "pk": t.pk, "next_rowid": t.next_rowid,
                           "rows": self._dump_rows(t)}
        return {"tables": state}

    def _restore(self, snap: dict) -> None:
        for name in list(self.tables):
            if name not in snap["tables"]:
                del self.tables[name]             # 事务里建的表：回滚后必须消失
        for name, td in snap["tables"].items():
            if name not in self.tables:
                t = self._new_table(td["cols"], td["pk"])     # 事务里删掉的表：还原结构
            else:
                t = self.tables[name]
            t.next_rowid = td["next_rowid"]
            self._set_rows(t, td["rows"])


def _after(v):
    """整数键的 >a 等价于 >=a+1；浮点/字符串没有"下一个值"，直接用原值（区间放大一档，
    正确性由后续 WHERE 过滤保证，只影响索引扫描范围）。"""
    return v + 1 if isinstance(v, int) and not isinstance(v, bool) else v


def _before(v):
    return v - 1 if isinstance(v, int) and not isinstance(v, bool) else v


def _narrow_max(cur, val):
    """收窄下界。cur 为 None 表示之前无界；类型不可比时保持原界——
    宁可多扫一些，也不能把该返回的行扫掉。"""
    if cur is None:
        return val
    try:
        return max(cur, val)
    except TypeError:
        return cur


def _narrow_min(cur, val):
    if cur is None:
        return val
    try:
        return min(cur, val)
    except TypeError:
        return cur
