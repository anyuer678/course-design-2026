# 展示层工程 —— 每个项目一个自包含 HTML 展示页（口径）

**用户点项（2026-10-03）**："每个项目都要有前端和展示"。本工程把它落成可验收的形式：
仓库里 33 个项目**每个一个自包含 HTML 展示页**（双击即看、零网络依赖），
仓库根 `showcase/index.html` 是总入口。**页面是提交物**（进仓库、进 git），
不是构建垃圾——生成器 + 新鲜度校验照 `traceability.csv` 的同一套做法。

## 一、页面规范（每条都有机器核对，`check.py` 执行）

1. **单文件自包含**：UTF-8 + `lang="zh-CN"` + 非空 `<title>`，以 `<!DOCTYPE html>` 开头；
   **零网络依赖**——`src=`/`href=`/`url()` 不得指向外部（协议或 `//` 开头）；
   全文出现 `http(s)://` 的唯一例外是 W3C 命名空间串（`www.w3.org`，它是标识符不是请求）。
2. **必备锚点**：`<body data-showcase="<项目 id>">`（与 `manifest.json` 对得上）、
   `id="facts"`（实测数字区）、`id="demo"`（展示/交互区）、`id="repro"`（怎么自己跑）。
3. **生成物标记**：页脚必须含重生成命令字符串 `tools/showcase.py --write`。
4. **脚本规范**：不用 `innerHTML / outerHTML / document.write / insertAdjacentHTML`
   （数据可信与否不是例外理由）；每个内联 `<script>` 过 `node --check`
   （机器上没有 node 时记一条 skipped，不算红）。
5. **数据全部现算**：页面数据由各项目 `tools/showcase.py` 从**本仓库真实产物**现算嵌入；
   `--check` 重算比对，过期即红。
6. **交互 = 对真实产物的回放 / 切换 / 筛选**，不是第二套实现：JS 里不许重算业务结果，
   只负责把现算好的数据渲染出来。
7. **观感归用户**：好不好看、顺不顺手由你双击打开验收，我不代勾（与 B16 走查同一规矩）。

## 二、生成器与校验规范

- 生成器：`projects/<P>/tools/showcase.py`，两种模式——
  `--write` 现算并写出 `projects/<P>/web/showcase.html`；`--check` 重算比对（不写盘），退出码 0/1。
- 项目内测试：新鲜度、数据抽查（与现算源一致）、自包含 lint、负面对照。
- 仓库级：`showcase/check.py` 统一再验（结构 + 自包含 + node --check + 逐项目 `--check`
  子进程 + 总入口新鲜度与链接）；负面对照在 `showcase/tests/`。
- 总入口：`showcase/index.html` 由 `python showcase/check.py --write-index` 从
  `manifest.json` 生成（已交付的给链接、待补的给状态签）；链接目标不存在即红。

## 三、批次表（一轮一批；做完把 `manifest.json` 里对应项转 `done` 再更新本表）

| 批次 | 主题 | 项目 | 状态 |
|---|---|---|---|
| 1 | 口径与试点（编译器透视） | `B13-tinylang` | 已交付 |
| 2 | 算法与离散基本盘 | `B12-algo-arena`、`B3-logic-lab`、`B4-algebra-rsa` | 已交付（2026-10-03） |
| 3 | 系统底层 | `B5-cpu-sim`、`B6-asm-lab`、`B9-os-sim` | 已交付（2026-10-03） |
| 4 | 数据结构与工程 | `B1-cpp-ministl`、`B2-datastruct-lab`、`B7-mini-make` | 已交付（2026-10-03） |
| 5 | 网络与安全 | `B8-mini-shell`、`B11-net-lab`、`B32-sec-lab` | 已交付（2026-10-03） |
| 6 | 数据库与分布式 | `B10-minidb`、`B30-mini-raft`、`B38-mini-redis` | 已交付（2026-10-03；整合补全归本会话） |
| 7 | 人工智能与数据 | `B23-ml-from-scratch`、`B25-nlp-lab`、`B26-datamining` | 已交付（2026-10-03；整合补全归本会话） |
| 8 | 视觉 / 物联网 / 工业 | `B24-cv-scanner`、`B35-iot-mqtt`、`B37-industry-ai` | 已交付（2026-10-03） |
| 9 | 数据与可视化（存量对齐） | `B27-course-kg`、`B28-bi-dashboard`、`B29-bigdata-spark`、`B33-viz-algo`、`B34-path-planner` | 已交付（2026-10-03） |
| 10 | 交互 / 工具 / 业务存量 | `B14-java-paint`、`B31-shorturl`、`B39-tech-radar`、`B40-career-map`、`B41-thesis-seeds`、`dorm-repair` | 已交付（2026-10-03） |

存量说明（批次 9/10 的额外工作，都要按上表第一节的规范对齐）：

- `B33`/`B34`/`B27` 已有"自包含交互页"生成器，但产物不进仓库（`build/` 或临时目录）——
  批次 9 把展示页提升为**提交物**（页面进各自 `web/showcase.html`）；
- `B31`/`dorm-repair` 的浏览器前端要起服务器（产品/原型形态，不是展示页）——前端保持不动，
  批次 10 另做展示页（介绍 + 实测数字 + 起服务的方式 + 交互要点）；
- `B14` 真窗口 GUI：展示页嵌入它自己的**离屏渲染自检产物**（真实 PNG 产物路径或内联图），
  不假装能开窗；
- `B28`/`B35`/`B24` 已有 SVG/PNG 产物：展示页引用同一套产物（不另造数据）。

## 四、运行

```
python showcase/check.py                  # 仓库级校验（结构/自包含/逐项目 --check/总入口）
python showcase/check.py --write-index    # 重生成总入口 showcase/index.html
python -m unittest discover -s showcase/tests
```

单项目：`python tools/showcase.py --write`（在项目目录里跑）。

## 五、边界（先说死，免得走形）

- 不引入任何框架/字体/CDN；页面离线可看（file:// 双击）。
- 不把业务逻辑写进 JS；不重写第二套实现。
- 不替用户勾"观感通过"；每批交付后由你双击看。
- 页面里的数字只能来自现算或注明出处；引用 README 数字必须带"见 README"字样。

## 六、交互组件（2026-10-03 升级，随生成物一起受新鲜度校验）

三条统一约定（全部零依赖、无外部请求、GBK 可编码）：

1. **总入口**（`showcase/index.html`，由 `check.py --write-index` 生成）：实时搜索（项目编号/课程/
   关键词）、批次筛选 chips、命中计数；键盘：`/` 聚焦搜索、`Esc` 清空、回车打开第一条可见项。
2. **每页顶部导航条**（出现在"← 作品集总入口"之后）：`上一件 X · 下一件 Y`——顺序 = 总入口显示
   顺序（批次分组序），首尾页缺省对应方向；链接为相对路径，页内零外链口径不变。
3. **长文页页签组件**（`.pj-tabs/.pj-pane`，纯 HTML+CSS+无框架 JS）：把长演示原文切成可切换段落，
   已用于 B14 / B31 / B39 / B40 / B41 / dorm-repair 六页（其余页面的既有 chips 组件照旧）。

口径：交互是**生成物的一部分**——任何改动必须落进各项目生成器再 `--write`，`--check` 过期仍红；
交互 JS 一律过 `node --check`（校验器执行）。观感与手感仍归用户实跑验收。

## 七、实时实验台（showcase/lab.py，2026-10-03）——让前端真正控制后端

用户反馈"前端相当于 PPT，缺少对真实后端的控制"后的补齐：展示页默认仍是**静态自包含**（双击即看），
另外提供一台**本地实验台**，页面接上它就从"录像"变成"控制台"：

- **启动**：仓库根 `python showcase/lab.py`（纯标准库，只绑 127.0.0.1:7788）。之后从
  `http://127.0.0.1:7788/showcase/index.html` 打开任意页面，或双击本地页（实验台在跑即可），
  右下角出现控制台面板；实验台没跑时页面**完全静默**（角落只留一条可关闭的小提示）。
- **能做什么**：启动/停止 6 个**已注册的真实服务**（B11 netlab HTTP、B31 短链、B38 Redis 子集、
  B35 MQTT broker、B28 看板、dorm 原型），对运行中的服务**发任意原始请求**（文本框里 `\r \n \t \\ \xNN` 转义成字节；回复文本 + 字节并排显示），对全部 Python 项目**真跑 demo.py/测试套件**（B1/B2/B5/B6/B7/B9/B14
  走 `run.bat`），并**实时看**这些进程的 stdout/stderr。B8 要在 WSL 里跑，实验台不替它选环境（如实显示未接）。
- **API**（页面 lab.js 与 lab.py 一一对应）：`/lab/api/ping|info|start|stop|run|log|sock`。
- **安全边界（写死）**：只绑回环；只执行 `lab.py` 注册表里的**固定命令**（客户端只能选 id，
  带不了命令/参数/路径）；`sock` 只转发到实验台自己启动过的端口；进程在实验台退出时统一清理。
- **页面侧**：每页生成物里内嵌一段引导脚本（无花括号、f-string 安全；`file://` 时从 127.0.0.1:7788
  加载 `/showcase/lab.js`，失败即静默）；控制台界面全部 DOM API 构建（无 innerHTML），`node --check` 随
  校验器执行。
- **自证**：`python showcase/lab.py --selftest`（真起 B31 → 真发请求断言 201 → 真停）；
  2026-10-03 全服务冒烟 6/6：B31 `201 Created`（341B）、B38 `+PONG`、B35 `CONNACK 20 02 00 00`、
  B28 `200 OK`（5719B）、dorm `200 OK`（6998B）、B11 `HTTP/1.1 404`（真服务的正确回答）。

