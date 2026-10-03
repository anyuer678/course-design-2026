# B32-sec-lab —— 信息安全导论实验：四组"漏洞版 vs 修复版"对照 + 一个静态扫描器

**课程映射**：信息安全导论（PLAN 批次 7，复用 B11/B31 的 HTTP 与路径校验经验）。

一句话：**同一个错误模型，四个不同的解析器**。SQL 引擎、HTML 词法器、口令的比较逻辑、
文件系统的路径解析——数据一旦在这些位置获得"语法身份"，就会发生注入类问题。
这里每组都放**并排的漏洞版与修复版**，用同一份输入量出差距，并且**每条判定都要能被改动弄红**。

**三条边界（写在代码里，不只在文档里）**
1. 只在 `127.0.0.1`、内存数据库和临时目录里活动；不联网、不碰任何第三方目标。
2. 每组"漏洞版"都是本实验自己写的教学靶；载荷是教科书级最小样本，不构成攻击能力。
3. 不做真实渗透、不做免杀/绕过 WAF、不做缓冲区溢出（PLAN 的选做项）；不宣称"转义一次就安全"。

## 运行

```
run.bat                            # 五步：测试(discover 60) → 直跑 50 → 政策核对 → 六段演示 → 展示页新鲜度
python -m unittest discover -s tests   # 60 项（50 核心 + 10 展示页）
python tests\test_b32.py               # 50 项核心（直跑入口）
python tests\test_showcase.py          # 10 项展示页（直跑单文件）
python demo.py                         # 六段演示，数字全部现算
python tools\showcase.py --write       # 重生展示页 web\showcase.html（--check 过期即红）
```

纯标准库（`sqlite3` / `hashlib` / `hmac` / `secrets` / `html` / `http.server` / `ast`），**零下载零安装**。

## 目录

| 路径 | 是什么 |
|---|---|
| `sec32/sqli.py` | SQL 注入：谓词改写、UNION 取数、二阶注入、叠句接口差异、LIKE 元字符 |
| `sec32/xss.py` | HTML 注入：四种上下文（文本/属性/JS/href）、`&` 假转义、真 HTTP 取证层 |
| `sec32/creds.py` | 口令存储：明文/MD5/PBKDF2 + 盐与迭代、常量时间比较、可预测令牌 |
| `sec32/traversal.py` | 路径穿越：join 直开 / 黑名单 / 前缀检查 / 解析后归属判定 + 与 stdlib 的分歧表 |
| `sec32/audit.py` | 静态扫描器：`ast` 扫拼接点 + 人工登记表 + **双向比对** |
| `tests/test_b32.py` | 50 项测试（含三处"改坏临时副本"的反向证明与沙箱守卫） |
| `tests/test_showcase.py` | 10 项展示页测试（新鲜度/篡改必红/四组对照解析钉住/计时脱敏真生效） |
| `tools/showcase.py` | 展示页生成器 → `web/showcase.html`（四组对照/扫描器/演示全部现算；第 3 段计时脱敏成 `[现场]`） |
| `demo.py` | 六段演示 |

## 知识点 · 实现 · 怎么被验证（不是"跑过了"，是"能失败"）

| 课程概念 | 落在哪里 | 怎么被验证 |
|---|---|---|
| 注入 = 数据获得语法身份 | 四组并排的 vuln/fixed | 每组都有"漏洞版拿到不该拿的、修复版拿不到"的成对断言 |
| 参数绑定 vs 拼接 | `login_*` / `search_*` | 注释截断（`admin' --`）在拼接版登入 admin、绑定版被拒；UNION 泄漏 2 行 vs 0 行 |
| 载荷成立需要**语法条件** | `PAYLOAD_UNION` 的列数、`--` 收尾 | 列数不对 → `OperationalError`；课本那条 `' OR '1'='1` 因 AND 优先级**在本谓词里不成立**（也写成断言） |
| 标识符不能绑定 | `order_bound` / `order_whitelist` | 绑参列名是**静默无效**（与无排序同序、≠ 真排序）；白名单对合法输入结果不变，对载荷 `COLUMN_NOT_ALLOWED` |
| 二阶注入：危险的 sink 不是 source | `note_report_*` | 安全写入 + 拼接读取 → 泄漏散列；同一数据绑定读取 → 只剩正文 |
| 危害取决于执行接口 | `stacked_outcome` | 同一叠句载荷：`execute()` → `ProgrammingError`（表还在），`executescript()` → 表数 3→2 |
| 按上下文转义 | `escape_text` / `escape_script` / `safe_href` | 6 载荷在漏洞版全部有信号、修复版 0 条；修复版逐字等于 `html.escape(quote=True)` 且往返无损 |
| 二次解码 | `&` 未转义的后果 | `&lt;script&gt;` 解一次就变回标记 => 单列一条断言 |
| 脚本块 / JS 字面量边界 | `</script` 计数、词法还原 | 数据提前闭合脚本块被抓；反斜杠吞掉 JS 右定界符被抓 |
| 口令派生要"贵" | `creds.cost_table` | 现算吞吐：MD5 ≈1.4M/s、PBKDF2-120k ≈19/s => **慢 7 万倍**；100 万词字典 0.7 秒 vs 15 小时 |
| 盐与常量时间比较 | `store_pbkdf2` / `verify_pbkdf2` | 同口令加盐后摘要不同、两边都能验；改迭代次数验不过 |
| 令牌不可预测 | `token_with_random` / `token_with_secrets` | 已知种子能复现 `random` 令牌（断言 True）而 `secrets` 不能 |
| 路径穿越的四种写法 | `serve_join/blacklist/prefix/guarded` | 15 条载荷判定表：join 越界 6 条、黑名单 3 条、**前缀检查在兄弟目录上被骗**、修复版 0 条 |
| 前缀字符串检查的坑 | `serve_prefix` | 直接断言 `static_evil` 的绝对路径 `startswith(static)` 为真、`is_relative_to` 为假 |
| stdlib 不是安全判断 | `stdlib_reference` | `unquote` 一次/两次的行为、Windows 大小写无关、`+` 不被 `unquote` 当空格——全部实测登记 |
| 静态检查会瞎 | `audit.sql_sites` | 把包装函数 `_rows/_outcome` 从 sink 集合摘掉，扫描点数必须下降（包装函数是藏 `conn.execute` 的地方） |
| 登记表不能装饰 | `JUDGED` + `problems()` | 双向比对：扫到没登记红、登记了扫不到红；`order_whitelist` 这种"形态像但安全"的也必须在册 |

## 实测（2026-10-02，本轮全部重跑）

- 测试：**60 项通过（50 核心 + 10 展示页）**；discover 60 = 直跑 50 + 展示页 10；
  pytest 口径 **50 passed + 41 subtests**（核心套件）；`ruff F,E9` clean。
- 四组读数：SQL 的 4 例登录/2 例查询/4 例排序/二阶/叠句全部按预期分化；
  XSS **6/6** 载荷在漏洞版有信号、修复版 **0** 条、往返一致 **6/6**；
  穿越判定表 15 条（修复版越界 **0**）；口令成本表见上（实时测量）。
- `run.bat` 连跑两次退出码 **0**、日志 `not recognized` **0**、目录 **无新增文件**
  （2026-10-03 展示层批次⑤后按五步重测：各 196 行，规范化后逐字相同——
  规范项=单测计时 + 第 3 段实时测量数字）。
- 展示页（2026-10-03 展示层工程批次⑤）：`web/showcase.html` 单文件自包含——六段演示原文
  （第 3 段吞吐按规则脱敏成 `[现场]`，页面不冻结会过期的计时数字）、**四组对照速览**
  （SQL 14 行分化 / XSS 8 行信号计数 / 穿越判定表 15 条 + 标准库参照）、**静态扫描器**
  （逐文件拼接点 + 八个拼接点名册 + 「摘掉包装函数 8 → 1」的失效证明）；与现算**逐字一致**
  （`--check` 过期即红）。展示页测试 10 项（`python tests\test_showcase.py`）。
- demo 六段退出码 0；**第 3 段是实时测量**，两次运行有 ±5% 自然波动，
  其余段落逐字一致（可用 `python demo.py > a.txt` 跑两遍 `diff` 自证）。

## 本轮事故记录（这个项目同时是事故的源头，必须写在这里）

我在写"反向证明"（把被测代码复制到临时目录改坏，验证判定不是摆设）时，把副本根目录算成
`parents[2] / "_probe_b32_xss"`（也就是 `projects/_probe_b32_xss`），而清理写成
`shutil.rmtree(work.parent)` —— `work.parent` 正是 **`projects/`**。它**删掉了整个 `projects/` 两次**
（第二次是我把带同一 bug 的测试从备份恢复出来、没审计就直接跑）。完整经过与逐项目恢复状态见
仓库根 **`ACCIDENT-2026-10-02.md`**。

现在的防线（都在 `tests/test_b32.py` 里，且守卫本身有测试）：
- `make_probe_root()`：临时副本**只能建在仓库之外**（`tempfile.mkdtemp`），建完再断言一次；
- `destroy_probe_root()`：**只允许删"本函数亲手建、且登记在案"的那一个目录**，仓库内路径与外人建的目录一律拒绝；
- 三条反向测试证明这道守卫会拒绝仓库内路径、会拒绝它没建过的目录（守卫是安慰剂还是防线，由测试回答）。

## 明确不做（本期范围外）

真实系统渗透与漏洞扫描；WAF/IDS 绕过与免杀；缓冲区溢出（PLAN 选做项）；
口令策略与多因素认证的工程实现；密钥管理与证书；SOAP/WS-Security 那一层（属 B19/B10）；
把本目录的靶件暴露到回环地址之外（有测试与常量双保险）。

## 练习建议（G2，自己动手）

1. 把 `login_bound` 改回拼接，跑测试：哪几条先红？错误信息能不能指出"数据拿到了语法身份"？
2. 给 `order_whitelist` 加一个合法列（比如 `phone DESC` 的第二种写法），说明为什么加列不用改 SQL。
3. 在 `xss.py` 里新增一个"`<script>` 里直接用 `html.escape`"的修复版，构造一条能打破它的载荷并写测试。
4. 把 `creds.DEFAULT_ITERS` 从 120k 调到 1k，说出哪几条断言会红、为什么它们该红。
5. 给 `traversal` 加一条"尾随空格"载荷（`ok.txt `），解释为什么修复版会拒它、而这条拒绝的代价是什么。
6. 把 `audit.JUDGED` 里 `order_whitelist` 的定性改成"危险"，看 `problems()` 是否点名——这就是"登记表不是装饰"。

## 已知局限（说清楚，不含糊）

- 全部是本机教学靶与合成数据；**结论不外推**到真实系统，也不构成任何攻击能力。
- "浏览器会不会真的执行脚本"属于浏览器行为：本项目只证明到**响应字节与 Content-Type** 层，未在浏览器里验证。
- 时序侧信道只做**代码写法**层面（`hmac.compare_digest`），不假装能在 Python 层量出可靠纳秒差。
- 口令成本表是**单核 Python** 的数量级论证，不是 GPU/ASIC 的攻击成本。
- 静态扫描器只认它登记的 sink 形态（`execute/executemany/executescript` 与本项目的两个包装函数）；
  换一个项目要重新登记，否则它会"全绿"——这一点在测试里被专门证明过。
