# 02 · 精简 SRS（宿舍报修系统）

> B15 产物。**这份文档里的三张表是规范性的（normative）**：它们不是给人看的说明，
> 而是 `spec/workorder.py` 的唯一出处，由 `checks/check_docs.py` 逐条比对。
> 改表不改代码、或改代码不改表，`run.bat` 当场红灯。
>
> 表格格式是机器约定：列名、取值集合都不能随手改（详见 `checks/check_docs.py` 里的解析器）。

## 1. 术语与枚举

| 枚举 | 取值 | 说明 |
|---|---|---|
| 角色 `Role` | `STUDENT` `WORKER` `ADMIN` | 学生（报修人）、维修员、管理员（宿管/派单人） |
| 状态 `State` | `DRAFT` `SUBMITTED` `ASSIGNED` `IN_PROGRESS` `RESOLVED` `CLOSED` `CANCELLED` | 草稿、待派单、已派单、维修中、已完工待验收、已关闭（终态）、已取消（终态） |
| 动作 `Action` | `submit` `assign` `reassign` `return_pool` `accept` `decline` `resolve` `confirm` `reject_check` `force_close` `cancel` `escalate` | 见第 3 节状态转换表 |
| 分类 `Category` | `WATER_ELEC` `NETWORK` `FURNITURE` `OTHER` | 水电、网络、家具、其他（假设值，AQ-06） |
| 优先级 `Priority` | `LOW` `NORMAL` `HIGH` `URGENT` | 时限见第 6 节 SLA 表 |

## 2. 功能需求（FR）

`验证入口` 一列：`T:` 开头表示本轮已有可执行测试（检查器会核实该测试确实存在），
`待验证(轮次)` 表示本轮无法执行、由后续哪一轮接手。**不允许留空，也不允许写一个不存在的测试。**

| ID | 需求 | 来源 | 验证入口 |
|---|---|---|---|
| FR-01 | 学生可新建报修草稿，填写宿舍编号、报修分类、优先级、描述与联系方式 | PLAN 批次 5 | `T:tests/test_workorder_spec.py::test_valid_order_accepts_minimal_fixture` |
| FR-02 | 草稿可反复修改后提交；提交动作是一次状态转换并校验字段 | 假设（ACT-01 怕填错） | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| FR-03 | 系统对必填与格式问题**一次性报出全部错误**，且不改工单状态 | B13/B14 的"收集所有错误"教训 | `T:tests/test_workorder_spec.py::test_validation_reports_all_problems_at_once` |
| FR-04 | 同一宿舍同一分类存在未进入终态的报修单时，提交前给出重复提示 | 假设（痛点 3） | `T:tests/test_workorder_spec.py::test_duplicate_open_order_detected` |
| FR-05 | 管理员查看待派单队列，并把工单派给指定维修员 | PLAN 批次 5 | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| FR-06 | 管理员可改派、可把已派单退回待派单队列 | 假设（ACT-03 要能纠偏） | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| FR-07 | 被派单的维修员可接单（进入维修中）或拒单（退回队列） | PLAN 批次 5 | `T:tests/test_workorder_spec.py::test_permission_matrix_matches_srs` |
| FR-08 | 维修员填写完工说明后标记完工，工单进入待验收 | PLAN 批次 5 | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| FR-09 | 报修学生可验收通过（关闭）或退回维修（回到维修中，同一维修员） | 假设（ACT-01 有发言权） | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| FR-10 | 管理员可在验收超时时强制关闭 | 假设（防止悬挂，AQ-03） | `T:tests/test_workorder_spec.py::test_permission_matrix_matches_srs` |
| FR-11 | 学生可取消自己的草稿或待派单工单；管理员可取消待派单/已派单工单并写明理由 | 假设 | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| FR-12 | 学生查询自己的报修单，可按状态与分类筛选 | PLAN 批次 5（最小链路含查询） | `T:tests/test_workorder_spec.py::test_visibility_matrix_matches_srs` |
| FR-13 | 维修员查询公共池（待派单）与派给自己的工单 | 同上 | `T:tests/test_workorder_spec.py::test_visibility_matrix_matches_srs` |
| FR-14 | 管理员可按宿舍编号、分类、状态、优先级筛选全部工单 | 假设（ACT-03 要汇总） | `T:tests/test_workorder_spec.py::test_filters_narrow_the_fixture_set` |
| FR-15 | 每次状态变更追加一条历史记录：谁、何时、从哪个状态到哪个状态、理由 | 假设（ACT-03 要追责） | `T:tests/test_workorder_spec.py::test_history_is_append_only` |

## 3. 状态转换表（**规范性**）

前置条件代码见第 4 节图例。`允许角色` 多个用逗号分隔。

| 转换 ID | 动作 | 起始状态 | 目标状态 | 允许角色 | 前置条件 |
|---|---|---|---|---|---|
| TR-01 | submit | DRAFT | SUBMITTED | STUDENT | owner,valid_fields |
| TR-02 | assign | SUBMITTED | ASSIGNED | ADMIN | assignee_required |
| TR-03 | reassign | ASSIGNED | ASSIGNED | ADMIN | assignee_required |
| TR-04 | return_pool | ASSIGNED | SUBMITTED | ADMIN | reason |
| TR-05 | accept | ASSIGNED | IN_PROGRESS | WORKER | assignee |
| TR-06 | decline | ASSIGNED | SUBMITTED | WORKER | assignee |
| TR-07 | resolve | IN_PROGRESS | RESOLVED | WORKER | assignee,resolution_note |
| TR-08 | confirm | RESOLVED | CLOSED | STUDENT | owner |
| TR-09 | reject_check | RESOLVED | IN_PROGRESS | STUDENT | owner,reason |
| TR-10 | force_close | RESOLVED | CLOSED | ADMIN | acceptance_timeout |
| TR-11 | cancel | DRAFT | CANCELLED | STUDENT | owner |
| TR-12 | cancel | SUBMITTED | CANCELLED | STUDENT | owner |
| TR-13 | cancel | SUBMITTED | CANCELLED | ADMIN | reason |
| TR-14 | cancel | ASSIGNED | CANCELLED | ADMIN | reason |
| TR-15 | escalate | IN_PROGRESS | SUBMITTED | ADMIN | reason |

三条从表里读出来、但值得单独写明的规则：

* `CLOSED` 与 `CANCELLED` 是**终态**，本表没有给它们任何出边（BR-02）。
  检查器会遍历 `状态 × 动作 × 角色` 全部组合，断言从终态出发一个都不允许——
  这条断言只有在"表里真的没有出边"时才成立，加了 reopen 动作就会红，逼我显式改文档。
* `reassign`（TR-03）是**状态不变的转换**：目标状态等于起始状态。
  模型必须允许"状态不变但 assignee 变、且留痕一条"的转换，否则派错人只能退回队列重派。
* `escalate`（TR-15）只给管理员，不给维修员。维修员修不动时**没有自助退回的通道**
  （只有被派单时的 `decline`），这是一个刻意的收紧，登记在 AQ-04。

## 4. 前置条件代码图例（**规范性**）

| 代码 | 含义 | 谁保证 |
|---|---|---|
| `none` | 无附加条件 | — |
| `owner` | 操作者就是该工单的报修学生 | 服务端比对，不信任前端（NFR-02） |
| `assignee` | 操作者就是该工单当前派给的维修员 | 服务端比对 |
| `assignee_required` | 请求必须携带一名在岗维修员 | 请求校验（FR-03） |
| `valid_fields` | 字段校验全部通过 | 见第 7 节字段规则 |
| `resolution_note` | 完工说明非空 | 见第 7 节字段规则 |
| `reason` | 必须给出理由文本 | 见第 7 节字段规则 |
| `acceptance_timeout` | 该单停留 `RESOLVED` 已满验收宽限期（第 8 节，默认 168 小时，可配置） | 服务端用注入的时钟算，不看前端传来的"多久了" |

## 5. 角色权限矩阵（**规范性**，与第 3 节交叉核对）

`允许` 表示该角色可以发起该动作；`—` 表示不可以。
**检查器会独立地从第 3 节的表聚合出"每个动作的允许角色集合"，再和这张表比对**——
两张表只要有一处不一致就红灯。写两遍不是冗余，是因为需求文档里"两处说法不一"正是缺陷的高发形态。

| 动作 | STUDENT | WORKER | ADMIN |
|---|---|---|---|
| submit | 允许 | — | — |
| assign | — | — | 允许 |
| reassign | — | — | 允许 |
| return_pool | — | — | 允许 |
| accept | — | 允许 | — |
| decline | — | 允许 | — |
| resolve | — | 允许 | — |
| confirm | 允许 | — | — |
| reject_check | 允许 | — | — |
| force_close | — | — | 允许 |
| cancel | 允许 | — | 允许 |
| escalate | — | — | 允许 |

## 6. 查询可见性矩阵（**规范性**）

| 角色 | 可见范围 | 说明 |
|---|---|---|
| STUDENT | OWN | 只看自己提的单（含自己的 `DRAFT`）；看不到别人的草稿 |
| WORKER | OWN_OR_POOL_OR_RESOLVED | `assignee` 是当前本人的单（`ASSIGNED`/`IN_PROGRESS`/`RESOLVED`）+ 全部 `SUBMITTED` 公共池 + **`resolved_by` 是自己的历史单**。终态仍然清空 `assignee`（第 12 节），"当前负责人"只有一个含义；查历史靠 `resolved_by`，它**只用于可见性、不参与权限判定**（AQ-12 已于 2026-10-01 裁决，见 BR-11） |
| ADMIN | ALL | 全部工单，含草稿 |

取值只允许 `OWN` / `OWN_OR_POOL` / `OWN_OR_POOL_OR_RESOLVED` / `ALL` 四个代码。检查器把文档里的代码与
`spec/workorder.py` 声明的代码比对；测试再用一份 12 单的样例数据**穷举**
`工单 × 角色`，按独立写出的谓词验证可见集合——文档、模型声明、模型实现三层必须同时一致。

草稿可见性是这张表里最容易被随手放过的点：`DRAFT` 只有本人和管理员能看到，
维修员看不到。理由是草稿内容可能不完整（甚至宿舍编号还没填），
把它推进公共池等于让维修员基于坏数据判断（AQ-07）。

## 7. 业务规则（BR）

| ID | 规则 | 出处/理由 |
|---|---|---|
| BR-01 | 提交后描述与联系方式不可修改；要改只能取消重提 | 假设默认值，AQ-01（改动会牵动 FR-02、留痕口径） |
| BR-02 | 终态不可复活：`CLOSED`/`CANCELLED` 没有任何出边 | 第 3 节表的可核对推论 |
| BR-03 | 一张工单同一时刻只有一个维修员（`assignee` 单值） | 假设；多班组协同不在范围（01 节） |
| BR-04 | `IN_PROGRESS` 的工单只能由当前 `assignee` 推进 | TR-07 的 `assignee` 前置条件 |
| BR-05 | 取消、退回公共池、验收退回必须给理由 | 第 3 节 `reason` 列 |
| BR-06 | 每次成功转换追加一条历史，历史不可修改、不可删除 | FR-15、NFR-01 |
| BR-07 | 同宿舍同分类且未进入终态的工单存在时，视为重复并提示 | FR-04 |
| BR-08 | SLA 从**首次进入** `SUBMITTED` 起算；改派、退回不重置 | 假设，AQ-02（否则来回推诿可以把时限洗成无限） |
| BR-09 | 归属判定（`owner`/`assignee`）在服务端完成，前端隐藏按钮不算防线 | NFR-02 |
| BR-10 | `force_close` 只在 `RESOLVED` 停留满验收宽限期（默认 168 小时，可配置）后才允许 | AQ-03 于 2026-10-01 裁决；第 8 节宽限期规则 |
| BR-11 | `resolved_by` 只用于可见性，**不参与权限判定**；终态的 `assignee` 仍清空 | AQ-12 于 2026-10-01 裁决；避免"当前负责人"有两种含义（第 6、12 节） |

## 8. SLA 表（**规范性**）

| 优先级 | 响应时限（小时） |
|---|---|
| LOW | 72 |
| NORMAL | 24 |
| HIGH | 8 |
| URGENT | 2 |

时限参数（**规范性**，`tools/export_contract.py` 把这张表原样写进契约，Java 与 Python 都读它，不许各自硬编码）：

| 参数 | 值（小时） | 出处 |
|---|---|---|
| `ACCEPTANCE_GRACE_HOURS` 验收宽限期 | 168 | AQ-03 于 2026-10-01 裁决（7 天，必须可配置） |

换算规则（BR-08 + 下面这条）也是规范的一部分：

* `sla_due_at = 首次进入 SUBMITTED 的时刻 + 时限小时数`。
* 逾期判定：`now >= sla_due_at` 且状态不是 `CLOSED`/`CANCELLED`/`RESOLVED`。
  已完工待验收（`RESOLVED`）不再算逾期——维修侧已经交付，球在学生和管理员手里（AQ-03 已裁决，见下）。
* **验收宽限期（AQ-03 于 2026-10-01 裁决）**：`RESOLVED` 停留时间超过 `ACCEPTANCE_GRACE_HOURS`
  （默认 **168 小时 = 7 天**，必须是配置项而不是硬编码）之后，管理员才可以 `force_close`；
  没到点就关闭是**拒绝**而不是"允许但没人管"。理由：不给阈值就等于"管理员随时可以替学生宣布修好了"，
  给了阈值才有可写的测试，也才有 AC-24。
* 宽限期的起算点是**最后一次进入 `RESOLVED`** 的时刻（`resolved_at`），不是 `submitted_at`：
  学生退回再修（`reject_check → … → resolve`）会重新起算，否则第一次验收就把学生的退回权吃掉了。
* 宽限期手算样例（测试里作为出处写死，防止"实现即定义"）：`resolved_at = 1000.0`、宽限 168 小时，
  `168 × 3600 = 604800`，`1000 + 604800 = 605800` → 到期时刻 `605800.0`；
  于是 `t = 605799.0` 强制关闭被拒，`t = 605800.0` 允许（边界取"达到即算超时"，与 `is_overdue` 同一口径）。
* 手算样例（测试里作为出处写死，防止"实现即定义"）：
  `NORMAL` 从 `t=1000.0` 起算 → 到期 `t=1000 + 24×3600 = 87400.0`；
  `URGENT` 从 `t=0` 起算 → 到期 `7200.0`。

## 9. 字段与校验规则（FR-03 的展开）

| 字段 | 规则 | 违反时的错误码 |
|---|---|---|
| `room` 宿舍编号 | 形如 `字母+2位数字-3位数字`（例：`A01-101`）；大小写归一为大写 | `ROOM_FORMAT` |
| `category` 分类 | 必须是第 1 节枚举之一 | `CATEGORY_UNKNOWN` |
| `priority` 优先级 | 必须是第 1 节枚举之一 | `PRIORITY_UNKNOWN` |
| `description` 描述 | 去掉首尾空白后长度 1..500；不得只有空白 | `DESCRIPTION_LENGTH` |
| `contact` 联系方式 | 11 位数字且以 `1` 开头（**假设的校园手机号格式**，AQ-08） | `CONTACT_FORMAT` |
| `reason` 理由 | 出现即必填，去空白后长度 1..200 | `REASON_REQUIRED` |
| `resolution_note` 完工说明 | 出现即必填，去空白后长度 1..500 | `NOTE_REQUIRED` |
| `assignee` 维修员工号 | 非空字符串，最长 32 | `ASSIGNEE_REQUIRED` |

校验必须**一次报全**（FR-03）：这是 B13/B14 两轮反复验证过的做法——
逐条报错会让提交者改一处跑一次，而"改一处引入一处"正是这种交互的产物。

校验参数（**规范性**，B18 追加：Java 侧读这张表，不许把长度抄成自己的常量）：

| 字段 | 最小长度 | 最大长度 | 格式代码 |
|---|---|---|---|
| `room` | 8 | 8 | ROOM_PATTERN |
| `description` | 1 | 500 | NONE |
| `contact` | 11 | 11 | CONTACT_PATTERN |
| `reason` | 1 | 200 | NONE |
| `resolution_note` | 1 | 500 | NONE |
| `assignee` | 1 | 32 | NONE |

`room` 的最小/最大都写 8 是因为它的规则是**固定长度**格式（`字母+2位-3位` = 8 个字符），
不是"1..8 以内都行"；写清这一点是为了让"上限"这一列不被读成弹性范围。
`格式代码` 只允许 `NONE` / `ROOM_PATTERN` / `CONTACT_PATTERN` 三个值，
它告诉实现"这个字段除了长度还要过正则"，而正则本身长什么样由上面的规则列写——
**检查器核对的是长度数字**，因为数字最容易被两边抄歪。

## 10. 非功能需求（NFR）

| ID | 需求 | 验证方式 |
|---|---|---|
| NFR-01 | 留痕不可篡改：历史记录只追加，任何"修改历史"的接口都不存在 | `T:tests/test_workorder_spec.py::test_history_is_append_only` |
| NFR-02 | 权限判定只在服务端：同一动作换个发起者就换个结论，与前端展示无关 | `T:tests/test_workorder_spec.py::test_permission_matrix_matches_srs` |
| NFR-03 | 一次提交的校验要么全过、要么收集全部问题，绝不"报错即吞掉状态"（失败后状态不变） | `T:tests/test_workorder_spec.py::test_validation_failure_leaves_state_unchanged` |
| NFR-04 | 中文字段在命令行与测试输出里不乱码（UTF-8 全链路） | `人工确认（B15）`——由 `run.bat` 的 `chcp 65001` + `PYTHONUTF8=1` 保证；PLAN §6 要求**看输出而不是只看退出码**，这一步只能人眼确认 |
| NFR-05 | 时间由外部注入，测试不许 `sleep`：SLA 与逾期判定接受显式 `now` | `T:tests/test_workorder_spec.py::test_time_is_injected_not_read` |
| NFR-06 | 待派单队列查询在 1 万单以内响应小于 1 秒 | `待验证（B20）`——本轮没有可运行系统，也没有真实数据量 |
| NFR-07 | 认证由外部提供，本系统不保存口令 | `待验证（B18）`；本期只有 IF-01 的接口声明 |

NFR-06、NFR-07 明确标"待验证"而不是打个勾，是因为 PLAN 第 6 节不许把没跑过的东西写成完成。

## 11. 外部接口声明（IF）

| ID | 对手方 | 我需要它什么 | 本期是否实现 |
|---|---|---|---|
| IF-01 | 校园统一身份 | 给定会话，返回角色与工号 | 不实现，模型入参直接接受 `(Role, actor_id)` |
| IF-02 | 通知通道（短信/推送） | 状态变更时通知相关人 | 不实现（01 节列为范围外），但 FR-15 的留痕是它未来的数据源 |
| IF-03 | 时钟 | 可信的当前时间 | 由调用方注入（NFR-05） |
| IF-04 | 存储 | 工单与历史的持久化 | 不实现；B18 用关系数据库，届时同一张状态表由 JUnit 对照（B20） |

## 12. 数据字典（工单字段）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | 字符串 | 是 | 工单号 |
| `reporter` | 字符串 | 是 | 报修学生标识（`owner` 判定用） |
| `room` | 字符串 | 是 | 宿舍编号，见第 9 节 |
| `category` | 枚举 | 是 | 见第 1 节 |
| `priority` | 枚举 | 是 | 见第 8 节 |
| `description` | 字符串 | 是 | 1..500 |
| `contact` | 字符串 | 是 | 见第 9 节 |
| `state` | 枚举 | 是 | 见第 1 节 |
| `assignee` | 字符串或空 | 否 | 当前维修员；`SUBMITTED`/终态下为空 |
| `resolved_by` | 字符串或空 | 否 | **最后处理该单的维修员工号**，`resolve` 时写入、之后不再清空；只用于第 6 节可见性，不参与权限判定（BR-11、AQ-12） |
| `resolved_at` | 浮点秒或空 | 否 | **最后一次**进入 `RESOLVED` 的时刻，验收宽限期起算点（BR-10） |
| `created_at` | 浮点秒 | 是 | 建单时刻（注入） |
| `submitted_at` | 浮点秒或空 | 否 | **首次**进入 `SUBMITTED` 的时刻，SLA 起算点（BR-08） |
| `sla_due_at` | 浮点秒或空 | 否 | `submitted_at + 时限`，由优先级表算出 |
| `history` | 记录列表 | 是 | 只追加；每条含 `at/from/to/action/actor/reason` |

`submitted_at` 特意与 `created_at` 分开：草稿可以先存着、之后再提交，
如果 SLA 从 `created_at` 起算，"早建晚提"就会凭空吃掉时限——这是第 8 节换算规则的一部分，
也是一条容易被实现者顺手简化掉、之后谁也发现不了的规则（测试 `test_sla_starts_at_first_submission` 盯着它）。

### 12.1 字段写入时机（**规范性**，B18 追加）

上一张表说"有哪些字段"，这张说"谁在什么时候写它"。B18 用 Java 重做时，
最容易出事的就是这一步：字典看懂了，写入时机各自理解，于是同一个字段在两边语义不同。
所以这一张也是规范，而且每行都必须挂一条**真实存在的测试**（检查器会去源码里找那个方法）。

| 字段 | 写入时机 | 由哪条测试钉住 |
|---|---|---|
| `assignee` | `assign`/`reassign` 写入；退回公共池、拒单、升级、进入终态时清空 | `T:tests/test_workorder_spec.py::test_assignee_cleared_when_leaving_assigned` |
| `resolved_by` | 仅 `resolve` 时写入操作者工号，之后**不清空**；只喂可见性，不参与权限（BR-11） | `T:tests/test_workorder_spec.py::test_resolved_history_is_visible_but_inert` |
| `resolved_at` | **每次**进入 `RESOLVED` 都重写（退回再修则宽限期重新起算，BR-10） | `T:tests/test_workorder_spec.py::test_acceptance_grace_is_configurable_and_blocks_force_close` |
| `submitted_at` | 首次进入 `SUBMITTED` 写入，之后任何转换都不改（BR-08） | `T:tests/test_workorder_spec.py::test_sla_starts_at_first_submission` |
| `sla_due_at` | 与 `submitted_at` 同一刻按第 8 节优先级表算出 | `T:tests/test_workorder_spec.py::test_sla_hours_match_srs_table` |
| `state` | 只由第 3 节的转换写；非法转换连历史都不追加（BR-02、NFR-03） | `T:tests/test_workorder_spec.py::test_illegal_transition_leaves_order_unchanged` |
| `history` | 每次成功转换追加一条，不可修改、不可删除（BR-06） | `T:tests/test_workorder_spec.py::test_history_is_append_only` |

字段名会被检查器与 `spec/workorder.py` 的 `Order` 数据类逐字比对——
**改了字段名而忘了改这张表，或者反过来，都会红灯**。
