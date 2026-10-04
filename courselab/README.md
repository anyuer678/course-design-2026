# CourseLab 课程工坊 —— 课程项目平台（毕设工程）

**每个课程各有一个小型项目平台**：把课设仓库里的 33 个项目、自包含展示页、实验台与练习册，
升格成一个能登录、能在线运行、能管理、能部署的 Web 平台（一份底座，每门课程一个工作区）。

- 定位与里程碑：`docs/PLAN.md`（角色矩阵 / 功能面 / 架构 / 里程碑 M0–M7）
- **详细设计（开工规格）**：`docs/DESIGN.md`（多端三端 / 18 个功能点 F1-F18 / 页面路由 /
  数据模型 / API 草案 / 部署设计）
- 现状：**M0–M7 全部交付**（M7 收官补全：F8 通知公告 / 管理动作审计 / 移动端响应式）——
  平台完整可用且可部署；自检 **100 项**全绿（`python server.py --selftest`）。
  功能面：账号与会话、33 门课程工作区、项目页（详情/演示/实验）、在线实验
  （SSE 日志/限额/审计/强停）、练习任务闭环（学生+教师）、**通知与公告（未读角标/课程公告/全员
  公告）**、管理端（看板 SVG/用户/课程治理/审计/**管理动作留痕**/审批）。运维面：`config.json`
  配置、注册审批流、备份/恢复/压测工具、开机自启脚本（需在部署机以管理员执行）。
- 文档：`docs/PLAN.md`（方案书）· `docs/DESIGN.md`（详细设计）· `docs/DEPLOY.md`（部署运维）·
  `docs/SECURITY.md`（安全边界报告）· `docs/THESIS.md`（论文素材索引）

## 角色与管理员账号

- 注册的账号默认是**学生**；
- 教师/管理员用命令行提升（先注册，再提升，立即生效）：
  `python server.py --promote 用户名 teacher`（或 admin）；
- 入口：顶栏「教师台」（/teacher.html）/「管理端」（/admin.html，仅管理员）；
- 教师只能管**绑定给自己**的课（管理员在管理端绑定）。

## 运行

```
双击 run.bat            # 起在 http://127.0.0.1:7900 并自动打开浏览器（正式数据在 data/app.db）
python server.py        # 同上（不开浏览器）
python server.py --config 路径 --host 0.0.0.0 --port 8000   # 部署到局域网（见 docs/DEPLOY.md）
python server.py --selftest   # 自检（临时库：账号/实验/任务/管理/工具 全链路 + 负面用例）
python server.py --promote 用户名 admin    # 角色工具（先注册，再提升）
```

## 目录

```
courselab/
  server.py        标准库 HTTP 服务 + 路由 + 会话 + SSE + 自检（零第三方依赖）
  app/             领域层：db / auth / courses / tasks / labs / admin / can（判定唯一源）
  web/             三端页面：学生（门户/登录/注册/课程/项目/我的任务/我的）· 教师台 · 管理端
  tools/           运维工具：backup / restore / bench / install_autostart / uninstall_autostart
  config.example.json  配置模板（复制为 config.json 生效；config.json 不进 git）
  data/ logs/ backup/   运行期数据（不进 git）
  docs/            PLAN / DESIGN / DEPLOY / SECURITY / THESIS 五份文档
  run.bat          启动脚本（纯 ASCII + CRLF）
```

说明：本目录与课设治理（showcase/g2/check_all）隔离；课程与项目数据现算自仓库
（`showcase/manifest.json` 是唯一出处），平台不维护第二份。
