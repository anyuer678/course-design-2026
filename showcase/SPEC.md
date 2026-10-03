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
