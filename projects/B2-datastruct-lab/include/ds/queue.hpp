// ds/queue.hpp —— 队列：循环数组 + 链式两种实现
//
// 课程要点：
//   - 循环队列的命门是**空/满的区分**：头尾指针相同既可能是空也可能是满。
//     本实现用 `size_` 记账（第三种办法；另两种是"留一个空位"与"加标记位"，README 有对比）；
//   - 取模回绕（`% cap_`）让"队尾跑过数组末尾"自动回到开头——演示里会把 head/tail
//     的轨迹打出来，看"绕圈"发生在哪几步；
//   - 链式队列 = 单链表 + 尾指针：入队尾插（O(1)）、出队头删（O(1)），没有容量上限，
//     代价是每个元素一份结点分配——两种实现互相对拍（同样的操作序列，同样的出队序列）。
#pragma once

#include <cstddef>
#include <new>
#include <stdexcept>
#include <utility>

#include "ds/linkedlist.hpp"

namespace ds {

template <class T>
class ArrayQueue {
public:
    explicit ArrayQueue(std::size_t capacity)
        : cap_(capacity ? capacity : 1),
          data_(static_cast<T*>(::operator new(cap_ * sizeof(T)))) {}

    ArrayQueue(const ArrayQueue&) = delete;             // 教学版：不拷贝（内含裸缓冲）
    ArrayQueue& operator=(const ArrayQueue&) = delete;

    ~ArrayQueue() {
        clear();
        ::operator delete(data_);
    }

    bool empty() const { return size_ == 0; }
    bool full() const { return size_ == cap_; }
    std::size_t size() const { return size_; }
    std::size_t capacity() const { return cap_; }

    std::size_t head() const { return head_; }
    std::size_t tail() const { return tail_; }

    void push(const T& v) {
        if (full()) throw std::out_of_range("ds::ArrayQueue::push 队满");
        new (data_ + tail_) T(v);             // 原始存储上构造
        tail_ = (tail_ + 1) % cap_;           // 回绕
        ++size_;
    }

    void pop() {
        if (empty()) throw std::out_of_range("ds::ArrayQueue::pop 队空");
        data_[head_].~T();
        head_ = (head_ + 1) % cap_;
        --size_;
    }

    T& front() {
        if (empty()) throw std::out_of_range("ds::ArrayQueue::front 队空");
        return data_[head_];
    }
    const T& front() const {
        if (empty()) throw std::out_of_range("ds::ArrayQueue::front 队空");
        return data_[head_];
    }

    void clear() {
        while (!empty()) pop();
        head_ = tail_ = size_ = 0;
    }

private:
    std::size_t cap_;
    T* data_;
    std::size_t head_ = 0;
    std::size_t tail_ = 0;
    std::size_t size_ = 0;
};

// 链式队列：复用 LinkedList（尾插/头删都是 O(1)）
template <class T>
class LinkedQueue {
public:
    bool empty() const { return list_.empty(); }
    std::size_t size() const { return list_.size(); }

    void push(const T& v) { list_.push_back(v); }
    void pop() {
        if (empty()) throw std::out_of_range("ds::LinkedQueue::pop 队空");
        list_.erase_at(0);
    }
    T& front() {
        if (empty()) throw std::out_of_range("ds::LinkedQueue::front 队空");
        return list_.at(0);
    }
    const T& front() const {
        if (empty()) throw std::out_of_range("ds::LinkedQueue::front 队空");
        return list_.at(0);
    }
    void clear() { list_.clear(); }

private:
    LinkedList<T> list_;
};

}  // namespace ds
