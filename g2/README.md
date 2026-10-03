# G2 练习册（生成物：`python g2/render.py --write`）

> 22 张卡片（B1–B22）：**口述提纲 / 独立修改任务 / 失败复现任务**——内容全部取自
> 各项目 README 的「练习建议」与「踩过的坑」（或 dorm-repair 的练习），**不新造题**；
> 每张卡的来源锚点由 `python g2/render.py --check` 逐字核对，README 一改就红。
> **完成归你**：卡片只搭脚手架，不代做、不代勾。

## 用法（每张卡 30–60 分钟）

1. 先做「口述提纲」：关掉代码把这些讲给空气听一遍；卡壳的点就是该回读的。
2. 做「独立修改任务」：改完跑项目 `run.bat`，全绿再收手。
3. 做「失败复现任务」：先写下「我预言哪条会红」，再跑——对不上是更有价值的收获。
4. 填「完成记录」。22 张全做完，你对这个仓库的掌握就不再是「我写过」，而是「我能改」。

## 卡片

| 卡 | 主题 | 课程 | 项目 |
|---|---|---|---|
| [B1](B1.md) | 手写 vector / list / string + 待办清单 | 计算机程序设计基础(C++) | `projects/B1-cpp-ministl` |
| [B2](B2.md) | 八个 ADT + 复杂度对照 | 数据结构 | `projects/B2-datastruct-lab` |
| [B3](B3.md) | 命题逻辑 + 二元关系 | 离散结构 | `projects/B3-logic-lab` |
| [B4](B4.md) | 数论 + 教学 RSA | 集合论与代数 | `projects/B4-algebra-rsa` |
| [B5](B5.md) | 五级流水线 CPU 模拟 | 数字设计与计算机原理(计组) | `projects/B5-cpu-sim` |
| [B6](B6.md) | x86-64 汇编四函数 + ABI 纪律 | 汇编语言 | `projects/B6-asm-lab` |
| [B7](B7.md) | 迷你 make + 日志统计 | 软件开发技术基础 | `projects/B7-mini-make` |
| [B8](B8.md) | 迷你 shell（fork/exec/管道/重定向） | 开源操作系统 | `projects/B8-mini-shell` |
| [B9](B9.md) | OS 模拟器：调度 / 页面置换 / FAT / 银行家 | 操作系统原理 | `projects/B9-os-sim` |
| [B10](B10.md) | 教学数据库：WAL + 事务 + B+ 树 | 数据库系统 | `projects/B10-minidb` |
| [B11](B11.md) | HTTP/1.1 子集 + GBN 可靠传输 | 计算机网络 | `projects/B11-net-lab` |
| [B12](B12.md) | 五大范式算法竞技场 | 算法分析与设计 | `projects/B12-algo-arena` |
| [B13](B13.md) | 编译器 tinylang（词法→VM） | 编译原理 | `projects/B13-tinylang` |
| [B14](B14.md) | Java 画板（撤销/重做 + 可信存取） | Java 面向对象程序设计 | `projects/B14-java-paint` |
| [B15](B15.md) | 需求工程：SRS + 可执行需求模型 | 软件工程基础 + 软件需求工程 | `projects/dorm-repair` |
| [B16](B16.md) | 交互设计：线框 + 四态 + 走查原型 | 软件交互设计 | `projects/dorm-repair` |
| [B17](B17.md) | 体系结构：依赖方向 + ADR + 契约 | 软件体系结构 | `projects/dorm-repair` |
| [B18](B18.md) | 平台层：Java 分层单体 + 跨语言对拍 | 软件开发架构平台 | `projects/dorm-repair` |
| [B19](B19.md) | 第二种接口形态：SOAP 1.2 端点 | SOA 原理与技术 | `projects/dorm-repair` |
| [B20](B20.md) | 测试与验证工程：收缩 / 变异 / 流水线 | 软件测试 | `projects/dorm-repair` |
| [B21](B21.md) | 质量门禁与失败分诊 | 软件质量保证 | `projects/dorm-repair` |
| [B22](B22.md) | 项目管理：事实台账 + 风险/复盘 | 软件项目管理 | `projects/dorm-repair` |

## 维护

- 机器可读源是 `g2/cards.json`；重渲染 `python g2/render.py --write`，校验 `python g2/render.py --check`。
- 改过任何项目的 README 练习建议/坑之后，`--check` 会因锚点漂移报红——按提示对齐锚点与文案。
- 自测（含「改坏必须红」的负面对照）：`python g2/tests/test_g2.py`。
