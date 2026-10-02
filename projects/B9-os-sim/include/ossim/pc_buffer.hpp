// ossim/pc_buffer.hpp —— 生产者-消费者：mutex + condition_variable 的有界缓冲区
//
// 课程要点：
//   - 两个条件变量（非空/非满）而不是一个：用同一个会在"叫醒对方"和"叫醒同类"之间
//     互相误伤，典型症状是唤醒丢失或惊群后又一次集体睡下；
//   - 水位（high watermark）用来证明容量从未越界——**断言它 ≤ 容量**比"看着没崩"强；
//   - 验证"不丢不重"不能只比总和：{1,1} 与 {0,2} 总和相同。测试把全部消息排序后
//     逐条比对（README 坑 7），同时抓住丢失、重复和错值。
#pragma once

#include <condition_variable>
#include <deque>
#include <mutex>
#include <utility>

namespace ossim {

template <class T>
class BoundedBuffer {
public:
    explicit BoundedBuffer(int capacity) : cap_(capacity) {}

    void put(T value) {
        std::unique_lock<std::mutex> lock(mu_);
        not_full_.wait(lock, [this] { return (int)buf_.size() < cap_; });
        buf_.push_back(std::move(value));
        if ((int)buf_.size() > watermark_) watermark_ = (int)buf_.size();
        ++total_put_;
        not_empty_.notify_one();
    }

    T get() {
        std::unique_lock<std::mutex> lock(mu_);
        not_empty_.wait(lock, [this] { return !buf_.empty(); });
        T value = std::move(buf_.front());
        buf_.pop_front();
        ++total_get_;
        not_full_.notify_one();
        return value;
    }

    long total_put() const { std::lock_guard<std::mutex> lock(mu_); return total_put_; }
    long total_get() const { std::lock_guard<std::mutex> lock(mu_); return total_get_; }
    int high_watermark() const { std::lock_guard<std::mutex> lock(mu_); return watermark_; }
    int size() const { std::lock_guard<std::mutex> lock(mu_); return (int)buf_.size(); }

private:
    const int cap_;
    mutable std::mutex mu_;
    std::condition_variable not_full_, not_empty_;
    std::deque<T> buf_;
    long total_put_ = 0, total_get_ = 0;
    int watermark_ = 0;
};

}  // namespace ossim
