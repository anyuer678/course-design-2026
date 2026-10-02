// mini/list.hpp —— 双向链表：带哨兵结点，迭代器是"指向结点的游标"
//
// 课程要点：
//   - 链表的核心不是"结点里有指针"，是**插入/删除时其他迭代器不失效**：
//     所以 list 的迭代器不能是下标，必须是结点指针；
//   - 哨兵（环形头结点）让"头插/尾插/空表"三种情形**同一段代码**处理，
//     代价是迭代器里要能认出哨兵 = end()；
//   - rule of five 照旧：拷贝 = 逐个复制结点；移动 = 把环**整体剪接**过来（O(1)）；
//   - 本实现只做双向迭代器（forward_iterator 的更弱表亲：没有随机访问，`it + n` 不存在）。
#pragma once

#include <cstddef>
#include <iterator>
#include <utility>

namespace mini {

template <class T>
class list {
    struct Node {
        Node* prev;
        Node* next;
        T value;

        template <class... Args>
        explicit Node(Args&&... args) : prev(nullptr), next(nullptr),
                                        value(std::forward<Args>(args)...) {}
    };

public:
    class iterator {
    public:
        using value_type = T;
        using difference_type = std::ptrdiff_t;
        using pointer = T*;
        using reference = T&;
        using iterator_category = std::bidirectional_iterator_tag;

        iterator() = default;
        explicit iterator(Node* node) : node_(node) {}

        T& operator*() const { return node_->value; }
        T* operator->() const { return &node_->value; }

        iterator& operator++() { node_ = node_->next; return *this; }
        iterator operator++(int) { iterator t = *this; ++*this; return t; }
        iterator& operator--() { node_ = node_->prev; return *this; }
        iterator operator--(int) { iterator t = *this; --*this; return t; }

        bool operator==(const iterator& o) const { return node_ == o.node_; }
        bool operator!=(const iterator& o) const { return node_ != o.node_; }

        Node* node() const { return node_; }

    private:
        Node* node_ = nullptr;
        friend class list;
    };

    class const_iterator {
    public:
        using value_type = T;
        using difference_type = std::ptrdiff_t;
        using pointer = const T*;
        using reference = const T&;
        using iterator_category = std::bidirectional_iterator_tag;

        const_iterator() = default;
        explicit const_iterator(const Node* node) : node_(node) {}
        const_iterator(const iterator& it) : node_(it.node()) {}   // iterator → const_iterator

        const T& operator*() const { return node_->value; }
        const T* operator->() const { return &node_->value; }

        const_iterator& operator++() { node_ = node_->next; return *this; }
        const_iterator operator++(int) { const_iterator t = *this; ++*this; return t; }
        const_iterator& operator--() { node_ = node_->prev; return *this; }
        const_iterator operator--(int) { const_iterator t = *this; --*this; return t; }

        bool operator==(const const_iterator& o) const { return node_ == o.node_; }
        bool operator!=(const const_iterator& o) const { return node_ != o.node_; }

    private:
        const Node* node_ = nullptr;
    };

    list() {
        root_.prev = &root_;
        root_.next = &root_;
    }

    list(const list& other) : list() {
        for (const T& v : other) push_back(v);
    }

    list(list&& other) noexcept : list() {
        adopt(other);
    }

    list& operator=(const list& other) {
        if (this != &other) {
            list tmp(other);
            swap(tmp);
        }
        return *this;
    }

    list& operator=(list&& other) noexcept {
        if (this != &other) {
            clear();
            adopt(other);
        }
        return *this;
    }

    ~list() { clear(); }

    // ---------------------------------------------------------------- 迭代器
    iterator begin() { return iterator(root_.next); }
    iterator end() { return iterator(&root_); }
    const_iterator begin() const { return const_iterator(root_.next); }
    const_iterator end() const { return const_iterator(&root_); }

    // ---------------------------------------------------------------- 容量
    bool empty() const { return size_ == 0; }
    std::size_t size() const { return size_; }

    T& front() { return root_.next->value; }
    const T& front() const { return root_.next->value; }
    T& back() { return root_.prev->value; }
    const T& back() const { return root_.prev->value; }

    // ---------------------------------------------------------------- 修改器
    void push_front(const T& v) { insert(begin(), v); }
    void push_front(T&& v) { insert(begin(), std::move(v)); }
    void push_back(const T& v) { insert(end(), v); }
    void push_back(T&& v) { insert(end(), std::move(v)); }

    template <class... Args>
    T& emplace_front(Args&&... args) {
        iterator it = insert(begin(), T(std::forward<Args>(args)...));
        return *it;
    }

    template <class... Args>
    T& emplace_back(Args&&... args) {
        iterator it = insert(end(), T(std::forward<Args>(args)...));
        return *it;
    }

    void pop_front() { erase(begin()); }
    void pop_back() { erase(iterator(root_.prev)); }

    iterator insert(iterator pos, const T& v) {
        Node* cur = pos.node();
        Node* n = new Node(v);
        n->prev = cur->prev;
        n->next = cur;
        cur->prev->next = n;
        cur->prev = n;
        ++size_;
        return iterator(n);
    }

    iterator insert(iterator pos, T&& v) {
        Node* cur = pos.node();
        Node* n = new Node(std::move(v));
        n->prev = cur->prev;
        n->next = cur;
        cur->prev->next = n;
        cur->prev = n;
        ++size_;
        return iterator(n);
    }

    iterator erase(iterator pos) {
        Node* n = pos.node();
        Node* nxt = n->next;
        n->prev->next = n->next;
        n->next->prev = n->prev;
        delete n;
        --size_;
        return iterator(nxt);
    }

    void clear() {
        Node* cur = root_.next;
        while (cur != &root_) {
            Node* nxt = cur->next;
            delete cur;
            cur = nxt;
        }
        root_.next = &root_;
        root_.prev = &root_;
        size_ = 0;
    }

    void swap(list& other) noexcept {
        // 哨兵不能对调（环内指针指向各自的哨兵），用三次移动整体剪接，各自 O(1)
        list tmp(std::move(other));
        other = std::move(*this);
        *this = std::move(tmp);
    }

private:
    Node root_;                 // 哨兵：root_.next 是首元素，root_.prev 是尾元素
    std::size_t size_ = 0;

    void adopt(list& other) {
        // 把 other 的整环剪到自己的哨兵上（O(1)），other 变成空表
        if (other.size_ == 0) return;
        root_.next = other.root_.next;
        root_.prev = other.root_.prev;
        root_.next->prev = &root_;
        root_.prev->next = &root_;
        size_ = other.size_;
        other.root_.next = &other.root_;
        other.root_.prev = &other.root_;
        other.size_ = 0;
    }
};

}  // namespace mini
