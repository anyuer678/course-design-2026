// ds/trace.hpp —— 只读操作轨迹观察口（默认关闭，为 B33 可视化导出事件流）
//
// 设计（为什么放在 B2 而不是 B33 里再造一套"可追踪的堆/图"）：
//   - 观察口挂在结构本体上，事件天然与实现同步；B33 只负责"导出 + 画"，不会漂移成
//     第二套算法（本仓库的复用纪律）；
//   - **默认关闭、行为不变**：`set_tracer(nullptr)` 或不设时 `record()` 直接返回，
//     现有测试/演示的输出与计数一个字节都不受影响（挂上后可重跑原测试自证）；
//   - 事件粒度是"**动画需要的粒度**"：每次交换/访问记一条，state 是**事件后的快照**
//     （堆数组内容 / 队列或栈内容）——回放器拿它就能逐帧重建画面；
//   - 快照按 `long long` 记录：教学导出用（T 需可静态转换为 long long，实际用 int）。
#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace ds {

struct TraceEvent {
    std::string op;                 // "push"/"pop"/"swap"/"build"/"visit"
    long long a = -1;               // 主下标或结点号
    long long b = -1;               // 副下标（swap 的另一端 / 距离值）
    std::vector<long long> state;   // 事件后的快照
};

class Tracer {
public:
    void enable() { enabled_ = true; }
    bool enabled() const { return enabled_; }

    void record(const std::string& op, long long a, long long b,
                const std::vector<long long>& state) {
        if (!enabled_) return;      // 默认关闭：零行为影响
        events.push_back(TraceEvent{op, a, b, state});
    }

    void clear() { events.clear(); }

    std::vector<TraceEvent> events;
    std::size_t size() const { return events.size(); }

private:
    bool enabled_ = false;
};

}  // namespace ds
