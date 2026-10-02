# 09 · 平台层（B18：Java / Spring Boot 重做）

> 这一份文档回答 B17 留下的问题：**同一台状态机怎样不被写成三遍**。
> 答案是"不靠自觉"：Java 侧不抄表，只读 `contracts/workflow.json`；
> 而"读"这件事本身由 `checks/check_arch.py` 与 `VerdictParityTest` 双向核对。

## 1. 环境实测（先确认再动手）

| 项 | 实测值 | 结论 |
|---|---|---|
| PATH 上的 JDK | Zulu OpenJDK 21.0.12 | 不用它，见下一行 |
| `JAVA_HOME` | `C:\Program Files\Java\jdk-17`（17.0.12） | Spring Boot 3.3.5 官方支持 17，Maven 实际用的就是它 |
| Maven | 不在 PATH，但 `~/.m2/wrapper/dists` 里有 **3.9.12** 已解压 | 直接调用绝对路径，**不安装** |
| Spring Boot starter | 本地已缓存 3.3.5（web/jdbc/validation/test） | 零下载 |
| H2 / JUnit | h2 2.2.224、junit-jupiter 5.10.5 已缓存 | 零下载 |
| Hibernate/JPA | **未缓存** | 所以选 `JdbcTemplate`：既不下载，又能让 SQL 与事务边界露在外面 |
| 离线构建 | `mvn -o -B test` 全绿（23 项） | 已验证，不是推测 |
| 打包产物真启动 | `java -jar target/repair-platform-0.18.0.jar`（25 MB）监听 8083，HTTP 走通 | **第一次真启动就失败过**，见第 10 节第 ① 条 |
| 重启恢复（应用级） | 杀掉进程 → 用同一个 H2 文件再起 → R006 仍 `CLOSED`、`resolved_by=w-1`、5 条留痕顺序正确 | 真关真开，不是单测推断 |

## 2. 分层与包（**规范性**，与真实 import 双向比对）

| 层 | 包 | 允许依赖 |
|---|---|---|
| boot | `course.dormrepair` | `org.springframework.boot.*` |
| contract | `course.dormrepair.contract` | `java.*`, `com.fasterxml.jackson.*` |
| domain | `course.dormrepair.domain` | `java.*`, `course.dormrepair.contract` |
| infra | `course.dormrepair.infra` | `java.*`, `java.sql`, `course.dormrepair.domain`, `course.dormrepair.contract`, `org.springframework.jdbc.*` |
| app | `course.dormrepair.app` | `java.*`, `course.dormrepair.domain`, `org.springframework.transaction.*` |
| web | `course.dormrepair.web` | `java.*`, `course.dormrepair.app`, `course.dormrepair.domain`, `course.dormrepair.contract`, `org.springframework.web.*`, `org.springframework.http.*` |
| soap | `course.dormrepair.soap` | `java.*`, `javax.xml.*`, `org.w3c.dom.*`, `org.xml.sax.*`, `course.dormrepair.app`, `course.dormrepair.domain`, `course.dormrepair.contract`, `org.springframework.web.*`, `org.springframework.http.*` |
| config | `course.dormrepair.config` | 所有层（组合根，唯一允许认识 infra 的地方） |

三件事由这张表保证，且都被机器核对：

* **领域层不知道 Spring 也不知道 SQL**。`domain` 只 import `java.util.*` 与 `contract`；
  换存储、换框架都不需要动判定逻辑（docs/08 的 ADR-02 在 Java 侧同样成立）。
* **依赖方向单向**。`app` 不许认识 `infra`——本轮我自己违反了这条：
  `RepairService` 用 `instanceof JdbcWorkOrderRepository` 去够 `visibleFiltered`，
  于是出现一条文档没允许的 `app → infra` 边。修法是把方法提到端口上，而不是给边开后门。
* **没有第二份契约**。`java/` 下不许出现 `workflow.json` 的副本；
  构建时由 `pom.xml` 的 `<resource>` 从 `../contracts` 复制进 jar（`check_arch.py` 会查这件事）。

## 3. 状态机在 Java 里怎么读契约

`WorkflowContract`（record）装的是：15 条转换、12 个动作、权限映射、可见性代码、
SLA 小时表、`acceptance_grace_hours=168`、`field_limits`（长度与格式代码）、`field_errors`、
`field_effects`（字段写入时机）。

`StateMachine` 里**没有任何一张手抄的表**：

* 能不能转换 → 查 `contract.transitions()`；
* 谁可以 → 查转换行的 `roles`；
* 要填什么 → `requiredInputs()` 从 `requires` 推；
* 长度与错误码 → `FieldRules` 从 `field_limits` / `field_errors` 取；
* 宽限期 → `acceptanceDue()` 用 `acceptance_grace_hours`，且允许调用方覆盖（AC-24）；
* 可见性 → `visibleTo()` 按契约代码分支，`JdbcWorkOrderRepository` 用**同一批代码**拼 WHERE。

一个具体的顺序陷阱：`roles` / `requires` 在 Java 里用 `List` 而不是 `Set`。
Python 侧 `preconditions` 是 `tuple(sorted(...))`，两个条件同时不满足时报**第一个**；
如果 Java 用无序集合，同一情形可能报另一个码，1680 格对拍表就会假性分叉。

## 4. 一次动作的事务边界

`RepairService.act()` = 一个 `@Transactional`：读单 → 领域判定 → 带 version 写回 → 追加留痕。

* 乐观锁：`work_order.version`，`UPDATE … WHERE id=? AND version=?`；影响行数不是 1 就返回 false，
  上层翻成 `409 CONCURRENT_UPDATE`。**不覆盖别人的结果**，也不静默重试。
* 留痕：`work_order_change(order_id, seq)` 主键，按 seq 续写；被拒的转换一条都不写。
* 工单号：H2 序列 `order_seq` 原子取号。"读最大值 +1"在并发下会发出两个同号单（B31 的教训）。
* DDL 由契约生成（`Schema.ddl(contract)`），字段长度不手抄；契约里缺 `field_limits` 就直接拒绝启动。

## 5. 跨语言对拍：1680 格判定逐格相同

`tools/export_verdict_table.py` 用固定序列造出 7 个状态的代表工单，穷举
`状态 × 动作 × 角色身份 × 输入齐全/缺失 × 时刻(宽限内/外)` 共 **1680 格**，
每格记 `OK:目标状态` 或 `ERR:错误码`。Java 侧 `VerdictParityTest` 独立重算同一张表。

实测的错误码分布（Python 侧生成，`--check` 可复现）：
`NO_SUCH_TRANSITION 1400`、`ROLE_NOT_ALLOWED 188`、`OWNER 20`、`ASSIGNEE 12`、
`REASON_REQUIRED 10`、`ASSIGNEE_REQUIRED 4`、`NOTE_REQUIRED 2`、`ACCEPTANCE_NOT_MATURE 2`。

为什么不只对拍转换表：转换表只说*允许*什么；会分叉的是**拒绝路径**——
先查角色还是先查前置条件、多个条件同时不满足报哪一个、到期时刻算不算逾期。
这些只有在两边都跑一遍同一次判定时才暴露。

**牙齿是验过的**：把 Java 的到期判定从 `now < due` 改成 `now <= due`，对拍立刻报
`RESOLVED|force_close|ADMIN|adm-1|empty|608800.0：Python OK:CLOSED vs Java ERR:ACCEPTANCE_NOT_MATURE`
（2 格分叉），改完还原、校验和一致。

反过来也补了一条：先改成 `isAcceptanceStale` 的 `>=` → `>` 时 **22 项测试全绿**——
说明对拍表管的是判定路径，视图标志位没人管。于是加了
`staleFlagAndDecisionShareOneBoundary`（阈值边界 + 与判定同口径）和 HTTP 层的
`acceptanceStale` 断言；重跑同一变异，新测试当场红。

## 6. 本轮实现的需求裁决

| 裁决 | 落在哪里 | 怎么被验 |
|---|---|---|
| AQ-02 SLA 72/24/8/2 且不重置 | `sla_hours` 契约 + `submitted_at` 只在首次进入时写 | `canonicalHappyPath…` 断言改派后仍是 87400.0；Python 侧穷举走查有同一条不变式 |
| AQ-03 验收宽限 168 小时、仅管理员、系统不自动关 | `acceptance_grace_hours` + 前置条件 `acceptance_timeout`（TR-10） | `forceCloseNeedsTheGracePeriodButAcceptsAConfiguredOne`（409 → 配 0 小时则 200）；AC-24 已从"待验证"转为可执行 |
| AQ-12 维修员可见自己处理过的历史单 | `resolved_by` 字段 + 可见性代码 `OWN_OR_POOL_OR_RESOLVED` | `workerHistoryVisibilityOverHttp`（w-1 看得见、w-2 看不见、`attemptable` 为空） |

三条都是用户回答"无偏好"后由我按推荐值定的，**性质仍是假设**，登记在 `docs/05`。

## 7. 明确不做（防止下一轮顺手加戏）

* **不做认证**。身份仍是 `?role=&actor=` 查询参数。真实令牌属于 B21/B22；
  之所以敢先上：授权判定全在领域层，换成真令牌不需要改任何一条规则。
* 不做 ORM、不做连接池调优、不做缓存与消息队列（B19/B20 的范围）。
* 不做前端。界面继续用 B16 的原型壳；Java 只提供 `/api`。
* 不做分布式与多实例时钟（AQ-05 仍未裁决）。
* 不测性能。并发测试只验"不覆盖"，不宣称吞吐数字。

## 8. 这份文档自己怎么被验证

| 声明 | 核对方式 |
|---|---|
| 第 1 节环境数字 | `run.bat` 第 1 步打印 `java -version` / Maven 版本；离线构建失败就会红灯 |
| 第 2 节分层表 | `checks/check_arch.py` 逐文件扫 `java/src/main/java` 的 `import`，与表**双向**比对；`java/` 下出现契约副本也报 |
| 第 3 节"没有第二台状态机" | `WorkflowContract.SUPPORTED_SCHEMA_VERSION` 不等于契约版本就拒绝启动；`VerdictParityTest` 对 1680 格 |
| 第 4 节事务与乐观锁 | `RepositoryTest`：stale version 被拒且不覆盖、两线程恰好一个写者、文件库重启后数据与留痕都在 |
| 第 6 节三条裁决 | 上面三行测试 + `docs/04` 的 AC-24/AC-40 指向真实存在的测试方法 |

## 9. 命令

```
# 一次性：离线构建 + 全部 Java 测试（约 25 秒）
cd java && mvn -o -B test

# 打包并真启动（H2 文件库，重启数据还在）
cd java && mvn -o -B -DskipTests package
java -Dfile.encoding=UTF-8 -jar target/repair-platform-0.18.0.jar

# 判定表重生成 / 核对
python tools/export_verdict_table.py --write
python tools/export_verdict_table.py --check
```

Windows 注意：Java 17 的 `file.encoding` 默认仍是平台码页（本机 GBK），
带中文的判定理由必须 `-Dfile.encoding=UTF-8`，否则断言会看到乱码——
surefire 已在 `pom.xml` 里配了 `argLine`，跑 jar 时要自己加。

## 10. 本轮真缺陷（按"发现方式"记，不按严重程度）

① **`AUTO_SERVER=TRUE` 与 `DB_CLOSE_ON_EXIT=FALSE` 不能共存**：H2 直接
`Feature not supported`，应用起不来。为什么 22 项测试全绿也没发现？
因为测试用内存库、且从没跑过打包产物——**"测试通过"和"能交付"不是一回事**。
修法：删掉 `AUTO_SERVER`，并把"真起 jar + 真发请求"写进这一节的验收。

② **详情接口复用列表查询，于是 `history` 永远是空数组**。状态、处理人都对，唯独留痕没有。
这种 bug 最阴：它不会让任何一条现有断言变红，除非你恰好去数历史条数。
发现方式恰恰是我去 curl 真接口而不是看测试输出。修法：详情走 `one()`（含 join），
并加断言"列表与详情的留痕条数必须一致"。

③ 修完 ② 又发现列表/详情**语义不一致**才是根因：列表固定返回空 history，
等于同一个字段名有两种含义。改成列表也批量补留痕（一条 `IN` 查询，不打 N 次）。

④ **MSYS 的 curl 会把命令行里的中文按 GBK 交给原生程序**，我一度以为是应用编码坏了。
用 Python 显式 UTF-8 发同一条请求，描述**逐字节相同**（17 字符 → 17 字符）。
教训：判定"是谁的锅"之前，先把工具链换一条路径。

⑤ `roles` / `requires` 在 Java 里必须是 **List 而不是 Set**：两边前置条件的检查顺序
决定"多个条件同时不满足时报哪一个码"，用无序集合就会假性分叉 1680 格表。

⑥ **H2 内存库随最后一条连接关闭而销毁**，而 `DriverManagerDataSource` 每条语句开一条新连接——
建表第一条执行完库就没了，第二条报 `Table WORK_ORDER not found`。加 `DB_CLOSE_DELAY=-1`。

⑦ 我自己写了 `app → infra` 的 `instanceof` 越界依赖，被新加的 Java 分层核对抓到方向正确——
但它是**我先写完再补的核对器**，所以是我自查出来的，不是被拦下来的。把方法提到端口上解决。

⑧ 开工前的离线探针上过一次当：`mvn -o test` 返回 `BUILD SUCCESS`，
但测试类叫 `T.java`，不匹配 surefire 的 `*Test.java` 命名，**一个测试都没跑**。
改名后立刻报 `Tests run: 1`。和 B16 那两次"退出码 0 不代表交付"同源。

⑨ **`run.bat` 的 Java 步骤我写成 `"%MVN" -o -B test`——少了一个百分号**，cmd 于是去找一个叫 `"MVN"`
的程序，报 `'"MVN"' is not recognized`，**而脚本退出码照旧 0**。
第一版只看了退出码就记为"跑通"，是第二次连跑 + grep `not recognized` 才暴露。
修法：把这段挪进 `tools/java_build.py`（Python 里 glob 定位 Maven，失败由 `|| exit /b 1` 传播）。
这是同一条坑第四次换面貌出现（B14 的 goto、B31 的中文 rem、B16 的长中文 echo、这次是变量名写歪）。

⑩ 我自己的**计数解析器把 23 个测试报成 46**：`mvn` 输出里既有"每个类一行 `Tests run:`"
又有"最后一行总计"，我把两种都相加了。修法是让两个来源互相核对——
逐类之和必须等于总计行，不等就判失败（`TestJavaBuildReporter` 四条断言盯着）。
刚给自己立了"SUCCESS 不等于跑了测试"的规矩，转头就在新造的指标上犯了同一类错，
这条比前面任何一条都更值得记：**新增度量时，先证明它会失败。**

⑪ 文档与记忆里的旧事实被本轮推翻：`Maven 未安装` 只对 `PATH` 成立，
`~/.m2/wrapper/dists` 里躺着重度使用中的 3.9.12。**"命令找不到"≠"没有安装"**，先查缓存再谈下载。
