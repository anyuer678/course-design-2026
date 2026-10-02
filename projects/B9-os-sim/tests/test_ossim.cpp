// ============================================================================
// tests/test_ossim.cpp —— OS 模拟器自测
// 调度：教材手算例子逐数对拍；页面置换：经典参考串 + Belady 异常 + 性质链
// 银行家：教材例子（安全/批准/拒绝）；FAT：内容回读 + 链结构 + 空文件/满盘/失败回滚
// 生产者-消费者：逐条消息守恒（不丢、不重、不错值）
// ============================================================================
#include <algorithm>
#include <cstdio>
#include <thread>
#include <vector>

#include "ossim/banker.hpp"
#include "ossim/fat.hpp"
#include "ossim/paging.hpp"
#include "ossim/pc_buffer.hpp"
#include "ossim/scheduler.hpp"

using namespace ossim;

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

static void test_scheduler() {
    section("调度算法：FCFS/SJF/RR 手算对拍");
    auto ps = sample_procs();

    // FCFS: 完成 7,11,12,16；周转 7,9,8,11；等待 0,5,7,7 -> 平均 4.75 / 8.75
    auto r1 = fcfs(ps);
    CHECK(r1.avg_waiting == 4.75);
    CHECK(r1.avg_turnaround == 8.75);
    CHECK(r1.gantt[0].name == "P1" && r1.gantt[0].start == 0 && r1.gantt[0].end == 7);
    CHECK(r1.gantt[3].end == 16);

    // SJF(非抢占): P1[0-7]，然后 P3(1) P2(4) P4(4)；等待 0,6,3,7 -> 4.0
    auto r2 = sjf(ps);
    CHECK(r2.avg_waiting == 4.0);
    CHECK(r2.gantt[1].name == "P3");

    // RR q=2（新到达先入队，再到期进程回队尾）:
    // P1[0-2] P2[2-4] P1[4-6] P3[6-7] P2[7-9] P4[9-11] P1[11-13] P4[13-15] P1[15-16]
    auto r3 = rr(ps, 2);
    CHECK(r3.gantt.size() == 9);
    CHECK(r3.gantt[0].name == "P1" && r3.gantt[0].end == 2);
    CHECK(r3.gantt[3].name == "P3" && r3.gantt[3].end == 7);
    CHECK(r3.gantt[8].name == "P1" && r3.gantt[8].end == 16);
    CHECK(r3.avg_turnaround == 9.0);         // 16+7+3+10 = 36/4
    CHECK(r3.avg_waiting == 5.0);            // 9+3+2+6 = 20/4

    // 优先级: P2(1) 最先就绪的优先者：t=0 只有 P1 -> P1[0-7]，然后 P2 P3 P4
    auto r4 = priority_sched(ps);
    CHECK(r4.gantt[0].name == "P1" && r4.gantt[1].name == "P2");

    // 时间片大小的影响：q 极大时 RR 退化为 FCFS
    auto big = rr(ps, 100);
    CHECK(big.avg_waiting == r1.avg_waiting);
}

static void test_paging() {
    section("页面置换：Belady 异常 + OPT/LRU/FIFO 教科书数值");
    // 经典参考串（Silberschatz 教材同款）
    std::vector<int> refs = {1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5};
    CHECK(fifo(refs, 3).faults == 9);
    CHECK(fifo(refs, 4).faults == 10);       // Belady 异常：4 帧反而更多缺页！
    CHECK(lru(refs, 3).faults == 10);
    CHECK(opt(refs, 3).faults == 7);

    // 性质链（随机串）：OPT 是下界——OPT 缺页数 <= LRU、<= FIFO。
    // 注意 LRU 与 FIFO 互不支配（上面的教材例子里 LRU=10 > FIFO=9），
    // 不能断言 LRU <= FIFO！
    uint64_t s = 88;
    auto rnd = [&]() { s = s * 6364136223846793005ull + 1; return (int)((s >> 33) % 8); };
    for (int t = 0; t < 50; ++t) {
        std::vector<int> r(100);
        for (auto& x : r) x = rnd();
        int f = 2 + t % 4;
        int o = opt(r, f).faults, l = lru(r, f).faults, ff = fifo(r, f).faults;
        CHECK(o <= l);
        CHECK(o <= ff);
    }
    // LRU 栈式性质：帧数越多缺页单调不增（OPT 同理；FIFO 不保证——见上）
    for (auto algo : {&lru, &opt}) {
        int prev = 1 << 30;
        for (int f = 1; f <= 7; ++f) {
            int cur = algo(refs, f).faults;
            CHECK(cur <= prev);
            prev = cur;
        }
    }
}

static void test_banker() {
    section("银行家算法：教材 5 进程 3 资源例子");
    // Silberschatz 经典数据
    Banker bk(5, 3,
              {3, 3, 2},   // available（10-7, 5-2, 7-5）
              {{7, 5, 3}, {3, 2, 2}, {9, 0, 2}, {2, 2, 2}, {4, 3, 3}},
              {{0, 1, 0}, {2, 0, 0}, {3, 0, 2}, {2, 1, 1}, {0, 0, 2}});
    auto [safe, seq] = bk.safety();
    CHECK(safe);
    CHECK(seq.size() == 5);
    // 序列里每个进程的资源需求都能被满足——逐项复验
    std::vector<int> work = {3, 3, 2};
    for (int i : seq) {
        CHECK(Banker::le(bk.need[i], work));
        for (int j = 0; j < 3; ++j) work[j] += bk.alloc[i][j];
    }

    // P1 请求 (1,0,2)：批准（教材标准结论），随后仍安全
    auto seq2 = bk.request(1, {1, 0, 2});
    CHECK(seq2.size() == 5);
    // P4 请求 (3,3,0)：超过 Need(P4) = (2,3,1) -> 拒绝
    bool threw = false;
    try { bk.request(4, {3, 3, 0}); } catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);
    // P0 请求 (0,2,0)：不超 Need，但分配后不安全 -> 拒绝并回滚
    threw = false;
    try { bk.request(0, {0, 2, 0}); } catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);
    // 回滚必须完整：available 恢复 (2,3,0)（批准 P1 请求后的状态）
    CHECK(bk.available[0] == 2 && bk.available[1] == 3 && bk.available[2] == 0);
}

static void test_fat() {
    section("FAT 文件系统：内容回读 / 链结构 / 块复用");
    FatFs fs(16);
    CHECK(fs.free_blocks() == 16);

    fs.write("a.txt", "HelloFAT");           // 8 字节 -> 2 块
    CHECK(fs.read("a.txt") == "HelloFAT");
    CHECK(fs.chain_of("a.txt").size() == 2);
    CHECK(fs.chain_of("a.txt")[0] == 0);     // 顺序分配：块 0、1
    CHECK(fs.chain_of("a.txt")[1] == 1);

    fs.write("b.dat", "xyz");                // 1 块（块 2）
    CHECK(fs.free_blocks() == 16 - 3);

    fs.append("b.dat", "more data!!");       // 追加 10 字节
    CHECK(fs.read("b.dat") == "xyzmore data!!");
    CHECK(fs.chain_of("b.dat").size() == 4); // 3+10=13 字节 -> ceil(13/4)=4 块

    // 删除释放 -> 新文件复用刚释放的块（第一次分配从低块号开始）
    fs.remove("a.txt");
    CHECK(fs.free_blocks() == 16 - 4);       // a.txt(2) 已还，剩 b.dat(4) 占用
    fs.write("c", "ABCD");
    auto chain = fs.chain_of("c");
    CHECK(chain.size() == 1);
    CHECK(chain[0] == 0);                    // 复用 a.txt 释放的块 0

    // 覆盖写：新链建成功后才释放旧链
    fs.write("c", "12345678");
    CHECK(fs.read("c") == "12345678");

    bool threw = false;
    try { fs.read("nope"); } catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);
}

static void test_fat_edge() {
    section("FAT 边界：空文件 / 满盘 / 分配失败既不泄漏块也不破坏旧内容");
    // 1) 空文件：不占块、读回空串、能追加
    FatFs fs(8);
    fs.write("e", "");
    CHECK(fs.exists("e"));
    CHECK(fs.read("e").empty());
    CHECK(fs.chain_of("e").empty());
    CHECK(fs.free_blocks() == 8);
    fs.append("e", "ABCD");                       // 空文件没有链尾，退化为整文件写
    CHECK(fs.read("e") == "ABCD");
    CHECK(fs.chain_of("e").size() == 1);
    fs.append("e", "EFGH");
    CHECK(fs.read("e") == "ABCDEFGH");
    fs.remove("e");
    CHECK(fs.free_blocks() == 8);

    // 2) 满盘：新文件分配失败 -> 半条链回滚，已有文件不受影响
    FatFs d(4);
    d.write("keep", "01234567");                  // 2 块，剩 2 块空闲
    int free_before = d.free_blocks();
    bool threw = false;
    try { d.write("new", "0123456789012345"); }   // 需要 4 块
    catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);
    CHECK(!d.exists("new"));
    CHECK(d.read("keep") == "01234567");
    CHECK(d.free_blocks() == free_before);

    // 3) 覆盖写失败：旧内容必须完好（先建新链，成功后才动旧链）
    threw = false;
    try { d.write("keep", std::string(32, 'x')); }
    catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);
    CHECK(d.read("keep") == "01234567");
    CHECK(d.chain_of("keep").size() == 2);
    CHECK(d.free_blocks() == free_before);

    // 4) 追加失败：文件大小与内容都保持原样
    threw = false;
    try { d.append("keep", "this extra content cannot fit"); }
    catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);
    CHECK(d.read("keep") == "01234567");
    CHECK(d.free_blocks() == free_before);

    // 5) 全部删除后空闲块回到初值——没有任何块被失败分配泄漏掉
    d.remove("keep");
    CHECK(d.free_blocks() == 4);

    // 6) 回归：两个文件的链不得相交（分配器忘占位时两条链都会拿到块 0）
    FatFs t(16);
    t.write("x", "AAAA");
    t.write("y", "BBBB");
    auto cx = t.chain_of("x"), cy = t.chain_of("y");
    CHECK(cx.size() == 1 && cy.size() == 1);
    CHECK(cx[0] != cy[0]);
    CHECK(t.read("x") == "AAAA" && t.read("y") == "BBBB");
}

static void test_producer_consumer() {
    section("生产者-消费者：4 线程 10 万条消息逐条不丢不重");
    BoundedBuffer<int> buf(8);               // 容量 8
    const int PROD = 2, CONS = 2, PER = 50000, TOTAL = PROD * PER;

    std::vector<std::thread> threads;
    for (int p = 0; p < PROD; ++p)
        threads.emplace_back([&buf, p, PER] {
            for (int i = 0; i < PER; ++i) buf.put(p * PER + i);
        });
    std::vector<std::vector<int>> got(CONS);  // 每个消费者写自己的桶，避免数据竞争
    for (int c = 0; c < CONS; ++c)
        threads.emplace_back([&buf, c, &got, PER, PROD, CONS] {
            for (int i = 0; i < PROD * PER / CONS; ++i) got[c].push_back(buf.get());
        });
    for (auto& t : threads) t.join();

    // 只比对总和是**不够**的：{1,1} 与 {0,2} 总和相同。这里要求每条消息恰好出现一次。
    std::vector<int> all;
    for (auto& v : got) all.insert(all.end(), v.begin(), v.end());
    std::sort(all.begin(), all.end());
    CHECK((int)all.size() == TOTAL);          // 不丢
    bool exact = all.size() == (size_t)TOTAL;
    for (size_t i = 0; exact && i < all.size(); ++i) exact = all[i] == (int)i;
    CHECK(exact);                             // 不重、不错值
    CHECK(buf.total_put() == buf.total_get());
    CHECK(buf.high_watermark() <= 8);        // 水位从未越界
}

int main() {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    std::printf("========== OS 模拟器自测 ==========\n");
    test_scheduler();
    test_paging();
    test_banker();
    test_fat();
    test_fat_edge();
    test_producer_consumer();
    std::printf("\n========== 结果：%d 项断言，%d 项失败 ==========\n", g_checks, g_fails);
    if (g_fails == 0) { std::printf("全部通过 ✔\n"); return 0; }
    std::printf("存在失败 ✘\n");
    return 1;
}
