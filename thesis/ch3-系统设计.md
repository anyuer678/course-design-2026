# 第 3 章 系统设计

> 状态：【已扩充 v2】——素材：DESIGN.md（§一/§二/§五/§六/§七）、PLAN.md（§五）、SECURITY.md。
> 口径说明：数据表以 `app/db.py` SCHEMA 为准（12 张已建表：核心 8 + 支撑 4；
> THESIS.md 的"六表"与 DESIGN §五 的"8 表"口径均过期——这正是"引用前现算"
> 纪律对素材文档同样生效的例子，2026-10-06 全量核对）。
> 【图表：…】为待绘制项。

## 3.1 总体架构

平台是单进程 Web 系统，自上而下分五层，依赖方向单向：

```
web（三端页面：学生 / 教师 / 管理端，原生 HTML/CSS/JS，零构建）
  │  HTTP + JSON API + SSE
HTTP 服务层（标准库 ThreadingHTTPServer + 自研路由表 + 会话）
  │
领域层（auth / courses / labs / tasks / notices / admin / can —— 判定唯一源）
  │
存储层（SQLite：平台态 + 文件系统：日志/备份/上传）
  │
运行时（子进程管理器：固定命令表、日志环、并发限额、超时与整树杀）
```

选择"单进程 + 标准库"的组合出于三个部署现实：课堂机器往往不能装软件包；
一个教师能运维的系统的复杂度上限很低；SQLite 的单文件形态让备份恢复变成
"复制一个文件"（存储口径见文献 [3]）。代价（并发上限、无 HTTPS）在安全
设计一节如实声明。

【图表：五层架构分层图】

## 3.2 概念模型与三条设计原则

**概念模型**：仓库里是"33 门课、每门课一个项目"；平台给每门课程开一个工作区，
工作区固定五块——简介区、项目区、演示与实验（项目页两页签）、练习任务、
资料与公告。

三条设计原则贯穿全部实现：

1. **内容源唯一**：课程/项目/演示/练习的**内容**不落库，每次请求现算自仓库
   （manifest + README + 练习卡）；数据库只存"平台态"（发布/排序/绑定教师/
   任务/记录/审计），两层按 id 关联。收益：内容不会在仓库和数据库之间漂移；
   代价：内容展示无法脱离仓库存在——这是有意的选择（本平台定位是课设仓库的
   "平台层"，不是通用 CMS）。
2. **判定唯一**：2.2 节的权限矩阵落成服务端一个函数 `can(user, action,
   target)`，三端页面的所有能力入口由它驱动渲染，前端不判权限——规则只有
   一份，越权测试有唯一依据。
3. **命令白名单**：在线实验沿用"客户端只能选 `项目 × 动作 id`"的边界——
   命令表在服务端写死，请求带不了任意命令、参数或路径。实验能力的安全性
   由这张表决定，而不是由输入过滤决定。

## 3.3 数据库设计

采用**两层结构**：仓库现算层（课程/项目内容）不落库；平台态层存 12 张表——
8 张核心表（下表）+ 4 张支撑表（讨论区 `posts`/`replies`、通知已读
`notice_reads`、访问计数 `visits`）。核心表如下：

| 表 | 关键字段 | 说明 |
|---|---|---|
| `users` | username, display_name, role, pwd_hash, pwd_salt, pwd_iter, status | 角色 student/teacher/admin；状态 pending/active/banned |
| `sessions` | token, user_id, expires_at, ip, ua | 登出/改密即失效；过期清扫 |
| `course_meta` | course, published, sort, teacher_id, summary, outline | 覆盖层：发布/排序/绑定教师 + 教师维护内容（旧库自动 ALTER 迁移） |
| `tasks` | course, title, body, due_at, created_by | 教师自建任务；内置任务来自 g2 练习卡（key=course#序号），不落库 |
| `task_records` | task_key, user_id, course, status, note, submission, submitted_at, grade, feedback, graded_at | 状态机 doing/done/submitted/graded；(task_key, user_id) 主键；重交清分 |
| `lab_runs` | user_id, pid, action, kind, started_at, finished_at, exit_code, log_tail | 实验审计与队列的数据源 |
| `admin_audit` | ts, actor_id, action, target, detail | 治理动作全量留痕（角色/状态/课程覆盖/公告/批阅） |
| `notices` | title, body, audience, created_by | 通知与公告 |

设计要点：口令参数（迭代次数）随用户行存——升级成本参数不影响老账号；
`course_meta` 是"覆盖层"而非内容副本（课程简介的现算部分与教师补充部分在
页面并列展示，各自标注来源）；实验审计单独成表并与 `admin_audit`（治理动作）
分离——前者是运行数据，后者是管理行为。

表间关系围绕"账号—行为"两条主线组织：`users` 与 `sessions` 是一对多（一个
用户可同时持有多个会话，改口令即清除其余会话、当前会话保留）；`tasks` 与
`task_records` 是一对多（一个任务多条学生完成记录，删除任务时级联清理记录，
不留孤儿）；`lab_runs` 以 `user_id + pid + action` 记录每一次实验运行，是 F14
队列与审计的数据源；`admin_audit` 与 `notices` 相对独立，分别服务治理留痕与
站内通知。两层模型之间的关联只有 id 引用：`course_meta.course` 对应现算层的
课程 id，内置任务的 `task_key`（course#序号）与 `lab_runs.pid` 对应项目 id——
**平台态表不外键约束现算内容**，因为后者不落库，内容改名或重组
由现算层自然呈现，平台态不随之失效。

【图表：ER 图（12 表：核心 8 + 支撑 4，与现算内容源的关联）】

## 3.4 接口设计

协议约定：请求与响应均为 JSON；错误统一 `{"ok": false, "error": "...",
"code": "..."}`；状态码语义沿用 HTTP 标准（400 参数 / 401 未认证 / 403 越权 /
404 不存在 / 409 冲突 / 429 限流 / 500 服务器错误）。API 分八组（v1 冻结
24 条，后续里程碑按需扩展，路由以服务端现行为准）：

| 分组 | 路由（摘要） | 覆盖功能点 |
|---|---|---|
| auth | register / login / logout / password、GET me | F1/F7/F16 |
| courses、projects | 课程目录与工作区、项目详情（含动作表） | F2/F3/F4 |
| labs | run / runs/{id} / **runs/{id}/log（SSE）** / stop | F5/F14 |
| tasks | tasks / claim / done / mine / **submit**（交作业） | F6/F7 |
| teacher | courses / course / **submissions（提交列表）** / **grade（批阅）** / tasks / tasks/{id}/delete / course/meta | F9–F11 |
| admin | users / courses / labs / labs/{id}/kill / dashboard | F12–F15 |
| notices | notices / {id}/read | F8 |

**SSE 事件格式**：实验日志流以 `event: log`（逐行日志）与 `event: done`
（退出码与耗时）两类事件推送——相比轮询，SSE 让学生在浏览器里看到"真的
在跑"的过程；相比 WebSocket，SSE 单向语义与实验日志的需求恰好匹配，实现
保持在标准库范围内（事件帧格式见文献 [5]）。

以登录接口为例说明协议形态（示意，与实现一致）：

```text
POST /api/auth/login
{"username": "stu01", "password": "..."}

成功：200，设置会话 Cookie（Set-Cookie），后续请求凭 Cookie 认证
失败：401/429，统一错误体：
{"ok": false, "error": "用户名或口令不正确", "code": "BAD_CREDENTIALS"}
```

SSE 端点（`GET /api/labs/runs/{id}/log`）的响应体由一串事件帧构成，帧格式
与 [5] 一致（`data` 载荷为 JSON 编码，与实现一致）：

```text
event: log
data: "[demo] 自检通过 42/42"

event: done
data: {"exit": 0, "seconds": 12.4, "pid": 812, "action": "demo"}
```

`log` 事件的载荷是 JSON 字符串形式的单行日志；`done` 事件携带退出码
（`exit`）、耗时（`seconds`）与运行元信息，客户端据此把"运行中"切换为
"已完成/失败"状态。

## 3.5 关键机制设计

1. **固定命令表沙箱**：实验的"动作"是服务端写死的 `(项目, 动作 id) → 命令`
   映射，客户端提交的只有 id——任意命令、参数、路径在结构上进不来。运行在
   子进程中执行，带并发限额（默认同时 2 个）、超时与**整树杀**（Windows 与
   POSIX 两套实现，保证不留孤儿进程）。
2. **SSE 日志流**：子进程日志入日志环，SSE 端点按事件边界推送；运行结束补
   `done` 事件；断线可用同一端点回放（自检断言"回放含 log 与 done"）。
3. **现算与覆盖层合并**：课程目录请求到达时现算仓库内容，再与 `course_meta`
   覆盖层合并返回；`catalog()` 以 mtime 做缓存，仓库未变时零重复扫描。
4. **绑定式教师授权**：教师与课程的绑定存 `course_meta.teacher_id`，`can()`
   在"本课"动作上显式校验绑定关系——教师权限的边界是数据，不是约定。
5. **会话生命周期**：Cookie 令牌 + 服务端 `sessions` 表；改口令使该用户其余
   旧会话全部失效（当前会话保留，"改密踢会话"）；过期会话由启动清扫 +
   惰性校验双路径回收。
6. **访问计数口径**：只计页面（`/` 与 *.html），资源与 API 不计——看板的
   "访问量"因此有明确语义（自检含"+2 精确断言"）。
7. **实验就绪判定**：实验进程"是否就绪"不能靠单次探测——子进程刚拉起时
   端口尚未监听，单次探测会把"还没好"误判成"起不来"。设计为**连续稳定
   观察**：连续多次探测成功才判定就绪。该机制的误报路径曾由白盒 A/B 实验
   复现并修复（见 4.8 节与里程碑 M11）。
8. **作业提交状态机**：练习任务的状态机为 `doing → done / submitted →
   graded`。两条防脏数据规则：学生**重交**使记录回到 submitted 并清空原
   分数与评语（教师看到的永远是当前版本）；教师对已批阅记录**重批改分**
   合法（改分是教师权责），但对未提交记录批阅一律 409。批改动作写入审计
   表，谁、何时、给谁、打了多少分可追溯。

## 3.6 安全设计

安全设计遵循"默认不信任，边界显式"（详见 SECURITY.md，五节均可成小节）：

- **网络边界**：默认只绑 127.0.0.1；`public_mode` 打开后收紧会话时长、注册
  转管理员审批、实验并发降为 1，页面常驻安全提示；
- **账号**：口令 PBKDF2-HMAC-SHA256，盐 + 迭代参数入库（口径出自文献 [4]），
  比对用 `hmac.compare_digest` 恒时比较；登录限流（滑窗）；会话可
  服务端强制下线；
- **权限**：`can()` 唯一判定源 + 越权负面用例（越权 403、自封拒绝、未绑定
  403、越级 403）；
- **运行沙箱**：固定命令表 + 并发限额 + 整树杀（见 3.5.1）；
- **注入面**：SQL 全参数化；页面渲染转义；CSRF 基线（SameSite Cookie +
  状态变更要求同源 Origin）。

**如实声明**（第 6 章局限的来源）：无 HTTPS、无 2FA、非容器级隔离、单机
单进程——课堂与可信局域网是设计目标场景，公网部署需要额外的反向代理与
运维能力。

五节安全设计可以收拢为一张威胁模型小结，每条威胁都对应一个**结构性边界**
与一个**负面用例锚点**（测试细节见第 5 章）：

| 威胁 | 结构性边界 | 负面用例锚点 |
|---|---|---|
| 越权访问 | `can()` 判定唯一源，前端不判权限 | 越权 403 / 越级 403 / 未绑定 403 |
| 任意命令执行 | 固定命令表，请求只带动作 id | 动作白名单自检 |
| 口令窃取与穷举 | PBKDF2 + 盐 + 恒时比较 + 登录限流 | 失败 5 次 429；改密踢会话 |
| CSRF | SameSite Cookie + 同源 Origin 校验 | 跨源 POST 403 |
| 注入（SQL/HTML） | 全参数化查询 + 页面转义 | 16 类畸形探针 |
| 资源滥用 | 并发限额 + 超时 + Content-Length 钳制 | 限额 429 自检 |
| 路径穿越 | 静态文件根目录约束 | `/repo/` 越界 404 |

这张表也是安全需求的验收索引：设计上每个威胁都有"结构上挡住"的手段，
测试上每条边界都有一个"这样应该被拒绝"的用例钉住——安全设计不依赖
"写代码时小心"。

## 3.7 部署设计

运行形态为单进程 `python server.py`（默认 `127.0.0.1:7900`），`config.json`
切 bind/port/data_dir/max_labs/session_hours/public_mode。两类目标场景：

- **课堂局域网（主打）**：教师机 `bind: 0.0.0.0`，学生浏览器访问
  `http://<教师机IP>:7900/`，实验并发限 2–4 防止课堂齐跑打爆机器；
- **单人 / 公网试用**：public_mode 收紧会话与审批，README 写明边界与备份要求。

运维面：`tools/backup.py`（`VACUUM INTO` 时间戳副本 + 上传文件清单）、恢复 =
停服替换 + 校验、`tools/bench.py` 压测、开机自启脚本、日志落盘保留 14 天自动
清理。数据目录（data/、logs/、backup/）均不进版本库。
