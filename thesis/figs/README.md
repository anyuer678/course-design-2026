# thesis/figs —— 论文图表（手写自包含 SVG）

沿用仓库"图表是自己拼出来的字符串，形状由数据决定"的传统（B28 看板 /
svgplot / DataScope 报告同一条纪律）：每张图零外链、白底、系统字体，可在
浏览器直接打开，也可在 Word/WPS 里"插入图片"或用浏览器截图后按学校模板
排版。**图形内容与代码/文档一一对应，改了实现要回来改图。**

| 文件 | 论文位置 | 内容与出处 |
|---|---|---|
| `fig-1-1-产品矩阵.svg` | 第 1 章 1.4 / 附录 A | Studio 门户 + 八个 managed 产品（端口/引擎来源/测试数）；出处：PRODUCTS.md §二 + check_all 15 步（2026-10-06） |
| `fig-3-1-总体架构.svg` | 第 3 章 3.1 | 五层单向依赖（web → HTTP 服务 → 领域层 → 存储 → 运行时）；出处：DESIGN §五、PLAN §五 |
| `fig-3-2-数据模型.svg` | 第 3 章 3.3 | 平台态 12 表（核心 8 详列 + 支撑 4 注记）+ 现算内容源虚线（两层结构，id 关联）；出处：app/db.py SCHEMA（12 张已建表，project_meta 未建） |
| `fig-3-3-时序-登录.svg` | 第 3 章 3.4 / 第 4 章 4.2 | 登录时序：限流 → PBKDF2 恒时比较（120000 迭代）→ 会话签发 → Cookie；失败路径与改密踢会话 |
| `fig-3-4-时序-在线实验.svg` | 第 3 章 3.4 / 第 4 章 4.4-4.5 | 实验时序：白名单动作 → spawn → SSE log/done 循环 → 审计落库 → 整树杀（含教训注释） |

## 校验

```bash
python -c "import glob,xml.etree.ElementTree as ET;
[ET.parse(f) for f in glob.glob('thesis/figs/*.svg')]"   # XML 良构（2026-10-06 五张全过）
```

渲染目检：2026-10-06 经 Edge headless（`--headless=new --screenshot`）逐张渲染并
目检——fig-3-1 领域层行尾"（判定唯一源）"溢出绿框当场抓出并删（与下一行
"权限矩阵落成唯一函数"同义冗余）；其余四张无溢出。SVG 编辑须防静默不落盘：
写盘后用独立通道复核（见 project_memory 教训）。

## 待用户

- 按学校模板的图表编号规则重命名（图 3-1 / 图 3-2…已按此占位）；
- 若模板要求位图，浏览器打开后导出 PNG（或用 `chrome --headless --screenshot`）。
