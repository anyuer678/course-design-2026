// ds/linkedlist.hpp —— 单链表：结点指针 + 头尾指针，把"指针跳了多少次"记成账
//
// 课程要点：
//   - 链表的**代价在"找"**：头插 O(1) 只动几个指针，但按下标/按值定位要顺着 next 一路跳——
//     `hops()` 数和顺序表的 `moves()` 数是同一个实验的两半（"搬"与"跳"的对照）；
//   - 尾指针让 push_back 也变成 O(1)（不然每次尾插都要先走到尾巴）；
//   - 反转是纯指针题：三个指针（prev/cur/next）一轮走完，不许申请第二个容器；
//   - 析构要一个一个 delete——节点的所有权在链表手里（RAII 的"链表版"）。
#pragma once

#include <cstddef>
#include <stdexcept>
#include <utility>

namespace ds {

template <class T>
class LinkedList {
    struct Node {
        T value;
        Node* next;
        explicit Node(const T& v) : value(v), next(nullptr) {}
    };

public:
    static constexpr std::size_t npos = static_cast<std::size_t>(-1);

    LinkedList() = default;

    LinkedList(const LinkedList& other) { copy_from(other); }

    LinkedList& operator=(const LinkedList& other) {
        if (this != &other) {
            LinkedList tmp(other);
            swap(tmp);
        }
        return *this;
    }

    LinkedList(LinkedList&& other) noexcept
        : head_(other.head_), tail_(other.tail_), size_(other.size_) {
        other.head_ = other.tail_ = nullptr;
        other.size_ = 0;
    }

    LinkedList& operator=(LinkedList&& other) noexcept {
        if (this != &other) {
            release();
            head_ = other.head_;
            tail_ = other.tail_;
            size_ = other.size_;
            other.head_ = other.tail_ = nullptr;
            other.size_ = 0;
        }
        return *this;
    }

    ~LinkedList() { release(); }

    bool empty() const { return size_ == 0; }
    std::size_t size() const { return size_; }

    void push_front(const T& v) {
        Node* n = new Node(v);
        n->next = head_;
        head_ = n;
        if (!tail_) tail_ = n;
        ++size_;
        ++links_;
    }

    void push_back(const T& v) {
        Node* n = new Node(v);
        if (tail_) {
            tail_->next = n;
        } else {
            head_ = n;
        }
        tail_ = n;
        ++size_;
        ++links_;
    }

    // 在下标 pos 处插入（pos ∈ [0, size]）：要走 pos 步找到前驱
    void insert_at(std::size_t pos, const T& v) {
        if (pos > size_) throw std::out_of_range("ds::LinkedList::insert_at");
        if (pos == 0) {
            push_front(v);
            return;
        }
        Node* prev = head_;
        for (std::size_t i = 0; i + 1 < pos; ++i) {
            prev = prev->next;
            ++hops_;
        }
        Node* n = new Node(v);
        n->next = prev->next;
        prev->next = n;
        if (tail_ == prev) tail_ = n;
        ++size_;
        ++links_;
    }

    void erase_at(std::size_t pos) {
        if (pos >= size_) throw std::out_of_range("ds::LinkedList::erase_at");
        if (pos == 0) {
            Node* old = head_;
            head_ = old->next;
            if (tail_ == old) tail_ = nullptr;
            delete old;
            --size_;
            ++links_;
            return;
        }
        Node* prev = head_;
        for (std::size_t i = 0; i + 1 < pos; ++i) {
            prev = prev->next;
            ++hops_;
        }
        Node* old = prev->next;
        prev->next = old->next;
        if (tail_ == old) tail_ = prev;
        delete old;
        --size_;
        ++links_;
    }

    T& at(std::size_t pos) {
        if (pos >= size_) throw std::out_of_range("ds::LinkedList::at");
        Node* cur = head_;
        for (std::size_t i = 0; i < pos; ++i) {
            cur = cur->next;
            ++hops_;
        }
        return cur->value;
    }
    const T& at(std::size_t pos) const {
        if (pos >= size_) throw std::out_of_range("ds::LinkedList::at");
        const Node* cur = head_;
        for (std::size_t i = 0; i < pos; ++i) {
            cur = cur->next;
            ++hops_;
        }
        return cur->value;
    }

    // 按值查找：返回下标或 npos
    std::size_t find(const T& v) const {
        const Node* cur = head_;
        std::size_t i = 0;
        while (cur) {
            ++comparisons_;
            if (cur->value == v) return i;
            cur = cur->next;
            ++hops_;
            ++i;
        }
        return npos;
    }

    // 原地反转：三个指针走一轮，不申请第二个容器
    void reverse() {
        Node* prev = nullptr;
        Node* cur = head_;
        tail_ = head_;
        while (cur) {
            Node* nxt = cur->next;
            cur->next = prev;
            prev = cur;
            cur = nxt;
            ++links_;
        }
        head_ = prev;
    }

    // 摘除所有等于 v 的结点，返回摘除个数
    std::size_t remove_all(const T& v) {
        std::size_t removed = 0;
        Node** link = &head_;                 // 指向"指向当前结点的指针"
        tail_ = nullptr;
        Node* last = nullptr;
        while (*link) {
            Node* cur = *link;
            ++comparisons_;
            if (cur->value == v) {
                *link = cur->next;
                delete cur;
                ++removed;
                ++links_;
            } else {
                last = cur;
                link = &cur->next;
            }
        }
        tail_ = last;
        size_ -= removed;
        return removed;
    }

    void clear() {
        release();
    }

    std::size_t hops() const { return hops_; }        // 指针跳步数
    std::size_t links() const { return links_; }      // 改链次数
    std::size_t comparisons() const { return comparisons_; }
    void reset_counters() {
        hops_ = 0;
        links_ = 0;
        comparisons_ = 0;
    }

    void swap(LinkedList& other) noexcept {
        std::swap(head_, other.head_);
        std::swap(tail_, other.tail_);
        std::swap(size_, other.size_);
    }

private:
    Node* head_ = nullptr;
    Node* tail_ = nullptr;
    std::size_t size_ = 0;
    mutable std::size_t hops_ = 0;
    mutable std::size_t links_ = 0;
    mutable std::size_t comparisons_ = 0;

    void copy_from(const LinkedList& other) {
        for (const Node* cur = other.head_; cur; cur = cur->next) push_back(cur->value);
    }

    void release() {
        Node* cur = head_;
        while (cur) {
            Node* nxt = cur->next;
            delete cur;
            cur = nxt;
        }
        head_ = tail_ = nullptr;
        size_ = 0;
    }
};

}  // namespace ds
