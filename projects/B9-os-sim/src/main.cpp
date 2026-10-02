// src/main.cpp —— 演示入口：./build/os-sim.exe [sched|paging|banker|fat|pc|all]
//
// 自测在 tests/test_ossim.cpp（183 项断言）；这里只做"把结论打印给人看"的演示，
// 每个模块都使用与自测相同的教科书例子，数字可与 README 的表格对照。
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "ossim/banker.hpp"
#include "ossim/fat.hpp"
#include "ossim/paging.hpp"
#include "ossim/pc_buffer.hpp"
#include "ossim/scheduler.hpp"

using namespace ossim;

static void demo_sched() {
    std::printf("== 调度（教材例子 P1[0,7] P2[2,4] P3[4,1] P4[5,4]）==\n");
    auto ps = sample_procs();
    auto show = [](const char* name, const SchedResult& r) {
        std::printf("  %-14s 等待 %.2f  周转 %.2f  甘特图：", name,
                    r.avg_waiting, r.avg_turnaround);
        for (auto& g : r.gantt) std::printf("%s[%d,%d] ", g.name.c_str(), g.start, g.end);
        std::printf("\n");
    };
    show("FCFS", fcfs(ps));
    show("SJF", sjf(ps));
    show("优先级", priority_sched(ps));
    show("RR q=2", rr(ps, 2));
    show("RR q=100", rr(ps, 100));
    std::printf("  说明：RR(q=2) 的入队约定是「新到达先入队、到期回队尾」；"
                "q 极大时退化为 FCFS（等待 4.75 与 FCFS 相同）。\n\n");
}

static void demo_paging() {
    std::printf("== 页面置换（参考串 1 2 3 4 1 2 5 1 2 3 4 5）==\n");
    std::vector<int> refs = {1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5};
    std::printf("  帧数 |  FIFO  LRU  Clock   OPT\n");
    for (int f = 3; f <= 4; ++f) {
        std::printf("   %d   |   %2d    %2d    %2d     %2d\n", f,
                    fifo(refs, f).faults, lru(refs, f).faults,
                    clock_sim(refs, f).faults, opt(refs, f).faults);
    }
    std::printf("  Belady 异常：FIFO 从 3 帧到 4 帧，缺页反而变多（9 → 10）。\n");
    std::printf("  注意：LRU ≤ FIFO **不成立**（本串 LRU=10 > FIFO=9），"
                "能断言的只有 OPT ≤ 任何算法。\n\n");
}

static void demo_banker() {
    std::printf("== 银行家算法（Silberschatz 5 进程 3 资源）==\n");
    Banker bk(5, 3, {3, 3, 2},
              {{7, 5, 3}, {3, 2, 2}, {9, 0, 2}, {2, 2, 2}, {4, 3, 3}},
              {{0, 1, 0}, {2, 0, 0}, {3, 0, 2}, {2, 1, 1}, {0, 0, 2}});
    auto [safe, seq] = bk.safety();
    std::printf("  初始安全性：%s  序列：P", safe ? "安全" : "不安全");
    for (int i : seq) std::printf(" -> P%d", i);
    std::printf("\n");
    auto seq2 = bk.request(1, {1, 0, 2});
    std::printf("  P1 请求 (1,0,2)：批准，序列长度 %zu，Available 变为 (%d,%d,%d)\n",
                seq2.size(), bk.available[0], bk.available[1], bk.available[2]);
    try {
        bk.request(4, {3, 3, 0});
    } catch (const std::runtime_error& e) {
        std::printf("  P4 请求 (3,3,0)：拒绝（%s）\n", e.what());
    }
    try {
        bk.request(0, {0, 2, 0});
    } catch (const std::runtime_error& e) {
        std::printf("  P0 请求 (0,2,0)：拒绝（%s）；回滚后 Available=(%d,%d,%d)\n", e.what(),
                    bk.available[0], bk.available[1], bk.available[2]);
    }
    std::printf("\n");
}

static void demo_fat() {
    std::printf("== FAT 文件系统（16 块、每块 4 字节）==\n");
    FatFs fs(16);
    fs.write("a.txt", "HelloFAT");
    std::printf("  写 a.txt(8B) -> 链 %zu 块，首块 %d，空闲 %d\n",
                fs.chain_of("a.txt").size(), fs.chain_of("a.txt")[0], fs.free_blocks());
    fs.remove("a.txt");
    fs.write("c", "ABCD");
    std::printf("  删 a.txt 再建 c(4B)：c 复用块 %d（第一次分配从低块号开始）\n",
                fs.chain_of("c")[0]);
    FatFs d(4);
    d.write("keep", "01234567");
    int before = d.free_blocks();
    try {
        d.write("new", std::string(16, 'x'));
    } catch (const std::runtime_error&) {
        std::printf("  满盘写新文件：失败并被回滚——keep 内容完好=%s，空闲块数不变=%s\n",
                    d.read("keep") == "01234567" ? "是" : "否",
                    d.free_blocks() == before ? "是" : "否");
    }
    std::printf("\n");
}

static void demo_pc() {
    std::printf("== 生产者-消费者（2 生产者 + 2 消费者，各 2 万条）==\n");
    BoundedBuffer<int> buf(8);
    const int PROD = 2, CONS = 2, PER = 20000;
    std::vector<std::thread> ts;
    for (int p = 0; p < PROD; ++p)
        ts.emplace_back([&buf, p] { for (int i = 0; i < PER; ++i) buf.put(p * PER + i); });
    std::vector<int> all;
    std::mutex all_mu;
    for (int c = 0; c < CONS; ++c)
        ts.emplace_back([&buf, &all, &all_mu] {
            std::vector<int> mine;
            for (int i = 0; i < PROD * PER / CONS; ++i) mine.push_back(buf.get());
            std::lock_guard<std::mutex> lock(all_mu);
            all.insert(all.end(), mine.begin(), mine.end());
        });
    for (auto& t : ts) t.join();
    std::sort(all.begin(), all.end());
    bool exact = (int)all.size() == PROD * PER;
    for (std::size_t i = 0; exact && i < all.size(); ++i) exact = all[i] == (int)i;
    std::printf("  投递 %ld、取走 %ld、水位 %d（容量 8）；逐条比对（不丢不重不错值）：%s\n\n",
                buf.total_put(), buf.total_get(), buf.high_watermark(),
                exact ? "全部对上" : "有偏差");
}

int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    const std::string what = argc > 1 ? argv[1] : "all";
    std::printf("========== OS 模拟器演示（%s）==========\n\n", what.c_str());
    if (what == "sched" || what == "all") demo_sched();
    if (what == "paging" || what == "all") demo_paging();
    if (what == "banker" || what == "all") demo_banker();
    if (what == "fat" || what == "all") demo_fat();
    if (what == "pc" || what == "all") demo_pc();
    std::printf("演示结束。自测请跑：mingw32-make test\n");
    return 0;
}
