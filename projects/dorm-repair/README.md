# dorm-repair · 宿舍报修系统（B15 需求 + B16 交互 + B17 体系结构 + B18 平台层 + B19 双接口 + B20 测试工程 + B21 质量保证 + B22 项目管理）

这个目录是 **B15–B22 八个阶段共用**的业务目录（PLAN 第 5 节批次 5）。
B15 交付**需求**（SRS、用例、故事与验收标准、追踪矩阵 + 核对脚本）；
B16 交付**交互设计**（线框约定、四态规范、可访问性 + 一个真的能点起来走查的原型）；
B17 交付**体系结构**（分层与依赖方向、三条 ADR、机器可读契约，以及一个"依赖图是测出来的"核对器）；
B18 交付**平台层实现**（`java/`：Spring Boot 分层单体 + H2 + 事务与乐观锁 + 1680 格跨语言对拍）；
B19 交付**第二种接口形态**（手写 SOAP 1.2 + 由契约生成的 WSDL，零下载）；
B20 交付**测试与验证工程**（最小反例收缩、需求风险量化、变异自检台、分层流水线）——
问的不是"检查有没有通过"，而是"**检查自己会不会失效，失效了谁会响**"。
仍然**不是可上线系统**：没有真实认证、没有部署、没有前端接 Java、没有 CI 服务器。

一句话概括这几轮的做法：**需求文档里的表是可执行的，也是可被别的语言消费的**。
文档说 15 条转换、权限矩阵 12 个动作、可见性三种角色、宽限期 168 小时，
`spec/workorder.py` 就必须一模一样，`checks/check_docs.py` 逐格比对，测试再从文档独立誊一份期望值做第三方，
Java 侧只许**读契约**不许抄表，最后两边逐格对判定——
**"文档写了一套、代码做了另一套、另一个语言又做了第三套"这件事不允许靠人记得去核对。**

## 产物清单

| 路径 | 是什么 | 谁核对它 |
|---|---|---|
| `docs/01-scope.md` | 范围、在/不在范围内、**来源声明**（我没做过任何真实调研） | 人工走查（B16 复核） |
| `docs/02-srs.md` | FR 15 / BR 11 / NFR 7 / IF 4 + 三张**规范性表**（状态转换、权限矩阵、可见性矩阵）+ SLA 与宽限期表 + 字段规则与**校验参数表** + 数据字典与**字段写入时机表** | `checks/check_docs.py` |
| `docs/03-use-cases.md` | 用例 6 个：角色、前后置、主流程、扩展流、异常流 | 检查器（覆盖关系） |
| `docs/04-user-stories.md` | 故事 13 个 + 验收标准 40 条（Given/When/Then） | 检查器（每条 AC 的验证入口必须能落地） |
| `docs/05-open-questions.md` | **12 条待决问题**：我替真实用户做的判断、默认值、影响面、谁裁决 | 人工（需求评审） |
| `docs/06-wireframes.md` | B16：五个视图的文字线框 + 元素与需求回链 + **四态（正常/加载/空/错误）约定** + 可访问性规范 | `tests/test_prototype.py`（落点与契约） |
| `docs/07-walkthrough.md` | B16：20 步浏览器走查清单，**结果列全部留空**等用户填写 | 覆盖率有测试（13 个故事都要有条目），**结果由人填** |
| `docs/08-architecture.md` | B17：约束、三种风格的**实测指标表**、分层职责、**依赖方向表**、横切关注点、不做清单 | `checks/check_arch.py`（两张表都要与实测相等） |
| `docs/adr/ADR-01…03` | B17：三条决策记录（单体 / 判定源唯一 / 契约文件），每条含背景·决定·备选·后果·验证方式 | `check_arch.py::check_adrs`（五节齐全、被引用、无孤儿） |
| `contracts/workflow.json` | B17：**由 SRS 现算的机器可读契约**（转换、权限、可见性、SLA、宽限期、校验参数、字段写入时机、错误码），供 B18/B20 消费；v2 | `export_contract.py --check` + `check_arch.py` 三方比对 |
| `contracts/verdict_table.json` | B18：**1680 格判定表**（状态 × 动作 × 身份 × 输入 × 时刻 → 目标状态或错误码），跨语言对拍的基准 | `tools/export_verdict_table.py --check` + Java `VerdictParityTest` |
| `tools/export_verdict_table.py` | 用固定序列从 `spec` 现算判定表（**故意只测拒绝路径**） | `tests/test_architecture.py`（含"改坏模型必须让表变红"） |
| `docs/10-soa.md` | B19：为什么选 SOAP 不选 gRPC（**本机依赖实测**）、双接口覆盖范围、**状态字面量白名单**、WSDL 由契约生成、本轮真缺陷 4 条、明确不做 | `check_arch.py::check_java_state_literals`（双向）+ Java 对拍 |
| `docs/09-platform.md` | B18：环境实测数字、**Java 分层表（与真实 import 双向比对）**、契约消费点、事务边界、对拍结论、**本轮真缺陷 11 条**、明确不做 | `check_arch.py::check_java` |
| `java/` | B18：Spring Boot 3.3.5 分层单体（`contract/domain/infra/app/web/config`），H2 + JdbcTemplate + 乐观锁 + REST | 37 项 JUnit 测试（离线 `mvn -o test`）+ `check_arch.py` 扫 import |
| `tools/export_contract.py` | 文档 → 契约的导出器；三方不一致就拒绝产出 | `tests/test_architecture.py` |
| `checks/check_arch.py` | 架构核对器：真实 import 边与文档声明、契约三方、ADR 完整性、新文档 ID 不悬空 | `tests/test_architecture.py`（含故意改坏的反向测试） |
| `arch/style_probe.py` | 同一个用例在三种风格下的结构指标对照（**共用同一份 `spec`**） | `test_style_metrics` 等；文档表必须等于实测输出 |
| `prototype/server.py` | B16：走查原型的服务（复用 B11 的 netlab + B15 的模型） | `tests/test_prototype.py` |
| `prototype/web/` | B16：`index.html` / `app.js` / `style.css` / `favicon.svg`，只用 `textContent` 建节点 | 静态契约测试 + `node --check` |
| `spec/workorder.py` | 可执行需求模型：状态机、权限、可见性、字段校验、SLA、只追加留痕；B16 又加了 `attemptable()` / `required_inputs()` 供界面读取 | `tests/` |
| `checks/check_docs.py` | 文档-模型-矩阵三方一致性检查器（`--write` 重新生成矩阵） | `tests/test_docs_consistency.py` |
| `traceability.csv` | 追踪矩阵，**由文档生成**，不是手工维护的账本 | 检查器比对内容 |
| `docs/11-testing.md` | B20：四件验证产物各自"能被什么弄红"、流水线 9 层实测耗时、本轮 4 次自欺记录、14 条反向探针清单、明确不覆盖什么 | `tests/test_pipeline.py` + `tools/pipeline.py` 的 mutation 层 |
| `tools/shrink.py` | B20：把反例动作序列缩到最小（ddmin），并用 BFS **独立**算一遍最短；两者必须相等 | `tests/test_shrink.py`（10 项 / 23 subTest） |
| `tools/consequences.py` | B20：把 AQ-10（循环无上界）与 AQ-11（优先级自选）的后果**量化**成可核对数字 | `tests/test_consequences.py`（11 项 / 4 subTest，含"测量必须响应"） |
| `tools/mutation_check.py` | B20：变异自检台——12 条变异 + 1 条阴性对照，每条都要把对应核对器弄红 | `tests/test_mutation_check.py`（8 项 / 21 subTest）+ `pipeline` 的 mutation 层 |
| `tools/pipeline.py` | B20：9 层本地离线流水线；**退出码 0 但读不到数＝红**；每层报耗时与读数 | `tests/test_pipeline.py`（8 项 / 18 subTest） |
| `docs/13-project-plan.md` | B22：计划与范围——七轮实际做了什么/明确不做（分『决定不做』『环境所限』『延后』三种），外加**指标一览表**：台账 27 个键每个都被引用一次 | `checks/check_pm.py`（`pm` 层）+ `tests/test_pm.py` |
| `docs/14-risk-register.md` | B22：风险登记册——每条**未裁决** AQ 必须在册（少一条就红），9 条工程风险每条都写"怎么知道它发生了" | `checks/check_pm.py`（漏登记/把已裁决当未决都会红） |
| `docs/15-retrospective.md` | B22：复盘——坑按"只有跑起来才知道 / 已有规则本可避免 / 本次实现自身的技术错"分类，并列出三条**跨轮复发**的模式 | `checks/check_pm.py`（分类必须恰好覆盖全部编号，重号漏号都红） |
| `tools/project_ledger.py` | B22：**事实台账**。从 PLAN §7 标题、`docs/05`、`contracts/*.json`、`docs/12`、变异登记表、README 坑编号现算 27 个键；`--write/--check/--refresh` | `tests/test_pm.py`（值比对、装饰键、幂等刷新、台账自洽） |
| `contracts/ledger.json` | B22：台账落盘物。管理文档里的数字只能写成 `L:键=值` 标记，由它现算校验 | `checks/check_pm.py` + `pm` 层 |
| `checks/check_pm.py` | B22：管理文档核对器（台账新鲜、标记不过期、风险登记全、复盘分类是划分） | `tests/test_pm.py` 15 项 / 9 subTest，另加 2 条登记变异 |
| `docs/12-qa.md` | B21：两张**规范表**（门禁口径：10 层谁拦谁放；分诊：7 类怎么归）＋『明确不做』清单 | `tools/export_gate.py --check` + `checks/check_qa.py` + `tests/test_gate.py` |
| `contracts/gate.json` | B21：由 docs/12 现算的门禁契约（10 层 / blocking 8 / advisory 2 / 7 类分诊），门禁执行器只读它 | `export_gate.py --check`（改表不重生成即过期）+ `tests/test_gate.py` |
| `tools/export_gate.py` | QA 表 → 契约的导出器：层集合与流水线**必须完全相等**、`mutation` 不许被降级、每类分诊必须有真实样本 | `tests/test_gate.py`（降级 / 少一层 / 伪兜底特征各有断言） |
| `tools/triage.py` | 失败分诊：按契约里的顺序规则把一段失败输出归到 7 类之一并给下一步 | `--selftest` 用 **15 条登记变异的真实失败输出**逐条验；`tests/test_triage.py` 用生产代码自己打印的句子验 |
| `tools/quality_gate.py` | 门禁执行器：口径过期就**拒判**；blocking 全绿才 PASS；advisory 红了点名不放空 | 实跑 PASS（8 个 blocking 层全绿，50.04 s） |
| `checks/check_qa.py` | QA 层核对器：门禁契约新鲜、走查证据列不许吹牛、结果列必须仍是『未验证』 | `tests/test_gate.py::WalkthroughEvidence`（假测试名 / 看不懂的证据 / 代填 / 缺证据） |
| `docs/07-walkthrough.md` | B21 加第 4 列『自动证据』：要么 `T:文件::方法`（会去源码核实），要么明写『只能人工』；**『你的结果』仍归用户填** | `checks/check_qa.py`（本轮就是它抓出我 12 条引用漏了 `test_` 前缀） |
| `tools/walkthrough_pack.py` | B16 backlog ①：按**规范序列**在真原型上重放 20 步，从 spec + 种子现算每步期望；并核对 docs/07 的关键断言（说法过期即红，红在步号上） | `tests/test_walkthrough_pack.py`（18 项，四种改坏各有负面对照） |
| `docs/16-walkthrough-pack.md` | B16 backlog ①：走查**现算期望值对照表**（生成物，20 步与 docs/07 逐号对应；『你的实际/一致？』两列留空给你填） | `walkthrough_pack.py --check` + run.bat 第 3 步 |
| `demo.py` / `say.py` / `run.bat` | 需求 + 原型走查演示（12 段）；中文提示（见『踩过的坑』第 1 条）；一键核对（8 步，另有 `run.bat pipeline` / `run.bat gate`） | 实跑 |

## 运行与核对

```
run.bat                                  八步：环境 → 文档一致性 → 架构核对 → 测试 → 演示 → Java 构建+双接口对拍 → B20 三层自检 → 起原型
run.bat no-web                           前七步跑完就停（不开浏览器也能核对全部可自动部分，含 Java）
run.bat pipeline                         只跑 `tools/pipeline.py`：11 层一条命令，本地离线，约 50 秒
run.bat gate                             只跑质量门禁：读 contracts/gate.json 判 PASS / BLOCKED 并分诊
                                         （门禁共 11 层，其中 blocking 9 层；B22 加了 `pm` 层）
python checks/check_docs.py              只核对文档、模型与矩阵
python checks/check_docs.py --write      改完文档后重新生成 traceability.csv
python checks/check_arch.py              核对 Python 依赖图、契约三方、ADR、以及 Java 分层
python tools/export_contract.py --write  改完 SRS 的表后重新导出 contracts/workflow.json
python tools/export_verdict_table.py --write   重新生成 1680 格判定表（跨语言对拍基准）
python tools/walkthrough_pack.py --check      核对 docs/16 没过期、docs/07 每步关键断言与现算一致
python tools/walkthrough_pack.py --write      改过 spec/种子/原型后，重生成 docs/16 走查期望对照表
python -m unittest discover -s tests -v
python demo.py                            十一段演示（9 平台层与对拍、10 两种接口、11 验证工程）
python tools/pipeline.py --list           十层流水线：每层管什么、什么改动会让它红
python tools/quality_gate.py              门禁判定（blocking 全绿才 PASS；口径过期直接拒判）
python tools/project_ledger.py --dump     台账：管理文档里每个数字的现算出处
python tools/project_ledger.py --refresh  把 docs/13–15 的 L: 标记刷成现算值（数字不由人手抄）
python tools/triage.py --selftest         用 15 条登记变异的真实失败输出验分诊规则（约 10 秒）
python tools/export_gate.py --write       改完 docs/12 的门禁/分诊表后重新导出 gate.json
python tools/pipeline.py --only docs      只跑一层（可重复 --only）
python tools/mutation_check.py --verbose  12 条变异逐条印 diff、副本指纹与核对器完整输出
python -m prototype.server --port 8010    只起 B16 原型，浏览器打开 http://127.0.0.1:8010/
cd java && mvn -o -B test                 只跑 Java 平台层（离线，37 项）
cd java && java -jar target/repair-platform-0.18.0.jar   真起平台层，HTTP 在 :8083
```

Python 侧只用标准库（`ast` / `csv` / `enum` / `dataclasses` / `json` / `unittest`），无第三方依赖；
HTTP 层来自同仓库的 B11（`prototype/server.py` 自己挂路径，不复制 netlab）。
Java 侧依赖 Spring Boot 3.3.5 + H2 + JUnit 5，**全部已在 `~/.m2` 缓存**，离线 `-o` 构建实测可过；
本轮**没有下载也没有安装**任何东西（详见 `docs/09-platform.md` 第 1 节）。

## 实测到的数字

* 文档一致性检查：**通过**，`FR 15 / BR 11 / NFR 7 / IF 4 / UC 6 / US 13 / AC 40 / 转换 15 / 待决 12`。
  （B15 时 BR 9 / AC 39；B18 因 AQ-03、AQ-12 两条裁决各加一条 BR，AC 加一条历史可见性。）
* 架构核对：**通过**——8 个组件、20 条 Python import 边与 `docs/08` 双向相等；
  判定源只有 `spec/workorder.py` 一份；契约与文档、模型三方一致；
  **Java 6 个包的分层表与真实 import 双向相等**（`docs/09` 第 2 节）。
* Python 测试：**155 项 + 201 个 subTest 通过**（`unittest` 报 `Ran 155 tests / OK`，`pytest` 同数），`ruff --select F,E9` 干净。
  （B17 收尾 93 + 133；B18/B19 到 118；B20 加四个测试文件：`test_shrink` 10/23、`test_consequences` 11/4、
  `test_mutation_check` 8/21、`test_pipeline` 8/18。）数字每次重测，不照抄——见"踩过的坑"第 18 条。
* Java 测试：**37 项通过**（离线 `mvn -o test`，约 30 秒；B18 收尾时是 23 项，B19 加了 6 项信封 + 8 项双接口对拍），其中 `VerdictParityTest` 逐格比对 **1680 格判定**。
* 打包产物**真启动**验证过：`java -jar` 起在 :8083，HTTP 走完 建单→提交→派单→接单→完工→强关；
  四种拒绝码（`ASSIGNEE_REQUIRED` / `ROLE_NOT_ALLOWED` / `NOTE_REQUIRED` / `ACCEPTANCE_NOT_MATURE`）、
  宽限期覆盖（`graceHours=0` → 放行）、可见性（w-1 看得见自己修的、w-9 看不见）都实测；
  杀进程后用同一个 H2 文件再起，工单状态、`resolved_by` 与 5 条留痕顺序**都在**。
* 分层流水线（**B22 收尾实测**）：**11 层全绿、54.63 s**（B21 加 `qa`、B22 加 `pm`），本地离线、零下载。
  最慢两层是 javatests 23.85 s 与 pytests 17.46 s；变异自检台 **17/17 条把对应核对器弄红**
  （B22 加了 `pm-stale-ledger`、`pm-risk-row-dropped`），阴性对照 1 条保持绿。
* 质量门禁（同一次跑）：`PASS —— 9 个 blocking 层全绿`，单次 **53.65 s**；分诊自测 **17/17**
  条真实失败样本落到声明的类别；`contracts/gate.json` = 11 层 / blocking 9 / advisory 2 / 8 类分诊。
* 项目台账：**27 个键**全部现算、全部被 `docs/13` 第 8 节引用；本轮新增 4 条坑后台账算出 50，
  `--refresh` 自动写回 **4 处** `L:` 标记，`pm` 层随即核对通过——数字不手抄是机制不是口号。
* Python 测试（**B16 backlog ① 本轮重测**）：**216 项 + 298 个 subTest 通过**（`pytest` 与 `unittest` 同数；
  198 + 新增 `test_walkthrough_pack.py` 18 项），`ruff --select F,E9` 干净。
* 走查期望值生成器（B16 backlog ①）：`walkthrough_pack.py --check` **通过**——docs/16 与现算逐字一致、
  docs/07 的 20 步 41 条窄断言全对上（四种改坏各有负面对照）；**它抓出并修掉了 docs/07 三处过期期望**
  （第 8 步把接单链切断的 `R006`、第 13 步沿用 AQ-03 裁决前的"随时能关"、第 16 步徽章文案），
  另精修第 6/7/9/15 步的说法。run.bat 两次退出码 0、规范化日志逐字相同（各 279 行）。
* 40 条验收标准里：**40 条都有可执行测试**（AC-24 本轮从"待验证（B18）"转可执行）；
  7 条非功能需求：4 条可执行、2 条待验证（B20 等）、1 条只能人工确认（中文显示，NFR-04）。
  **没有一个验证入口是空的，也没有一个指向不存在的测试**——检查器会去源码里核实方法真的在。

## 课程知识点、产物、验证

| 知识点 | 落在哪里 | 怎么被验证 |
|---|---|---|
| 需求层次（业务/用户/系统）与 FR 编号 | `02-srs.md` 第 2 节 | 检查器要求每条 FR 至少被一个用例或故事引用，否则报"孤儿需求" |
| 功能性 vs 非功能性需求 | FR / NFR 两张表 | NFR 的"验证方式"也必须是三种之一，不能只写一句愿望 |
| 用例建模（角色、前后置、扩展流、异常流） | `03-use-cases.md` | 覆盖关系被机器读进追踪矩阵；异常流大多有对应测试 |
| 用户故事与验收标准（Given/When/Then） | `04-user-stories.md` | 每个 US 至少一条 AC（缺了红灯）；AC 的验证入口必须能解析 |
| 需求追踪矩阵 | `traceability.csv` | **由文档生成并与提交内容比对**，过期即红灯（PLAN 里原本列为"选做扩展"） |
| 状态机 / 工作流建模 | 第 3 节转换表 + `spec` 的 `TRANSITIONS` | 文档与模型逐格比对；穷举深度 6 走查所有合法序列并核对四条不变式 |
| 权限模型（RBAC 的最小版本） | 第 5 节权限矩阵 | 与转换表**彼此**一致；测试再独立誊一份表做第三方 |
| 数据可见性与越权 | 第 6 节可见性矩阵 | 样例 12 单穷举 `工单 × 角色`，与手誊谓词逐个相同；另有一条"先收口再筛选"的泄漏测试 |
| 字段校验与错误报告策略 | 第 9 节 + `validate_order` | 一次报全（五个错就是五个），且失败后状态与留痕不变 |
| 需求歧义与假设登记 | `05-open-questions.md` | 12 条 AQ 全部有编号被文档引用；引用了不存在的 ID 会被检查器抓到 |
| 输入不可信 / 时间与身份注入 | NFR-02、NFR-05 | `test_time_is_injected_not_read`（读源码断言没有取时钟调用）、`test_owner_and_assignee_…` |
| 界面状态设计（正常 / 加载 / 空 / 错误） | `06-wireframes.md` V2、V3 + `prototype/web/` | 空态与错误态 markup 各有落点且文案区分二者；筛选到零结果走空态（`test_filters_narrow_without_escaping_visibility`、`test_blank_state_marker_survives_a_re_render`） |
| 表单就地错误与焦点管理 | `06` V2、`app.js` 的 `renderFieldErrors` | `test_frontend_maps_field_errors_to_each_field`（每字段一个落点、`aria-invalid` 翻转、汇总条数、焦点送第一个） |
| 可访问性（label、role、aria-live、Tab/Esc、表格语义） | `06` V5 + `index.html` | `test_index_is_served_with_a11y_contracts`、`test_every_form_control_has_a_label`、`test_describedby_targets_exist`、`test_table_header_matches_rendered_columns` |
| 界面不复制业务规则（单一判定源） | `spec.attemptable()` / `required_inputs()` → API → 按钮 | `test_no_business_rules_duplicated_in_js`、`test_detail_reports_attemptable_and_required_inputs_from_the_model` |
| 越权不可靠"隐藏按钮"防御 | NFR-02、V1 | 前端不显示 + 服务端仍拒（`test_server_refuses_actions_the_role_cannot_take`），且工单未被改动 |
| 架构风格比较（单体 / 端口-适配器 / 服务 + 事件总线） | `docs/08` 第 2 节 + `arch/style_probe.py` | 文档指标表必须等于实测输出；三种风格终态相同、判定源调用次数相同；C 的"重复状态点 = 1"是**测出来的**（乱序投递把副本写回旧值） |
| 分层与依赖方向（谁可以依赖谁） | `docs/08` 第 3、4 节 | `check_arch.py` 用 `ast` 扫真实 import，与声明的边集**双向相等**；越界与"文档画了代码没有"都算失败 |
| 领域层纯净性（不依赖传输与时钟） | `spec/` | `check_arch.py::check_domain_purity`；反向测试：往 `spec/` 塞一个 `import netlab` 的文件，核对器必须连报两条、删掉后立刻恢复干净 |
| 架构决策记录（ADR） | `docs/adr/ADR-01…03` | `check_adrs`：五节齐全（背景/决定/备选/后果/验证方式）、被 08 引用、无孤儿文件 |
| 契约先行（跨语言一致性的地基） | `contracts/workflow.json` + `tools/export_contract.py` | 三方比对（文档现算 = 契约 = `spec`）；`--check` 检出过期；故意改模型必须红灯 |
| 分层与依赖方向（Java 侧兑现 ADR-02） | `docs/09` 第 2 节 + `java/src/main/java/course/dormrepair/*` | `check_arch.py::check_java`：扫真实 `import` 与表**双向**比对；喂假 import 的三条反向测试（越界 / 领域不纯 / 声明未用） |
| 单一判定源跨语言 | `java/…/contract/WorkflowContract.java` + `domain/StateMachine.java` | `java/` 下不许有契约副本（构建时从 `../contracts` 复制）；schema 版本不符直接拒绝启动 |
| 状态机的**行为等价**而非结构等价 | `contracts/verdict_table.json`（1680 格） | Java `VerdictParityTest` 独立重算逐格比对；把到期边界挪一格 → 精确报出 2 格分叉 |
| 事务边界与并发写冲突 | `app/RepairService.act()` + `work_order.version` | `staleVersionIsRefusedAndDoesNotOverwrite`、两线程并发派单**恰好一个**成功、留痕只多一条 |
| 持久化与重启恢复 | `infra/Schema`（DDL 由契约生成）+ H2 文件库 | 单测真关真开；打包 jar 杀掉再起，工单、`resolved_by` 与 5 条留痕顺序都在 |
| 数据级权限落到 SQL | `JdbcWorkOrderRepository.visible/visibleFiltered` | 可见性在 WHERE 收口（先收口再筛选）；w-1 看得见自己修过的历史单、w-9 看不见 |
| 阈值可配置（AC-24 的落地形态） | `spec.ACCEPTANCE_GRACE_HOURS` → 契约 `acceptance_grace_hours` → Java `graceHours` 参数 | 同一时刻换阈值判定翻转（Python 与 Java 各一条测试）；硬编码就写不出这条断言 |
| 跨工具链的编码与"假绿灯" | `java/pom.xml`（surefire `argLine` UTF-8）、docs/09 第 10 节 | 类名不匹配 → `BUILD SUCCESS` 但 0 个测试；MSYS curl 中文参数被转 GBK —— 都靠"换一条路径复验"发现 |

| 服务契约与两种接口形态（REST vs SOAP 1.2） | `docs/10` + `java/…/soap/*` | 同一身份两侧**可见集合、按钮、错误码逐字相同**（`SoapInterfaceTest` 8 项）；注入一条 SOAP 自造规则立刻精确分叉 |
| 描述文件与契约同源（WSDL 不许手写） | `java/…/soap/Wsdl.java` | 测试比对 `StateType` 枚举与契约 `states` 集合；多一个少一个都红 |
| 消息格式的可解释性 | `Attemptable` / `Input` / `Change>Action` 元素名 | 撞名会让客户端按层级猜语义（本轮踩过）；测试按元素名读回，不用 indexOf |
| XML 的安全解析（XXE） | `SoapEnvelope.parseXml` | 两条反向测试：带 DOCTYPE 与带实体引用的信封都必须被拒；另配**正向**测试证明合法信封真能通过 |
| 最小失败序列（反例收缩，调试用） | `tools/shrink.py` | ddmin 与 BFS **各自独立**算最短，7 个状态全等且每个见证单步不可删；空序列也要单独试一次 |
| 需求风险的量化（未裁决项不是免责声明） | `tools/consequences.py` + `docs/11` 第 1 节 | AQ-10 循环 6 步、时限全程冻结、痕迹 6→12→21；AQ-11 4 档 × 3 配比，且"改宽 URGENT 时限则逾期率必须降"这条**测量响应性**本身被测试 |
| 变异测试（证明核对器会失败） | `tools/mutation_check.py`（12 条登记 + 1 条对照） | 每条要求 ①退出码非 0 ②输出里出现**预期的那条原因**；跑任何变异之前，未变异副本的四个核对器必须全绿 |
| 持续集成与流水线分层 | `tools/pipeline.py`（9 层） | 不 fail-fast；**退出码 0 但读不到数＝红**；`--require` 让"本机没 Maven"算失败而不算跳过；报告里的耗时与计数全是本轮实测 |
| 质量门禁（什么算不合格、谁必须拦） | `docs/12` 第 1 节 → `contracts/gate.json` → `tools/quality_gate.py` | 口径与流水线层集合**必须完全相等**；把 `mutation` 降成 advisory 会被拒（登记变异 `gate-downgrade` 现场验）；口径过期时门禁**拒判**而不是给 PASS |
| 失败分诊（红了先做什么） | `docs/12` 第 2 节 → 同一份契约 → `tools/triage.py` | 按顺序命中、最后一类必须兜底；**每条规则都要有真实样本**——15 条登记变异的真实输出逐条验（`--selftest`），手写假日志不算 |
| 人工走查与自动证据对齐 | `docs/07` 第 4 列 + `checks/check_qa.py` | 声称 `T:` 的必须能在源码里找到那个方法；结果列被代填成『通过』立刻红——那一列归用户 |
| 项目管理：数字的唯一出处 | `tools/project_ledger.py` → `contracts/ledger.json` → `docs/13` 第 8 节 | 管理文档只能写 `L:键=值`，`pm` 层重算比对；台账里没人引用的"装饰键"会被直接判红（本轮就是它抓出我自己两条键没被引用） |
| 风险登记与复盘的完整性 | `docs/14`、`docs/15` + `checks/check_pm.py` | 每条未裁决 AQ 都必须在册（少一条就红）；复盘分类必须**恰好**覆盖全部坑编号（重号、漏号、条数与列表不符都红） |
| 度量不许当装饰 | 门禁报告里的每个数字都现算（层数、样本数、走查分布、耗时） | 写死一个数字就少一处核对；`qa` 层读不到那四个数会判『退出码 0 但读不到数』 |
| 测试隔离（工具也会互相污染） | 每条变异独享一份 947 KB 副本 | 共用副本时核对器写进副本的 `.pyc` 会让下一个变异"在盘上但不在行为里"；两条常驻测试盯着这件事 |
## 踩过的坑（本轮真实记录）

1. **`run.bat` 里的中文 `echo` 又被 cmd 切了**，而且这次**不是** `chcp` 之前的注释：前言全 ASCII，
   最后一个长中文 `echo` 照样被从中间读起，报 `'接手，SRS' is not recognized`，**退出码仍是 0**。
   上一轮我从 B31 的现象总结出的规则（"第一个 echo 之前保持 ASCII"）**是不够的**——
   正文里的中文本身就是赌局。改法是整份 `.bat` 纯 ASCII，中文提示放进 `say.py` 由 Python 打印。
   规则已按新证据改写进 PLAN 第 6 节。抓到它靠的不是退出码，而是"在日志里 grep `not recognized`"。
2. **演示里那条"追踪入口真的能跑"的测试，一开始是假的**：我把 `tests/test_x.py::method`
   直接拼成 `tests.test_x.method` 交给 unittest，少了一层 TestCase 类名，结果
   `ran=1 failures=0 errors=1`——看起来跑过了，其实是加载错误。修法是导入模块、
   遍历找到定义该方法的 `TestCase` 子类再执行，并让 demo 在 `not wasSuccessful()` 时**直接退出**。
   这类"把 error 当 ran"的错觉，比一个显式失败危险得多。
3. **一个真正的模型缺陷是被穷举走查抓到的，不是被写测试时想到的**：
   `confirm` 和 `force_close` 都能走到 `CLOSED`，却都忘了清空 `assignee`，
   和数据字典"终态下 assignee 为空"矛盾。补了 `test_closing_clears_the_current_assignee`
   作为具名回归。**"从草稿出发穷举所有合法序列"这种测试值得为任何工作流写一遍。**
4. **检查器最初只会说"这条转换两边不一样"**，说不出哪一格不一样（我删掉模型里一条转换时，
   它报的方向还是反的）。改成按转换 ID 逐字段比对后，报错直接指出
   `TR-01 的前置条件不一致：文档 (…) vs 模型 (…, 'teleport')`——
   **诊断信息不精确的检查器，会让人学会忽略它。**
5. **文档里我自己写了两个不存在的引用**：一处 AC 提到 `AQ-03` 但检查器只把 FR/BR/NFR 当合法引用；
   一处枚举正则只匹配大写字母，把动作表读成空集合。两处都是**检查器自己的 bug**，
   红灯方向却反过来指向我，说明"工具报错"也要先查工具。
6. **`{set}` 放进元组里当集合比较**：`unhashable type: 'set'`。要写 `frozenset`。
7. 另外三处是**我的期望值/用法写错而代码是对的**：`return_pool` 只能从 `ASSIGNED` 发起（我拿 `SUBMITTED` 去试）、
   `assigned()` 已经含 2 条留痕（我断言成 4 条，实际是 6）、`submitted()` 不是零留痕（我断言 `()`）。
   按 PLAN 第 6 节"期望值必须有出处"，这三条都先算过再写才算数。

### B16 追加的坑（交互设计与原型）

8. **`node --check` 通过 ≠ 前端能跑**：我在 `app.js` 里把函数定义成 `busy()` 却调用 `setBusy()`——
   语法完全合法，浏览器里才 `ReferenceError`。补了一条便宜的"名称解析"测试
   （`test_every_called_helper_is_defined`：被调用的自有函数必须有定义），它当场又帮我抓到一个
   把 `async function` 当函数调用的误判。**没有 jsdom 也能拦住一整类运行时错误，这种测试值得写。**
9. **可见性文档与模型悄悄不一致**：第 6 节原来写维修员能看"自己处理过的"单，
   但模型在进入终态时清空 `assignee`，于是修过的单他反而看不到。
   是**我手写的期望集合**（`w-2` 该看到 `R005`）与实现冲突时暴露的。
   处理方式不是改代码迎合 prose，而是把规则写准、并把"要不要让维修员查自己修过的历史"登记为 **AQ-12**。
10. **表格列数不匹配**：`<thead>` 里 7 个 `<th>`，`renderRows()` 生成 8 个单元格（多了"打开"那一列）。
    肉眼很容易漏，读屏器会念错位置——现在有一条测试专门数这两边。
11. **`</input>` 这种无效闭合**：给复选框写 label 时顺手写了 `<input ...></input>`。
    浏览器会自己纠错，于是错误被吞掉；现在有一条静态断言盯着。
12. **导入顺序会让"复用"看起来像坏了**：测试里先 `import netlab` 再 `import prototype.server`
    就 `ModuleNotFoundError`——因为是后者负责把 B11 挂进 `sys.path`。这类顺序依赖要在注释里写死，
    否则下一个人会以为是 B11 没准备好。
13. **原型里"现在几点"必须来自模型**：界面要显示逾期，就得有个 `now`。
    如果前端读浏览器时钟、后端读 `time.time()`，同一条单两个人看到的逾期状态会不一样
    （还会让测试变成 sleep）。现在两边都用模型里的假时钟，走查每次看到的都一样（NFR-05）。

### 一处我特意**没有**自动化的东西

`attemptable()` 只表示"这个状态与角色下**可以点**"，不含前置条件；点下去仍可能被服务端拒
（没填理由、不是本人）。我**没有**把按钮改成"条件不满足就禁用"，因为那需要在前端复制一份
前置条件判断，正是第 9 条要避免的"两处说法不一"。代价是界面上会出现点了才被拒的按钮——
这是有意的取舍，写在 `06-wireframes.md` 的 V4 里，也请你在走查时判断这样是否可接受。

### B17 追加的坑（体系结构与契约）

14. **`sorted()` 一组 dict 直接崩**：契约比对里我 `sorted([{...} for ...])`，Python 没法比两个 dict →
    `TypeError: '<' not supported between instances of 'dict' and 'dict'`。
    比集合前先想清楚**按什么排序**（这里按转换 ID）。同一个坑我在 B15 踩过一次（把 `set` 放进元组）。
15. **指标本身是错的**：风格 C 第一版"重复状态点 = 0"，因为我只比了最终值——
    最后一次写入正好覆盖对了，就把问题掩盖成"没问题"。真正的危害是**乱序投递**，
    所以对照里必须主动把旧事件迟到投一次，才能测出副本会退回到 `SUBMITTED`。
    教训和 B12/B13 一样：**指标测不到风险，等于没有那条指标**。
16. **核对器自己也有 bug**：`same_outcome()` 已经返回集合，我又写了 `len({calls})` →
    `unhashable type: 'set'`。给"检查器"写代码时，它同样需要被测试跑一遍才知道能不能跑。
17. **文档改了代码没改，被自己的核对器抓了一次现场**：我给 `demo.py` 加了第 8 段（要 import `arch`、`tools`），
    忘了改 `docs/08` 的依赖表，`run.bat` 当场红灯
    （`依赖越界：demo → arch（文档没允许这条边）`）。这正是这张表要起的作用——**它不是画给人看的图**。
18. **本轮最后一个错处是我的文档数字**：收尾时写的是"93 项 + 128 个 subTest"，其中 93 是新测的、
    **128 是从 B16 那行照抄的**。按 `addSubTest` 重新计数（`pytest` 也直接报）实际是 **133**——
    `test_architecture.py` 带进 5 个。结论和第 15 条同源：**没重跑的数字就是没根据的数字**，
    哪怕它写在"已知局限"旁边也一样。

### B18 追加的坑（平台层与跨语言）

19. **`mvn -o test` 返回 BUILD SUCCESS，但一个测试都没跑**：开工前的离线探针里我把测试类命名为 `T.java`，
    不匹配 surefire 的 `*Test.java` 约定，于是静默跳过。改名后才报 `Tests run: 1`。
    这是"退出码 0 不等于交付"的第 N 次现身，而且**这次是新工具链上的第一次**。
20. **打包产物从没真启动过，而 22 项测试全绿**：`AUTO_SERVER=TRUE` 与 `DB_CLOSE_ON_EXIT=FALSE`
    在 H2 里互斥，`java -jar` 当场 `Feature not supported` 起不来——测试用内存库、又不跑 jar，
    所以完全看不见。**"测试通过"和"能交付"是两件事**，必须真的把 jar 起一次。
21. **详情接口的 `history` 永远是空数组**：`GET /api/orders/{id}` 复用了列表查询，而列表不 join 留痕表。
    状态、处理人都对，唯独留痕没有——没有任何一条现有断言会变红。是我去 curl 真接口才发现的。
22. 修 21 时才发现根因更糟：**同一个字段名两种含义**（列表恒空、详情才有）。
    改成列表也批量补留痕，并加断言"列表与详情条数必须一致"。
23. **MSYS 的 curl 会把命令行参数按 GBK 交给原生程序**，我一度判定"应用把中文弄坏了"。
    换 Python 显式 UTF-8 发同一条请求，中文描述逐字节相同。**先怀疑工具链，再改应用。**
24. Java 的 `roles` / `requires` 必须是 **List 不是 Set**：两边"多个前置条件同时不满足报哪一个"
    依赖检查顺序，用无序集合会让 1680 格对拍**假性分叉**。
25. **H2 内存库随最后一条连接关闭而销毁**，而 `DriverManagerDataSource` 每条语句一条新连接：
    建表第二条报 `Table WORK_ORDER not found`。加 `DB_CLOSE_DELAY=-1` 才成立。
26. **对拍表测不到视图标志位**：把 `isAcceptanceStale` 的 `>=` 改成 `>`，22 项测试全绿——
    判定路径有表管，视图谓词没人管。补了 `staleFlagAndDecisionShareOneBoundary` + HTTP 层断言，
    再跑同一变异才见红。**"覆盖了"要看它能不能失败。**
27. 我自己写了 `app → infra` 的 `instanceof` 越界依赖（文档没这条边），是新加的 Java 分层核对
    按规则该抓的——但它是**我先写完再补的核对器**，属于自查而非被拦。修法是把方法提到端口上。
28. **`run.bat` 的 Java 步骤我写成 `"%MVN" -o -B test`，少了一个百分号**：cmd 真去找一个叫 `"MVN"` 的程序，
    报 `not recognized`，**而整个脚本退出码照旧 0**。第一版我只验退出码就记成"跑通"了——
    第二次连跑并 grep `not recognized`（这是 PLAN §6 早写下的规矩）才抓到。
    现在这段由 `tools/java_build.py` 负责定位 Maven 并跑构建，批处理只留 `python tools/java_build.py || exit /b 1`。
29. **我新写的 mvn 计数解析器把 23 报成 46**：`mvn` 既打"每个类一行 `Tests run:`"又打"最后一行总计"，
    我两种都加了。修法是让两个来源互相核对（逐类之和 = 总计行，不等就判失败），并给解析器补 4 条断言。
    这条最值得记：**刚立完"SUCCESS 不等于跑了测试"的规矩，就在新造的指标上犯了同一类错**；
    新增任何度量，第一件事是证明它会失败。

### B19 追加的坑（双接口与加固）

30. **照抄来的 XML 加固配置在这台机器上根本无效**：`disallow-doctype-declaration` 是 Xerces 专有的特性名，
    JDK 自带解析器不认。我的"失败关闭"逻辑于是让每次解析都报 INTERNAL，
    结果是 **XXE 防护一次都没真正生效过**，只是把所有请求都拒了、看起来很像很安全。
    修法与教训：**安全/加固配置必须配一条正向测试**（给一个合法请求，断言它真的通过）——
    否则"拒绝一切"和"防护到位"这两种状态在测试里长得一模一样。
31. Java 里我把内嵌 record 命名成 `Element`，**遮住了 `org.w3c.dom.Element`**；
    按钮元素又写成 `<Action>`，与留痕里的 `<Action>` 撞名。报文格式里的歧义一旦发布就永久留着，
    改成 `Item` / `Attemptable` 都是编译期或读回时才暴露，不是设计期想出来的。
32. 我朝 SOAP 发了个 `<Assign>` 想做错误码对拍，拿到 `CLIENT` 其实是**正确行为**
    （第二种接口只覆盖查询），我却把它写成"码值分叉"。范围没想清楚时，测试会比实现先错。
33. 测试与实现**各写了一遍解析**（我的测试版忘了剥反引号）→ 测试红、实现绿。
    抽出 `state_literal_allow_list()` 让两边共用同一个函数才修好：**重复的解析迟早漂移**。
34. 又踩一次管道退出码：`python checks/check_arch.py | tail -3; echo exit=$?` 读的是 `tail` 的码，
    明明报了 5 处问题却显示 `exit=0`。B7/B10 记过这条，这次是我在新地方重犯。


### B20 追加的坑（验证工程与流水线）

35. **变异"在盘上但不在行为里"**：所有变异挤同一份临时副本、跑完还原。`stale-contract` 单独跑变红、
    连跑就绿——因为核对器 `import spec.workorder` 把 `.pyc` 写进了**副本**，而 CPython 判缓存有效
    只看 pyc 头部那两个字段：源码 mtime 的**整数秒**与源码**字节数**，**源码内容从不参与比较**
    （实测：头部 mtime 字段就是 `int(st_mtime)`；换成同长度的另一份内容、mtime 复原后 `import` 仍读到旧值）。
    `copytree` 保留 mtime、还原后字节数复原、两次写又落在同一整秒，三个条件一起成立。修法是每条变异独享一份副本 + 子进程
    `PYTHONDONTWRITEBYTECODE=1`。**验证工具之间的污染和被测代码的 bug 一样真，只是更难看见。**
36. **我的反向探针自己没直读退出码**：它一边打印出 pytest 的 `1 failed`，一边把结论判成"没红"。
    这条坑在 B7/B10/B19 记过三次（管道后的 `$?`），这次换了个地方重演——在我用来做验证的脚本里。
    现在探针一律先印原始 `returncode`，结论从它推出来。
37. **"把断言删掉"不是反向验证**：第一条探针是去测试文件里把断言换成 `assertEqual(1, 1)`，那当然绿，
    什么也没证明。有效的探针改的是**数据与被测代码**（登记表锚点改过时、核对器路径写错、
    隔离改回共用副本、去掉未知 id 的守卫），看对应测试是否变红。
38. **红要红在预期的那个原因上**：`matrix-stale` 第一版是"加一条占位 AC"，`check_docs` 确实红了，
    但红的原因是"这条 AC 没有测试引用"，不是"追踪矩阵过期"——等于没测到那条。
    换成"改 FR-01 的验证入口指向另一个**真实存在**的测试"，才只剩矩阵过期这一个违规。
39. **`--only <拼错的 id>` 是空绿**：待跑列表为空 → "0 条失败" → 退出码 0。流水线与自检台各加一条守卫
    （未知层/未知变异 id 直接算失败），并各配一条常驻测试。

### B21 追加的坑（质量门禁与分诊）

40. **分诊特征串凭记忆写，被自己的自测打回 12/15**。我以为 `check_docs` 打印的是
    『文档一致性发现』，真实文本是『文档一致性**检查**发现』——三条 `doc-model-divergence` 样本
    全落进兜底类。规则必须由真实输出反推：**这正是『每类都要有真实样本』这条约束存在的理由**。
41. **兜底那格被切成一个伪特征串**。`strip_ticks` 先按分隔切段、再过滤含『兜底』的段，
    于是『（兜底，不命中以上任何特征）』的后半句变成一条**真的模式**写进 `gate.json`；
    兜底规则带着模式就不再是兜底。由 `tests/test_gate.py` 的分隔符断言抓到。
42. **给走查表加列时插错位置**（列索引算错，20 行的证据全并进『期望』单元格）。
    靠 `check_docs.tables_in` 的列数校验现形——表头 5 列而行 4 列立刻报。
43. **`T:` 引用漏掉 `test_` 前缀**：抄测试名时被 `sed` 吃掉了前缀，12 条全指向不存在的方法，
    `checks/check_qa.py` 一次报 13 处。B15 那条老规矩这轮反过来保护了我：**引用一个不存在的测试比留空更坏**。
44. **prototype 那条变异一开始『红』在拷贝缺陷上**：临时副本里没有 B11 的 `netlab`，`server.py` 直接
    `RuntimeError`——看着像核对器抓到了，其实是自检台没带外部依赖。修法是 `EXTERNAL_DEPS` 显式带上，
    并写明『这是拷贝不是链接，B11 变了这里用的仍是拷贝时的版本』。
45. **中文串里嵌裸引号又把补丁脚本写崩**（`"结果列被检查器代填成"通过""`）——同类错第三次犯，
    这次连我要写进文档的那句话自己都没通过语法检查。
46. **新命令的分支要各自真跑**：`tools/triage.py` 忘了 `sys.path.insert`，`--text` 分支一切正常，
    只有 `--selftest` 才 `ModuleNotFoundError`。

### B22 追加的坑（项目台账与管理文档）

47. **台账的事实源在项目目录之外，副本没把它带过去**：`tools/project_ledger.py` 读仓库根的
    `PLAN.md`（`ROOT.parent.parent`），而变异自检台的副本只拷了 `projects/dorm-repair/`。
    于是两条 PM 变异"红"在 `FileNotFoundError` 的 traceback 上——**退出码非 0、但原因完全不是那条**。
    这是 B21 刚立的"红要红在该红的原因上"在同一轮内第二次现身。修法是副本布局改成
    `outer/projects/<副本>`，把 `PLAN.md` 放到 `outer/`、`B11-net-lab` 放到 `outer/projects/`，
    与真实目录深度一致；同时让台账在缺源时**报一句人话**而不是抛 traceback。
48. **分诊特征串又写错了（第二次）**：我给 `artifact-stale` 加的特征是"与现算事实不一致"，
    而 `check_pm` 真实打印的是"写 L:verdict_cells=1681，**台账现算** 1680"——自测报 16/17。
    同一条教训第二次犯，说明我还没养成"先看一眼真实输出再写规则"的动作；
    现在这条串是从自测的报错文本里复制来的，不是回忆出来的。
49. **往门禁表插 `pm` 行时漏了第 4 列**：GFM 列数校验当场报"第 21 行列数 3 与表头 4 不符"。
    这一条我记它不是因为难，而是因为**如果那张表没有机器读，我就不会发现**。
50. **我的 PM 测试第一版有两处自己的错**：① 助手函数为了让断言成立去改 `facts()` 的返回值——
    那是在测试里造假现场；② 以为 `verdict_cells` 只出现在指标表一行，实际正文还有一处，
    于是"删一行"没触发预期告警。两条都是**测试红而产品没错**，改的是测试。
51. **我自己的探针写死了分类表的数字**：`tests/test_pm.py` 里两条反向探针用
    `"12 | 1, 8, 11, 12,"` 这种字面量定位，B22 一加分类条目它们就悄悄失效（改成断言"文档没错"了）。
    发现方式是**跑一遍就红**——红在测试而不是产品上。已改成从表里现取行再改坏，
    于是"探针不许依赖具体数字"和"文档不许手抄数字"这两条其实是同一个毛病，我在同一轮里各犯一次。

### B16 backlog ① 追加的坑（走查期望值生成器）

52. **期望也会过期，而且没有任何东西会红**：docs/07 的「期望」列是 B16 手写的；B18 把验收
    宽限期落成 168 小时后，第 13 步还写着"现在任何时刻都能关"——你按旧期望走查，会把
    **正确的拒绝**当成缺陷记下来。直到 `tools/walkthrough_pack.py` 第一次重放才暴露。
    修法不是"这次改对"：期望改成现算（`--write`），并在 `--check` 里核对 docs/07 的关键
    断言——说法过期就红，红在步号上。**手写的东西要有人重算，否则它就是会过期的**。
53. **单步都对、连起来断链**：第 8 步"对 R006 退回公共池"（要理由——没错）、第 9 步"w-2 对
    R006 接单"（要 ASSIGNED——也没错）：每一步单独看都成立；连起来是死路——第 8 步成功后 R006 已在
    `SUBMITTED`，第 9 步的"接单"在 `SUBMITTED` 下**根本没有这个动作**。这个错只有在
    **整条规范序列重放**时才露头（单步核对永远发现不了）。修法：第 8 步改对第 7 步刚派出的
    那张（`R009`），R006 留给接单链；生成器的负面对照钉住"第 8 步不许再出现 R006"。

## 已知局限（说清楚，不含糊）

* **仍不是可上线系统**：B16 的原型是**走查用**的——内存数据、重启即清空、没有存储与并发。
  B18 的 Java 层有真存储、真事务与乐观锁，但**没有真实认证**：身份仍是 `?role=&actor=` 查询参数（B21/B22 的范围）。
* **B17 不写任何 Java 代码**：那轮产物是结构、契约与决策记录。第 2 节的三种风格指标是**结构计数**，
  只回答"多服务会多出哪些必须兜的东西"，不是性能比较，也不能外推成"微服务好/坏"的结论。
* **B18 的并发测试只验"不覆盖"**：两个线程并发派单，实测恰好一个写入成功、版本只推进一次、留痕只多一条。
  它**不宣称**吞吐、延迟或锁竞争表现——没有性能实验，也就没有那类结论。
* **B18 没有多实例语义**：单进程 + 单 H2 文件库。时钟回拨、多实例时钟不一致（AQ-05）仍未裁决也未实现。
* **需求来源是假设**：没有真实调研、没有校方制度依据（01 节来源声明）。12 条 AQ 里任何一条被裁决成别的值，
  都会同时改到文档、模型、契约和测试——这正是我把默认值钉成可执行形式的原因。
  **B18 已裁决 3 条**（AQ-02/03/12，用户回答"无偏好"后由我按推荐值定，性质仍是假设），
  每次裁决都真的动了四处：SRS 表、`spec`、契约 v2、测试——检查器全程盯着，没让任何一处单独改成功。
* **追踪矩阵的"业务规则/接口"两列是共现推导**：同一用例或同一验收标准里同时出现的 BR/IF 才会挂上，
  所以它偏粗（UC-01 里的 BR 会出现在该用例覆盖的每条 FR 行上）。这是可核对的保守近似，
  不是手工声明的精确映射——真要更细，就得让 AC 逐条显式声明 BR，那会明显加重文档负担。
* **权限模型只到"动作级"**：字段级权限（例如维修员能不能改优先级）、数据级行权限以外的
  组织维度（班组、楼栋归属）都没有建模。
* **状态机允许循环**：`IN_PROGRESS → SUBMITTED → ASSIGNED → IN_PROGRESS` 无上界（AQ-10）。
  `test_the_pingpong_loop_is_reachable_and_is_a_risk` 故意断言它**可达**，将来加上限就会红灯，逼改动同步回文档。
* **B20 的流水线没有 CI 服务器**：它是本地一条命令（`run.bat pipeline` / `python tools/pipeline.py`），
  不并发、无缓存、每次 42 s 全跑。接 GitHub Actions 需要联网与授权，本轮按 PLAN 第 8 节没做。
* **变异登记表是纯文本锚点**：那 12 条靠 `find` 字符串定位。重构改动那几行文本，锚点命中数就变，
  自检台会**报错并拒绝跑**（不会静默跳过）——代价是这张表得随重构一起维护。
* **AQ-11 的数字带假设**：到达间隔、工时、优先级配比都是我拟的（`consequences.py` 里 `source` 字段就这么写），
  所以它只能说明"在这些假设下会这样"。AQ-10 那组不同，它是模型性质的闭式测量。
* **`spec` 是需求模型不是产品实现**：字段用字符串枚举、没有校验层与存储层分离、不做 I/O。
  B18 已经用 Java 重做过一次，**判定源仍是这一份**：Java 读 `contracts/workflow.json`，
  两边逐格对判定（1680 格）。B20 的 JUnit 对照同一批需求 ID，不另起口径。

## 下一轮接手什么

* **B16（已完成，2026-10-01）**：线框与四态约定见 `06-wireframes.md`，可点原型见 `prototype/`；
  原本 3 条 `待验证（B16）` 里的 AC-05、AC-39 已换成可执行入口，AC-24（超时阈值）仍留给 B18。
  **走查清单 20 行的结果列是空的**，那部分我不会替你填。
* **B17（已完成，2026-10-01）**：分层与依赖方向、三条 ADR、机器可读契约与"依赖图实测"核对器；
  **本轮不写任何 Java 代码**，也没拆服务。`docs/08` 两张表由 `checks/check_arch.py` 与 `arch/style_probe.py` 盯着。
* **B18（已完成，2026-10-01）**：`java/` 是 Spring Boot 分层单体 + H2 + 事务与乐观锁 + REST，
  **状态机不重写**：它读 `contracts/workflow.json`，并与 Python 逐格对判定（`VerdictParityTest`，1680 格）。
  AQ-02/03/12 三条裁决已在这一轮落地（宽限期可配置、`resolved_by` 可见性、SLA 不重置）。
  仍**没有**：真实认证、前端接 Java、多实例、性能实验。
* **B19（已完成，2026-10-01）**：查询用例 UC-05 多了一种接口形态——手写 SOAP 1.2 端点 + 由契约生成的 WSDL，
  **零下载**（本机没有 Spring WS / gRPC 缓存，这是实测出来的选型理由，见 `docs/10` 第 1 节）。
  判定没有第二份：同一身份的可见集合、按钮、错误码两边逐字相同（`SoapInterfaceTest` 8 项）；
  谁能自己判断状态由 `docs/10` 的**状态字面量白名单**双向核对（3 个文件，扫描前先剥注释）。
  写操作**故意没有**放进 SOAP，理由写在 `docs/10` 第 2 节。
* **B20（已完成，2026-10-01）**：四件验证产物各自都能被证明会失败——最小反例收缩（`tools/shrink.py`，
  与 BFS 独立算的最短全等）、需求风险量化（`tools/consequences.py`，AQ-10/AQ-11 报出数字而不是"有风险"）、
  变异自检台（`tools/mutation_check.py`，收尾时 12 条变异 + 1 条阴性对照）、9 层本地流水线
  （`tools/pipeline.py`，收尾实测 41.94 s；**B21 已把它加到 10 层、登记表加到 15 条**，最新数字见上面）。
  文档见 `docs/11-testing.md`。
  **没有**接真实 CI 服务器（GitHub Actions 要授权与联网，本轮没做），也**没有**替换 `run.bat` 的分步走查。
* **B21（已完成，2026-10-01）**：门禁口径落成两张规范表——`docs/12` → `contracts/gate.json` →
  `tools/quality_gate.py`（实跑 `PASS —— 8 个 blocking 层全绿`，50.04 s）；
  失败分诊 7 类**每条规则都有真实样本**（`tools/triage.py --selftest` 用 15 条登记变异的真实失败输出逐条验）；
  走查清单加『自动证据』列，由 `checks/check_qa.py` 守着：声称有证据的测试必须真存在，
  『你的结果』那一列仍归用户（本轮它抓出我 12 条引用漏了 `test_` 前缀）。
  **没有**分支保护 / CODEOWNERS / 云端 CI / 覆盖率百分比——理由在 `docs/12` 第 5 节。
* **B22（已完成，2026-10-01）**：不加新机制，改做**项目视角的账**——`docs/13` 计划与范围、
  `docs/14` 风险登记册、`docs/15` 复盘，加上唯一的机制：**事实台账**
  （`tools/project_ledger.py` 现算 27 个键，管理文档只能写 `L:键=值`，`checks/check_pm.py` 逐个核，
  台账自己还拒绝"没人引用的装饰键"）。流水线升到 **11 层**（新增 `pm`，blocking 9），
  变异登记 **17 条**、分诊 **8 类**，实跑 `PASS —— 9 个 blocking 层全绿`（53.65 s）。
  本轮最有说服力的两处：① 台账键第一次跑就抓出我自己两条没人读的装饰键；
  ② 两条 PM 变异一开始"红"在副本缺 `PLAN.md` 的 traceback 上，被"红要红在该红的原因上"这条 B21 规矩当场拦下。
* **B23（下一轮，批次收尾）**：PLAN 的批次 5 只到 B22；此后按 §7 排到批次 6（B23 起，人工智能导论 / 计算机视觉等），
  或按你的课设答辩需要，先补 dorm-repair 的 G2 与 `docs/07` 走查。**开工前需要你指定方向**，我不自行选题。
* **B22 之前规划的"项目视角的账"（原文，留作背景）**：把 B15–B21 的证据串成项目视角的账：范围如何逐轮收窄、
  12 条待决问题里 3 条已裁决 9 条仍未决各带来什么代价、哪些坑本可预防而哪些只能靠实测发现；
  产物是计划/风险/复盘三份管理文档，不新增功能，也不提交代码。
* **B21（质量保证）**：本轮把"验证会不会失效"变成了本地一条命令；B21 该补的是**质量门禁的口径**——
  哪些层必须绿才允许合入、失败后怎么分诊、`docs/07` 那 20 行人工走查如何与自动层对齐。
* **仍未裁决的 9 条 AQ**：**AQ-10 / AQ-11 本轮不再空口**——`tools/consequences.py` 已把它们的后果量化
  （`docs/11` 第 1 节），数字可复现；裁决仍需要真实用户或校方口径。

## 练习建议（G2，自己动手）

1. 给状态机加"退回公共池次数上限"（AQ-10 的裁决），看哪几条测试与文档必须同时改。
2. 加一个"维修员自助退回"的动作（AQ-04），走一遍：改文档表 → `--write` 重生矩阵 → 让测试变红 → 再补模型。
   然后回答：界面上这个按钮该出现在哪些状态？如果你打算在 `app.js` 里加判断，先回去看第 9 条踩坑。
3. 把字段级权限（维修员可否改优先级）建模进第 5 节的表，并想清检查器该怎么核对。
4. 用真实口径重算 SLA（AQ-02）：如果时限应该从"接单"而不是"提交"起算，BR-08 和哪几条 AC 会一起改？
5. **故意把文档和模型改歪一处**（例如只改 `02-srs.md` 里 HIGH 的时限），看检查器报不报、报得准不准——
   这一步是确认"这套核对机制真的在工作"，而不是"它恰好通过了"。
6. 给"强制关闭"加二次确认（或按 AQ-03 加悬挂时长提示），改完跑 `run.bat`：
   哪几条测试应该红、哪几条根本管不到这件事？说不出来就说明测试有洞。
