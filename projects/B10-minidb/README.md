# B10-minidb —— 带 WAL、页式快照与事务的教学型数据库

**课程映射**：数据库系统原理（B+ 树索引、关系代数执行、SQL 解析、恢复与事务）
**2026-10-02 扩展**：B41 候选①开题实施——持久性工程化（提交即 fsync + 页式快照 + 崩溃对账）。

不是"用数据库"，而是"写一个数据库"：词法/语法分析 → 计划器 → 执行器 →
B+ 树索引 → WAL 预写日志 → **页式快照（逐页校验和/双头槽位/坏页回退）** →
崩溃恢复 → BEGIN/COMMIT/ROLLBACK。压轴验收是**与 sqlite3 对拍**：
同一批随机 SQL 打到两个库上，结果必须逐行相同。

## 运行

```
run.bat                          # 自测（53 项：36 核心 + 17 持久性）+ 七段演示
python -m unittest discover -s tests     # 53 项（双入口同数）
python tests\test_minidb.py      # 只跑核心 36 项
python tests\test_durability.py  # 只跑持久性 17 项（含真子进程硬退的崩溃对账）
python demo.py                   # 七段演示（临时目录里建库，跑完即删）
python tools\logdiff.py a.log b.log      # 两次 run.bat 日志的规范化比对（只有【实测】毫秒在动）
```

`run.bat` 用纯 ASCII + CRLF + `chcp 65001` + `set PYTHONUTF8=1`。写它时踩过一次：`echo` 文案里
不能出现未转义的 `>`，cmd 会当成重定向——不报错、退出码照样 0，只是提示行被截断，
并在项目目录里凭空多出一个中文碎片命名的文件。已改成 `→`，另外 9 个项目的脚本一并复查。

## 目录

```
minidb/btree.py      B+ 树：数据只在叶子，叶子用链表串起来（范围扫描的本质）
minidb/sqlparser.py  词法 + 递归下降解析，输出 tuple 形式的 AST
minidb/engine.py     执行器 / 计划器 / 存储 / WAL / 事务 / 恢复（带 LSN 与 fsync 策略）
minidb/pager.py      页式快照：固定页 + 逐页 crc + 双头槽位 + 代追加/回退 + 压实（B41 候选①）
tests/test_minidb.py B+ 树压测、语义与约束、原子性、事务恢复、JOIN、sqlite3 对拍（36 项）
tests/test_durability.py 页文件单元 + 真子进程硬退崩溃对账 + LSN 交界窗口（17 项）
demo.py              七段演示：CRUD -> 计划器 -> 约束 -> JOIN -> 事务 -> 恢复 -> 持久性工程化
```

## 课程知识点 与 代码模块映射

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
| WAL 预写日志与 LSN | `_log` / `_append_wal` | 已提交语句先落日志（带单调 lsn）再改内存；恢复只重放 lsn > 快照 lsn |
| **提交即持久（durability）** | `_append_wal` 的 flush+fsync | durable 模式提交返回前 fsync；COMMIT 内多条语句**组提交**一次 fsync |
| **页式快照文件** | `pager.py` `PageFile` | 固定页 + 每页 (长度,crc32) 尾标；数据页 fsync 后切换头槽位 |
| **双头槽位与坏页回退** | `pager.py` `load()` | 头槽位 0/1 交替写；新代坏页 -> 回退旧代并留 warnings，两代都坏 -> 响亮报错 |
| 检查点与快照 | `_write_snapshot` | CHECKPOINT 写页式快照（含 lsn）-> 头落盘 -> 才删 WAL（写前次序） |
| 空间回收 | `pager.py` `_compact` | 浪费超过倍数阈值 -> 重写小文件 + 原子替换（此后不可回退，声明在案） |
| 崩溃恢复（ARIES 的玩具版） | `_load` / `_replay` | 快照（可回退一代）+ 按 lsn 重放 WAL；撕裂尾行丢弃 |
| 事务隔离（粗粒度） | `txn_snapshot` / `_restore` | BEGIN 存全量快照，ROLLBACK 还原 |
| 投影与别名 | `_projection` | `*`：单表出裸列名、多表出限定名；显式列以 SQL 里写的名字为键，`AS` 改名 |

## 持久性工程化（B41 候选①，2026-10-02）

**协议（先写死再实现）**：
1. 每条写语句带**单调 lsn**；日志行追加后 `flush + fsync`（durable 模式）才算"已提交"——
   **提交返回 = 已落盘**；事务里的多条语句**组提交**（一次 fsync）。
2. CHECKPOINT：快照负载（含 `lsn`）按固定页写成一个**代**，追加在文件尾部
   （新代不覆盖旧代）→ 数据页 fsync → 写非活动**头槽位**（seq 单调）→ fsync →
   **才**删除 WAL。任何一步崩溃，文件都停在一个自洽状态上。
3. 恢复：读双头槽位取最新完好代；**新代坏页/坏头 -> 回退旧代**，再看 WAL——
   若崩在"换头"与"删 WAL"之间，重放按 lsn 跳过已进快照的记录（不双放）。
4. 空间没边涨：浪费超过倍数阈值触发**压实**（重写 + 原子替换）。

**demo 第 7 段的计量（本机实测，跑 demo.py 可复现）**：
- 真子进程 `os._exit(0)` 硬退后重启：逐条对账"已提交的一条不少"；
- 100 次自动提交 INSERT：durable（每次 fsync）vs 非 durable 的毫秒对照；
- 页大小对照（同一份数据 CHECKPOINT 一次）：512/4096/16384 的**文件字节与数据页数**；
- 打坏最新代一个数据页：重新打开**回退到上一代**并打印警告原文。

**本机参考读数（2026-10-02 一轮实测，跨运行有波动）**：fsync 对照 71.9 ms vs 30.9 ms
（差 ≈41 ms/100 条 → 每次提交 fsync 约 0.4 ms，与 B41 基准的 8KB 写盘边际成本同量级）；
页大小 512 字节时 400 行快照占 19456 字节 / 21 数据页，4096 时 24576 / 3 页，16384 时 49152 / 1 页——
**页大省页数但放大写放大**，页小反之（这就是"页大小"要当参数实验的原因）。

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
12. **页式快照第一版把 trailer 写在了页中间**：数据页 = 块 + (长度,crc) + 零填充，
    读的时候 `page[-8:]` 取到的是填充零 → "负载长度不符：0 != 168"。
    **尾标必须在页的最末尾**（块 + 零填充 + trailer）——格式里每个字节的
    位置都是契约。
13. **换页长补零对齐写在 gen_offset 处**：`seek(gen_offset)` 之后才写
    `gen_offset - file_size` 字节的零填充，等于把真正的代内容又往后推了
    "填充长度"那么多字节——槽位指向的位置坐着的是一段零。补零必须**从 EOF 写**。
14. **Engine 只吃字符串路径**：`path + ".wal"` 撞上 `pathlib.Path` 直接 TypeError。
    公开接口要么只收 str、要么显式 `str(path)`——"看起来像路径"的类型太多了。

## 测试策略（53 项：36 核心 + 17 持久性）

**核心 36 项（原样保留）**：
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

**持久性 17 项（本轮新增，`tests/test_durability.py`）**：
- 页文件：往返（单页/多页）、槽位交替、**坏数据页回退旧代**、坏头槽位回退、
  单代损坏必须响亮报错、双槽位全坏必须报错、头区全零视为"尚无快照"、
  压实把文件压回有界、**页长可在两次打开之间变化**（代自描述）。
- 引擎：**真子进程 `os._exit` 硬退后已提交必在/未提交必不在**、
  崩在"换头未删 WAL"之间不双放（把 WAL 文件留回去精确复现）、
  CHECKPOINT 次序与统计、WAL 行携带单调 lsn、durable 开关、页长配置进快照头。

## 已知局限（写清楚，不含糊）

- **单进程、无并发**：没有锁与 MVCC；两个 `Engine` 同时打开同一个库会互相覆盖。
- **快照是"整库重写"**：页是**存储计量与校验单位**，不是行级分页——
  真数据库要"行/索引页 + 影子页或 WAL 物理页 + 增量检查点"，见练习建议 1。
- **压实之后不能回退**：压实重写的文件只有一个代；在压实与下一次 CHECKPOINT
  之间的新代坏页，只能靠 WAL 重放兜底（若 WAL 也被清掉，就得靠备份）。
- **fsync 的代价是真实存在的**：durable 模式每次提交都要等盘（demo 有本机读数）；
  "断电安全"只到"进程级崩溃 + 文件系统不撒谎"这一层（真掉电依赖盘/OS 语义，
  测试策略里如实声明）。
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

1. 把页式快照从"整库重写"升级到**行/索引增量分页**：B+ 树页落盘、根页号写进头槽位、
   CHECKPOINT 只写脏页——先量一次"改了 1 行要写多少页"，再决定值不值。
2. 把 UPDATE 的日志从"整表镜像"改成"前后镜像 + LSN"，恢复时按 LSN 幂等重放
   （现在只保证不重放旧记录，还做不到单条幂等）。
3. 给 WAL 加**组提交窗口**（攒 N 条或 T 毫秒一次 fsync），用 demo 第 7 段的
   计量方法量"吞吐 vs 崩溃窗口"的取舍。
4. 实现 `COUNT(*)`/`SUM(col)` 与 `GROUP BY`，注意它们要在投影之前算。
5. 支持 `LEFT JOIN`：内表无匹配时补 NULL，并想清楚 `ON` 与 `WHERE` 的差别
   （谓词下推会把 LEFT 退化成 INNER）。
