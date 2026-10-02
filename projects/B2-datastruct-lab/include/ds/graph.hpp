// ds/graph.hpp —— 图：邻接表 / 邻接矩阵两种存法 + BFS / DFS 遍历
//
// 课程要点：
//   - 存法决定代价：邻接表省空间（O(V+E)），矩阵判"有没有边"是 O(1) 但空间 O(V²)。
//     两种存法各实现一遍 BFS，**结果必须逐点一致**（测试里对拍）；
//   - BFS 用队列、按层扩散 → 首次到达即最短（无权图的"最短路"）；DFS 用栈（迭代版，
//     不拿递归栈冒险），沿一条路走到黑再回退。两者的访问次序用 `order` 记下来对拍；
//   - 连通分量数：这里用 BFS 数（每遇到未访问点开一棵）——它是并查集实现的**独立参照**，
//     谁也别信自己（对拍纪律）；
//   - `scans()` 数"看了多少条边"：无向图一遍 BFS 扫 2E 条弧，这是 O(V+E) 的实测口径。
#pragma once

#include <cstddef>
#include <stdexcept>
#include <vector>

#include "ds/trace.hpp"

namespace ds {

struct Edge {
    int to;
    int weight;
};

// ---------------------------------------------------------------- 邻接表

class Graph {
public:
    explicit Graph(int n, bool directed = false)
        : n_(n), directed_(directed), adj_(make_adj(n)) {}

    static std::vector<std::vector<Edge>> make_adj(int n) {
        if (n <= 0) throw std::invalid_argument("ds::Graph 结点数必须为正");
        return std::vector<std::vector<Edge>>(static_cast<std::size_t>(n));
    }

    int n() const { return n_; }
    bool directed() const { return directed_; }
    std::size_t edge_count() const { return edges_; }
    const std::vector<Edge>& neighbors(int u) const {
        check(u);
        return adj_[static_cast<std::size_t>(u)];
    }

    // 只读观察口（默认 nullptr = 零影响；矩阵版未接，README 注明）
    void set_tracer(Tracer* tracer) { tracer_ = tracer; }

    void add_edge(int u, int v, int weight = 1) {
        check(u);
        check(v);
        adj_[static_cast<std::size_t>(u)].push_back(Edge{v, weight});
        if (!directed_) adj_[static_cast<std::size_t>(v)].push_back(Edge{u, weight});
        ++edges_;
    }

    // BFS：dist 里 -1 = 不可达；order 是访问次序
    void bfs(int start, std::vector<int>& dist, std::vector<int>& order) {
        check(start);
        dist.assign(static_cast<std::size_t>(n_), -1);
        order.clear();
        std::vector<char> seen(static_cast<std::size_t>(n_), 0);
        // 手工用数组当队列（教学图——正是队列 ADT 的应用场景）
        std::vector<int> queue(static_cast<std::size_t>(n_));
        std::size_t head = 0, tail = 0;
        dist[static_cast<std::size_t>(start)] = 0;
        seen[static_cast<std::size_t>(start)] = 1;
        queue[tail++] = start;
        while (head < tail) {
            int u = queue[head++];
            order.push_back(u);
            for (const Edge& e : adj_[static_cast<std::size_t>(u)]) {
                ++scans_;
                if (!seen[static_cast<std::size_t>(e.to)]) {
                    seen[static_cast<std::size_t>(e.to)] = 1;
                    dist[static_cast<std::size_t>(e.to)] = dist[static_cast<std::size_t>(u)] + 1;
                    queue[tail++] = e.to;
                }
            }
            trace("visit", u, dist[static_cast<std::size_t>(u)], queue, head, tail);
        }
    }

    // DFS（迭代版）：显式栈；order 为前序
    void dfs(int start, std::vector<int>& order) {
        check(start);
        order.clear();
        std::vector<char> seen(static_cast<std::size_t>(n_), 0);
        std::vector<int> stack;
        stack.push_back(start);
        while (!stack.empty()) {
            int u = stack.back();
            stack.pop_back();
            if (seen[static_cast<std::size_t>(u)]) continue;
            seen[static_cast<std::size_t>(u)] = 1;
            order.push_back(u);
            const std::vector<Edge>& ns = adj_[static_cast<std::size_t>(u)];
            for (std::size_t i = ns.size(); i-- > 0;) {   // 逆序压栈 → 弹出时按原顺序访问
                ++scans_;
                if (!seen[static_cast<std::size_t>(ns[i].to)]) stack.push_back(ns[i].to);
            }
            trace("visit", u, -1, stack, 0, stack.size());
        }
    }

    // 连通分量数（按 BFS 数；对无向图语义）
    int components() {
        std::vector<int> dist, order;
        int count = 0;
        std::vector<char> seen(static_cast<std::size_t>(n_), 0);
        for (int s = 0; s < n_; ++s) {
            if (seen[static_cast<std::size_t>(s)]) continue;
            ++count;
            bfs(s, dist, order);
            for (int v : order) seen[static_cast<std::size_t>(v)] = 1;
        }
        return count;
    }

    std::size_t scans() const { return scans_; }
    void reset_counters() { scans_ = 0; }

private:
    int n_;
    bool directed_;
    std::vector<std::vector<Edge>> adj_;
    std::size_t edges_ = 0;
    std::size_t scans_ = 0;
    Tracer* tracer_ = nullptr;

    // 事件后的快照：BFS 取队列 [head, tail) 区间，DFS 取整栈
    void trace(const char* op, long long a, long long b, const std::vector<int>& frontier,
               std::size_t from, std::size_t to) {
        if (tracer_ == nullptr) return;
        std::vector<long long> snap;
        snap.reserve(to > from ? to - from : 0);
        for (std::size_t i = from; i < to; ++i) {
            snap.push_back(static_cast<long long>(frontier[i]));
        }
        tracer_->record(op, a, b, snap);
    }

    void check(int u) const {
        if (u < 0 || u >= n_) throw std::out_of_range("ds::Graph 结点越界");
    }
};

// ---------------------------------------------------------------- 邻接矩阵（判边 O(1)，遍历接口对齐邻接表）

class MatrixGraph {
public:
    explicit MatrixGraph(int n, bool directed = false)
        : n_(n), directed_(directed), m_(make_m(n)) {}

    static std::vector<int> make_m(int n) {
        if (n <= 0) throw std::invalid_argument("ds::MatrixGraph 结点数必须为正");
        return std::vector<int>(static_cast<std::size_t>(n) * static_cast<std::size_t>(n), 0);
    }

    int n() const { return n_; }

    void add_edge(int u, int v, int weight = 1) {
        check(u);
        check(v);
        at(u, v) = weight;
        if (!directed_) at(v, u) = weight;
    }

    bool has_edge(int u, int v) const {
        check(u);
        check(v);
        return at(u, v) != 0;
    }

    void bfs(int start, std::vector<int>& dist, std::vector<int>& order) const {
        check(start);
        dist.assign(static_cast<std::size_t>(n_), -1);
        order.clear();
        std::vector<int> queue(static_cast<std::size_t>(n_));
        std::size_t head = 0, tail = 0;
        dist[static_cast<std::size_t>(start)] = 0;
        queue[tail++] = start;
        while (head < tail) {
            int u = queue[head++];
            order.push_back(u);
            for (int v = 0; v < n_; ++v) {
                if (has_edge(u, v) && dist[static_cast<std::size_t>(v)] < 0) {
                    dist[static_cast<std::size_t>(v)] = dist[static_cast<std::size_t>(u)] + 1;
                    queue[tail++] = v;
                }
            }
        }
    }

private:
    int n_;
    bool directed_;
    std::vector<int> m_;

    int& at(int u, int v) {
        return m_[static_cast<std::size_t>(u) * static_cast<std::size_t>(n_) +
                  static_cast<std::size_t>(v)];
    }
    int at(int u, int v) const {
        return m_[static_cast<std::size_t>(u) * static_cast<std::size_t>(n_) +
                  static_cast<std::size_t>(v)];
    }
    void check(int u) const {
        if (u < 0 || u >= n_) throw std::out_of_range("ds::MatrixGraph 结点越界");
    }
};

}  // namespace ds
