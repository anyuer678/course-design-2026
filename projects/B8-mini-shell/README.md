# B8-mini-shell —— mini-shell：fork/exec、管道、重定向、内建与子进程回收（开源操作系统）

**课程映射**：开源操作系统（PLAN 批次 2）。

一句话：**shell 是进程课的总复习**——一行命令背后是 fork、exec、pipe、dup2、waitpid 的
完整链条；"内建命令为什么必须存在"（cd 改的是 shell 自己的进程状态）与"管道为什么需要
N-1 根管子"都在实现里给出答案，而**僵尸进程是去 /proc 里当面数的**，不是嘴上说不漏。

**平台声明**：本 shell 用 POSIX API（`fork/execvp/pipe/dup2/waitpid`），**Windows 原生没有
fork**，所以实际运行在 **WSL2 Ubuntu-24.04**（PLAN §8 的既有环境，未安装/未下载任何新东西）。
`run.bat` 只是 Windows 侧薄包装：把三步交给 `wsl -d Ubuntu-24.04` 执行 `run.sh`。
纯 C11 + 标准库工具，零第三方依赖。

**范围声明**：命令执行、`|` 管道（任意段）、`< > >>` 重定向、内建 `cd/exit/pwd`、
子进程回收、退出码口径（`$?` = 最后一段；信号死亡 = 128+信号）。
**不做**（PLAN 选做项）：后台任务与作业控制（`&`/`jobs`/`fg`）、变量展开、通配符、
引号转义全语法、脚本编程结构；Ctrl-C 只做**最小正确行为**（shell 忽略 SIGINT、子进程恢复
默认处置）。`#` 整行注释与单双引号是最小支持集。

## 运行

```
run.bat                     # Windows 入口：三步——WSL 编译+双入口自测+演示 → 展示页新鲜度 → 展示页测试
bash run.sh                 # （WSL 里）等价入口
gcc -std=c11 -O2 -Wall -Wextra -o build/msh src/msh.c
python3 -m unittest discover -s tests        # 24 项（discover 入口）
python3 tests/test_msh.py                    # 24 项（直跑入口，与上同数）
python3 demo.py                              # 六段演示，结果全部实测
./build/msh                                  # 交互使用（Ctrl-D 退出）
python tests\showcase_check.py               # 9 项展示页测试（Windows 侧直跑；命名原因见目录表）
python tools\showcase.py --write             # 重生展示页 web\showcase.html（--check 过期即红）
```

## 目录

| 路径 | 是什么 |
|---|---|
| `src/msh.c` | mini-shell 本体：词法（引号/运算符）→ 管道语法 → fork/exec/dup2/waitpid |
| `tests/test_msh.py` | 24 项测试：脚本驱动会话，逐条验证行为契约（含 /proc 数僵尸） |
| `demo.py` | 六段演示：退出码 / 内建 / 管道 / 重定向 / 回收 / 错误路径，全部实测 |
| `tests/showcase_check.py` | 9 项展示页测试。**命名偏离说明**：本项目主测试在 WSL 里由 `unittest discover` 跑，"双入口同数 = 24" 是 run.sh 的硬口径——`test*.py` 命名的文件会被 WSL 的 discover 抓到（模块级跳过也计入 Ran），所以展示页测试起名 `showcase_check.py`（模式外），只在 Windows 侧直跑 |
| `tools/showcase.py` | 展示页生成器 → `web/showcase.html`（用**一次** `wsl` 调用完成编译+双入口自测+六段演示+八脚本回放，再解析成结构化数据） |
| `run.sh` | Linux 侧一键入口：编译 → 双入口自测（计数行去计时）→ 演示 |
| `run.bat` | Windows 侧入口：`wsl -d Ubuntu-24.04 -e bash -c "./run.sh"` → 展示页新鲜度 → 展示页测试 |

## 知识点 · 实现 · 怎么被验证

| 课程知识点 | 代码 | 验证方式 |
|---|---|---|
| fork + execvp | `run_pipeline` 子进程分支 | `true/false/sh -c 'exit 42'` 的退出码实测；找不到命令 → stderr + 127 且 shell 继续 |
| 管道 = N 进程 + N-1 根 pipe | `pipe()`/`dup2`/端点关闭 | 两段/三段管道现场（`printf \| sort \| head`）；父进程**关掉多余端点**（不关会挂死） |
| 重定向是 dup2 的艺术 | 子进程 `open`+`dup2` | `>` 截断、`>>` 追加、`<` 读入、管道+落盘组合；坏路径报错但 shell 继续 |
| 内建命令（改自己） | 单命令时 shell 本体执行 `cd/exit/pwd` | `cd /tmp` 后 `pwd` 变、跨行保持；**管道里的 cd 按外部命令处理**（找不到 → 127）有专项用例 |
| 退出码口径 | `waitpid` + `WIFEXITED/WIFSIGNALED` | `$?`=最后一段（`true \| false` → 1）；信号死亡 = 128+15=143；`exit N` 显式码 |
| 子进程回收 | 逐 pid `waitpid`，`EINTR` 重试 | **会话跑到一半去 /proc 数僵尸 = 0**（`test_zombie_reaping`）；run 完 `children` 为空 |
| stdin 继承（`cat` 直接可读） | `read_line` 用**逐字节 read** | `cat` 后继续喂的行原样输出——若用 `fgets` 会被 stdio 预读吞掉（专项用例钉住） |
| 引号与注释 | `lex` | `"a  b"` 保留空格、`'x  y'`、`a"b c"d` 拼接、`\"` 转义；未闭合引号报错且不崩 |
| 语法错误分类 | `build_pipeline` | 5 类坏语法（管道空侧、重定向缺文件名、空命令…）各自报错、逐个有断言 |

## 实测（2026-10-02，事故后重建；数字均为本轮现算）

- 自测：**24 项测试全过、双入口同数**（`discover` 与直跑都是 `Ran 24 tests`）。
- `run.bat` 连跑两次退出码 **0**、`not recognized` **0**、`build/` 之外**无新增**、
  两次日志**逐字相同**（自测段用 `sed` 去掉 unittest 计时行——确定性是设计出来的；
  2026-10-03 展示层批次⑤后按三步重测：各 70 行，原始日志仅展示页测试的 1 行计时不同）。
- 演示现算读数：`exit 42` → 42；`printf | sort | head -2` → `a b`；`>` 截断 / `>>` 追加
  实测；**3 条命令跑完僵尸 = 0、未回收子进程 = 0**；3 条坏语法全部报错后仍输出 `done`。
- 展示页（2026-10-03 展示层工程批次⑤）：`web/showcase.html` 单文件自包含——六段演示现场输出、
  **八脚本会话回放**（管道 / 重定向落盘回读 / 内建 cd / 退出码 0-1-127 / 错误路径）、
  双入口自测原始计数；路径规范化为 `<项目根>`（页面不绑机器）；与现算**逐字一致**
  （`--check` 过期即红）。展示页测试 9 项（`python tests\showcase_check.py`）。
- **2026-10-03 修掉一个真实竞态（被展示页测试逼出来的）**：`test_zombie_reaping` 与 demo
  第 5 段原先"轮询到空快照就 break"——shell 还没 fork 之前就把"没发生过"当"回收完毕"：
  假红实测出现两次（展示页测试首跑一次、3 连跑首跑一次），假绿是同一竞态的另一半
  （demo 可能什么都没做就报"回收 0 个"）。同步点改为：测试用 `echo done > sync.txt`
  的**文件信号**（且它是最后一条命令——之后的空快照才是稳定结论），demo 用 `sleep 0.2`
  这个看得见的子进程当同步点。修复后 24 项连跑 6 次全绿、demo 两遍逐字一致（页面哈希不变）。

## 重建说明（2026-10-02 事故后，非逐字）

原目录在事故中**完全丢失**（三个恢复源都只有引用没有全文），本目录按 PLAN §4 的 B8 范围条目
（"fork/exec、管道、重定向、内建命令与子进程回收"）重建。原记录只有一句"WSL 20 项，管道冒烟正常"
——**原 20 项的内容没有记录，不冒充**：重建版是 24 项测试 + 六段实测演示，规模全部可点。
原环境（哪个发行版、哪个编译器版本）无记录；本重建固定为 WSL2 Ubuntu-24.04 + gcc 13.3，
并把这个选择写进平台声明。

## 重建时踩到的坑（都留了钉子）

1. **"空行 = EOF"的真 bug**：`read_line` 对空行返回 0，而主循环把 `<=0` 当 EOF——
   于是**第一行是空行时整个 shell 直接退出**。是 `test_comments_and_blank_lines`
   把它抓出来的；修法：`-1` 才是 EOF，`0` 是合法的空行。
2. **stdio 预读会吞掉子进程的 stdin**：最初想用 `fgets` 读命令行——缓冲会把 `cat`
   该看到的行先吃走。改成逐字节 `read()`（慢一点，语义对），并把 `cat` 继承 stdin
   做成断言钉死。
3. **管道端点必须关干净**：父进程不关写端，下游的读端等不到 EOF——整条管道挂死。
   实现里"父进程关写端/上游关读端"按对处理，三段管道能跑完就是证明。
4. **两条我写错的测试期望**（实现是对的）：管道 `$?` 口径是**最后一段**（`cd /tmp | cat`
   整体是 0，cd 的 127 在子进程里）；`exit` 无参数 = `$?`（脚本最后一条是 `false` 就退 1）。
   ——又一次"失败先怀疑期望值"。
5. **WSL 默认发行版是 docker-desktop**（没有 bash）：必须 `-d Ubuntu-24.04` 点火，
   否则报 `execvpe(bash) failed`；`wsl.exe` 的提示信息走 **UTF-16LE 的 stderr**，
   在 git-bash 里会显示成乱码——工具侧设 `WSL_UTF8=1` 并只读 stdout。
6. **命令替换吞退出码**：`out=$(python3 ...)` 里若测试失败，`set -e` 不会拦住
   后续的 `echo`——改成 `if ! out=$(...)` 显式分支，失败时原样打印输出再退出。
7. **计时行是日志逐字一致的天敌**：unittest 的 `Ran 24 tests in 0.9s` 两次必然不同；
   `sed 's/ in [0-9.]*s$//'` 去掉后，两次 run.bat 日志才真正逐字一致。

## 明确不做（本期范围外）

后台任务 `&` 与作业控制（`jobs/fg/bg`）、信号交互（脚本里的 trap/信号清单）、
变量与环境操作（`$VAR`、`export`）、通配符展开、命令替换 `$(...)`、`&&/||` 链、
历史与行编辑；这些是 PLAN 选做项，README 不留半成品接口。

## 练习建议（G2，自己动手）

1. 加 `&` 与 `jobs`：后台子进程不 wait，另存 pid 表；说明"后台任务"为什么必须改回收逻辑
   （SIGCHLD / WNOHANG 轮询），以及僵尸检查要跟着改什么。
2. 加 `&&` 与 `||`：把"单行多命令"从管道的两层语法里切出来，画出你改了哪一层。
3. 给 `lex` 加反斜杠转义与 `$VAR` 展开（只做最小子集），说清"展开发生在词法之后、
   执行之前"的位置。
4. 用 `strace -f -e trace=process,desc ./build/msh` 跑一段管道，对着 trace 数
   fork/pipe/dup2/wait4 的次序，和 `run_pipeline` 的代码逐行对上。
