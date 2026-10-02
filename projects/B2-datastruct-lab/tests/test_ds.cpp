// tests/test_ds.cpp —— B2 自测：手算边界 + 与 std 对拍 + 交互菜单脚本驱动
//
// 纪律（和本仓库其它项目一致）：
//   1. 期望值来自手算（写出算式）或独立参照（std::set/std::queue/BFS/反复松弛）；
//   2. 计数器（moves/hops/comparisons/probes）的期望值也是手算的——
//      "O(n)" 的演示数字必须从小样例一步步推得出来，大样例才可信；
//   3. 菜单也能被测试：run_menu 收 istringstream、吐 ostringstream，断言输出；
//   4. 纯内存测试，不碰文件系统。
#include <cstdio>
#include <queue>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "ds/bst.hpp"
#include "ds/check.hpp"
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

// ---------------------------------------------------------------- 顺序表

static void test_seqlist_edges() {
    long long m0 = ds::checker().mark();

    ds::SeqList<int> s;
    CHECK(s.empty() && s.size() == 0);
    bool threw = false;
    try { (void)s.at(0); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);

    s.reserve(8);                          // 先预留：下面量到的移动都是"纯搬元素"，不含扩容
    for (int i = 1; i <= 3; ++i) s.push_back(i * 10);   // [10 20 30]
    s.reset_counters();

    s.insert(0, 5);                        // [5 10 20 30]：30→3 号位、20→2、10→1，共 3 步
    CHECK(s.moves() == 3);
    CHECK(s.size() == 4 && s[0] == 5 && s[3] == 30);

    s.reset_counters();
    s.insert(2, 15);                       // [5 10 15 20 30]：30→4、20→3，共 2 步
    CHECK(s.moves() == 2);
    CHECK(s[2] == 15 && s[3] == 20);

    s.reset_counters();
    s.erase(0);                            // [10 15 20 30]：10→0、15→1、20→2、30→3，共 4 步
    CHECK(s.moves() == 4);
    CHECK(s.size() == 4 && s[0] == 10 && s[3] == 30);

    s.reset_counters();
    CHECK(s.find(20) == 2);                // 10、15、20 比三次
    CHECK(s.comparisons() == 3);
    CHECK(s.find(999) == ds::SeqList<int>::npos);
    CHECK(s.comparisons() == 3 + 4);       // 又比了 4 次（全扫）

    threw = false;
    try { s.erase(4); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);
    threw = false;
    try { s.insert(9, 1); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);

    // 拷贝独立 + 自赋值
    ds::SeqList<int> copy(s);
    s[0] = -1;
    CHECK(copy[0] == 10 && s[0] == -1);
    ds::SeqList<int>& self = s;
    s = self;
    CHECK(s[0] == -1 && s.size() == 4);

    // 空表插入（pos == size 也走追加分支）
    ds::SeqList<int> fresh;
    fresh.insert(0, 7);
    CHECK(fresh.size() == 1 && fresh[0] == 7);

    std::printf("  [顺序表边界] %lld 项\n", ds::checker().mark() - m0);
}

// ---------------------------------------------------------------- 单链表

static void test_linkedlist_edges() {
    long long m0 = ds::checker().mark();

    ds::LinkedList<int> l;
    CHECK(l.empty());
    for (int i = 3; i >= 1; --i) l.push_front(i);   // [1 2 3]
    l.push_back(4);                                  // [1 2 3 4]
    CHECK(l.size() == 4 && l.at(0) == 1 && l.at(3) == 4);

    l.reset_counters();
    CHECK(l.find(3) == 2);
    CHECK(l.hops() == 2);                            // 走过 1、2 两点
    CHECK(l.comparisons() == 3);                     // 比了 1、2、3

    l.insert_at(1, 99);                              // [1 99 2 3 4]
    CHECK(l.size() == 5 && l.at(1) == 99 && l.at(2) == 2);
    l.erase_at(0);                                   // [99 2 3 4]
    CHECK(l.at(0) == 99 && l.size() == 4);

    l.reverse();                                     // [4 3 2 99]
    CHECK(l.at(0) == 4 && l.at(1) == 3 && l.at(3) == 99);

    // remove_all：重复值、删头、删尾，删空后再 push（tail_ 完整性）
    ds::LinkedList<int> r;
    for (int v : {1, 2, 3, 2, 4, 2}) r.push_back(v);
    CHECK(r.remove_all(2) == 3);                     // [1 3 4]
    CHECK(r.size() == 3 && r.at(0) == 1 && r.at(1) == 3 && r.at(2) == 4);
    CHECK(r.remove_all(1) == 1);                     // [3 4]，删头
    CHECK(r.remove_all(4) == 1);                     // [3]，删尾
    CHECK(r.size() == 1 && r.at(0) == 3);
    r.push_back(9);                                  // 删尾后尾指针仍然要对
    CHECK(r.size() == 2 && r.at(1) == 9);
    CHECK(r.remove_all(3) == 1 && r.remove_all(9) == 1);
    CHECK(r.empty());
    r.push_back(5);
    CHECK(r.size() == 1 && r.at(0) == 5);

    // 反转的边界：空表与单结点
    ds::LinkedList<int> empty_l;
    empty_l.reverse();
    CHECK(empty_l.empty());
    ds::LinkedList<int> one;
    one.push_back(7);
    one.reverse();
    CHECK(one.size() == 1 && one.at(0) == 7);

    // 拷贝独立 + 移动后源可复用
    ds::LinkedList<int> src;
    for (int v : {1, 2, 3}) src.push_back(v);
    ds::LinkedList<int> cpy(src);
    src.push_back(4);
    CHECK(cpy.size() == 3 && src.size() == 4);
    ds::LinkedList<int> moved(std::move(src));
    CHECK(moved.size() == 4 && src.empty());
    src.push_back(1);
    CHECK(src.size() == 1);

    bool threw = false;
    try { (void)l.at(99); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);
    threw = false;
    try { l.erase_at(99); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);

    std::printf("  [单链表边界] %lld 项\n", ds::checker().mark() - m0);
}

// ---------------------------------------------------------------- 栈 / 队列 / 表达式

static void test_stack_queue_edges() {
    long long m0 = ds::checker().mark();

    // 括号匹配：手算的七个样例
    CHECK(ds::brackets_match(""));
    CHECK(ds::brackets_match("abc"));
    CHECK(ds::brackets_match("()"));
    CHECK(ds::brackets_match("([{}])"));
    CHECK(ds::brackets_match("a(b[c]{d})e"));
    CHECK(!ds::brackets_match("([)]"));
    CHECK(!ds::brackets_match("("));
    CHECK(!ds::brackets_match(")"));

    // 栈的后进先出
    ds::Stack<int> st;
    st.push(1); st.push(2); st.push(3);
    CHECK(st.top() == 3 && st.size() == 3);
    st.pop();
    CHECK(st.top() == 2);
    st.pop(); st.pop();
    CHECK(st.empty());
    bool threw = false;
    try { st.pop(); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);

    // 中缀→后缀→求值：手算三例
    CHECK(ds::infix_to_postfix("1+2*3") == "1 2 3 * +");
    CHECK(ds::eval_postfix("1 2 3 * +") == 7);
    CHECK(ds::infix_to_postfix("(1+2)*3") == "1 2 + 3 *");
    CHECK(ds::eval_postfix("1 2 + 3 *") == 9);
    CHECK(ds::infix_to_postfix("10+2") == "10 2 +");
    CHECK(ds::eval_postfix("10 2 +") == 12);
    CHECK(ds::infix_to_postfix("1+2-3") == "1 2 + 3 -");       // 同级左结合
    CHECK(ds::eval_postfix("1 2 + 3 -") == 0);
    threw = false;
    try { (void)ds::infix_to_postfix("(1+2"); } catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);
    threw = false;
    try { (void)ds::infix_to_postfix("a+1"); } catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);
    threw = false;
    try { (void)ds::eval_postfix("1 +"); } catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);
    threw = false;
    try { (void)ds::eval_postfix("1 2 + 3"); } catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);
    threw = false;
    try { (void)ds::eval_postfix("1 0 /"); } catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);

    // 循环队列：容量 4 的绕圈，head/tail 全手推
    ds::ArrayQueue<int> q(4);
    q.push(1); q.push(2); q.push(3); q.push(4);
    CHECK(q.full() && q.size() == 4);
    CHECK(q.head() == 0 && q.tail() == 0);             // 满时头尾又相遇：4 % 4 == 0
    threw = false;
    try { q.push(5); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);
    CHECK(q.front() == 1);
    q.pop();
    CHECK(q.head() == 1 && q.size() == 3);
    q.push(5);                                         // 尾部回绕到 0 号槽
    CHECK(q.tail() == 1 && q.size() == 4);
    CHECK(q.front() == 2);
    for (int want : {2, 3, 4, 5}) {
        CHECK(q.front() == want);
        q.pop();
    }
    CHECK(q.empty());
    threw = false;
    try { (void)q.front(); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);

    // 链式队列同一套语义
    ds::LinkedQueue<int> lq;
    lq.push(1); lq.push(2);
    CHECK(lq.front() == 1 && lq.size() == 2);
    lq.pop();
    CHECK(lq.front() == 2);
    lq.pop();
    CHECK(lq.empty());
    threw = false;
    try { lq.pop(); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);

    std::printf("  [栈/队列/表达式] %lld 项\n", ds::checker().mark() - m0);
}

// ---------------------------------------------------------------- BST

static void test_bst_edges() {
    long long m0 = ds::checker().mark();

    ds::BST<int> t;
    CHECK(t.empty() && t.height() == 0);
    CHECK(t.insert(50));
    CHECK(!t.insert(50));                              // 重复不插
    for (int v : {30, 70, 60, 80}) t.insert(v);
    CHECK(t.size() == 5 && t.height() == 3);

    ds::SeqList<int> order;
    t.in_order(order);
    CHECK(order.size() == 5);
    CHECK(order[0] == 30 && order[1] == 50 && order[2] == 60 &&
          order[3] == 70 && order[4] == 80);
    CHECK(t.min() == 30 && t.max() == 80);

    // 删叶（60）：结构 50(30, 70(60, 80))
    CHECK(t.erase(60));
    CHECK(!t.erase(60));
    order.clear();                                     // in_order 是"追加"语义：复用前要清
    t.in_order(order);
    CHECK(order.size() == 4 && order[2] == 70 && order[3] == 80);

    // 逐情形手推：叶 / 双子 / 单子 / 根
    ds::BST<int> u;
    for (int v : {50, 30, 70, 60, 80}) u.insert(v);   // 50(30, 70(60, 80))
    CHECK(u.height() == 3);
    CHECK(u.erase(70));                                // 双子：中序后继 80 顶替，80 原结点摘除
    order.clear();
    u.in_order(order);
    CHECK(order.size() == 4);
    CHECK(order[0] == 30 && order[1] == 50 && order[2] == 60 && order[3] == 80);
    CHECK(u.height() == 3);                            // 50(30, 80(60))：右子树高 2，总高 3
    CHECK(u.erase(30));                                // 叶：直接摘
    order.clear();
    u.in_order(order);
    CHECK(order.size() == 3 && order[0] == 50 && order[2] == 80);
    CHECK(u.erase(80));                                // 单子：60 上提
    order.clear();
    u.in_order(order);
    CHECK(order.size() == 2 && order[0] == 50 && order[1] == 60);
    CHECK(u.erase(60));                                // 叶
    CHECK(u.erase(50));                                // 根（最后一个结点）
    CHECK(u.empty() && u.height() == 0);
    bool threw = false;
    try { (void)u.min(); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);

    // 高度对照：升序插入退化 vs 折半插入较平衡
    ds::BST<int> degenerate;
    for (int i = 1; i <= 15; ++i) degenerate.insert(i);
    CHECK(degenerate.height() == 15);                  // 升序 = 一条链
    ds::BST<int> balanced;
    for (int v : {8, 4, 12, 2, 6, 10, 14, 1, 3, 5, 7, 9, 11, 13, 15}) balanced.insert(v);
    CHECK(balanced.height() == 4);                     // 完全二叉树高 4（15 个结点 = 2^4-1）
    CHECK(degenerate.size() == balanced.size());

    std::printf("  [BST 边界] %lld 项\n", ds::checker().mark() - m0);
}

// ---------------------------------------------------------------- 哈希

static void test_hash_edges() {
    long long m0 = ds::checker().mark();

    // 链地址：三个同余键（1、17、33 ≡ 1 mod 16）必落同一条链
    ds::HashChaining hc(16);
    CHECK(hc.insert(1));
    CHECK(hc.insert(17));
    CHECK(hc.insert(33));
    CHECK(!hc.insert(17));                             // 重复
    CHECK(hc.longest_chain() == 3);
    CHECK(hc.contains(17) && hc.contains(33) && !hc.contains(2));
    CHECK(hc.erase(17));
    CHECK(!hc.erase(17));
    CHECK(!hc.contains(17) && hc.contains(33));
    CHECK(hc.longest_chain() == 2);
    std::size_t probes0 = hc.probes();
    (void)hc.contains(49);                             // 49 % 16 == 1：落进非空链，未命中也要比完整条链
    CHECK(hc.probes() > probes0);                      // 查找一定在探测计数里留痕
    std::size_t probes1 = hc.probes();
    (void)hc.contains(999);                            // 999 % 16 == 7：空桶，比 0 个键
    CHECK(hc.probes() == probes1);                     // 空桶不比较——这也是"探测"口径的一部分

    // 线性探测：墓碑不能切断探测链
    ds::HashLinear hl(8);
    CHECK(hl.insert(1));                               // 槽 1
    CHECK(hl.insert(9));                               // 1 被占 → 探测到 2
    CHECK(hl.insert(17));                              // → 3
    CHECK(!hl.insert(9));
    CHECK(hl.contains(17) && hl.contains(9));
    CHECK(hl.erase(1));                                // 槽 1 变墓碑
    CHECK(hl.tombstones() == 1);
    CHECK(!hl.contains(1));
    CHECK(hl.contains(9));                             // 墓碑之后仍能查到
    CHECK(hl.contains(17));
    CHECK(hl.insert(25));                              // 复用墓碑位（1 % 8 == 1）
    CHECK(hl.tombstones() == 0 && hl.size() == 3);
    CHECK(hl.contains(25) && hl.contains(9) && hl.contains(17));

    // 负数键
    ds::HashChaining hn(4);
    CHECK(hn.insert(-3));
    CHECK(hn.contains(-3) && !hn.contains(3));
    CHECK(hn.erase(-3));

    // 负载上限：容量 8 的线性表，第 7 个键会触发抛错（6/8 == 3/4）
    ds::HashLinear hfull(8);
    for (int k = 0; k < 6; ++k) CHECK(hfull.insert(k * 8));   // 全落 0 号位也不影响计数
    bool threw = false;
    try { (void)hfull.insert(100); } catch (const std::length_error&) { threw = true; }
    CHECK(threw);
    CHECK(hfull.size() == 6);

    std::printf("  [哈希] %lld 项\n", ds::checker().mark() - m0);
}

// ---------------------------------------------------------------- 堆

static void test_heap_edges() {
    long long m0 = ds::checker().mark();

    ds::Heap<int> h;
    for (int v : {5, 3, 8, 1, 9, 2}) h.push(v);
    CHECK(h.verify());
    CHECK(h.top() == 1);
    std::vector<int> popped;
    while (!h.empty()) {
        popped.push_back(h.top());
        h.pop();
        CHECK(h.verify());                             // 每步都盯不变量
    }
    CHECK(popped.size() == 6);
    CHECK(popped[0] == 1 && popped[1] == 2 && popped[2] == 3 &&
          popped[3] == 5 && popped[4] == 8 && popped[5] == 9);

    bool threw = false;
    try { (void)h.top(); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);
    threw = false;
    try { h.pop(); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);

    // 堆排序（含升/降序、空数组、单元素、已排序）
    std::vector<int> v{5, 1, 4, 2, 8};
    ds::heap_sort(v);
    CHECK(v.size() == 5 && v[0] == 1 && v[4] == 8);
    for (std::size_t i = 1; i < v.size(); ++i) CHECK(v[i - 1] <= v[i]);
    ds::heap_sort(v, false);
    for (std::size_t i = 1; i < v.size(); ++i) CHECK(v[i - 1] >= v[i]);
    std::vector<int> empty_v;
    ds::heap_sort(empty_v);
    CHECK(empty_v.empty());
    std::vector<int> one{7};
    ds::heap_sort(one);
    CHECK(one.size() == 1 && one[0] == 7);

    // 线性建堆 vs 逐个插入：比较次数的量级对照（同一份数据）
    std::vector<int> data;
    for (int i = 0; i < 63; ++i) data.push_back((i * 37 + 11) % 100);   // 固定伪随机序列
    ds::Heap<int> by_build;
    by_build.build(data);
    ds::Heap<int> by_pushes;
    for (int x : data) by_pushes.push(x);
    CHECK(by_build.verify() && by_pushes.verify());
    CHECK(by_build.comparisons() < by_pushes.comparisons());   // 线性建堆的比较次数应显著更少
    std::printf("    （63 个元素：线性建堆比较 %zu 次 vs 逐个插入 %zu 次）\n",
                by_build.comparisons(), by_pushes.comparisons());

    std::printf("  [堆] %lld 项\n", ds::checker().mark() - m0);
}

// ---------------------------------------------------------------- 并查集 / 图

static void test_unionfind_graph_edges() {
    long long m0 = ds::checker().mark();

    ds::UnionFind uf(5);
    CHECK(uf.components() == 5);
    CHECK(uf.unite(0, 1));
    CHECK(uf.unite(1, 2));
    CHECK(!uf.unite(2, 0));                            // 已经连通
    CHECK(uf.components() == 3);
    CHECK(uf.connected(0, 2));
    CHECK(!uf.connected(0, 3));
    CHECK(uf.unite(0, 3));
    CHECK(uf.components() == 2);
    bool threw = false;
    try { (void)uf.find(5); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);

    // 路径压缩：连成一条链后，重复 find 的步数应下降（第二次几乎直达）
    ds::UnionFind chain(8);
    for (int i = 0; i + 1 < 8; ++i) chain.unite(static_cast<std::size_t>(i), static_cast<std::size_t>(i + 1));
    chain.reset_counters();
    (void)chain.find(0);
    std::size_t first = chain.steps();
    chain.reset_counters();
    (void)chain.find(0);
    std::size_t second = chain.steps();
    CHECK(second <= first);
    CHECK(second <= 1);                                // 压缩后一步到根

    // 图：6 个点两个分量 + 一个孤立点
    ds::Graph g(6);
    g.add_edge(0, 1);
    g.add_edge(1, 2);
    g.add_edge(3, 4);
    CHECK(g.components() == 3);
    std::vector<int> dist, order;
    g.bfs(0, dist, order);
    CHECK(dist[0] == 0 && dist[1] == 1 && dist[2] == 2);
    CHECK(dist[3] == -1 && dist[5] == -1);
    CHECK(order.size() == 3 && order[0] == 0 && order[1] == 1 && order[2] == 2);
    g.dfs(0, order);
    CHECK(order.size() == 3 && order[0] == 0 && order[1] == 1 && order[2] == 2);

    // scans：连通分量上 BFS 应恰好扫 2E 条弧（无向图）
    g.reset_counters();
    g.bfs(0, dist, order);
    CHECK(g.scans() == 2 * 2);                         // 分量 {0,1,2} 有 2 条边

    // 有向图：0→1、0→2，从 1 出发谁也到不了
    ds::Graph dg(3, true);
    dg.add_edge(0, 1);
    dg.add_edge(0, 2);
    dg.bfs(1, dist, order);
    CHECK(dist[1] == 0 && dist[0] == -1 && dist[2] == -1);
    CHECK(order.size() == 1);

    // 邻接矩阵同题：与邻接表逐点比对
    ds::MatrixGraph mg(6);
    mg.add_edge(0, 1);
    mg.add_edge(1, 2);
    mg.add_edge(3, 4);
    CHECK(mg.has_edge(0, 1) && mg.has_edge(1, 0) && !mg.has_edge(0, 3));
    std::vector<int> mdist, morder;
    mg.bfs(0, mdist, morder);
    std::vector<int> dist2, order2;
    g.bfs(0, dist2, order2);
    for (int v = 0; v < 6; ++v) {
        CHECK(mdist[static_cast<std::size_t>(v)] == dist2[static_cast<std::size_t>(v)]);
    }
    CHECK(morder == order2);

    threw = false;
    try { ds::Graph bad(0); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);
    threw = false;
    try { g.add_edge(0, 9); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);

    std::printf("  [并查集/图] %lld 项\n", ds::checker().mark() - m0);
}

// ---------------------------------------------------------------- 与 std 对拍（万级检查）

static void test_crosschecks() {
    long long m0 = ds::checker().mark();
    long long total = 0;

    auto run = [&](const char* name, ds::OpReport rep) {
        CHECK(rep.failures == 0);
        if (rep.failures) std::printf("    %s 首处失败: %s\n", name, rep.first_failure.c_str());
        return rep.checks;
    };

    for (unsigned seed = 1; seed <= 25; ++seed) total += run("seqlist", ds::crosscheck_seqlist(seed, 80));
    for (unsigned seed = 1; seed <= 25; ++seed) total += run("linkedlist", ds::crosscheck_linkedlist(seed, 80));
    for (unsigned seed = 1; seed <= 25; ++seed) total += run("arrayqueue", ds::crosscheck_arrayqueue(seed, 80));
    for (unsigned seed = 1; seed <= 30; ++seed) total += run("bst", ds::crosscheck_bst(seed, 80));
    for (unsigned seed = 1; seed <= 20; ++seed) total += run("hash-chain", ds::crosscheck_hash_chain(seed, 80));
    for (unsigned seed = 1; seed <= 20; ++seed) total += run("hash-linear", ds::crosscheck_hash_linear(seed, 80));
    for (unsigned seed = 1; seed <= 25; ++seed) total += run("heap", ds::crosscheck_heap(seed, 80));
    for (unsigned seed = 1; seed <= 20; ++seed) total += run("unionfind", ds::crosscheck_unionfind(seed, 10, 40));
    for (unsigned seed = 1; seed <= 20; ++seed) total += run("graph", ds::crosscheck_graph(seed, 8, 35));

    CHECK(total > 30000);                              // 实打实的万级检查，不是几十项
    std::printf("  [与 std/参照实现对拍] 共 %lld 项检查\n", total);
    std::printf("  [与 std/参照实现对拍] 断言 %lld 项\n", ds::checker().mark() - m0);
}

// ---------------------------------------------------------------- 交互菜单（脚本驱动）

static void test_menu_script() {
    long long m0 = ds::checker().mark();

    const std::string script =
        "1\n"                       // 顺序表
        "1\n5\n"                    // 追加 5
        "1\n7\n"                    // 追加 7
        "5\n"                       // 打印
        "4\n5\n"                    // 查找 5
        "0\n"                       // 返回
        "3\n"                       // 栈/表达式
        "1\n([])\n"                 // 括号匹配
        "2\n(1+2)*3\n"              // 中缀求值
        "0\n"
        "5\n"                       // BST
        "1\n7\n1\n3\n1\n9\n"
        "4\n"                       // 中序
        "5\n"                       // 高度
        "0\n"
        "4\n"                       // 队列
        "1\n4\n1\n5\n1\n6\n1\n7\n"
        "2\n"                       // 出队
        "1\n8\n"                    // 回绕入队
        "0\n"
        "6\n"                       // 哈希
        "1\n17\n1\n33\n"
        "4\n"                       // 统计
        "0\n"
        "7\n"                       // 堆
        "1\n9\n1\n3\n1\n7\n"
        "2\n"                       // 取顶
        "0\n"
        "8\n"                       // 并查集
        "1\n0 1\n1\n1 2\n3\n"       // 合并两次 + 分量数
        "0\n"
        "9\n"                       // 图
        "1\n0 1\n1\n1 2\n2\n0\n"    // 加两条边、BFS
        "4\n"                       // 连通分量
        "0\n"
        "0\n";                      // 退出
    std::istringstream in(script);
    std::ostringstream out;
    int rc = ds::run_menu(in, out);
    CHECK(rc == 0);
    std::string text = out.str();

    auto has = [&](const char* needle) {
        CHECK(text.find(needle) != std::string::npos);
    };
    has("[5 7]");                    // 顺序表打印
    has("找到于下标 0");
    has("括号匹配");
    has("后缀式: 1 2 + 3 * ；求值 = 9");
    has("中序: 3 7 9");
    has("高度 = 2");
    has("出队 4");
    has("已入队");                    // 回绕入队打印
    has("longest_chain=2");           // 17 与 33 同链（1+16k 里的两个）？33 % 16 == 1，17 % 16 == 1 → 同链 2 个
    has("取出 3");                    // 小顶堆先出 3
    has("分量数 = 8");                // 10 结点合并两次 → 8
    has("BFS 序: 0 1 2");
    has("连通分量数 = 6");            // 8 结点 + 两条边 → 6

    // 非法输入不清空程序：喂一个非数字，应该显示"无此选项"后继续，直到 0 退出
    std::istringstream bad("x\n0\n");
    std::ostringstream out2;
    CHECK(ds::run_menu(bad, out2) == 0);
    CHECK(out2.str().find("无此选项") != std::string::npos);

    // 输入流耗尽 = 正常退出
    std::istringstream eof("");
    std::ostringstream out3;
    CHECK(ds::run_menu(eof, out3) == 0);

    std::printf("  [菜单脚本] %lld 项\n", ds::checker().mark() - m0);
}

int main() {
    std::printf("B2-datastruct-lab 自测：手算边界 + 与 std/参照实现对拍 + 菜单脚本\n");
    test_seqlist_edges();
    test_linkedlist_edges();
    test_stack_queue_edges();
    test_bst_edges();
    test_hash_edges();
    test_heap_edges();
    test_unionfind_graph_edges();
    test_crosschecks();
    test_menu_script();
    return ds::checker().report("B2 自测");
}
