// ds/unionfind.hpp —— 并查集：路径压缩 + 按秩合并
//
// 课程要点：
//   - "谁和谁连在一起"用一棵**父指针森林**表示：find 追到根，根相同即连通；
//   - 两个优化都是"省未来的路"：按秩合并让树长矮（O(log n)），路径压缩把走过的路
//     直接改道指到根（近 O(1) 摊还）——`steps()` 数 find 走了多少步，演示里
//     压缩前后的步数对照就是从它量出来的；
//   - 正确性参照：测试用"随机图 BFS 算连通分量"与并查集对拍——两套完全独立的
//     连通性算法给出同一划分，才叫"对"（PLAN 一贯的对拍纪律）。
#pragma once

#include <cstddef>
#include <stdexcept>
#include <utility>
#include <vector>

namespace ds {

class UnionFind {
public:
    explicit UnionFind(std::size_t n) : parent_(n), rank_(n, 0) {
        for (std::size_t i = 0; i < n; ++i) parent_[i] = i;
    }

    std::size_t size() const { return parent_.size(); }

    // 找根（迭代版两趟：先追到根，再把一路上的结点直接挂到根）
    std::size_t find(std::size_t x) {
        if (x >= parent_.size()) throw std::out_of_range("ds::UnionFind::find");
        std::size_t root = x;
        while (parent_[root] != root) {
            root = parent_[root];
            ++steps_;
        }
        while (parent_[x] != root) {
            std::size_t nxt = parent_[x];
            parent_[x] = root;
            x = nxt;
        }
        return root;
    }

    // 合并两个集合；返回 false 表示本来就连通（无需合并）
    bool unite(std::size_t a, std::size_t b) {
        std::size_t ra = find(a);
        std::size_t rb = find(b);
        if (ra == rb) return false;
        if (rank_[ra] < rank_[rb]) std::swap(ra, rb);
        parent_[rb] = ra;                    // 矮树挂到高树上
        if (rank_[ra] == rank_[rb]) ++rank_[ra];
        --components_;
        return true;
    }

    bool connected(std::size_t a, std::size_t b) { return find(a) == find(b); }

    // 连通分量个数（初始 n，每次成功合并减一）
    std::size_t components() const { return components_; }

    std::size_t steps() const { return steps_; }         // find 走过的父指针步数
    void reset_counters() { steps_ = 0; }

private:
    std::vector<std::size_t> parent_;
    std::vector<unsigned> rank_;
    std::size_t components_ = parent_.size();
    std::size_t steps_ = 0;
};

}  // namespace ds
