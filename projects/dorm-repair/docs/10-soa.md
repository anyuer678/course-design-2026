# 10 · 两种接口，一份规则（B19：SOA）

> 这一轮只回答一个问题：**加一种接口，会不会顺便长出第二套判定？**
> 答案不靠自觉，靠三样东西：SOAP 层只许调应用服务、状态字面量白名单、
> 以及"同一身份两种接口结果必须逐字相同"的对拍。

## 1. 为什么是 SOAP 而不是 gRPC（**实测**，不是偏好）

`docs/09` 第 1 节立过规矩：先查本机有什么，再谈下载。实测结果：

| 需要的东西 | 本机状态 | 结论 |
|---|---|---|
| `spring-boot-starter-web-services` | `~/.m2/repository` 里**没有** | 要走标准 Spring WS 就得联网下载 |
| SAAJ / `jakarta.xml.ws` / `wsdl4j` / CXF | **没有** | 同上 |
| `io.grpc` | **没有** | gRPC 路线需要下载一串依赖 |
| `com.google.protobuf` | 只有一个孤立目录，没有 grpc 栈 | 不足以离线跑 gRPC |
| JDK 自带 `java.xml`（DOM/SAX） | 有 | **SOAP 信封可以零下载手写** |
| `spring-boot-starter-web`（已缓存） | 有 | 承载端点不需要新依赖 |

PLAN 第 8 节要求"涉及下载先说明体积与替代方案"。这里不需要说明：**一个字节都没下**。
代价也说清楚：信封解析、错误码编码、WSDL 生成都是我手写的，约 300 行，
好处是"一份规则"这件事中间没有任何黑盒可藏。

## 2. 第二种接口覆盖到哪一步

只提供 **UC-05（查询工单）** 的两个操作：

| 操作 | 入参 | 出参 |
|---|---|---|
| `ListOrders` | `Role` `Actor`，可选 `State` `Category` `Room` `Priority` `Overdue` | `Count` + 若干 `Order` |
| `GetOrder` | `Role` `Actor` `Id` | 一个 `Order`（不可见即 `Fault/NOT_FOUND`） |

**写操作（提交、派单、完工…）故意不在 SOAP 侧提供**。这不是偷懒，是范围决定：
本轮要证明的是"读路径不会长出第二套判定"，加写路径只会把风险面翻倍。
所以错误码对拍只在两边都有的操作上比——上一版我朝 SOAP 发了个 `<Assign>`，
拿到 `CLIENT` 其实是正确行为，我却把它当成"码值分叉"，是我的测试写错了。

`Order` 里的字段名与 REST 视图一一对应：`Id` `State` `Assignee` `ResolvedBy` `Overdue`
`AcceptanceStale`，按钮叫 **`Attemptable`**、输入叫 `Input`。
按钮元素一开始我叫它 `<Action>`，结果和历史留痕 `<Change><Action>` 撞名——
客户端只能靠"它在第几层"猜它是按钮还是记录。**歧义一旦进了报文格式，就永远留在报文格式里。**

## 3. 状态字面量白名单（**规范性**，`check_arch.py` 双向核对）

Java 里谁可以出现状态名（`"SUBMITTED"` 这类字符串常量），这张表说了算。
它等价于 Python 侧的"定义 `TRANSITIONS` 的模块只能有一个"：**判定要么集中，要么就是分叉**。

| Java 文件（相对 dorm-repair） | 允许出现的状态字面量 | 为什么必须在代码里 |
|---|---|---|
| `java/src/main/java/course/dormrepair/domain/WorkOrder.java` | `DRAFT` | 建单初态是聚合自身的不变式，不是流程规则 |
| `java/src/main/java/course/dormrepair/domain/StateMachine.java` | `SUBMITTED`, `RESOLVED` | 字段写入时机（`submitted_at` 只在首次进入、`resolved_at` 每次进入 RESOLVED）要看目标状态；可见性谓词也按状态收口 |
| `java/src/main/java/course/dormrepair/infra/JdbcWorkOrderRepository.java` | `SUBMITTED`, `RESOLVED`, `CLOSED`, `CANCELLED` | 可见性与逾期必须落到 SQL 的 WHERE 里（先收口再筛选），是同一批规则的另一种表达，不是第二套判定 |

核对规则（`check_arch.py::check_java_state_literals`）：

* 扫 `java/src/main/java/**/*.java`，**先剥注释**再找状态字面量。
  为什么剥：我在 SOAP 文件的注释里写过 `state.equals("SUBMITTED")` 当反例说明，
  不剥注释扫描器就会报"这里长出一套自己的规则"——**散文冒充代码的假阳性**。
* 白名单里有、代码里没有 → 报"白名单过期"；代码里有、白名单没有 → 报"疑似第二份状态表"。
* 状态集合本身来自 `contracts/workflow.json`，所以改了 SRS 的状态枚举，这张表也得跟着重核。

## 4. 故障码为什么必须"跨接口同字"

REST 用 HTTP 状态码表达拒绝（403/409/400），SOAP 的语义是"信封到达了，结果可能是 Fault"，
HTTP 层几乎恒 200。如果各自只表达在自己那套协议里的分类（`soap:Sender` vs 403），
客户端就得为每种接口写一套错误处理——**那才是 SOA 里真正会烂掉的地方**。

做法：业务码放进 SOAP 1.2 的 `Fault/Code/Subcode/Value`，值**就是** REST 里 `error` 字段的字符串
（`ROLE_NOT_ALLOWED`、`NOT_FOUND`、`BAD_IDENTITY`、`ACCEPTANCE_NOT_MATURE`…）。
Subcode 是 QName（`ns:ROLE_NOT_ALLOWED`），所以提供了 `SoapEnvelope.faultCodeOf()` 剥前缀，
让对拍能逐字比较，而不是靠 `indexOf` 猜。`mcode`（`env:Sender`/`env:Receiver`）只表示谁错了。

## 5. WSDL 由契约现算

`GET /api/soap/repair?wsdl` 返回的描述里，`StateType` / `ActionType` / `RoleType` /
`CategoryType` / `PriorityType` / `VisibilityCodeType` / `FaultCodeType` 的枚举值
全部从 `workflow.json` 生成，测试逐字比对两边集合。

为什么较真这个：描述文件与契约一旦分叉，客户端会按服务端已经不接受的枚举值发消息，
而那种失败**不会有任何地方报错**，只会变成"莫名其妙的拒绝"。

## 6. 本轮真缺陷（5 处，全是我自己的）

① **`disallow-doctype-declaration` 是 Xerces 专有的特性名，JDK 自带解析器不认**。
我照抄了网上那套 XML 加固配置，结果每次解析都走"安全配置失败"分支——
XXE 防护**实际上一次都没生效过**，只是恰好把所有请求都拒了，看起来像"很安全"。
修法：改成显式挡在解析之前（扫 `<!doctype` / `<!entity`）+ `FEATURE_SECURE_PROCESSING`
+ `ACCESS_EXTERNAL_DTD=""` + entityResolver 抛错。**教训：加固配置必须有一条正向测试**
（现在 `refusesDoctypeAndExternalEntities` 与 `entityInsidePayloadWithoutDoctype...` 各管一头）。

② `SoapEnvelope` 里我的内嵌 record 也叫 `Element`，把 `org.w3c.dom.Element` 遮住了，
于是 DOM 辅助方法全在跟我的类型较劲（javac 报"无法转换"）。改名 `Item` 解决。

③ 按钮元素 `<Action>` 与留痕里的 `<Action>` 撞名（见第 2 节）。改 `Attemptable`。

④ 测试里两处 Java 语法/语义错误：`"a" + "b".getBytes()` 让 `getBytes` 只作用于最后一段字面量，
整个表达式退化成 String；以及中文断言消息里嵌了双引号。**这类错误编译器会抓，
但"公共池那单我忘了 submit"不会**——它让 `assertTrue(可见)` 红了一次，
而红的原因是我的期望，不是实现。

⑤ **管道吃掉退出码**：`python checks/check_arch.py | tail -3; echo "exit=$?"` 报的是 `tail` 的码，
核对器明明列出 5 处问题却显示 `exit=0`。同一条坑在 B7/B10 记过，这次是我在新地方重犯——
**读退出码必须直连被检进程**（或显式取 `PIPESTATUS`）。

## 7. 对拍与它的牙齿

`SoapInterfaceTest` 8 项：同一批数据、同一组身份，
REST 与 SOAP 的**可见集合、按钮、错误码**必须一致；筛选条件两边结果一致；未知操作 `CLIENT`；
WSDL 枚举 = 契约枚举；XXE/DOCTYPE 被拒。

牙齿是验过的，不是嘴上说的：我往 `SoapQueryService` 里塞了一条 SOAP 自己的规则
（维修员不看公共池），对拍立刻精确报出
`WORKER/w-1 两种接口的可见集合必须相同 ==> expected: [R002, R003, R004] but was: [R002, R004]`；
改完还原并核对 md5 一致。**能被证明会失败的测试，才算在测东西。**

## 8. 明确不做

* 不提供 SOAP 写操作（见第 2 节）；不提供 WS-Security、WS-Addressing、可靠投递、异步回调。
* 不做 WSDL 导入/绑定完整性校验，也不生成客户端桩——手写 XML 只到"能互操作地读"。
* 不接 ES/JMS/ESB，不引 broker（PLAN 第 8 节：涉及资源占用先问）。
* 不测性能，不比较 REST 与 SOAP 的耗时——本轮只比**结果**。

## 9. 命令

```
cd java && mvn -o -B test          # 37 项：含 8 项双接口对拍 + 6 项信封层
python checks/check_arch.py        # 分层表 + 状态字面量白名单，都是双向核对
curl -X POST -H "Content-Type: application/soap+xml" --data-binary @req.xml \
     http://127.0.0.1:8083/api/soap/repair
curl "http://127.0.0.1:8083/api/soap/repair?wsdl"
```

Windows 提示：curl 在 MSYS 下会把命令行里的中文按 GBK 交给原生程序（`docs/09` 第 10 节第 ④ 条），
所以中文报文请用文件 `--data-binary @req.xml` 发，别用 `-d '中文'`。
