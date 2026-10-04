# CourseLab 课程工坊 —— 课程项目平台（毕设工程）

**每个课程各有一个小型项目平台**：把课设仓库里的 33 个项目、自包含展示页、实验台与练习册，
升格成一个能登录、能在线运行、能管理、能部署的 Web 平台（一份底座，每门课程一个工作区）。

- 定位与完整方案：`docs/PLAN.md`（角色矩阵 / 功能面 / 架构 / 里程碑 M0–M6）
- 现状：**M0（方案书 + 可运行骨架）**

## 运行

```
双击 run.bat            # 起在 http://127.0.0.1:7900/ 并自动打开浏览器
python server.py        # 同上（不开浏览器）
python server.py --selftest   # 自检：health / 课程目录现算 / 首页 / 项目页可打开
```

## 目录

```
courselab/
  server.py        标准库 HTTP 服务 + 自研路由 + 自检（零第三方依赖）
  web/index.html   占位首页（列出仓库现算的 33 个项目）
  docs/PLAN.md     方案书（里程碑与验收口径）
  run.bat          启动脚本（纯 ASCII + CRLF）
```

说明：本目录与课设治理（showcase/g2/check_all）隔离；课程与项目数据现算自仓库
（`showcase/manifest.json` 是唯一出处），平台不维护第二份。
