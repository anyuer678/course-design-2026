# B10-minidb —— 带 WAL 与事务的教学型数据库

**课程映射**：数据库系统原理（B+ 树索引、关系代数执行、SQL 解析、恢复与事务）

不是"用数据库"，而是"写一个数据库"：词法/语法分析 → 计划器 → 执行器 →
B+ 树索引 → WAL 预写日志 → 崩溃恢复 → BEGIN/COMMIT/ROLLBACK。
压轴验收是**与 sqlite3 对拍**：同一批随机 SQL 打到两个库上，结果必须逐行相同。

## 运行

```
run.bat                          # 自测（36 项）+ 全流程演示
python tests\test_minidb.py      # 只跑自测
python demo.py                   # 只看演示（临时目录里建库，跑完即删）
```

`run.bat` 用 CRLF + `chcp 65001` + `set PYTHONUTF8=1`。写它时踩过一次：`echo` 文案里
不能出现未转义的 `>`，cmd 会当成重定向——不报错、退出码照样 0，只是提示行被截断，
并在项目目录里凭空多出一个中文碎片命名的文件。已改成 `→`，另外 9 个项目的脚本一并复查。

## 目录

```
minidb/btree.py      B+ 树：数据只在叶子，叶子用链表串起来（范围扫描的本质）
minidb/sqlparser.py  词法 + 递归下降解析，输出 tuple 形式的 AST
minidb/engine.py     执行器 / 计划器 / 存储 / WAL / 事务 / 恢复
tests/test_minidb.py B+ 树压测、语义与约束、原子性、事务恢复、JOIN、sqlite3 对拍
demo.py              六段演示：CRUD -> 计划器 -> 约束 -> JOIN -> 事务 -> 恢复
```

## 课程知识点 ↔ 代码模块映射

| 课程知识点 | 代码 | 说明 |
|---|---|---|
| B+ 树插入分裂 / 删除借用合并 | `btree.py` | 阶 order 可配；叶子右链支持顺序扫描 |
| 索引范围扫描 | `btree.py` `range_scan` | `lo`/`hi` 传 `None` 表示该侧无界 |
| 聚簇主键索引 | `engine.py` `Table.index` | 索引里存 pk -> rowid，行本体在 `rows` 字典 |
| 词法分析 | `sqlparser.py` `tokenize` | 一条正则扫数字/字符串/限定列名/运算符 |
| 递归下降与优先级 | `sqlparser.py` | OR < AND < NOT < 比较；`users.id` 整体是一个记号 |
| AST | tuple | `("select", base, cols, where, order, limit, joins, labels)` |
| 计划选择 | `engine.py` `_plan`/`_index_range` | 主键上的等值/范围 -> 索引扫描，否则全表扫 |
| 谓词下推 | `_joined_rows` | WHERE 在合并后的行上求值（教学简化，见局限） |
| 嵌套循环连接 | `_joined_rows` | 逐张表累加中间结果 |
| **索引嵌套循环连接** | `_join_lookup` | ON 形如"内表主键 = 另一列"时改走主键点查 |
| 三值逻辑 | `_eval` | 与 NULL 比较得 UNKNOWN；只有 `IS [NOT] NULL` 返回真值 |
| 实体完整性（主键） | `_check_insert` / update 预检查 | 含同一条语句内部的重复 |
| 语句原子性 | `_check_insert`、update 的 `changes` | 先全部校验，再落地并写日志 |
| WAL 预写日志 | `_log` / `_append_wal` | 已提交的写语句先落日志再改内存 |
| 检查点与快照 | `_write_snapshot` | 事务进行中禁止 CHECKPOINT |
| 崩溃恢复（ARIES 的玩具版） | `_load` / `_replay` | 快照 + 重放 WAL；撕裂尾行丢弃 |
| 事务隔离（粗粒度） | `txn_snapshot` / `_restore` | BEGIN 存全量快照，ROLLBACK 还原 |
| 投影与别名 | `_projection` | `*`：单表出裸列名、多表出限定名；显式列以 SQL 里写的名字为键，`AS` 改名 |

## 一条 SELECT 的旅程（演示里能看到）

```
"SELECT name FROM users WHERE id = 3 ORDER BY score DESC LIMIT 5"
  tokenize   -> [('SELECT',...), ('ident','name'), ...]
  parse      -> ("select", ("users",None), ["name"], ("cmp","=",("col","id"),("lit",3)),
                 [("score",True)], 5, [], [None])
  _sources   -> [(别名, Table)] + [ON 条件]
  _col_map   -> 列名 -> 行内键（限定名不歧义，裸列名冲突时置 None）
  _check_col -> 执行前统一校验列，报错不等到扫描中途
  _plan      -> 主键上有等值/范围 -> range_scan，否则全表 items()
  _eval      -> 逐行求 WHERE（三值），_sort_key 做多键稳定排序
  _projection-> 只挑出要输出的列，包成 dict 返回
```

## 支持的 SQL 子集

```
CREATE TABLE t (col INTEGER|TEXT|REAL, ..., PRIMARY KEY (col)|PRIMARY KEY col)
INSERT INTO t VALUES (...), (...)          -- 多行；支持负数与 NULL 字面量
SELECT cols | * FROM t [别名] [INNER] JOIN t2 [别名] ON expr [WHERE] [ORDER BY] [LIMIT]
DELETE FROM t WHERE expr
UPDATE t SET col = 字面量, ... WHERE expr
BEGIN / COMMIT / ROLLBACK / CHECKPOINT
表达式：= != < <= > >=  IS [NOT] NULL  AND OR NOT  括号  列名（可用 表名.列名）
```

## 实现时踩到的坑（都是先跑出错误再修的）

1. **`UPDATE ... SET 主键 = 新值` 会悄悄弄坏索引**：只改 `rows` 不删旧键，
   之后 `WHERE id = 2` 会返回完全不相干的那一行。改完必须"删旧键 + 插新键"，
   并且插入前要检查新值是否已被别的行占用。
2. **多行 INSERT 中途失败留下半条语句**：第一行已写进内存、日志却没写，
   重启后内存和磁盘分叉。必须先整条校验，再落地。
3. **CHECKPOINT 落下未提交数据**：快照写的是"当前内存"，而事务中的改动已经在
   内存里了。不挡住 CHECKPOINT，ROLLBACK 就形同作废。
4. **事务里的 DDL 回滚不掉**：快照只存行数据的话，事务里 `CREATE TABLE` 建的表
   回滚后还留在内存里。`_snapshot` 必须连表结构和 `next_rowid` 一起存。
5. **WAL 最后一行撕裂会让整个库打不开**：崩溃时半条 JSON 记录被追加进去，
   `json.loads` 抛异常。只有"文件末尾且没有换行"的那一行可以安全丢弃，
   中间损坏必须报错——静默跳过等于丢数据。
6. **Windows 的 `\r\n` 让按字节截断砍错位置**：文本模式读出来的行数 ≠ 字节数，
   `f.truncate(len(前面几行))` 会砍进最后一条正常记录。日志统一按 LF 写、
   截断时整段重写。
7. **`SELECT *` 把内部字典直接吐出来**：为了支持限定列名，行里同时存了
   `users.id` 和 `id` 两份，直接返回会让每一列重复两遍。投影必须给出显式清单。
8. **`IS NULL` 被解析成 `= NULL`**：这样任何比较运算符撞上 NULL 都会被当成
   "判空"，`age > NULL` 竟然能选出行。`IS [NOT] NULL` 是独立节点，
   而 `= NULL` 永远是 UNKNOWN。
9. **三值逻辑的 AND/OR 短路写反**：`UNKNOWN OR TRUE` 应该得 TRUE，
   先判 NULL 就返回 UNKNOWN 是错的；`UNKNOWN AND FALSE` 同理应得 FALSE。
10. **主键是 TEXT 时索引范围扫描崩了**：用 `±inf` 表示"无界"会让
    `str` 和 `float` 比较直接 TypeError。改用 `None` 表示该侧无界。
11. **只看列名判断"内表主键"会连错表**：自连接时 `a.id` 和 `b.id` 的裸列名都是
    主键名，必须连别名前缀一起判，否则点查取错表。

## 测试策略（36 项）

- **B+ 树**：`order=4` 小阶数频繁分裂，800 键随机插入后与有序列表逐项对照；
  删除 600 个键的一半再对照；范围扫描与 Python 过滤等价。
- **解析**：记号/AST 结构、非法语句必须报错。
- **语义与约束**：负数字面量、TEXT 主键范围、三值逻辑真值表（`= NULL` vs
  `IS NULL`）、列不存在/歧义、列数不匹配。
- **原子性**：多行 INSERT 撞主键整条回退（含 `next_rowid` 不被白消耗）、
  UPDATE 撞主键被拒且不入 WAL、改主键后索引一致、删后再插同主键、
  事务内单条失败不影响事务继续。
- **计划正确性**：同一份数据，有主键（索引扫描）与无主键（全表扫）在 7 种
  WHERE 下结果必须一致；等值查询确实打印了"索引"计划。
- **事务与恢复**：快照 + WAL 混合恢复（重启两次结果稳定）、CHECKPOINT 后
  WAL 清空、撕裂尾行丢弃后仍可继续写、WAL 中间损坏拒绝打开、
  回滚还原行/索引/`next_rowid`/表结构、事务中禁止 CHECKPOINT。
- **JOIN**：INNER 语义（孤儿行、无匹配、空表）、别名与限定名、多表 `*` 的键、
  索引嵌套循环与全表扫两种计划结果一致、三表连接、外键为 NULL。
- **对拍 sqlite3**：200 行随机数据 + 300 轮随机 SELECT/UPDATE/DELETE，
  含 12 种 WHERE 条件（NULL、括号、NOT、OR）；另有 5 条 JOIN 查询对拍。

## 已知局限（写清楚，不含糊）

- **单进程、无并发**：没有锁与 MVCC；两个 `Engine` 同时打开同一个库会互相覆盖。
- **持久性是"最后一次提交可能丢"**：日志追加后没有 `flush`/`fsync`，
  进程被杀时操作系统缓存里的内容可能没到磁盘。真数据库必须 fsync 提交记录。
- **UPDATE 记整表镜像**：重放简单，日志体积随表大小线性增长。工程做法是前后镜像
  或物理页 + LSN。
- **只有主键索引，没有二级索引**：非主键条件一律全表扫。
- **主键为 NULL 的两行可以重复**（NULL 不建索引），这是简化的直接代价。
- **`JOIN` 只支持 INNER**，且 ON 只支持单个等值条件；没有 LEFT/RIGHT、
  没有自然连接、没有子查询、聚合函数、`GROUP BY`、`DISTINCT`、表达式运算
  （`SET score = score + 1` 不支持）。写成 `LEFT JOIN` 时 `LEFT` 会被当成
  表别名，报错信息会绕到"列不存在"上——这是别名的宽松规则带来的副作用。
- **`SELECT *` 在多表时用限定名作键**（sqlite 用裸名并让同名列互相覆盖）。
  写明的列则以 SQL 里写的名字为键：`SELECT users.id FROM users` 的键是 `users.id`，
  要短名就用 `AS`。
- **`ORDER BY` 不能引用 `AS` 别名。**

## 练习建议

1. 给 `age` 建二级索引，让 `WHERE age > 30` 也走索引，并处理"二级索引里存
   (age, rowid)、删除主键行时要同步"的问题。
2. 把 UPDATE 的日志从"整表镜像"改成"前后镜像 + LSN"，恢复时按 LSN 幂等重放。
3. 提交时 `f.flush()` + `os.fsync(f.fileno())`，再测一次"崩溃后是否丢提交"，
   体会 WAL 的 durability 到底靠什么保证。
4. 实现 `COUNT(*)`/`SUM(col)` 与 `GROUP BY`，注意它们要在投影之前算。
5. 支持 `LEFT JOIN`：内表无匹配时补 NULL，并想清楚 `ON` 与 `WHERE` 的差别
   （谓词下推会把 LEFT 退化成 INNER）。
