// ds/heap.hpp —— 二叉堆：上浮/下沉、线性建堆、堆排序
//
// 课程要点：
//   - 堆只承诺"**父不劣于子**"（弱序）：数组形态 `heap[i]` 的孩子是 `2i+1 / 2i+2`，
//     没有指针、没有空隙——这就是"用数组表示完全二叉树"；
//   - 建堆有两种：逐个插入（n 次上浮，O(n log n)）与**从底向上线性建堆**
//     （n/2 次下沉，O(n)）——演示里把两者的比较次数实测量出来对照；
//   - 堆排序 = 建堆 + n 次"取顶放尾"；`verify()` 是整树检查（每对父子都比一遍），
//     测试拿它在每次操作后盯住不变量；
//   - 比较器约定：`Cmp(a, b) == true` 表示 a 应排在 b 前面（父的位置）。
//     默认 `std::less` → 小顶堆；要接 std::priority_queue（大顶堆）传 `std::greater`。
#pragma once

#include <cstddef>
#include <functional>
#include <stdexcept>
#include <utility>
#include <vector>

#include "ds/trace.hpp"

namespace ds {

template <class T, class Cmp = std::less<T>>
class Heap {
public:
    Heap() = default;
    explicit Heap(Cmp cmp) : cmp_(cmp) {}

    // 挂上只读观察口后，push/pop/build 与每次交换都会记事件（默认 nullptr = 零影响）
    void set_tracer(Tracer* tracer) { tracer_ = tracer; }

    bool empty() const { return data_.size() == 0; }
    std::size_t size() const { return data_.size(); }

    void push(const T& v) {
        data_.push_back(v);
        sift_up(data_.size() - 1);
        trace("push", static_cast<long long>(data_.size() - 1), -1);
    }

    void pop() {
        if (empty()) throw std::out_of_range("ds::Heap::pop 空堆");
        std::swap(data_[0], data_[data_.size() - 1]);
        data_.pop_back();
        if (!empty()) sift_down(0);
        trace("pop", 0, -1);
    }

    const T& top() const {
        if (empty()) throw std::out_of_range("ds::Heap::top 空堆");
        return data_[0];
    }

    // 线性建堆：从最后一个非叶结点往前下沉。**不清空已有内容**，是对现有数组整理成堆
    void build(const std::vector<T>& items) {
        data_.clear();
        for (const T& v : items) data_.push_back(v);
        if (data_.size() >= 2) {
            for (std::size_t i = data_.size() / 2; i-- > 0;) sift_down(i);
        }
        trace("build", -1, -1);
    }

    // 整树检查：每对父子都必须满足堆序（测试在每次操作后调用）
    bool verify() const {
        for (std::size_t i = 1; i < data_.size(); ++i) {
            if (cmp_(data_[i], data_[(i - 1) / 2])) return false;
        }
        return true;
    }

    std::size_t comparisons() const { return comparisons_; }
    std::size_t swaps() const { return swaps_; }
    void reset_counters() {
        comparisons_ = 0;
        swaps_ = 0;
    }

private:
    std::vector<T> data_;
    Cmp cmp_{};
    std::size_t comparisons_ = 0;
    std::size_t swaps_ = 0;
    Tracer* tracer_ = nullptr;

    void trace(const char* op, long long a, long long b) {
        if (tracer_ == nullptr) return;
        std::vector<long long> snap;
        snap.reserve(data_.size());
        for (const T& v : data_) snap.push_back(static_cast<long long>(v));
        tracer_->record(op, a, b, snap);
    }

    void sift_up(std::size_t i) {
        while (i > 0) {
            std::size_t parent = (i - 1) / 2;
            ++comparisons_;
            if (!cmp_(data_[i], data_[parent])) break;
            std::swap(data_[i], data_[parent]);
            ++swaps_;
            trace("swap", static_cast<long long>(i), static_cast<long long>(parent));
            i = parent;
        }
    }

    void sift_down(std::size_t i) {
        while (true) {
            std::size_t left = 2 * i + 1;
            std::size_t right = 2 * i + 2;
            std::size_t best = i;
            if (left < data_.size()) {
                ++comparisons_;
                if (cmp_(data_[left], data_[best])) best = left;
            }
            if (right < data_.size()) {
                ++comparisons_;
                if (cmp_(data_[right], data_[best])) best = right;
            }
            if (best == i) break;
            std::swap(data_[i], data_[best]);
            ++swaps_;
            trace("swap", static_cast<long long>(i), static_cast<long long>(best));
            i = best;
        }
    }
};

// 堆排序：建堆 + 逐个取顶；ascending=true 用默认小顶，false 传 greater
template <class T>
void heap_sort(std::vector<T>& v, bool ascending = true) {
    if (ascending) {
        Heap<T> h;
        h.build(v);
        for (std::size_t i = 0; i < v.size(); ++i) {
            v[i] = h.top();
            h.pop();
        }
    } else {
        Heap<T, std::greater<T>> h;
        h.build(v);
        for (std::size_t i = 0; i < v.size(); ++i) {
            v[i] = h.top();
            h.pop();
        }
    }
}

}  // namespace ds
