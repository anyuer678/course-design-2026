# CourseLab 详细设计 v1（可直接开工的规格）

> 配套：`docs/PLAN.md`（定位与里程碑总纲）；本文是**开工规格**（概念 / 多端 / 功能点 / 数据 / API / 部署）。
> 角色权限矩阵以 PLAN 为唯一出处，本文只引用不重复。

## 零、对标自检（对应用户给的三条标尺）

| 标尺 | 本设计的落实 | 对应编号 |
|---|---|---|
| **多端** | 三端：学生端（PC + 移动浏览器响应式 H5）、教师端、管理端；同一服务进程托管 | 见 §二 |
| **十几个功能点** | 18 个功能点（F1-F18，全部编号，里程碑按编号跟踪） | 见 §三 |
| **能真实部署使用** | 单进程 + 配置 + 数据目录 + 备份/恢复 + 课堂局域网与公网两种场景 | 见 §七 |

现状：**M0–M9 全部交付**——平台完整可用且可部署：账号（含**修改口令**）、33 门课程工作区与
项目页、在线实验（SSE/限额/审计）、练习任务闭环、管理端（看板含**访问量**/治理/审批）、
**教师课程维护**（补充简介/大纲/发布开关）、F8 通知公告、管理动作审计、移动端响应式、
**日志落盘（保留 14 天）**、配置化与运维工具（备份恢复/压测/自启）、部署/安全/论文三份文档。
后续按需平移到主流栈或扩展（见 THESIS §展望）。

## 一、概念模型：什么叫"每个课程各有一个小型项目平台"

仓库现状是"33 门课、每门课一个项目"（现算自 `showcase/manifest.json`）。
平台做的事情：给**每门课程**开一个工作区（小型项目平台），工作区固定五块：

```
平台门户
 └─ 课程工作区（每门课一个，如「计算机网络」）
     ├─ 简介区    课程一句话 / 大纲 / 教师与开课信息
     ├─ 项目区    该课的项目清单（当前 1:1）→ 项目页
     ├─ 演示与实验  项目页两个页签：在线演示（既有自查页嵌入）、在线实验（真跑）
     ├─ 练习任务  该课的练习（内容源：g2/ 练习册）＋ 领取/提交记录
     └─ 资料与公告 附件 / 站内公告
```

三条设计原则：
1. **内容源唯一**：课程/项目元数据现算自仓库（manifest + 各 README），平台数据库只存
   "平台态"（发布/排序/封面/任务/记录/审计），两层按 id 关联；仓库改了，平台跟着变。
2. **判定唯一**：角色权限矩阵（PLAN §三）落成服务端一个函数 `can(user, action, target)`，
   页面只读判定结果，不复制规则。
3. **命令白名单**：在线实验沿用 lab 的边界——客户端只能选 `项目 × 动作 id`，
   命令表在服务端写死，带不了任意命令/参数/路径。

## 二、多端设计（三端总览）

| 端 | 使用者 | 入口 | 核心职责 | 形态 |
|---|---|---|---|---|
| 学生端 | 学生 / 访客 | `/`（对外主入口） | 浏览课程与项目 → 看演示 → 动手实验 → 做任务 | 响应式 Web（PC + 手机浏览器自适应），零构建 |
| 教师端 | 教师 | `/teacher/` | 维护本课（简介/大纲/项目关联/发布）、布置与查看任务、本课统计 | Web |
| 管理端 | 管理员 | `/admin/` | 平台治理：用户/课程与项目/实验审计与队列/平台看板 | Web |

口径（写死）：**不做原生 App**（无构建链、可部署优先）；"多端"= 三端同源 Web，
学生端同一套页面在移动浏览器上按响应式规则呈现（不维护第二套移动站）。

三端共享：同一套设计 token 样式、同一个 JSON API、同一份权限模型；
三端各自的页面目录：`web/student/`、`web/teacher/`、`web/admin/`（同进程托管）。

## 三、功能点全清单（18 个，编号即里程碑的跟踪单位）

**学生端（F1-F8）**
- **F1 注册 / 登录 / 登出**：用户名 + 口令；口令 PBKDF2（盐 + 迭代，参数写进文档）；
  会话 = Cookie 令牌 + 服务端会话表（可强制下线）；登录限流（滑窗计数）。
- **F2 门户首页**：平台概览（课程数 / 项目数 / 练习卡数）+ 课程目录（搜索 + 批次筛选）。
- **F3 课程工作区**：每门课一个工作区（§一 的五块结构），展示现算的课程信息与项目清单。
- **F4 项目页**：详情（一句话 / 知识点 / 踩坑摘要，现算自 README）＋ **在线演示**
  （嵌入既有自包含展示页）＋ **在线实验**页签。
- **F5 在线实验**：对"项目 × 动作"表发起点选（跑演示 / 跑测试 / 启停服务）；
  SSE 实时日志流；结果与耗时落审计。
- **F6 练习任务**：任务列表（内容源自 g2 卡片）；领取 → 完成记录 → 进度条。
- **F7 个人中心**：我的任务、我的实验记录、修改口令。
- **F8 通知与公告**：未读计数、列表、已读标记。

**教师端（F9-F11）**
- **F9 课程维护**：补充简介（≤120 字）/ 大纲（≤2000 字）/ 发布开关（覆盖层写回平台 DB，
  课程页并列展示并标明维护教师）；关联项目＝manifest 1:1 现算，不设编辑；封面（cover）不做。
- **F10 任务布置与查看**：按课布置任务（标题/说明/截止）、查看领取与完成名单；
  内置任务即 g2 卡片，自定义任务不强制挂卡（如实登记）。
- **F11 本课统计**：完成率、实验次数排行（本课项目 lab_runs 按人聚合 Top 10）、最近活动（限本人课程）。

**管理端（F12-F15）**
- **F12 用户管理**：注册审批、角色调整（学生/教师/管理员）、封禁/解封。
- **F13 课程与项目治理**：上架/下架、排序、封面、教师绑定。
- **F14 实验审计与队列**：全部实验运行记录（谁/何时/项目/动作/耗时/结果）；
  并发限额（默认同时 2 个）；运行中任务可强停（整树杀）。
- **F15 平台看板**：访问量（`/` 与 *.html 页面计数，匿名计入；资源与 API 不计）、实验数、
  任务完成、活跃用户（手写 SVG，不引图表库）。

**平台底座（F16-F18）**
- **F16 会话与安全边界**：`can()` 判定唯一源；越权负面用例进测试；默认只绑回环；
  公网开关显式打开；CSRF 基线（SameSite Cookie + 状态变更需同源）。
- **F17 数据备份与恢复**：`tools/backup.py`（SQLite `VACUUM INTO` 时间戳副本 + 上传文件清单）；
  恢复 = 停服替换 + 校验；备份不进 git。
- **F18 部署与配置**：`config.json`（bind/port/data_dir/max_labs/session_hours/public_mode）；
  `run.bat` 与 `python server.py` 双入口；开机自启脚本；日志落盘
  `<数据目录>/logs/app-日期.log`，启动时清理超 14 天（目录不可写时降级为仅控制台）。

## 四、页面与路由（信息架构）

| 路径 | 端 | 页面 | 权限 |
|---|---|---|---|
| `/` | 学生 | 门户首页（F2） | 公开 |
| `/login`、`/register` | 学生 | 登录 / 注册（F1） | 公开 |
| `/courses/{code}` | 学生 | 课程工作区（F3） | 公开（任务区需登录） |
| `/projects/{pid}` | 学生 | 项目页：详情 / 演示 / 实验 三页签（F4/F5） | 公开；实验需登录 |
| `/tasks`、`/me` | 学生 | 任务与个人中心（F6/F7） | 登录 |
| `/teacher/`、`/teacher/courses/{code}` | 教师 | 教师台与课程维护（F9） | 教师 |
| `/teacher/tasks`、`/teacher/stats` | 教师 | 任务与统计（F10/F11） | 教师 |
| `/admin/`、`/admin/users` | 管理 | 总览与用户（F12） | 管理员 |
| `/admin/courses`、`/admin/labs`、`/admin/dashboard` | 管理 | 治理 / 审计与队列 / 看板（F13-F15） | 管理员 |

页面内所有"能力"（按钮/入口）由 `can()` 驱动渲染——前端不判权限。

## 五、数据模型（SQLite；两层结构）

原则：**仓库现算层**（课程/项目/演示/练习内容）不落库、每次现算；
**平台态层**（下表）只存平台自己的状态。两层按 `pid` / `course` 关联。

| 表 | 关键字段 | 说明 |
|---|---|---|
| `users` | id, username, display_name, role, pwd_hash, pwd_salt, pwd_iter, status, created_at, last_login | role: student/teacher/admin；status: pending/active/banned |
| `sessions` | token, user_id, created_at, expires_at, ip, ua | 登出/改密即失效；过期清扫 |
| `course_meta` | course, published, sort, teacher_id, summary, outline | 覆盖层：发布/排序/绑定教师 + 教师维护的补充简介/大纲（旧库自动 ALTER 迁移；cover 未做） |
| `project_meta`（未建） | — | 项目治理并入课程治理：课程:项目=1:1，项目随课程上/下架 |
| `tasks` | id, course, pid, title, body, due_at, created_by, g2_card | 内容源可挂 g2 卡片 id |
| `task_records` | task_key, user_id, course, status, note, submission, submitted_at, grade, feedback, graded_at, updated_at | status: doing/done/submitted/graded；(task_key, user_id) 主键；重交清分（M12） |
| `lab_runs` | id, user_id, pid, action, started_at, finished_at, exit, log_tail | 审计与 F14 队列的数据源 |
| `audit` | id, ts, actor, action, target, detail, ip | 治理动作全量留痕 |
| `notices` | id, title, body, audience, created_by, created_at | F8 |

## 六、API 草案（v1；M2 前冻结）

约定：请求/响应 JSON；错误统一 `{"ok": false, "error": "...", "code": "..."}`；
状态码 400/401/403/404/409/429/500；SSE 事件 `event: log` / `event: done`（附 `data: {...}`）。

| 分组 | 路由 | 说明 |
|---|---|---|
| auth | `POST /api/auth/register|login|logout`、`POST /api/auth/password`、`GET /api/me` | F1/F16/F7 |
| courses | `GET /api/courses`、`GET /api/courses/{code}` | F2/F3（现算 + 覆盖层合并） |
| projects | 项目详情与"项目 × 动作"表随 `GET /api/courses/{code}` 返回（**无独立 /api/projects 路由**，F4 数据经课程详情负载下发） | F4（详情 + 演示地址 + 动作表） |
| labs | `POST /api/labs/run`、`GET /api/labs/runs/{id}`、`GET /api/labs/runs/{id}/log`（SSE）、`POST /api/labs/runs/{id}/stop` | F5（动作 id 白名单） |
| tasks | `GET /api/tasks`、`POST /api/tasks/{id}/claim`、`POST /api/tasks/{id}/done`、`GET /api/tasks/mine` | F6/F7 |
| tasks（M12） | `POST /api/tasks/submit`（交作业，重交清分）、`GET /api/teacher/submissions?course&key`、`POST /api/teacher/grade`（0-100，已批可改分） | F6/F10 |
| teacher | `GET /api/teacher/courses`、`GET /api/teacher/course`、`POST /api/teacher/tasks`、`POST /api/teacher/tasks/{id}/delete`、`POST /api/teacher/course/meta` | F9-F11 |
| admin | `GET/PUT /api/admin/users`、`PUT /api/admin/courses|projects`、`GET /api/admin/labs`、`POST /api/admin/labs/{id}/kill`、`GET /api/admin/dashboard` | F12-F15 |
| notices | `GET /api/notices`、`POST /api/notices/{id}/read` | F8 |
| 补充端点 | `GET /api/labs/active`、`GET /api/labs/runs/mine`、`GET /api/admin/overview`、`GET /api/admin/audit`、`POST /api/notices/read-all` | F5/F14/F15/F8 |

上表为 v1 草案（24 条含 SSE）；M3–M8 实际扩展多处（通知/审计/口令/课程维护/服务页面等），
路由以 `server.py` 现行为准。

## 七、部署设计（能真实部署使用）

**运行形态**：单进程。`python server.py`（默认 `127.0.0.1:7900`）；
`config.json` 或命令行切 `bind/port/data_dir/max_labs/session_hours`。

**目录**：
```
courselab/
  server.py / web / docs / tools
  data/       app.db（SQLite）、uploads/    ← 唯一可变状态，不进 git
  logs/       轮转日志（保留 14 天），不进 git
  backup/     备份产物，不进 git
```

**场景 A：课堂局域网（主打）**——老师机器：`config.json` 里 `bind: 0.0.0.0`；
学生手机/电脑浏览器访问 `http://<老师机IP>:7900/`；实验并发限 2-4，防止课堂齐跑打爆机器；
管理端只对教师/管理员开放。

**场景 B：单人 / 公网试用**——`public_mode: true` 时：强制会话超时收紧、
注册转"管理员审批"、实验并发限 1；页面顶部常驻安全提示；README 写明边界与备份要求。

**运维**：备份 `python tools/backup.py`（手动/计划任务均可）；恢复=停服替换 app.db + 校验行数；
升级=替换代码目录（data/ 不动）；Windows 开机自启用计划任务（`tools/` 下脚本，M6 交付）。

## 八、里程碑映射（与 PLAN §七对齐）

| 里程碑 | 覆盖功能点 | 验收要点 |
|---|---|---|
| **M0 已完成** | 骨架 | selftest 4/4；现算目录 33 项 |
| M1 账号与会话（已交付） | F1 + F16（会话部分） | 注册/登录/登出端到端；越权与并发会话负面用例 |
| M2 课程目录与项目页（已交付） | F2/F3/F4 | 33 门课工作区可浏览；项目页三页签（演示可看）；协议 v1 冻结 |
| M3 在线实验（已交付） | F5 + F14（队列部分） | 真实跑通演示/测试；SSE 日志滚动；并发限额与整树杀 |
| M4 任务闭环（已交付） | F6/F10/F11 | 布置→领取→完成全链路；完成率统计与现算一致 |
| M5 多端补全（已交付） | F7/F9/F12/F13/F15（F8 转入 M7 落地） | 三端可用；看板手写 SVG；角色/状态/课程治理留审计 |
| M6 部署与论文素材（已交付） | F16 审批/F17/F18 | 课堂场景真机演示；备份/恢复演练；需求/设计/测试/部署四章素材 |
| M7 收官补全（已交付） | F8 + 管理动作审计 + 响应式 | 通知可见性负面用例（未绑定 403/越级 403）；四类动作留痕；≤720px 断点样式 |
| M8 F7/F9 补全（已交付） | F7 修改口令 + F9 课程维护 | 旧口令校验计入限流、其他会话即失效；教师维护的 403/超长 400/下架隐藏；旧库 ALTER 迁移保数据 |
| M9 对账补全②（已交付） | F11/F14/F15/F18 | 访问量只计页面（+2 精确断言、API 不计）；日志保留 14 天自动清理；排行按人聚合；审计含耗时 |
| M10 健壮性审查（已交付） | 全接口 | 畸形类型探针 16 类全 4xx 零崩溃；teacher_id 500 修复；Content-Length 钳制 |
| M11 并发与清理审查（已交付） | 实验台 + 会话 | 就绪判定连续稳定观察（白盒 A/B 复现误报→修复）；停止文案区分；会话启动清扫 |

## 九、边界（这一版说"不"）

- 不做原生 App、即时通讯、音视频、白板（参照项目只是规模标尺）；
- 不引云服务/付费组件/前端构建链；不接 CI；
- 课程/项目内容不落库（现算是唯一口径）；权限判定不写第二份。
