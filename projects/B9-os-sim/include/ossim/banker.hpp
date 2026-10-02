// ossim/banker.hpp —— 银行家算法：安全序列 + 请求三步判定 + 失败回滚
//
// 课程要点：
//   - Need = Max − Allocation（本实现把 need 直接存下来，因为它正是判定用的那张表）；
//   - 安全性检查：反复找"需求 ≤ Work"的进程，能找全就是安全序列，找不全就不安全；
//   - 请求三步：① 请求 ≤ Need？② 请求 ≤ Available？③ **试探性分配后还安全吗**？
//     前两步只需比较，第三步必须"先分配、再检查、不安全就回滚"——
//     回滚不完整（漏还 Available 或漏恢复 Need）是这类作业里最常见的错。
#pragma once

#include <stdexcept>
#include <vector>

namespace ossim {

class Banker {
public:
    // 参数顺序按"教材给数据的方式"来：(进程数, 资源数, Available, **Max**, **Allocation**)。
    // Need 由 Max − Allocation 现算——第一版把 Max/Allocation 的顺序写反了，
    // 于是 Need 变成了 Allocation，P1 的合法请求被当成"超过 Need"拒绝。
    // 参数一律带 `_in` 后缀：**成员初始化列表里的同名名字先解析到成员**，
    // `alloc(std::move(alloc))` 会变成"用自己（此时还是空的）move 自己"，
    // 参数反而没用上——测试里表现为 `alloc[i]` 越界断言。这类坑编译器不报错。
    Banker(int n_proc, int n_res, std::vector<int> avail_in,
           std::vector<std::vector<int>> max_in, std::vector<std::vector<int>> alloc_in)
        : n(n_proc), m(n_res), available(std::move(avail_in)),
          alloc(std::move(alloc_in)), need(std::move(max_in)) {
        for (int i = 0; i < n; ++i)
            for (int j = 0; j < m; ++j) need[i][j] -= alloc[i][j];
    }

    // 逐分量 ≤：安全序列复验与三步判定都用它，只此一份实现。
    static bool le(const std::vector<int>& a, const std::vector<int>& b) {
        for (std::size_t i = 0; i < a.size(); ++i)
            if (a[i] > b[i]) return false;
        return true;
    }

    // 安全性检查：返回 (是否安全, 一个安全序列)。不修改任何状态。
    std::pair<bool, std::vector<int>> safety() const {
        std::vector<int> work = available;
        std::vector<bool> done(n, false);
        std::vector<int> seq;
        for (int round = 0; round < n; ++round) {
            bool progressed = false;
            for (int i = 0; i < n; ++i) {
                if (done[i] || !le(need[i], work)) continue;
                for (int j = 0; j < m; ++j) work[j] += alloc[i][j];
                done[i] = true;
                seq.push_back(i);
                progressed = true;
            }
            if (!progressed) break;
        }
        if ((int)seq.size() == n) return {true, seq};
        return {false, {}};
    }

    // 请求 (进程 i，向量 req)：批准则返回**分配后仍然成立**的安全序列；
    // 任何一种拒绝都抛 std::runtime_error，且状态必须回到调用前（回滚）。
    std::vector<int> request(int i, const std::vector<int> req) {
        if (!le(req, need[i]))
            throw std::runtime_error("请求超过 Need：不合法，直接拒绝");
        if (!le(req, available))
            throw std::runtime_error("资源不足：此刻无法满足，进程等待");
        // 试探性分配
        for (int j = 0; j < m; ++j) {
            available[j] -= req[j];
            alloc[i][j] += req[j];
            need[i][j] -= req[j];
        }
        auto [safe, seq] = safety();
        if (!safe) {
            for (int j = 0; j < m; ++j) {          // 回滚：三个数组都要还回去
                available[j] += req[j];
                alloc[i][j] -= req[j];
                need[i][j] += req[j];
            }
            throw std::runtime_error("分配后系统不安全：拒绝并回滚");
        }
        return seq;
    }

    int n, m;
    std::vector<int> available;
    std::vector<std::vector<int>> alloc;
    std::vector<std::vector<int>> need;
};

}  // namespace ossim
