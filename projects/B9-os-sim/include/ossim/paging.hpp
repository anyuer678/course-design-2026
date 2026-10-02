// ossim/paging.hpp —— 页面置换：FIFO / LRU / Clock / OPT（含 Belady 异常）
//
// 课程要点：
//   - 缺页次数是唯一被断言的量；实现细节（用什么容器、怎么找牺牲页）不影响它；
//   - **LRU ≤ FIFO 不是定理**：两者互不支配（经典串下 LRU=10 > FIFO=9）。
//     能断言的只有 OPT ≤ 任何算法——测试里按这个来，第一版就断错在这里（README 坑 1）；
//   - Belady 异常：FIFO 加帧反而更多缺页（经典串 3 帧 9 次、4 帧 10 次）；
//   - LRU 与 OPT 有栈式性质：帧数增加缺页单调不增；FIFO 没有这条。
#pragma once

#include <algorithm>
#include <climits>
#include <deque>
#include <list>
#include <vector>

namespace ossim {

struct PagingResult {
    int faults = 0;
};

// 先进先出：牺牲最早进入的页。
inline PagingResult fifo(const std::vector<int>& refs, int frames) {
    PagingResult r;
    std::deque<int> q;
    for (int page : refs) {
        if (std::find(q.begin(), q.end(), page) != q.end()) continue;
        ++r.faults;
        if ((int)q.size() == frames) q.pop_front();
        q.push_back(page);
    }
    return r;
}

// 最近最少使用：命中的页搬到链表头，牺牲链表尾。
inline PagingResult lru(const std::vector<int>& refs, int frames) {
    PagingResult r;
    std::list<int> recency;                       // 头 = 最近使用
    for (int page : refs) {
        auto it = std::find(recency.begin(), recency.end(), page);
        if (it != recency.end()) {
            recency.erase(it);
            recency.push_front(page);
            continue;
        }
        ++r.faults;
        if ((int)recency.size() == frames) recency.pop_back();
        recency.push_front(page);
    }
    return r;
}

// Clock（第二次机会）：环形缓冲 + 引用位，指针扫过时给第二次机会。
inline PagingResult clock_sim(const std::vector<int>& refs, int frames) {
    PagingResult r;
    std::vector<int> pages(frames, -1);
    std::vector<bool> used(frames, false);
    int hand = 0, filled = 0;
    for (int page : refs) {
        bool hit = false;
        for (int i = 0; i < frames; ++i) {
            if (pages[i] == page) { used[i] = true; hit = true; break; }
        }
        if (hit) continue;
        ++r.faults;
        if (filled < frames) { pages[filled] = page; used[filled] = true; ++filled; continue; }
        while (used[hand]) { used[hand] = false; hand = (hand + 1) % frames; }
        pages[hand] = page;
        used[hand] = true;
        hand = (hand + 1) % frames;
    }
    return r;
}

// 最优：牺牲"下一次使用最晚"的页——需要看未来，只用于做下界参照。
inline PagingResult opt(const std::vector<int>& refs, int frames) {
    PagingResult r;
    std::vector<int> mem;
    for (std::size_t i = 0; i < refs.size(); ++i) {
        const int page = refs[i];
        if (std::find(mem.begin(), mem.end(), page) != mem.end()) continue;
        ++r.faults;
        if ((int)mem.size() < frames) { mem.push_back(page); continue; }
        int victim = 0, farthest = -1;
        for (int k = 0; k < frames; ++k) {
            int next_use = INT_MAX;
            for (std::size_t j = i + 1; j < refs.size(); ++j) {
                if (refs[j] == mem[k]) { next_use = (int)j; break; }
            }
            if (next_use > farthest) { farthest = next_use; victim = k; }
            if (farthest == INT_MAX) break;       // 谁都不再用：随便挑最先遇到的
        }
        mem[victim] = page;
    }
    return r;
}

}  // namespace ossim
