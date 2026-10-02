# B7-mini-make —— Makefile 子集 + 依赖图 + 增量构建（软件开发技术基础）

**课程映射**：软件开发技术基础（PLAN 批次 2）。

一句话：**make 的核心不是"跑命令"，而是依赖图上的偏序**——目标只在全部前置就绪后执行，
环要在执行之前被检出，是否重建由 mtime 决定，失败要**传播**（不是崩溃）。

**先声明范围**（不冒充完整 make）：支持目标/前置/recipe、`.PHONY`、`-f/-C/-j/-q` 与多目标；
**不支持**变量展开与 `$@/$<` 自动变量、模式规则、隐式规则、`include`、条件判断。
recipe 逐行交给 shell（Windows 下是 cmd）执行。

## 运行

```
run.bat                                         # 三步：15 项测试 → 增量构建演示 → 日志分析演示
python -m unittest discover -s tests            # 15 项
python src\mm.py -f demo\Makefile               # 全量构建
python src\mm.py -f demo\Makefile               # 再跑一次 → 全部 up to date
python src\mm.py -f demo\Makefile -j 4 run      # 并发 + 目标 run
python src\logstat.py demo\sample_build.log     # 按消息模板聚合的警告统计
```

纯标准库（`argparse` / `subprocess` / `threading` / `concurrent.futures` / `re`），**零下载零安装**。

## 目录

| 路径 | 是什么 |
|---|---|
| `src/mm.py` | mini-make：解析 → 依赖图 → 环检测 → 拓扑序 → mtime 增量 → `-j` 分批并发 → 失败传播 |
| `src/logstat.py` | 编译日志统计：把 `file:line:col: severity: message` 归并成"哪类消息最多" |
| `tests/test_mini_make.py` | 15 项测试（解析/拓扑/环/增量/构建/失败传播/并发对拍/日志统计） |
| `demo/Makefile` + `demo/src/greet.cpp` | 演示工程：产物进 `build/`，`clean` 一条命令还原 |
| `demo/sample_build.log` | 合成的 GCC 风格日志（给 logstat 用） |

> **交付细节**：`.gitignore` 里有 `*.log`，而 `demo/sample_build.log` 是**测试夹具**不是运行产物，
> 所以它是用 `git add -f` 强制入库的——否则新克隆缺这个文件，`run.bat` 第 3 步会直接失败。

## 知识点 ↔ 实现 ↔ 怎么被验证

| 课程知识点 | 代码 | 验证方式 |
|---|---|---|
| Makefile 解析（目标/前置/recipe/`.PHONY`） | `Makefile.load` | 逐字段断言；重复目标、recipe 出现在目标之前都要报错 |
| 依赖图与拓扑序 | `Makefile.order` | 人工推的偏序逐条断言（`a` 在 `b` 前、`b` 在 `c` 前、`all` 最后） |
| 环检测 | 同上 | `a↔b` 报错信息里必须出现 `a -> b -> a` 这条环 |
| 增量构建 | `needs_build` / `mtime` | 目标比前置新 → 不重建；`utime` 把前置调新 → 必须重建 |
| 失败传播 | `Builder.build` | 上游 `exit 7` → 返回码 1、**下游目标不执行**（断言产物不存在） |
| 并发与一致性 | `Builder` 的分批线程池 | `-j4` 与 `-j1` 的构建集合**对拍**，且产物集合一致 |
| 伪目标语义 | `.PHONY` | `all` 每次都要执行，哪怕同名文件存在 |
| 日志分析 | `logstat.parse` | 按"数字抹掉"的消息模板聚合；空日志必须给 0 而不是崩或假装有数据 |

## 实测（2026-10-02，事故后按本文件与 `run.bat` 的规格重建）

- 测试：**15 项通过**（`unittest` 与 `pytest` 双入口同数）；两个源文件语法与行为均实跑。
- `run.bat` 连跑两次退出码 **0**、日志 `not recognized` **0**、目录**无新增文件**
  （`demo/build/` 已被 `clean` 还原）；两次日志差异只有 1 行 `Ran 15 tests in 0.3xxs`。
- 演示读数（现算）：全量构建"构建 2 个"；第二次"跳过 1 个（up to date）"；
  `os.utime` 改 mtime 后重新构建；`run` 目标打印三行问候；`logstat` 把 11 条诊断
  归并成 5 类（`comparison of integer expressions…` 3 次最多）并复述工具的
  `7 warnings generated / 1 errors generated`。

## 重建时踩到的坑（2026-10-02；本仓库已有的坑照旧数）

1. **相对路径必须相对 Makefile 目录**，不是进程 cwd。第一版按 cwd 解析：在临时目录里跑测试时
   文件前置一个个"不存在"，recipe 还会把产物写进仓库——真 make 的 `-C/‑f` 语义就是这条。
2. **失败传播是"流程"，不是"崩溃"**：`build()` 要返回非 0 并跳过下游，而不是把异常抛给调用方；
   否则"上游失败时下游没执行"这件事就没法被断言。
3. **`classmethod` 里写了 `self.PHONY_PREFIX`**：构造函数里能跑通、类方法里当场 `NameError`。
4. **我在这份 `run.bat` 里又踩了一次仓库自己记过的坑**：`echo ... clean -> full -> ...` 里的 `->`
   被 cmd 当成重定向，静默生成一个名为 `rebuild` 的垃圾文件并截断那行输出。
   PLAN §6 早就写着"分隔流程一律写 `→`，而 `.bat` 正文纯 ASCII"——正确做法是**把这行改成逗号分隔**
   （箭头版提示留给 Python 打印）。教训：规则写在文档里，不等于写脚本时会想起来。
5. **原子替换要带断言**：我两次用脚本改测试里的 recipe，转义在 heredoc 里被吃掉，
   替换静默没生效——后来改成"先 `assert 锚点 in 文本` 再替换"，no-op 立刻暴露。

## 明确不做（本期范围外）

变量与自动变量、模式/隐式规则、`include`、条件、`.DELETE_ON_ERROR` 之类的精细语义；
跨平台 recipe（本项目的 recipe 是 cmd 形态）；把 `-j` 做到"真正的依赖级流水线"（当前是分批并行，
语义上等价于串行的结果，测试里对拍过）。

## 练习建议（G2，自己动手）

1. 给 mm.py 加变量展开（`CC = g++`、`$(CC)`），并写一条"未定义变量报错"的测试。
2. 把分批并发改成"依赖就绪即调度"的流水线，用 `time.sleep` 当 recipe 比较总耗时。
3. 给 logstat 加"按文件分组"的视图，说明为什么"哪类消息最多"和"哪个文件最脏"是两个问题。
4. 让 `clean` 只在产物存在时才执行（`needs_build` 现在对伪目标恒真），说清这样做的代价。
