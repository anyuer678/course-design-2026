# B29-bigdata-spark —— 工业日志的 PySpark 清洗、聚合与 Spark SQL（工业大数据处理技术）

**课程映射**：工业大数据处理技术（PLAN 批次 6，安装决策点②）。

一句话：**大数据的"对"仍然要对拍**——同一份日志，Spark（DataFrame API）与
"最笨但最可信"的纯 Python 参照逐行相等；**清洗的账要能对上**——缺陷按已知数量注入，
Spark 的分类计数必须与账本逐类相符；**倾斜不是形容词**——同键同分区的行数分布
2.51 倍（确定性读数）就是它的量尺，salting 的对策以"结果与直接 groupBy 逐行相等"背书。

**环境声明（决策点②的落实）**：经用户批准安装 **pyspark 4.2.0**（用户级 pip）。
体积如实登记：**下载约 317MB，安装后实测占用 503MB**（其中 jars 477MB）——
比建议表里的"~300MB"大：那是压缩包体积，**安装体积要按解压后算**（本仓库第一条实测记录）。
JVM 用本机既有 Zulu JDK 21 / JDK 17（无需新装）。

**范围声明**：local 模式；日志清洗（四类坏行分类 + 与注入账本对账）、聚合
（device×level / 每小时错误 / top 错误码）、同一批查询的 **DataFrame 与 Spark SQL 双实现**、
倾斜实验（分区分布 + salting 两阶段聚合）。**不做**：GB 级扩量（先确认磁盘/内存预算再谈）、
Streaming、真集群、UDF/性能调参。

## 运行

```
run.bat                                          # 三步：25 项测试 → 六段演示 → 展示页新鲜度（约 3.5 分钟，Spark 起停占大头）
python -m unittest discover -s tests             # 25 项（17 核心 + 8 展示页；核心约 45s）
python tests\test_spark.py                       # 17 项核心（直跑入口）
python demo.py                                   # 六段；数据写在 build\
python tools\showcase.py --write                 # 重生展示页 web\showcase.html（--check 过期即红）
python tools\logdiff.py a.log b.log              # 两次 run.bat 日志的规范化比对（见下"日志怎么比"）
```

## 目录

| 路径 | 是什么 |
|---|---|
| `sparklab/session.py` | 会话入口：**PYSPARK_PYTHON 坑**、in-memory catalog、warehouse 进临时目录、进度条关闭、shuffle 分区数收缩 |
| `sparklab/genlog.py` | 合成工业日志：四类缺陷按账本注入 + 键倾斜开关 |
| `sparklab/clean.py` | 纯 Python 清洗：坏行四类分类（与 Spark 侧同一套正则与优先级） |
| `sparklab/reference.py` | 纯 Python 参照聚合（Counter + sorted） |
| `sparklab/jobs.py` | Spark 版：DataFrame API 与 Spark SQL 双实现（rlike 复刻清洗规则） |
| `sparklab/skew.py` | 倾斜：分区行数分布 / salting 两阶段 / 结果对拍 |
| `tests/test_spark.py` | 17 项测试（账本对账 / 逐行对拍 / 手工六行样例 / 空输入 / 倾斜正确性） |
| `tools/logdiff.py` | 日志规范化比对器（时间戳 / 清理播报 / 计时数字三类噪声，规范统计可审计） |

## 知识点 · 实现 · 怎么被验证

| 课程知识点 | 代码 | 验证方式 |
|---|---|---|
| 数据质量与注入账本 | `genlog` + `clean` | 四类缺陷按已知数量注入；清洗隔离计数**逐类相等**（小样本与 40 万行各一遍） |
| 清洗规则"同一把尺子" | `clean.classify_line` vs `jobs.parsed` | 同一套正则常量 + 同一优先级（CASE WHEN 对应 if-elif）；**逐行对拍 1986 行** |
| Spark 与纯 Python 对拍 | `jobs` vs `reference` | device×level（24 行）、每小时错误、top 错误码（k=1/3/5）全部逐行相等 |
| DataFrame 与 Spark SQL 同引擎 | `jobs.sql_*` | 同一视图上 SQL 三查询 == DataFrame 三查询 == 纯 Python 参照 |
| 空值语义与优先级 | `jobs.parsed` | 手工六行样例（含"多缺陷行只归第一类"）逐类计数断言 |
| 分区与倾斜 | `skew.partition_row_counts` | `repartition(4,'device')` 分布 [55k, 82.5k, 55k, **207k**] → 倾斜比 **2.51**；随机重分区 1.00 |
| salting 两阶段聚合 | `skew.salted_group_count` | 结果与直接 groupBy **逐行相等**（含热键 dev-01=207159）；测试钉住 |
| 边界 | `test_empty_input` | 空输入：分类计数 {}、聚合空列表（不是崩） |
| 日志可比性 | `tools/logdiff.py` | 两次 run.bat 日志规范化后**逐字相同（各 85 行）**，规范统计两侧对称 |

## 实测（2026-10-02，首次交付；数字均为本轮现算）

- 测试：**25 项全过（17 核心 + 8 展示页）**；discover 25 = 直跑 17 + 展示页 8
  （核心约 45s——Spark 会话只起一次；展示页测试每次 collect 真跑一遍约 30 秒的演示，这是设计成本）。
- 数据：40 万行 / 23.1MB；账本 {bad_timestamp 40, bad_level 32, missing_field 24, bad_code 16}，
  Spark 分类计数逐类相等、清洗后 399,888 行 == 真值。
- 对拍：device×level 24 行、每小时 24 行、top 错误码 [(404,118),(500,113),(503,101)]——
  DataFrame == SQL == 纯 Python，全部 True。
- 倾斜：按 device 重分区分布 [55080, 82514, 55135, **207159**] → **比值 2.51**；
  随机重分区 [99971×4] → 1.00；salting 结果 == 直接 groupBy。
- 耗时（本机 local[2]，热身 2 次后实测一次）：plain **173ms** / salted **250ms**——
  **MB 级本地数据上 salting 更慢**（两次 shuffle 的开销大于倾斜代价）。
  这不是失败：它说明"什么时候该用 salting"要拿数据规模与倾斜代价算账，README 不做口号式推荐。
- `run.bat` 连跑两次退出码 **0**、`build/` 之外无新增、`not recognized` 0；
  两次日志经 `tools/logdiff.py` 规范化后逐字相同（规范三类噪声的条数两侧一致）。

**日志怎么比（B29 特有）**：Spark 日志里有三类**机器噪声**——JVM 时间戳、
Windows taskkill 的进程清理播报（出现位置与 PID 不稳定）、实时测量值（计时）。
比对前用 `tools/logdiff.py` 规范化，它会把"规范掉了哪几类、各几行"打印出来供审计；
除这三类外必须逐字相同。这是把"声明式免责"换成"机制化核对"（同 B8 的去计时行做法）。

## 展示页（2026-10-03 展示层批次⑨）

`web/showcase.html` 由 `tools/showcase.py` 真跑 `demo.py` 现算——**只取 stdout**（Spark 的 JVM 日志
在 stderr，天然不进页面）；**四条规范化**：warehouse 临时目录→`<临时目录>`、生成 40 万行用时→
`<当场>`、第 6 段耗时列→`<当场>`、JVM 退出清理行（含 PID，每次必不同）整行移除并留计数说明。
页内三个页签：六段原文 / 清洗对账账本（逐行读数表）/ 倾斜实验（分布读数 + 读法说明）。
**25 项（17 核心 + 8 展示页）全过**；三步 run.bat 两跑退出码 0/0、logdiff 规范化后逐字相同
（原始各 94 行→规范后 88 行；规范项两侧对称：JVM 时间戳 4 / 进程清理播报 6 / 单测计时 1 /
warehouse 临时名 1 / 生成耗时 1 / 实测耗时 1）。

## 坑（都留了钉子）

1. **`PYSPARK_PYTHON` 必须显式指向完整解释器**：默认拉起 `python3`，而本机 `python3` 是
   **Microsoft Store 的占位桩**（`WindowsApps\python3`）——worker 起不来，JVM 等回连超时，
   报 `Python worker failed to connect back`。A/B 对照：设了就过、不设必挂。
   落实在 `sparklab/session.py`（比用户手动 export 更不容易漏）。
2. **"~300MB"是下载体积不是安装体积**：实测安装占用 **503MB**（jars 477MB）。
   体积登记必须写清"下载/安装"两个口径。
3. **`[0-2]\d` 会放行 25 点**：第一版时间戳正则让 `25:02:03` 过关（测试期望对了、正则错了）。
   修正为 `([01]\d|2[0-3])`，并且 Python/Spark 两侧**共用同一常量**防漂移。
4. **`winutils.exe` 找不到只是 WARN**：本地模式（`file://` + in-memory catalog）不需要它；
   真正致命的是第 1 条的 worker 起不来——报警要看清楚再治。
5. **对拍前先钉契约**：`msg=` 前缀剥不剥、`code=` 只留三位——两边写成同一句话，
   否则"对拍"会红在契约分歧上而不是实现错误上。
6. **进度条是日志逐字比对的敌人**：`spark.ui.showConsoleProgress=false` 关掉；
   关不掉的噪声（时间戳/PID/计时）用 `tools/logdiff.py` 规范化并**报告规范条目**。

## 明确不做（本期范围外）

GB 级扩量（PLAN 原话：先确认磁盘/内存预算；本机当前用 23MB 数据全链路可复现）、
Streaming / Structured Streaming、多节点集群与资源调度、UDF 与 Catalyst 深度调参、
AQE 自动倾斜处理的开关对比（留作练习）。

## 练习建议（G2，自己动手）

1. 把 `skew_device_ratio` 调到 0.8、数据提到 200 万行，重测 plain/salted 耗时，
   找出"salting 开始划算"的拐点，并解释它和 shuffle 分区数的关系。
2. 打开 AQE（`spark.sql.adaptive.enabled=true` + `skewedJoin.enabled`），
   对比显式 salting 与 AQE 自动处理的耗时与结果——说清"引擎已经会做什么、我们为什么还要懂"。
3. 给清洗加第 5 类缺陷（如 device 名不存在），先把注入与两侧实现同步改、
   再看哪些测试红了——体会"契约先行"。
4. 用 `.explain(True)` 看三条 SQL 的物理计划，指出 Exchange（shuffle）分别出现在哪一步，
   与 `skew.py` 的分布读数对上。
