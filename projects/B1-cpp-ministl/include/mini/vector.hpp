// mini/vector.hpp —— 动态数组：迭代器是裸指针，RAII 管住缓冲区
//
// 课程要点（程序设计基础 C++）：
//   - 三个指针就够描述一个 vector：`data_ / size_ / cap_`。容量增长取 ×2 摊还 O(1)，
//     "增了多少倍"是**实现自由**而不是语义，但 amortized 常数必须说清；
//   - **RAII**：构造拿到的内存，析构一定还；拷贝 = 深拷贝（各自一份），
//     移动 = 偷走对方的缓冲并把对方置空——五个特殊成员函数（rule of five）一个不少；
//   - 迭代器就是 `T*`，`insert/erase` 之后**旧迭代器可能失效**（增长时换缓冲）；
//     本实现用"下标"在内部调整，所以外部拿到的失效迭代器不会被静默使用——由调用者负责；
//   - 异常安全只承诺**基本保证**（抛异常不泄漏），不承诺强保证（成长中途失败会保留原值，
//     但 insert 的多步搬移中途失败可能留下合法但未定义的内容）——这是明说的范围边界。
#pragma once

#include <cstddef>
#include <initializer_list>
#include <new>
#include <stdexcept>
#include <utility>

namespace mini {

template <class T>
class vector {
public:
    using value_type = T;
    using size_type = std::size_t;
    using iterator = T*;
    using const_iterator = const T*;

    vector() = default;

    vector(std::initializer_list<T> init) {
        reserve(init.size());
        for (const T& v : init) push_back(v);
    }

    vector(const vector& other) {
        reserve(other.size_);
        for (size_type i = 0; i < other.size_; ++i) push_back(other.data_[i]);
    }

    vector(vector&& other) noexcept
        : data_(other.data_), size_(other.size_), cap_(other.cap_) {
        other.data_ = nullptr;
        other.size_ = 0;
        other.cap_ = 0;
    }

    vector& operator=(const vector& other) {
        if (this != &other) {
            vector tmp(other);      // 先做副本：拷贝中途失败不破坏 *this（转手再换）
            swap(tmp);
        }
        return *this;
    }

    vector& operator=(vector&& other) noexcept {
        if (this != &other) {
            destroy_all();
            ::operator delete(data_);
            data_ = other.data_;
            size_ = other.size_;
            cap_ = other.cap_;
            other.data_ = nullptr;
            other.size_ = 0;
            other.cap_ = 0;
        }
        return *this;
    }

    ~vector() { release(); }

    // ---------------------------------------------------------------- 元素访问
    T& operator[](size_type i) { return data_[i]; }
    const T& operator[](size_type i) const { return data_[i]; }

    T& at(size_type i) {
        if (i >= size_) throw std::out_of_range("mini::vector::at");
        return data_[i];
    }
    const T& at(size_type i) const {
        if (i >= size_) throw std::out_of_range("mini::vector::at");
        return data_[i];
    }

    T& front() { return data_[0]; }
    const T& front() const { return data_[0]; }
    T& back() { return data_[size_ - 1]; }
    const T& back() const { return data_[size_ - 1]; }
    T* data() { return data_; }
    const T* data() const { return data_; }

    // ---------------------------------------------------------------- 迭代器
    iterator begin() { return data_; }
    iterator end() { return data_ + size_; }
    const_iterator begin() const { return data_; }
    const_iterator end() const { return data_ + size_; }
    const_iterator cbegin() const { return data_; }
    const_iterator cend() const { return data_ + size_; }

    // ---------------------------------------------------------------- 容量
    bool empty() const { return size_ == 0; }
    size_type size() const { return size_; }
    size_type capacity() const { return cap_; }

    void reserve(size_type n) {
        if (n > cap_) grow(n);
    }

    void clear() {
        destroy_all();
        size_ = 0;
    }

    void resize(size_type n) {
        if (n < size_) {
            for (size_type i = n; i < size_; ++i) data_[i].~T();
            size_ = n;
        } else {
            reserve(n);
            for (size_type i = size_; i < n; ++i) new (data_ + i) T();
            size_ = n;
        }
    }

    void resize(size_type n, const T& fill) {
        if (n < size_) {
            for (size_type i = n; i < size_; ++i) data_[i].~T();
            size_ = n;
        } else {
            reserve(n);
            for (size_type i = size_; i < n; ++i) new (data_ + i) T(fill);
            size_ = n;
        }
    }

    // ---------------------------------------------------------------- 修改器
    void push_back(const T& v) { emplace_back(v); }
    void push_back(T&& v) { emplace_back(std::move(v)); }

    template <class... Args>
    T& emplace_back(Args&&... args) {
        if (size_ == cap_) grow(size_ + 1);
        new (data_ + size_) T(std::forward<Args>(args)...);
        ++size_;
        return data_[size_ - 1];
    }

    void pop_back() {
        --size_;
        data_[size_].~T();
    }

    iterator insert(iterator pos, const T& v) {
        size_type idx = static_cast<size_type>(pos - data_);
        if (size_ == cap_) grow(size_ + 1);
        if (idx == size_) {
            new (data_ + size_) T(v);
            ++size_;
            return data_ + idx;
        }
        new (data_ + size_) T(std::move_if_noexcept(data_[size_ - 1]));
        for (size_type i = size_ - 1; i > idx; --i) {
            data_[i] = std::move_if_noexcept(data_[i - 1]);
        }
        data_[idx] = v;
        ++size_;
        return data_ + idx;
    }

    iterator erase(iterator pos) {
        size_type idx = static_cast<size_type>(pos - data_);
        for (size_type i = idx; i + 1 < size_; ++i) {
            data_[i] = std::move_if_noexcept(data_[i + 1]);
        }
        --size_;
        data_[size_].~T();
        return data_ + idx;
    }

    void swap(vector& other) noexcept {
        std::swap(data_, other.data_);
        std::swap(size_, other.size_);
        std::swap(cap_, other.cap_);
    }

private:
    T* data_ = nullptr;
    size_type size_ = 0;
    size_type cap_ = 0;

    static T* allocate(size_type n) {
        return n ? static_cast<T*>(::operator new(n * sizeof(T))) : nullptr;
    }

    void grow(size_type need) {
        size_type newcap = cap_ ? cap_ : 4;
        while (newcap < need) newcap *= 2;
        T* buf = allocate(newcap);
        size_type moved = 0;
        try {
            // move_if_noexcept：T 的移动可能抛异常时退回拷贝，搬移失败旧缓冲仍完好
            for (; moved < size_; ++moved) {
                new (buf + moved) T(std::move_if_noexcept(data_[moved]));
            }
        } catch (...) {
            for (size_type i = 0; i < moved; ++i) buf[i].~T();
            ::operator delete(buf);
            throw;
        }
        destroy_all();
        ::operator delete(data_);
        data_ = buf;
        cap_ = newcap;
    }

    void destroy_all() {
        for (size_type i = 0; i < size_; ++i) data_[i].~T();
    }

    void release() {
        destroy_all();
        ::operator delete(data_);
        data_ = nullptr;
        size_ = 0;
        cap_ = 0;
    }
};

template <class T>
void swap(vector<T>& a, vector<T>& b) noexcept {
    a.swap(b);
}

}  // namespace mini
