# G2 练习册（生成物：`python g2/render.py --write`）

> 40 张卡片（B1–B41；B36 未做）：**口述提纲 / 独立修改任务 / 失败复现任务**——内容全部取自
> 各项目 README 的「练习建议」与「踩过的坑」（或 dorm-repair 的练习），**不新造题**；
> 每张卡的来源锚点由 `python g2/render.py --check` 逐字核对，README 一改就红。
> **完成归你**：卡片只搭脚手架，不代做、不代勾。

## 用法（每张卡 30–60 分钟）

1. 先做「口述提纲」：关掉代码把这些讲给空气听一遍；卡壳的点就是该回读的。
2. 做「独立修改任务」：改完跑项目 `run.bat`，全绿再收手。
3. 做「失败复现任务」：先写下「我预言哪条会红」，再跑——对不上是更有价值的收获。
4. 填「完成记录」。40 张全做完，你对这个仓库的掌握就不再是「我写过」，而是「我能改」。

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
| [B23](B23.md) | 五个机器学习算法全手写 | 人工智能导论 | `projects/B23-ml-from-scratch` |
| [B24](B24.md) | 文档扫描仪（检测→还原→二值化） | 计算机视觉 | `projects/B24-cv-scanner` |
| [B25](B25.md) | 中文分词 + 朴素贝叶斯 | 自然语言处理 | `projects/B25-nlp-lab` |
| [B26](B26.md) | Apriori + K-means + 可追溯清洗链 | 数据挖掘与实践 | `projects/B26-datamining` |
| [B27](B27.md) | 课程知识图谱（先修关系） | 知识图谱与知识工程 | `projects/B27-course-kg` |
| [B28](B28.md) | BI 看板 + 指标口径 | 数据分析与商务智能 | `projects/B28-bi-dashboard` |
| [B29](B29.md) | PySpark 日志清洗与倾斜实验 | 工业大数据处理技术 | `projects/B29-bigdata-spark` |
| [B30](B30.md) | Raft 共识模拟（快照 + 成员变更） | 分布式与云计算 | `projects/B30-mini-raft` |
| [B31](B31.md) | 短链服务（HTTP + SQLite） | Web系统与技术 | `projects/B31-shorturl` |
| [B32](B32.md) | 安全实验四组（漏洞版 vs 修复版） | 信息安全导论 | `projects/B32-sec-lab` |
| [B33](B33.md) | 算法可视化（操作记录回放动画） | 可视化技术 | `projects/B33-viz-algo` |
| [B34](B34.md) | 栅格 A* / Dijkstra / BFS 规划 | 无人系统 | `projects/B34-path-planner` |
| [B35](B35.md) | 手写 MQTT（broker + 客户端 + 入库对账） | 工业物联网技术 | `projects/B35-iot-mqtt` |
| [B37](B37.md) | 设备故障预测（复用的边界由实测决定） | 行业软件前沿应用 | `projects/B37-industry-ai` |
| [B38](B38.md) | mini-redis（RESP2 + 过期 + 主从复制） | 软件工程案例分析与实践 | `projects/B38-mini-redis` |
| [B39](B39.md) | 技术雷达（记录模板 + 可机验证据） | 专业前沿技术讲座 | `projects/B39-tech-radar` |
| [B40](B40.md) | 技能差距矩阵（证据可核验 + JD 映射器） | 专业实习 | `projects/B40-career-map` |
| [B41](B41.md) | 毕设候选三维可行性（数字会过期） | 毕业设计（论文） | `projects/B41-thesis-seeds` |

## 维护

- 机器可读源是 `g2/cards.json`；重渲染 `python g2/render.py --write`，校验 `python g2/render.py --check`。
- 改过任何项目的 README 练习建议/坑之后，`--check` 会因锚点漂移报红——按提示对齐锚点与文案。
- 自测（含「改坏必须红」的负面对照）：`python g2/tests/test_g2.py`。
