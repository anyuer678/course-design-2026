# B6-asm-lab —— x86-64 汇编：字符串反转 / 斐波那契 / 排序（汇编语言）

**课程映射**：汇编语言（PLAN 批次 2）。

一句话：**汇编的正确性分两层**——运行时行为对（与 C++ 参照逐数对拍），**结构也可见证**
（objdump 反汇编里逐条断言序言/收尾/寄存器纪律）；而"调用约定"不是口号：
`abi_probe_call` 拿哨兵值进、掩码出，还配一个**故意违规的反面教材**证明探针真会亮灯。

**平台与范围声明**：Windows x64 + GNU as（`.intel_syntax noprefix`，MinGW 工具链的
`gcc/as/objdump`），**不是 MASM/8086** 教材环境；参数一律 **64 位**（Windows x64 的
C++ `long` 是 32 位——这是重建时踩出的最大一坑，见下）。**不做**（PLAN 选做项）：
调试器单步教程、优化前后对照实验、浮点/SIMD、`.seh` 展开信息；也不写任何 shellcode
或注入类代码（教学只到"函数被正确地调用与返回"为止）。

## 运行

```
run.bat                                        # 四步：汇编+自测 → 演示 → 反汇编结构对照 → 展示页新鲜度
gcc -c asm\reverse.s -o build\asm\reverse.o    # （run.bat 里把四个 .s 和探针都汇编了）
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude tests\test_asm.cpp build\asm\*.o -o build\tests.exe
build\tests.exe                                # 自测：373 项断言
build\asm-lab.exe                              # 演示：五段
python tools\disasm_check.py                   # 反汇编结构对照：23 项检查
python tools\showcase.py --write               # 重生展示页 web\showcase.html（--check 过期即红）
```

只用 MinGW 工具链（gcc/g++/as/objdump）与标准库，**零下载零安装**。

## 目录

| 路径 | 是什么 |
|---|---|
| `asm/reverse.s` | 两指针原地反转（按字节；两指针相向而行，不建栈帧） |
| `asm/fib.s` | 斐波那契迭代版（**纯寄存器叶函数**：反汇编里没有任何 push/pop） |
| `asm/sort.s` | 插入排序（比例变址 `[rcx + r8*8]`；8 字节步长是契约的一部分） |
| `asm/stackframe.s` | `asm_sum_positive`：**完整栈帧**示范（push rbp / mov rbp,rsp / leave；借用 rbx 并归还） |
| `tests/abi_probe.s` | 调用约定探针：哨兵值进、被破坏位掩码出；外加反面教材 `abi_bad_clobber` |
| `tests/test_asm.cpp` | 373 项断言（边界手算 + 对拍 + ABI 探针 + 越界围栏） |
| `tools/disasm_check.py` | 反汇编结构对照（对着 objdump 输出逐条断言，含 C++ 调用点证据） |
| `src/main.cpp` | 五段演示 + `include/check.hpp` 断言计数器 |

## 知识点 · 实现 · 怎么被验证

| 课程知识点 | 代码 | 验证方式 |
|---|---|---|
| 两指针反转 | `asm_reverse` | 手算 7 例（含空串/单字符）；**越界哨兵围栏**（只许动指定 5 字节）；60 组对拍 `std::reverse` + 翻两次还原 |
| len 语义与边界 | 同上 | len≤0 不动内存；指针为空的 0 长调用安全（测试直接传 `nullptr,0`） |
| 迭代斐波那契 | `asm_fib` | 手算 0..10；fib(93)=12200160415121876738（u64 边界）；**0..93 全量与 C++ 参照对拍**；负数=0 |
| 比例变址寻址 | `asm_sort` | 手算 4 例（空/单/逆序/重复）；**60 组对拍 `std::sort`**（值域故意窄、重复多） |
| 完整栈帧 | `asm_sum_positive` | 手算 4 例 + 60 组参照对拍；**反汇编 6 项结构断言**（push rbp / mov rbp,rsp / leave / ret / push rbx / pop rbx） |
| 叶函数 vs 栈帧函数 | `fib/reverse/sort` vs `sum_positive` | 结构检查同时验两端：前者**没有任何 push/pop**，后者序言收尾齐全——"要不要建帧"是能被反汇编证实的取舍 |
| **调用约定（callee-saved）** | `abi_probe.s` | 8 个 callee-saved 寄存器填哨兵 → 调用目标 → 逐位比较：**四个函数全 0**；反面教材**必须**亮 bit0（探针自证） |
| C++ · 汇编互调 | `extern "C"` + Windows x64 寄存器约定 | demo 反汇编里能读到 4 个符号上的 `call` 调用点（工具第 6 组检查） |
| 反汇编对照 | `tools/disasm_check.py` | 23 项结构断言对接 objdump 真实输出；序言/收尾现场截取打印 |

## 实测（2026-10-02，事故后重建；数字均为本轮现算）

- 自测：**373 项断言，0 项失败**。分组：反转 130、斐波那契 109、排序 65、栈帧函数 64、ABI 探针 5。
- ABI 探针掩码（0 = 一个 bit 都没动）：`reverse=0 fib=0 sort=0 sum=0`；
  反面教材 `abi_bad_clobber` = **1**（bit0=rbx，探针确实会亮灯）。
- `run.bat` 连跑两次退出码 **0**、`not recognized` **0**、`build/` 之外**无新增文件**、
  两次日志**逐字相同**（各 93 行；干净重跑：先删 `build/` 再全程重建）。
- 展示页（2026-10-03 展示层工程批次③）：`web/showcase.html` 单文件自包含——五段演示现场输出、
  ABI 探针掩码表（四函数全 0 + 反面教材 bit0 亮）、23 项反汇编对照与序言/收尾截取；
  与现算**逐字一致**（`--check` 过期即红）。
- 反汇编结构对照：**23 项通过 0 失败**，含 `sum_positive` 的序言收尾现场截取。
- 演示现算读数：`"Hello, asm-lab!"` → `"!bal-msa ,olleH"`；fib(0..10) 表 + fib(93)；
  12 元素排序与 `std::sort` 逐元素一致；负数数组正数和 = 29。

## 重建说明（2026-10-02 事故后，非逐字）

原目录在事故中**完全丢失**（三个恢复源都只有引用没有全文），本目录按 PLAN §4 的 B6 范围条目
（"字符串反转、斐波那契和排序；C++ 调用，寄存器与栈帧反汇编对照"）重建。
原记录只有一句"B6 40 断言"——**原 40 项的构成不知道，也不冒充**：重建版 373 项断言 +
23 项反汇编结构检查，规模全部可点。原环境用哪个汇编器没有记录；本重建选 GNU as（MinGW 自带，
零下载）并把这个选择写进平台声明。

## 重建时踩到的坑（这一轮的坑几乎全是"整数宽度"）

1. **Windows x64 陷阱一：参数宽度**。C++ 侧写 `long len`（32 位），传 `-3` 进 rdx 是
   `0xfffffffd`（零扩展）——汇编按 64 位读成 **42.9 亿**，反向遍历一路写到段错误。
   gdb 寄存器现场实证（`rdx=0xfffffffd`）后在 README 钉住：**接口一律 `long long`**。
2. **陷阱二：数组步长**。`asm_sort` 按 8 字节步长寻址，测试却传 `long` 数组（4 字节元素）
   ——写穿堆，NTDLL 报 `c0000374`（堆损坏），bash 里表现为莫名其妙的怪退出码。
   两个陷阱同根：**汇编没有类型系统，"宽度"必须由接口契约写清**。
3. **`leave` 把 `pop rbp` 折进去了**：反汇编检查第一版要求显式 `pop rbp`，于是 FAIL——
   这次是**检查器错了**，不是函数错了。改成"`leave` + `ret` 收尾"并注明折叠关系。
4. **`mov rbx, imm64` 反汇编成 `movabs`**：检查器正则漏认 mnemonic，被自己的输出当场纠正。
5. **objdump 不认含中文的绝对路径**（`Illegal byte sequence`）：工具里改为
   `cwd=build/asm` + 相对文件名调用——和 bash 直接调用时的行为对齐。
6. **探针的指针宽度**：`reinterpret_cast<long>(buf)` 在 x64 上装不下指针（编译期报错），
   改走 `uintptr_t` 中转，顺带绕开 `-Wcast-function-type` 告警。

## 明确不做（本期范围外）

MASM/8086 语法与 DOS 中断调用；浮点/SIMD 寄存器；`.seh` 异常展开表；
宏与多模块链接；调试器单步教程（重建时用过 gdb 定位第 1 条坑，但没做成教程）；
优化前后对照（PLAN 选做项——练习 4 给了一条可做的路径）。

## 练习建议（G2，自己动手）

1. 手写 `asm_strlen`，把 `asm_reverse` 改成"只收一个指针"的版本（自找长度），
   说清"以 0 结尾"的代价（多扫一遍）。
2. 写递归版 `asm_fib_rec`，用 gdb 或 `objdump -d` 数每一层的栈帧怎么叠；与迭代版对比。
3. 把 `abi_probe.s` 扩到 SSE 寄存器（xmm6–xmm15 也是 Windows x64 的 callee-saved），
   再加一个"故意破坏 xmm6"的反面教材。
4. 把 `sum_positive` 同题的 C++ 函数分别用 `-O0` 与 `-O2` 编译，`objdump` 对照调用约定
   与栈帧差异（PLAN 的选做项之一，从这里起步）。
