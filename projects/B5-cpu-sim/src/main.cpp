// src/main.cpp —— B5 演示入口：cpu-sim.exe [--chart] [program.asm]
//
// 默认：跑单周期与五级流水线两个模型，打印最终状态与周期对比（双模型对拍）。
// --chart：打印流水线时空图（每周期一格，S=停顿，F=冲刷）。
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "asm.hpp"
#include "cpu.hpp"
#include "pipeline.hpp"

using namespace b5;

static std::string read_file(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("打不开程序文件：" + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

static void seed_array(Machine& m, const std::vector<int32_t>& values) {
    for (std::size_t i = 0; i < values.size(); ++i) m.mem.words[i] = values[i];
}

static std::string regs_of(const Machine& m) {
    std::string s;
    for (int i = 1; i <= 12; ++i) {
        if (m.regs.r[i] != 0) s += "r" + std::to_string(i) + "=" + std::to_string(m.regs.r[i]) + " ";
    }
    return s.empty() ? "(全 0)" : s;
}

int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    bool chart = false;
    std::string path = "programs/bubble.asm";
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--chart") chart = true;
        else path = a;
    }
    try {
        Assembled asm_ = assemble(read_file(path));
        std::printf("程序：%s（%zu 条指令）\n", path.c_str(), asm_.program.size());

        if (chart) {
            PipelineCpu pipe_(64);
            auto r = pipe_.run(asm_.program);
            std::printf("\n流水线时空图（IF | ID | EX | MEM | WB；S=停顿 F=冲刷）\n");
            std::printf("cycle   IF        ID        EX        MEM       WB\n");
            for (const auto& row : r.chart)
                std::printf("%5d   %-9s %-9s %-9s %-9s %-9s\n", row.cycle,
                            row.cols[0].c_str(), row.cols[1].c_str(), row.cols[2].c_str(),
                            row.cols[3].c_str(), row.cols[4].c_str());
            std::printf("\n总共 %d 周期：停顿 %d 次、冲刷 %d 次；分支 %d（跳了 %d 次）\n",
                        r.stats.cycles, r.stalls, r.flushes, r.stats.branches,
                        r.stats.branches_taken);
            return 0;
        }

        const std::vector<int32_t> kInput = {5, 1, 4, 2, 3};
        SingleCycleCpu single(64);
        seed_array(single.machine(), kInput);
        auto s1 = single.run(asm_.program);

        PipelineCpu piped(64);
        seed_array(piped.machine(), kInput);      // run() 保留调用方写入的初值
        PipeResult r2 = piped.run(asm_.program);
        std::printf("\n单周期：%d 周期，%zu 条 trace；%s\n", s1.cycles, single.machine().trace.size(),
                    regs_of(single.machine()).c_str());
        std::printf("流水线：%d 周期（停顿 %d、冲刷 %d）；%s\n", r2.stats.cycles, r2.stalls,
                    r2.flushes, regs_of(r2.machine).c_str());
        std::printf("排序结果：mem[0..4] = ");
        for (int i = 0; i < 5; ++i) std::printf("%d ", single.machine().mem.words[i]);
        std::printf("\n双模型寄存器一致：%s\n",
                    regs_of(single.machine()) == regs_of(r2.machine) ? "是" : "否");
    } catch (const std::exception& exc) {
        std::printf("错误：%s\n", exc.what());
        return 1;
    }
    return 0;
}
