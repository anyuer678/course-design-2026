# B33-viz-algo —— 算法可视化：B2 导出操作记录，回放成可交互网页（可视化技术）

**课程映射**：可视化技术（PLAN 批次 7）。

一句话：**动画不是"再算一遍"，是"回放已记录的操作"**——B2 的结构库带一个只读 trace
观察口（默认关闭），导出器把堆排序/图遍历跑成操作记录（JSON），回放器与页面都只是
在移动"记录下标"：播放/暂停/单步/上一步全都不重算算法，画面与算法天然同源。

**复用声明（本仓库纪律）**：B33 **不重写**任何结构或算法——`ds/heap.hpp`、`ds/graph.hpp`
直接 include 自 `../B2-datastruct-lab/include`（run.bat 会检查它存在）；为让"结构本体"
发声，B2 于 2026-10-02 增补 `ds/trace.hpp`（**只读、默认关闭**，挂上 Tracer 后
push/pop/build/swap 与 BFS/DFS visit 各记一条事件；B2 的 428 项断言与 run.bat 两次
日志逐字相同均已重跑复核）。

**范围声明**：堆排序（建堆 + 逐个取顶）与图遍历（BFS/DFS）动画；播放/暂停/单步/上一步/速度；
数据内嵌单文件 HTML。**不做**（PLAN 选做项）：D3、树操作动画、跨语言实时绑定。
**动画观感**（动没动、清不清楚）属用户实跑验收，自动化只覆盖到"记录保真 + 页面结构 +
JS 语法"。

## 运行

```
run.bat                                          # 三步：编译导出器+导出 → 11 项测试 → demo（生成 build\viz.html）
g++ -std=c++17 -O2 -Wall -Wextra -static -I../B2-datastruct-lab/include tools/export_trace.cpp -o build/export_trace.exe
build\export_trace.exe build\traces              # 三份 JSON：sort / bfs / dfs
python -m unittest discover -s tests             # 11 项（双入口同数）
python demo.py                                   # 导出 + 回放核对 + 生成页面 + node --check
```

零依赖：g++（已有）+ Python 标准库；页面零框架、零下载。**打开 `build\viz.html` 即可看动画。**

## 目录

| 路径 | 是什么 |
|---|---|
| `tools/export_trace.cpp` | 导出器：用 B2 的 Heap/Graph 跑固定场景（8 个数、7 结点图），吐 sort/bfs/dfs JSON |
| `vizlab/replay.py` | 独立回放/参照：排序按 B2 的 pop 协议逐步重建，BFS/DFS 用 Python 从头写一遍做对拍 |
| `vizlab/page.py` | 生成自包含 HTML：数据内嵌 + 手写 JS 动画器（条形图 + SVG 图 + 控制条） |
| `tests/test_viz.py` | 11 项测试（记录保真 / 负面自证 / 页面结构 / 内嵌数据 / 确定性 / node --check） |
| `demo.py` | 演示：导出 → 保真核对 → 生成页面 → 语法体检 → 用户验收指引 |

## 知识点 ↔ 实现 ↔ 怎么被验证

| 课程知识点 | 代码 | 验证方式 |
|---|---|---|
| 数据与视图分离 | trace JSON（数据） vs page.py（视图） | 页面内嵌数据**逐字节等于** JSON 文件（extract + json.loads + 相等断言） |
| "演的是真算法" | `replay.replay_sort` | 20 事件**逐步重建**：每个 swap 后逐位等于快照、pop 取出的必须是当时堆顶、build 后堆序成立；负面自证：改坏一条快照必须报错 |
| BFS/DFS 语义对拍 | `replay.reference_bfs/dfs` | Python 独立实现产出**同口径**逐步记录（visit + 队列/栈快照），与 C++ 导出逐访问相等；b 字段与独立算的距离相等 |
| 状态机驱动的交互 | page.py 的 `makeAnimator` | 播放/暂停/单步/上一步都只是下标移动；结构断言（控件 id 齐备） |
| 自包含与确定性 | `build_page` | 同一 inputs 两遍构建**字节相同**；无网络请求、无随机数 |
| JS 语法 | node --check | 抽出 `<script>` 交给 node 语法体检（退出码 0；无 node/shim 时如实跳过） |

## 实测（2026-10-02，首次交付；数字均为本轮现算）

- 记录：sort 20 事件（1 build + 10 swap + 8 pop + 1 收尾）、BFS 7 步、DFS 7 步；
  JSON 字节数 {sort: 1274, bfs: 393, dfs: 396}。
- 保真：排序**逐步回放 0 失败**、终态 == `sorted(input)`；BFS/DFS 与独立 Python 参照
  **逐步相等**；负面自证（反转一条 swap 快照）回放器**必须报红**（测试钉住）。
- 页面：`build/viz.html` **13641 字节**（内嵌数据 2080 字节），`node --check` 退出码 **0**；
  两遍构建字节相同。
- `run.bat` 连跑两次退出码 **0**、`build/` 之外无新增、`not recognized` 0，
  两次日志差异只有 1 行 unittest 计时；**B2 侧复核**：428 项断言 0 失败、run.bat 两次
  日志逐字相同（trace 增补零行为影响）。

## 坑（都留了钉子）

1. **`echo` 里的 `->` 又双叒踩了**（仓库已记过两次：B7、B10）：run.bat 的
   `echo [3/3] demo (export -> ... -> node --check)` 在 cmd 里是**重定向**——
   当场生成垃圾文件 `node`；更阴的是它随后**遮蔽了真 node**（`shutil.which('node')`
   解析到 `.\node`），demo 跑到 node --check 时报 `WinError 193（不是有效的 Win32 程序）`。
   教训升级版：垃圾文件不只是垃圾，还能**劫持 PATH 上的同名可执行文件**；
   已改逗号分隔，并给 demo/test 的 node 调用加 OSError 兜底（查明原因、如实跳过）。
2. **回放协议必须"读源码得来"**：`Heap::pop` 里"根↔尾交换 + 丢尾"这步是**未记录**的，
   回放模型第一版没补它 → 16/20 步红；第二版把收缩挂在 pop 后 → 仍错（收缩发生在
   **build/pop 事件之后、下一轮取出开头**）；第三版照源码逐步对齐才 0 失败。
   教训：对拍红的时候，先把对方的**真实协议**抄清楚再修模型。
3. **"每帧长度都等于 n"是假假设**：取出过程中有一帧"在途"（元素已离开堆、还没进前缀），
   长度 n−1——断言要写精确相等（`回放 == 快照`）而不是加不该有的整齐假设。
4. **跨项目 include 用正斜杠**：`-I..\B2-datastruct-lab\include` 里的反斜杠会被 bash 当转义吃掉，
   g++ 报头文件找不到；`-I../B2-datastruct-lab/include` 稳定（cmd/POSIX 两界都认）。

## 明确不做（本期范围外）

D3 与任何图表库；树操作动画（BST 插入/删除的旋转可视化）；跨语言实时绑定（不把浏览器
接到活进程上）；录制/回放之外的编辑功能。页面不联网、不加载外部字体与脚本。

## 练习建议（G2，自己动手）

1. 给导出器加 BST 场景（借 B2 的 `ds::bst.hpp` 也加同款 trace 口），在页面加第三张卡片——
   先把"节点/边快照"的记录格式定死，再写渲染；体会"数据格式先行"。
2. 把 `makeAnimator` 的下标搬进 URL hash（`#step=7`），刷新页面能回到同一帧，
   说明"状态可寻址"对分享与复现的价值。
3. 加"逐步解释"文本框：每一步把 `op` 翻成一句人话（建堆/交换 k/v/取出最小值），
   再想想"解释文本应该由导出器生成还是页面生成"（提示：谁掌握上下文）。
4. 用 `performance.now()` 给播放循环加丢帧统计（数据量大时动画会追不上），
   说清"动画的时基"和"算法的步数"是两回事。
