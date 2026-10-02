// ossim/scheduler.hpp —— CPU 调度：FCFS / SJF / 优先级 / RR（含甘特图与指标）
//
// 课程要点：
//   - 非抢占（FCFS、SJF、优先级）与抢占（RR）的差别，最终都体现在"谁在什么时刻拿到 CPU"；
//   - 甘特图不是画着好看：把每一段时间片记下来，等待/周转指标才能被**逐段复算**；
//   - 等待时间 = 周转时间 − 突发时间（手算时最容易漏掉减 burst）；
//   - RR 的入队约定必须写死：**新到达的进程先入队，再轮到期的进程回队尾**。
//     顺序反过来，甘特图会完全不同（README 坑 2）。
#pragma once

#include <algorithm>
#include <deque>
#include <string>
#include <vector>

namespace ossim {

struct Proc {
    std::string name;
    int arrival;
    int burst;
    int priority;                  // 数字越小优先级越高
};

struct Gantt {
    std::string name;
    int start;
    int end;
};

struct SchedResult {
    std::vector<Gantt> gantt;
    double avg_waiting = 0.0;
    double avg_turnaround = 0.0;
};

// 教材手算例子：P1[0,7] P2[2,4] P3[4,1] P4[5,4]
// FCFS 完成 7,11,12,16；SJF 等待 0,6,3,7；RR(q=2) 甘特图 9 段。
inline std::vector<Proc> sample_procs() {
    return {{"P1", 0, 7, 3}, {"P2", 2, 4, 1}, {"P3", 4, 1, 4}, {"P4", 5, 4, 2}};
}

namespace detail {

// 把指标写回**同一个** SchedResult：第一版这里返回了新对象，甘特图被悄悄丢掉，
// 测试索引空 vector 触发 UB（表现成死循环）。甘特图和指标必须待在一个结构里。
inline void finish(SchedResult& r, const std::vector<Proc>& ps,
                   const std::vector<int>& completion) {
    double w = 0.0, t = 0.0;
    for (std::size_t i = 0; i < ps.size(); ++i) {
        const int turnaround = completion[i] - ps[i].arrival;
        t += turnaround;
        w += turnaround - ps[i].burst;
    }
    r.avg_waiting = w / (double)ps.size();
    r.avg_turnaround = t / (double)ps.size();
}

// 下一个"还没跑完"的进程最早什么时候到达——用于 CPU 空闲时把时间推进过去。
// 第一版只看全局最早到达，选中已完成的进程会让循环原地打转（空闲即死循环）。
inline int next_arrival(const std::vector<Proc>& ps, const std::vector<bool>& used) {
    int best = -1;
    for (std::size_t i = 0; i < ps.size(); ++i) {
        if (used[i]) continue;
        if (best < 0 || ps[i].arrival < best) best = ps[i].arrival;
    }
    return best;
}

}  // namespace detail

// 先来先服务：按到达顺序排队，跑完一个换下一个。
inline SchedResult fcfs(const std::vector<Proc>& ps) {
    std::vector<Proc> q = ps;
    std::stable_sort(q.begin(), q.end(), [](const Proc& a, const Proc& b) {
        return a.arrival < b.arrival;           // 同刻到达保持输入顺序（稳定）
    });
    SchedResult r;
    int now = 0;
    std::vector<int> done(q.size());
    for (std::size_t i = 0; i < q.size(); ++i) {
        now = std::max(now, q[i].arrival);
        r.gantt.push_back({q[i].name, now, now + q[i].burst});
        now += q[i].burst;
        for (std::size_t k = 0; k < ps.size(); ++k)
            if (ps[k].name == q[i].name) done[k] = now;
    }
    detail::finish(r, ps, done);
    return r;
}

// 最短作业优先（非抢占）：每次从**已到达**的进程里挑突发最短的。
inline SchedResult sjf(const std::vector<Proc>& ps) {
    std::vector<bool> used(ps.size(), false);
    std::vector<int> completion(ps.size(), 0);
    SchedResult r;
    int now = 0, finished = 0;
    while (finished < (int)ps.size()) {
        int pick = -1;
        for (std::size_t i = 0; i < ps.size(); ++i) {
            if (used[i] || ps[i].arrival > now) continue;
            if (pick < 0 || ps[i].burst < ps[pick].burst) pick = (int)i;   // 平局取先到达
        }
        if (pick < 0) { now = detail::next_arrival(ps, used); continue; }
        now = std::max(now, ps[pick].arrival);
        r.gantt.push_back({ps[pick].name, now, now + ps[pick].burst});
        now += ps[pick].burst;
        completion[pick] = now;
        used[pick] = true;
        ++finished;
    }
    detail::finish(r, ps, completion);
    return r;
}

// 优先级（非抢占，数字小 = 优先级高）。
inline SchedResult priority_sched(const std::vector<Proc>& ps) {
    std::vector<bool> used(ps.size(), false);
    std::vector<int> completion(ps.size(), 0);
    SchedResult r;
    int now = 0, finished = 0;
    while (finished < (int)ps.size()) {
        int pick = -1;
        for (std::size_t i = 0; i < ps.size(); ++i) {
            if (used[i] || ps[i].arrival > now) continue;
            if (pick < 0 || ps[i].priority < ps[pick].priority) pick = (int)i;
        }
        if (pick < 0) { now = detail::next_arrival(ps, used); continue; }
        now = std::max(now, ps[pick].arrival);
        r.gantt.push_back({ps[pick].name, now, now + ps[pick].burst});
        now += ps[pick].burst;
        completion[pick] = now;
        used[pick] = true;
        ++finished;
    }
    detail::finish(r, ps, completion);
    return r;
}

// 时间片轮转。约定（README 坑 2）：**新到达的先入队，再到期的回队尾**。
// q 足够大时退化为 FCFS——测试里有一条专门钉住这个极限行为。
inline SchedResult rr(const std::vector<Proc>& ps, int q) {
    std::vector<int> remain(ps.size(), 0);
    std::vector<int> completion(ps.size(), 0);
    for (std::size_t i = 0; i < ps.size(); ++i) remain[i] = ps[i].burst;

    std::vector<int> order(ps.size());
    for (std::size_t i = 0; i < ps.size(); ++i) order[i] = (int)i;
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
        return ps[a].arrival < ps[b].arrival;
    });

    SchedResult r;
    std::deque<int> ready;
    std::size_t next = 0;
    int now = ps.empty() ? 0 : ps[order[0]].arrival;
    int finished = 0;
    while (finished < (int)ps.size()) {
        while (next < order.size() && ps[order[next]].arrival <= now) {
            ready.push_back(order[next]);       // 新到达先入队
            ++next;
        }
        if (ready.empty()) { now = ps[order[next]].arrival; continue; }
        const int cur = ready.front();
        ready.pop_front();
        const int run = std::min(q, remain[cur]);
        const int start = now;
        now += run;
        remain[cur] -= run;
        r.gantt.push_back({ps[cur].name, start, now});
        while (next < order.size() && ps[order[next]].arrival <= now) {
            ready.push_back(order[next]);       // 片内到达的进程先于"回来"的旧进程
            ++next;
        }
        if (remain[cur] == 0) {
            completion[cur] = now;
            ++finished;
        } else {
            ready.push_back(cur);               // 用完了才回队尾
        }
    }
    detail::finish(r, ps, completion);
    return r;
}

}  // namespace ossim
