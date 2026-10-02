// tests/test_cpu.cpp —— B5 自测：ISA 语义 / 汇编器 / 单周期性质 / 流水线与单周期对拍
//
// 三条纪律（沿用本仓库其它项目）：
//   1. 期望值必须**手算得出或来自独立参照**——分支目标、排序结果、双模型一致性都属于此类；
//   2. 每条断言都能回答"被什么改动弄红"；
//   3. "双模型对拍"是本项目的核心验收：五级流水线可以不快，但最终寄存器与内存
//      必须与单周期逐字节相同；不等就说明转发/停顿/冲刷某一处错了。
#include <cstdio>
#include <string>
#include <vector>

#include "asm.hpp"
#include "cpu.hpp"
#include "isa.hpp"
#include "pipeline.hpp"

using namespace b5;

static int g_checks = 0, g_fails = 0;
#define CHECK(cond)                                                          \
    do {                                                                     \
        ++g_checks;                                                          \
        if (!(cond)) {                                                       \
            ++g_fails;                                                       \
            std::printf("  [FAIL] %s:%d  %s\n", __FILE__, __LINE__, #cond);  \
        }                                                                    \
    } while (0)

static void section(const char* name) { std::printf("[test] %s\n", name); }

// 跑一个程序（单周期），返回机器最终状态；mem 初值可选
static Machine run_single(const std::string& src, const std::vector<int32_t>& seed = {}) {
    Assembled a = assemble(src);
    SingleCycleCpu cpu(64);
    for (std::size_t i = 0; i < seed.size(); ++i) cpu.machine().mem.words[i] = seed[i];
    cpu.run(a.program);
    return cpu.machine();
}

static Machine run_pipe(const std::string& src, const std::vector<int32_t>& seed = {}) {
    Assembled a = assemble(src);
    PipelineCpu cpu(64);
    for (std::size_t i = 0; i < seed.size(); ++i) cpu.machine().mem.words[i] = seed[i];
    return cpu.run(a.program).machine;
}

static bool same_regs(const Machine& a, const Machine& b) {
    for (int i = 0; i < 32; ++i)
        if (a.regs.r[i] != b.regs.r[i]) return false;
    return true;
}

static bool same_mem(const Machine& a, const Machine& b) {
    for (std::size_t i = 0; i < a.mem.words.size(); ++i)
        if (a.mem.words[i] != b.mem.words[i]) return false;
    return true;
}

static void test_isa_semantics() {
    section("ISA 语义（单周期）：R 型 / I 型 / 访存 / 分支 / 跳转");
    // 1) addi
    CHECK(run_single("addi r1, r0, 5\nhalt\n").regs.r[1] == 5);
    // 2) add
    CHECK(run_single("addi r1, r0, 5\naddi r2, r0, 7\nadd r3, r1, r2\nhalt\n").regs.r[3] == 12);
    // 3) sub
    CHECK(run_single("addi r1, r0, 5\naddi r2, r0, 7\nsub r3, r1, r2\nhalt\n").regs.r[3] == -2);
    // 4) and  5) or
    CHECK(run_single("addi r1, r0, 6\naddi r2, r0, 3\nand r3, r1, r2\nhalt\n").regs.r[3] == 2);
    CHECK(run_single("addi r1, r0, 6\naddi r2, r0, 3\nor r3, r1, r2\nhalt\n").regs.r[3] == 7);
    // 6) slt（真）
    CHECK(run_single("addi r1, r0, 3\naddi r2, r0, 6\nslt r3, r1, r2\nhalt\n").regs.r[3] == 1);
    // 7) sll  8) srl
    CHECK(run_single("addi r1, r0, 3\nsll r2, r1, 2\nhalt\n").regs.r[2] == 12);
    CHECK(run_single("addi r1, r0, 12\nsrl r2, r1, 2\nhalt\n").regs.r[2] == 3);
    // 9) andi  10) ori
    CHECK(run_single("addi r1, r0, 6\nandi r2, r1, 3\nhalt\n").regs.r[2] == 2);
    CHECK(run_single("addi r1, r0, 6\nori r2, r1, 1\nhalt\n").regs.r[2] == 7);
    // 11) sw/lw 往返  12) 访存计数
    {
        Machine m = run_single("addi r1, r0, 42\nsw r1, 3(r0)\nlw r2, 3(r0)\nhalt\n");
        CHECK(m.regs.r[2] == 42);
        CHECK(m.mem.stores == 1 && m.mem.loads == 1);
    }
    // 13) 访存越界必须抛错（不是静默读到垃圾）
    {
        bool threw = false;
        try { run_single("addi r1, r0, 999\nlw r2, 0(r1)\nhalt\n"); }
        catch (const std::runtime_error&) { threw = true; }
        CHECK(threw);
    }
    // 14) 写 r0 被丢弃  15) 读 r0 恒为 0
    CHECK(run_single("addi r0, r0, 5\nhalt\n").regs.r[0] == 0);
    CHECK(run_single("addi r1, r0, 5\naddi r2, r0, 7\nsub r3, r1, r2\nadd r4, r0, r1\nhalt\n")
              .regs.r[4] == 5);
    // 16) 负立即数
    CHECK(run_single("addi r1, r0, -3\nhalt\n").regs.r[1] == -3);
    // 17) beq 跳转  18) beq 不跳
    CHECK(run_single("addi r1, r0, 1\nbeq r1, r1, skip\naddi r2, r0, 9\nskip:\nhalt\n")
              .regs.r[2] == 0);
    CHECK(run_single("addi r1, r0, 1\naddi r2, r0, 2\nbeq r1, r2, skip\naddi r3, r0, 9\nskip:\nhalt\n")
              .regs.r[3] == 9);
    // 19) bne 跳转  20) j 跳转
    CHECK(run_single("addi r1, r0, 1\naddi r2, r0, 2\nbne r1, r2, skip\naddi r3, r0, 9\nskip:\nhalt\n")
              .regs.r[3] == 0);
    CHECK(run_single("j over\naddi r1, r0, 9\nover:\naddi r2, r0, 4\nhalt\n").regs.r[2] == 4);
    // 21) halt 之后不再执行：trace 条数 == 周期数（且等于执行过的指令数）
    {
        Machine m = run_single("addi r1, r0, 1\naddi r2, r0, 2\nhalt\naddi r3, r0, 9\n");
        CHECK(m.trace.size() == 3 && m.cycles == 3);
    }
    // 22) slt 按**有符号**比较
    CHECK(run_single("addi r1, r0, -1\naddi r2, r0, 1\nslt r3, r1, r2\nhalt\n").regs.r[3] == 1);
}

static void test_assembler() {
    section("汇编器：两遍扫描、标签、操作数形态");
    // 23) 标签换成绝对地址（loop 在第 1 条）
    {
        Assembled a = assemble("addi r1, r0, 3\nloop:\naddi r1, r1, -1\nbne r1, r0, loop\nhalt\n");
        CHECK(a.program.size() == 4);
        CHECK(a.program[2].op == Op::BNE && a.program[2].target == 1);
    }
    // 24) "0(r2)" 形态的偏移与基址
    {
        Assembled a = assemble("lw r3, 0(r2)\nhalt\n");
        CHECK(a.program[0].op == Op::LW && a.program[0].rt == 3 &&
              a.program[0].rs == 2 && a.program[0].imm == 0);
    }
    // 25) 未定义标签必须报错  26) j 的目标也解析
    {
        bool threw = false;
        try { assemble("j nowhere\nhalt\n"); }
        catch (const std::runtime_error&) { threw = true; }
        CHECK(threw);
        Assembled a = assemble("j end\naddi r1, r0, 1\nend:\nhalt\n");
        CHECK(a.program[0].op == Op::J && a.program[0].target == 2);
    }
    // 27) 注释与同行标签
    {
        Assembled a = assemble("# 注释\nstart: addi r1, r0, 1   # 同行注释\nhalt\n");
        CHECK(a.program.size() == 2 && a.labels.at("start") == 0);
    }
    // 28) 反汇编（trace 与 chart 的可读性来自它）
    {
        Assembled a = assemble("addi r4, r5, -7\nhalt\n");
        CHECK(disasm(a.program[0]) == "addi r4, r5, -7");
    }
}

static void test_single_cycle_properties() {
    section("单周期性质：周期数、分支改变控制流");
    // 29) 直线程序：周期数 == 执行指令数
    {
        Assembled a = assemble("addi r1, r0, 1\naddi r2, r0, 2\naddi r3, r0, 3\nhalt\n");
        SingleCycleCpu cpu(64);
        CpuStats s = cpu.run(a.program);
        CHECK(s.cycles == 4 && s.instrs == 4);
    }
    // 30) 跳转真的改变了下一条指令（trace 里的 pc 序列）
    {
        Assembled a = assemble("j skip\naddi r1, r0, 9\nskip:\naddi r2, r0, 4\nhalt\n");
        SingleCycleCpu cpu(64);
        cpu.run(a.program);
        const std::string& t = cpu.machine().trace[0];
        CHECK(t.find("pc 0") != std::string::npos && t.find("pc 2") != std::string::npos);
    }
    // 31) trace 每个周期一条
    {
        Assembled a = assemble("addi r1, r0, 1\nhalt\n");
        SingleCycleCpu cpu(64);
        CpuStats s = cpu.run(a.program);
        CHECK(cpu.machine().trace.size() == (std::size_t)s.cycles);
    }
}

static void test_pipeline_matches_single_cycle() {
    section("五级流水线 vs 单周期：最终状态必须逐字节一致");
    const std::string mixed =
        "addi r1, r0, 5\naddi r2, r0, 7\nadd r3, r1, r2\nsub r4, r2, r1\n"
        "slt r5, r1, r2\nsll r6, r1, 1\nsw r3, 0(r0)\nsw r4, 1(r0)\nlw r7, 0(r0)\nlw r8, 1(r0)\n"
        "add r9, r7, r8\nbne r9, r1, skip\naddi r10, r0, 1\nskip:\nhalt\n";
    Machine s = run_single(mixed);
    Machine p = run_pipe(mixed);
    // 32) 寄存器一致  33) 内存一致
    CHECK(same_regs(s, p));
    CHECK(same_mem(s, p));
    // 34) 流水线不比单周期少（有排空与冒险）
    {
        Assembled a = assemble(mixed);
        SingleCycleCpu c1(64);
        PipelineCpu c2(64);
        CHECK(c2.run(a.program).stats.cycles >= c1.run(a.program).cycles);
    }
    // 35) load-use 冒险停顿恰好 1 周期
    {
        Assembled a = assemble("addi r1, r0, 1\nsw r1, 0(r0)\nlw r2, 0(r0)\nadd r3, r2, r1\nhalt\n");
        PipelineCpu cpu(64);
        auto r = cpu.run(a.program);
        CHECK(r.stalls == 1);
        CHECK(cpu.machine().regs.r[3] == 2);
    }
    // 36) 相邻 add/add 靠前递解决：零停顿且值正确
    {
        Assembled a = assemble("addi r1, r0, 2\naddi r2, r0, 3\nadd r3, r1, r2\nadd r4, r3, r1\nhalt\n");
        PipelineCpu cpu(64);
        auto r = cpu.run(a.program);
        CHECK(r.stalls == 0 && cpu.machine().regs.r[4] == 7);
    }
    // 37) 分支跳了要冲刷（≥1 次）  38) 分支没跳不冲刷
    {
        Assembled a = assemble("addi r1, r0, 1\nbeq r1, r1, skip\naddi r2, r0, 9\nskip:\nhalt\n");
        PipelineCpu cpu(64);
        CHECK(cpu.run(a.program).flushes >= 1);
    }
    {
        Assembled a = assemble("addi r1, r0, 1\naddi r2, r0, 2\nbeq r1, r2, skip\naddi r3, r0, 9\nskip:\nhalt\n");
        PipelineCpu cpu(64);
        CHECK(cpu.run(a.program).flushes == 0);
    }
    // 39) 冒泡排序：两个模型都排好，且寄存器一致
    {
        std::string sort_src =
            "addi r1, r0, 0\naddi r2, r0, 4\n"
            "outer:\nslt r10, r1, r2\nbeq r10, r0, done\naddi r3, r0, 0\n"
            "inner:\nsub r11, r2, r1\nslt r4, r3, r11\nbeq r4, r0, nextpass\n"
            "add r5, r3, r0\nlw r6, 0(r5)\naddi r7, r3, 1\nlw r8, 0(r7)\n"
            "slt r9, r8, r6\nbeq r9, r0, noswap\nsw r8, 0(r5)\nsw r6, 0(r7)\n"
            "noswap:\naddi r3, r3, 1\nj inner\n"
            "nextpass:\naddi r1, r1, 1\nj outer\ndone:\nhalt\n";
        std::vector<int32_t> seed = {5, 1, 4, 2, 3};
        Machine s2 = run_single(sort_src, seed);
        Machine p2 = run_pipe(sort_src, seed);
        CHECK(s2.mem.words[0] == 1 && s2.mem.words[1] == 2 && s2.mem.words[2] == 3 &&
              s2.mem.words[3] == 4 && s2.mem.words[4] == 5);
        CHECK(same_regs(s2, p2));
    }
}

int main() {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    std::printf("========== B5 教学 CPU 自测 ==========\n");
    test_isa_semantics();
    test_assembler();
    test_single_cycle_properties();
    test_pipeline_matches_single_cycle();
    std::printf("\n========== 结果：%d 项断言，%d 项失败 ==========\n", g_checks, g_fails);
    if (g_fails == 0) { std::printf("全部通过 ✔\n"); return 0; }
    std::printf("存在失败 ✘\n");
    return 1;
}
