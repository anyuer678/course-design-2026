// src/main.cpp —— B2 演示：六段脚本，数字全部运行时现算。默认跑脚本演示，
// 加 `--menu` 进入交互菜单（原始交付形态）。
//
//   1) 顺序表 vs 单链表："搬元素"与"跳指针"的代价对照（同一操作序列计数）
//   2) 栈与队列：括号匹配、中缀→后缀→求值、循环队列的绕圈轨迹
//   3) BST：升序插入退化 vs 折半插入，高度与比较次数对照
//   4) 哈希：链地址 vs 线性探测（同余键扎堆时的探测数）
//   5) 堆：线性建堆 vs 逐个插入；堆排序输出
//   6) 并查集 vs BFS 连通分量 + 路径压缩前后 find 步数
//
// 演示不打印耗时（只有计数与结构输出），两次运行应逐字相同。
#include <cstdio>
#include <cstring>
#include <iostream>
#include <random>
#include <string>
#include <vector>

#include "ds/bst.hpp"
#include "ds/fuzz.hpp"
#include "ds/graph.hpp"
#include "ds/hash.hpp"
#include "ds/heap.hpp"
#include "ds/linkedlist.hpp"
#include "ds/menu.hpp"
#include "ds/queue.hpp"
#include "ds/seqlist.hpp"
#include "ds/stack.hpp"
#include "ds/unionfind.hpp"

static void section(int no, const char* title) {
    std::printf("\n============================================================\n");
    std::printf("  %d) %s\n", no, title);
    std::printf("============================================================\n");
}

int main(int argc, char** argv) {
    if (argc > 1 && std::strcmp(argv[1], "--menu") == 0) {
        return ds::run_menu(std::cin, std::cout);
    }

    std::printf("B2-datastruct-lab 演示（交互模式：build\\datastruct.exe --menu）\n");

    // ------------------------------------------------------------------ 1
    section(1, "顺序表 vs 单链表：头部插入的\"搬\"与\"跳\"");
    const int n = 300;
    ds::SeqList<int> seq;
    seq.reserve(static_cast<std::size_t>(n));          // 排除扩容搬动，量纯插入移位
    ds::LinkedList<int> linked;
    for (int i = 1; i <= n; ++i) {
        seq.insert(0, i);
        linked.push_front(i);
    }
    std::printf("  头部插入 %d 次：顺序表共移动元素 %zu 步（≈n²/2），链表改链 %zu 次（O(1)/次）\n",
                n, seq.moves(), linked.links());
    seq.reset_counters();
    linked.reset_counters();
    for (int i = 1; i <= n; ++i) {
        (void)seq.find(i);                             // 列表当前是 [n, n-1, ..., 1]
        (void)linked.find(i);
    }
    std::printf("  再按值查找 %d 次：顺序表比较 %zu 次，链表跳链 %zu 步 + 比较 %zu 次\n",
                n, seq.comparisons(), linked.hops(), linked.comparisons());
    std::printf("  （两种查找同为 O(n)；头插才是差一个数量级的那个操作）\n");

    // ------------------------------------------------------------------ 2
    section(2, "栈与队列：括号匹配 / 中缀转后缀 / 循环队列绕圈");
    const char* samples[] = {"([])", "a(b[c]{d})e", "([)]", "(()"};
    for (const char* s : samples) {
        std::printf("  括号匹配 %-12s %s\n", s, ds::brackets_match(s) ? "配对" : "不配对");
    }
    std::string expr = "3*(4+5)-6";
    std::string post = ds::infix_to_postfix(expr);
    std::printf("  %s → 后缀 %s → 求值 %ld\n", expr.c_str(), post.c_str(), ds::eval_postfix(post));

    ds::ArrayQueue<int> queue(5);
    std::printf("  循环队列容量 5，轨迹（head,tail,size）：");
    int next = 1;
    for (int round = 0; round < 3; ++round) {
        queue.push(next++);
        queue.push(next++);
        std::printf("(%zu,%zu,%zu) ", queue.head(), queue.tail(), queue.size());
        (void)queue.front();
        queue.pop();
        std::printf("(%zu,%zu,%zu) ", queue.head(), queue.tail(), queue.size());
    }
    std::printf("\n");

    // ------------------------------------------------------------------ 3
    section(3, "BST：升序插入的退化和折半插入的平衡");
    ds::BST<int> degenerate;
    ds::BST<int> balanced;
    const int m = 31;
    for (int i = 1; i <= m; ++i) degenerate.insert(i);          // 1..31 升序
    auto insert_balanced = [&](int lo, int hi, auto&& self) -> void {
        if (lo > hi) return;
        int mid = lo + (hi - lo) / 2;
        balanced.insert(mid);
        self(lo, mid - 1, self);
        self(mid + 1, hi, self);
    };
    insert_balanced(1, m, insert_balanced);
    std::printf("  同一集合 {1..%d}：升序插入高度 %zu（=n），折半插入高度 %zu（≈log2 n+1）\n",
                m, degenerate.height(), balanced.height());
    std::printf("  插入比较次数：升序 %zu 次，折半 %zu 次\n",
                degenerate.comparisons(), balanced.comparisons());
    bool erased = balanced.erase(m / 2 + 1);           // 删根（双子情形）
    ds::SeqList<int> order;
    balanced.in_order(order);
    std::printf("  删根 %d（%s）后中序：", m / 2 + 1, erased ? "双子→后继顶替" : "失败");
    for (std::size_t i = 0; i < order.size(); ++i) std::printf("%d ", order[i]);
    std::printf("\n");

    // ------------------------------------------------------------------ 4
    section(4, "哈希：同余键扎堆时，链地址 vs 线性探测");
    const int hash_keys = 12;
    ds::HashChaining chain(16);
    ds::HashLinear linear(16);
    for (int i = 0; i < hash_keys; ++i) {
        int key = i * 16 + 1;                          // 全部 ≡ 1 (mod 16)
        chain.insert(key);
        linear.insert(key);
    }
    chain.reset_counters();
    linear.reset_counters();
    for (int i = 0; i < hash_keys; ++i) {              // 对 12 个键各查一次，再报探测数
        (void)chain.contains(i * 16 + 1);
        (void)linear.contains(i * 16 + 1);
    }
    std::printf("  12 个键全落同一条链/同一段槽（k ≡ 1 mod 16），各查 12 次：\n");
    std::printf("    链地址：最长链 %zu，探测合计 %zu 次\n",
                chain.longest_chain(), chain.probes());
    std::printf("    线性探测：探测合计 %zu 次（读作：平均每次查找看 %.1f 格）\n",
                linear.probes(), static_cast<double>(linear.probes()) / hash_keys);
    ds::HashChaining chain2(16);
    for (int k = 0; k < 12; ++k) chain2.insert(k);
    chain2.reset_counters();
    for (int k = 0; k < 12; ++k) (void)chain2.contains(k);
    std::printf("  分散键（k = 0..11）对照：最长链 %zu、探测合计 %zu 次（每键一眼命中）\n",
                chain2.longest_chain(), chain2.probes());
    std::printf("  删除一个键后线性探测仍能查到后面的键（墓碑不切断链）：");
    linear.erase(17);
    std::printf("查 33=%s，查 17=%s，墓碑=%zu\n",
                linear.contains(33) ? "有" : "无", linear.contains(17) ? "有" : "无",
                linear.tombstones());

    // ------------------------------------------------------------------ 5
    section(5, "堆：线性建堆 vs 逐个插入；堆排序");
    const int hn = 255;
    std::vector<int> data;
    data.reserve(static_cast<std::size_t>(hn));
    for (int i = hn; i >= 1; --i) data.push_back(i);   // **降序**：逼出逐个插入的最坏情形
    ds::Heap<int> by_build;
    by_build.build(data);
    ds::Heap<int> by_pushes;
    for (int x : data) by_pushes.push(x);
    std::printf("  降序 %d 个元素：线性建堆比较 %zu 次（O(n)），逐个插入比较 %zu 次（最坏 O(n log n)）\n",
                hn, by_build.comparisons(), by_pushes.comparisons());
    std::vector<int> small{42, 7, 19, 3, 88, 25, 61, 12, 50, 33};
    std::printf("  堆排序输入：");
    for (int x : small) std::printf("%d ", x);
    ds::heap_sort(small);
    std::printf("\n  升序输出：");
    for (int x : small) std::printf("%d ", x);
    std::printf("\n");

    // ------------------------------------------------------------------ 6
    section(6, "并查集 vs BFS：连通分量对拍 + 路径压缩");
    const int gn = 12;
    std::mt19937 rng(20261002);
    ds::Graph g(gn);
    ds::UnionFind uf(static_cast<std::size_t>(gn));
    int edges = 0;
    for (int u = 0; u < gn; ++u) {
        for (int v = u + 1; v < gn; ++v) {
            if (rng() % 100 < 35) {
                g.add_edge(u, v);
                uf.unite(static_cast<std::size_t>(u), static_cast<std::size_t>(v));
                ++edges;
            }
        }
    }
    std::printf("  随机图（n=%d，边=%d，种子固定）：并查集分量 %zu，BFS 分量 %d → %s\n",
                gn, edges, uf.components(), g.components(),
                uf.components() == static_cast<std::size_t>(g.components()) ? "一致" : "不一致！");

    // 路径压缩：200 个结点按"锦标赛"两两合并（每层翻倍），最深的一条链上量 find
    const int cn = 200;
    ds::UnionFind long_chain(cn);
    for (int width = 1; width < cn; width *= 2) {
        for (int i = 0; i + width < cn; i += 2 * width) {
            long_chain.unite(static_cast<std::size_t>(i), static_cast<std::size_t>(i + width));
        }
    }
    long_chain.reset_counters();
    for (int i = 0; i < cn; ++i) (void)long_chain.find(static_cast<std::size_t>(i));
    std::size_t total_first = long_chain.steps();
    long_chain.reset_counters();
    for (int i = 0; i < cn; ++i) (void)long_chain.find(static_cast<std::size_t>(i));
    std::size_t total_second = long_chain.steps();
    std::printf("  锦标赛式合并 %d 个结点后：全体 find 步数 首轮 %zu → 压缩后 %zu（第二次几乎直达根）\n",
                cn, total_first, total_second);

    std::printf("\n============================================================\n");
    std::printf("完成：6 段演示全部跑通。--menu 进入交互菜单；演示无耗时输出，两遍逐字一致。\n");
    return 0;
}
