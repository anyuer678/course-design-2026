// ds/fuzz.hpp —— 对拍引擎：同一串随机操作喂给"自研结构"与"标准库参照"
//
// 课程要点（继承本仓库的对拍纪律）：正确性不是写几个用例证明的，是**同一操作序列
// 在两套实现上逐步比对**出来的；每个引擎种子固定、失败可复现，并且被
// 测试（几万项断言）与演示（汇总读数）**共用同一份**。
//
// 参照物清单：
//   SeqList     vs std::vector            顺序表语义
//   LinkedList  vs std::vector（序列化后） 链式表语义（顺序一致性）
//   ArrayQueue  vs std::queue             队列语义（含回绕）
//   BST         vs std::set               有序集合语义
//   HashChaining/HashLinear vs std::unordered_set  集合语义（两种冲突策略同题）
//   Heap        vs std::priority_queue    堆序语义（另加整树 verify）
//   UnionFind   vs 图 BFS 连通分量         两套独立连通性算法
//   Graph       vs 反复松弛（Bellman–Ford 无权版）与邻接矩阵 BFS   最短路语义
#pragma once

#include <algorithm>
#include <cstddef>
#include <queue>
#include <random>
#include <set>
#include <string>
#include <unordered_set>
#include <vector>

#include "ds/bst.hpp"
#include "ds/graph.hpp"
#include "ds/hash.hpp"
#include "ds/heap.hpp"
#include "ds/linkedlist.hpp"
#include "ds/queue.hpp"
#include "ds/seqlist.hpp"
#include "ds/unionfind.hpp"

namespace ds {

struct OpReport {
    long long checks = 0;
    long long failures = 0;
    std::string first_failure;

    void fail(const std::string& what) {
        ++failures;
        if (first_failure.empty()) first_failure = what;
    }
};

inline std::string ctx(const char* name, unsigned seed, int step) {
    return std::string(name) + " seed=" + std::to_string(seed) + " step=" + std::to_string(step);
}

// find 结论核对：两边的"找到的下标"必须一致（不只比找没找到）
inline void check_find(OpReport& rep, const char* name, unsigned seed, int step,
                       bool found_a, std::size_t idx_a, bool found_b, std::size_t idx_b) {
    ++rep.checks;
    if (found_a != found_b || (found_a && idx_a != idx_b)) {
        rep.fail(ctx(name, seed, step) + " find 结论/下标不一致");
    }
}

// ---------------------------------------------------------------- 顺序表 vs std::vector

inline OpReport crosscheck_seqlist(unsigned seed, int steps) {
    OpReport rep;
    std::mt19937 rng(seed);
    SeqList<int> a;
    std::vector<int> b;
    for (int s = 0; s < steps; ++s) {
        unsigned op = rng() % 100;
        if (op < 40) {
            int v = static_cast<int>(rng() % 1000);
            a.push_back(v);
            b.push_back(v);
        } else if (op < 65) {
            int v = static_cast<int>(rng() % 1000);
            std::size_t idx = rng() % (b.size() + 1);
            a.insert(idx, v);
            b.insert(b.begin() + static_cast<std::ptrdiff_t>(idx), v);
        } else if (op < 85) {
            if (!b.empty()) {
                std::size_t idx = rng() % b.size();
                a.erase(idx);
                b.erase(b.begin() + static_cast<std::ptrdiff_t>(idx));
            }
        } else if (op < 93) {
            int v = static_cast<int>(rng() % 1000);
            std::size_t fa = a.find(v);
            auto it = std::find(b.begin(), b.end(), v);
            bool found_ref = it != b.end();
            std::size_t fb = found_ref ? static_cast<std::size_t>(it - b.begin())
                                       : SeqList<int>::npos;
            check_find(rep, "seqlist", seed, s,
                       fa != SeqList<int>::npos, fa, found_ref, fb);
        } else {
            if (b.size() > 8 && rng() % 4 == 0) {
                a.clear();
                b.clear();
            }
        }
        ++rep.checks;
        if (a.size() != b.size()) {
            rep.fail(ctx("seqlist", seed, s) + " size 不一致");
            continue;
        }
        for (std::size_t i = 0; i < b.size(); ++i) {
            ++rep.checks;
            if (a[i] != b[i]) {
                rep.fail(ctx("seqlist", seed, s) + " 第 " + std::to_string(i) + " 个元素不同");
                break;
            }
        }
    }
    return rep;
}

// ---------------------------------------------------------------- 单链表 vs std::vector（序列语义）

inline OpReport crosscheck_linkedlist(unsigned seed, int steps) {
    OpReport rep;
    std::mt19937 rng(seed);
    LinkedList<int> a;
    std::vector<int> b;
    for (int s = 0; s < steps; ++s) {
        unsigned op = rng() % 100;
        if (op < 25) {
            int v = static_cast<int>(rng() % 1000);
            a.push_front(v);
            b.insert(b.begin(), v);
        } else if (op < 50) {
            int v = static_cast<int>(rng() % 1000);
            a.push_back(v);
            b.push_back(v);
        } else if (op < 65) {
            int v = static_cast<int>(rng() % 1000);
            std::size_t idx = rng() % (b.size() + 1);
            a.insert_at(idx, v);
            b.insert(b.begin() + static_cast<std::ptrdiff_t>(idx), v);
        } else if (op < 80) {
            if (!b.empty()) {
                std::size_t idx = rng() % b.size();
                a.erase_at(idx);
                b.erase(b.begin() + static_cast<std::ptrdiff_t>(idx));
            }
        } else if (op < 88) {
            a.reverse();
            std::reverse(b.begin(), b.end());
        } else if (op < 94) {
            int v = static_cast<int>(rng() % 50);
            std::size_t before = b.size();
            std::size_t removed = a.remove_all(v);
            b.erase(std::remove(b.begin(), b.end(), v), b.end());
            ++rep.checks;
            if (removed != before - b.size()) {
                rep.fail(ctx("linkedlist", seed, s) + " remove_all 个数不对");
            }
        } else {
            int v = static_cast<int>(rng() % 1000);
            std::size_t fa = a.find(v);
            auto it = std::find(b.begin(), b.end(), v);
            bool found_ref = it != b.end();
            std::size_t fb = found_ref ? static_cast<std::size_t>(it - b.begin())
                                       : LinkedList<int>::npos;
            check_find(rep, "linkedlist", seed, s,
                       fa != LinkedList<int>::npos, fa, found_ref, fb);
        }
        ++rep.checks;
        if (a.size() != b.size()) {
            rep.fail(ctx("linkedlist", seed, s) + " size 不一致");
            continue;
        }
        for (std::size_t i = 0; i < b.size(); ++i) {
            ++rep.checks;
            if (a.at(i) != b[i]) {
                rep.fail(ctx("linkedlist", seed, s) + " 第 " + std::to_string(i) + " 个元素不同");
                break;
            }
        }
    }
    return rep;
}

// ---------------------------------------------------------------- 循环队列 vs std::queue

inline OpReport crosscheck_arrayqueue(unsigned seed, int steps) {
    OpReport rep;
    std::mt19937 rng(seed);
    const std::size_t cap = 6;
    ArrayQueue<int> a(cap);
    std::queue<int> b;
    for (int s = 0; s < steps; ++s) {
        unsigned op = rng() % 100;
        if (op < 45 && !a.full()) {
            int v = static_cast<int>(rng() % 1000);
            a.push(v);
            b.push(v);
        } else if (op < 85 && !a.empty()) {
            ++rep.checks;
            if (a.front() != b.front()) rep.fail(ctx("arrayqueue", seed, s) + " 队头不同");
            a.pop();
            b.pop();
        } else if (op < 95 && !a.empty()) {
            ++rep.checks;
            if (a.front() != b.front()) rep.fail(ctx("arrayqueue", seed, s) + " front 不同");
        } else if (!b.empty()) {
            std::size_t n = 1 + rng() % b.size();
            for (std::size_t i = 0; i < n; ++i) {
                ++rep.checks;
                if (a.front() != b.front()) rep.fail(ctx("arrayqueue", seed, s) + " 排空中队头不同");
                a.pop();
                b.pop();
            }
        }
        ++rep.checks;
        if (a.size() != b.size()) rep.fail(ctx("arrayqueue", seed, s) + " size 不一致");
    }
    return rep;
}

// ---------------------------------------------------------------- BST vs std::set

inline OpReport crosscheck_bst(unsigned seed, int steps) {
    OpReport rep;
    std::mt19937 rng(seed);
    BST<int> a;
    std::set<int> b;
    for (int s = 0; s < steps; ++s) {
        unsigned op = rng() % 100;
        int v = static_cast<int>(rng() % 100);
        if (op < 45) {
            ++rep.checks;
            bool ia = a.insert(v);
            bool ib = b.insert(v).second;
            if (ia != ib) rep.fail(ctx("bst", seed, s) + " insert 结论不一致（" + std::to_string(v) + "）");
        } else if (op < 70) {
            ++rep.checks;
            bool ea = a.erase(v);
            bool eb = b.erase(v) > 0;
            if (ea != eb) rep.fail(ctx("bst", seed, s) + " erase 结论不一致（" + std::to_string(v) + "）");
        } else if (op < 95) {
            ++rep.checks;
            if (a.contains(v) != (b.count(v) > 0)) {
                rep.fail(ctx("bst", seed, s) + " contains 不一致（" + std::to_string(v) + "）");
            }
        } else {
            a = BST<int>();                  // 偶尔整树重建，顺带过一遍拷贝构造
            for (int x : b) a.insert(x);
        }
        ++rep.checks;
        if (a.size() != b.size()) {
            rep.fail(ctx("bst", seed, s) + " size 不一致");
            continue;
        }
        // 中序 = 有序输出：逐元素对拍 set
        SeqList<int> order;
        a.in_order(order);
        auto it = b.begin();
        for (std::size_t i = 0; i < order.size(); ++i, ++it) {
            ++rep.checks;
            if (order[i] != *it) {
                rep.fail(ctx("bst", seed, s) + " 中序第 " + std::to_string(i) + " 个不同");
                break;
            }
        }
    }
    return rep;
}

// ---------------------------------------------------------------- 哈希两种 vs std::unordered_set

template <class Table>
inline OpReport crosscheck_hash_impl(const char* name, unsigned seed, int steps) {
    OpReport rep;
    std::mt19937 rng(seed);
    Table a(64);                            // 容量给足：线性探测不触 3/4 上限
    std::unordered_set<int> b;
    for (int s = 0; s < steps; ++s) {
        unsigned op = rng() % 100;
        int key = static_cast<int>(rng() % 200);
        if (op < 40) {
            ++rep.checks;
            bool ia = a.insert(key);
            bool ib = b.insert(key).second;
            if (ia != ib) rep.fail(ctx(name, seed, s) + " insert 结论不一致");
        } else if (op < 60) {
            ++rep.checks;
            bool ea = a.erase(key);
            bool eb = b.erase(key) > 0;
            if (ea != eb) rep.fail(ctx(name, seed, s) + " erase 结论不一致");
        } else if (op < 90) {
            ++rep.checks;
            if (a.contains(key) != (b.count(key) > 0)) {
                rep.fail(ctx(name, seed, s) + " contains 不一致");
            }
        } else {
            // 全体键扫描：对绝大多数键做一次 membership 对拍
            for (int k = 0; k < 40; ++k) {
                ++rep.checks;
                if (a.contains(k) != (b.count(k) > 0)) {
                    rep.fail(ctx(name, seed, s) + " 扫描键 " + std::to_string(k) + " 不一致");
                    break;
                }
            }
        }
        ++rep.checks;
        if (a.size() != b.size()) rep.fail(ctx(name, seed, s) + " size 不一致");
    }
    return rep;
}

inline OpReport crosscheck_hash_chain(unsigned seed, int steps) {
    return crosscheck_hash_impl<HashChaining>("hash-chain", seed, steps);
}

inline OpReport crosscheck_hash_linear(unsigned seed, int steps) {
    return crosscheck_hash_impl<HashLinear>("hash-linear", seed, steps);
}

// ---------------------------------------------------------------- 堆 vs std::priority_queue

inline OpReport crosscheck_heap(unsigned seed, int steps) {
    OpReport rep;
    std::mt19937 rng(seed);
    Heap<int> a;                            // 小顶
    std::priority_queue<int, std::vector<int>, std::greater<int>> b;
    for (int s = 0; s < steps; ++s) {
        unsigned op = rng() % 100;
        if (op < 55) {
            int v = static_cast<int>(rng() % 1000);
            a.push(v);
            b.push(v);
        } else if (op < 90 && !a.empty()) {
            ++rep.checks;
            if (a.top() != b.top()) rep.fail(ctx("heap", seed, s) + " 堆顶不同");
            a.pop();
            b.pop();
        } else if (!a.empty()) {
            ++rep.checks;
            if (a.top() != b.top()) rep.fail(ctx("heap", seed, s) + " 堆顶不同(top)");
        }
        ++rep.checks;                       // 整树堆序检查：不变量盯着每一步
        if (!a.verify()) rep.fail(ctx("heap", seed, s) + " 堆序被破坏");
        ++rep.checks;
        if (a.size() != b.size()) rep.fail(ctx("heap", seed, s) + " size 不一致");
    }
    return rep;
}

// ---------------------------------------------------------------- 并查集 vs 图 BFS 连通分量

inline OpReport crosscheck_unionfind(unsigned seed, int n, unsigned density_percent) {
    OpReport rep;
    std::mt19937 rng(seed);
    UnionFind a(static_cast<std::size_t>(n));
    Graph g(n);
    for (int u = 0; u < n; ++u) {
        for (int v = u + 1; v < n; ++v) {
            if (rng() % 100 < density_percent) {
                a.unite(static_cast<std::size_t>(u), static_cast<std::size_t>(v));
                g.add_edge(u, v);
            }
        }
    }
    ++rep.checks;
    if (a.components() != static_cast<std::size_t>(g.components())) {
        rep.fail(ctx("unionfind", seed, 0) + " 分量数不一致");
    }
    // 逐对连通性对拍：并查集 vs BFS
    std::vector<int> dist, order;
    for (int u = 0; u < n; ++u) {
        g.bfs(u, dist, order);
        for (int v = 0; v < n; ++v) {
            ++rep.checks;
            bool uf_conn = a.connected(static_cast<std::size_t>(u), static_cast<std::size_t>(v));
            bool bfs_conn = dist[static_cast<std::size_t>(v)] >= 0;
            if (uf_conn != bfs_conn) {
                rep.fail(ctx("unionfind", seed, 0) + " (" + std::to_string(u) + "," +
                         std::to_string(v) + ") 连通性不一致");
            }
        }
    }
    return rep;
}

// ---------------------------------------------------------------- 图 BFS vs 反复松弛 & 邻接矩阵

inline OpReport crosscheck_graph(unsigned seed, int n, unsigned density_percent) {
    OpReport rep;
    std::mt19937 rng(seed);
    Graph g(n);
    MatrixGraph mg(n);
    std::vector<std::pair<int, int>> edges;
    for (int u = 0; u < n; ++u) {
        for (int v = u + 1; v < n; ++v) {
            if (rng() % 100 < density_percent) {
                g.add_edge(u, v);
                mg.add_edge(u, v);
                edges.push_back({u, v});
            }
        }
    }
    const int INF = 1 << 29;
    for (int s = 0; s < n; ++s) {
        std::vector<int> dist, order;
        g.bfs(s, dist, order);
        std::vector<int> mdist, morder;
        mg.bfs(s, mdist, morder);
        // 参照一：邻接矩阵 BFS 必须与邻接表 BFS 逐点一致
        for (int v = 0; v < n; ++v) {
            ++rep.checks;
            if (dist[static_cast<std::size_t>(v)] != mdist[static_cast<std::size_t>(v)]) {
                rep.fail(ctx("graph", seed, s) + " 邻接表/矩阵距离不一致");
            }
        }
        // 参照二：无权最短路 = 反复松弛 n-1 轮（独立实现）
        std::vector<int> ref(static_cast<std::size_t>(n), INF);
        ref[static_cast<std::size_t>(s)] = 0;
        for (int round = 0; round < n - 1; ++round) {
            for (const auto& e : edges) {
                if (ref[static_cast<std::size_t>(e.first)] + 1 < ref[static_cast<std::size_t>(e.second)]) {
                    ref[static_cast<std::size_t>(e.second)] = ref[static_cast<std::size_t>(e.first)] + 1;
                }
                if (ref[static_cast<std::size_t>(e.second)] + 1 < ref[static_cast<std::size_t>(e.first)]) {
                    ref[static_cast<std::size_t>(e.first)] = ref[static_cast<std::size_t>(e.second)] + 1;
                }
            }
        }
        for (int v = 0; v < n; ++v) {
            ++rep.checks;
            int want = ref[static_cast<std::size_t>(v)] == INF ? -1 : ref[static_cast<std::size_t>(v)];
            if (dist[static_cast<std::size_t>(v)] != want) {
                rep.fail(ctx("graph", seed, s) + " 与反复松弛不一致（点 " + std::to_string(v) + "）");
            }
        }
    }
    return rep;
}

}  // namespace ds
