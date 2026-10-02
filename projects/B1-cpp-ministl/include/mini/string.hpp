// mini/string.hpp —— 堆上字符串：按长度记账，永远以 '\0' 收尾
//
// 课程要点：
//   - 字符串 = "字符缓冲 + 长度"；`c_str()` 是**视图**不是数据，谁写谁负责；
//   - 不变量：`size_` 说的是真实字节数（可以含 '\0'），`data_[size_] == '\0'`
//     只是给 C 接口看的"门面"；
//   - rule of five 与 vector 同款：拷贝深挖、移动偷缓冲；
//   - `s += s`（自追加）是经典坑：一旦扩容换缓冲，源指针指向旧缓冲就成了悬垂——
//     本实现遇到自追加先做临时副本，把这条从"靠运气"变成"靠代码"。
#pragma once

#include <cstddef>
#include <cstring>
#include <new>
#include <stdexcept>
#include <utility>

namespace mini {

class string {
public:
    static constexpr std::size_t npos = static_cast<std::size_t>(-1);

    string() = default;

    string(const char* s) {
        if (s) {
            std::size_t n = std::strlen(s);
            ensure(n);
            std::memcpy(data_, s, n);
            size_ = n;
            if (data_) data_[size_] = '\0';   // 空串不分配缓冲，c_str() 走 "" 字面量分支
        }
    }

    string(const char* s, std::size_t n) {   // 允许内嵌 '\0'
        ensure(n);
        if (n > 0) std::memcpy(data_, s, n);
        size_ = n;
        if (data_) data_[size_] = '\0';
    }

    string(const string& other) : string(other.data_, other.size_) {}

    string(string&& other) noexcept
        : data_(other.data_), size_(other.size_), cap_(other.cap_) {
        other.data_ = nullptr;
        other.size_ = 0;
        other.cap_ = 0;
    }

    string& operator=(const string& other) {
        if (this != &other) {
            string tmp(other);
            swap(tmp);
        }
        return *this;
    }

    string& operator=(string&& other) noexcept {
        if (this != &other) {
            release();
            data_ = other.data_;
            size_ = other.size_;
            cap_ = other.cap_;
            other.data_ = nullptr;
            other.size_ = 0;
            other.cap_ = 0;
        }
        return *this;
    }

    ~string() { release(); }

    // ---------------------------------------------------------------- 视图
    const char* c_str() const { return data_ ? data_ : ""; }
    const char* data() const { return data_; }
    std::size_t size() const { return size_; }
    std::size_t length() const { return size_; }
    bool empty() const { return size_ == 0; }
    std::size_t capacity() const { return cap_; }

    char& operator[](std::size_t i) { return data_[i]; }
    const char& operator[](std::size_t i) const { return data_[i]; }

    char& at(std::size_t i) {
        if (i >= size_) throw std::out_of_range("mini::string::at");
        return data_[i];
    }
    const char& at(std::size_t i) const {
        if (i >= size_) throw std::out_of_range("mini::string::at");
        return data_[i];
    }

    void clear() {
        size_ = 0;
        if (data_) data_[0] = '\0';
    }

    void reserve(std::size_t n) {
        if (n > cap_) grow(n);
    }

    // ---------------------------------------------------------------- 修改
    string& append(const string& other) {
        if (this == &other) {           // 自追加：先拷一份，再按普通路径走
            string copy(other);
            return append(copy);
        }
        if (other.size_ == 0) return *this;
        ensure(size_ + other.size_);
        std::memcpy(data_ + size_, other.data_, other.size_);
        size_ += other.size_;
        data_[size_] = '\0';
        return *this;
    }

    string& append(const char* s) {
        // 指针指向自己的缓冲（典型：s += s.c_str()）时先换算成偏移——
        // 扩容会把旧缓冲释放，直接 memcpy 就是悬垂读
        if (data_ && s >= data_ && s <= data_ + size_) {
            std::size_t off = static_cast<std::size_t>(s - data_);
            return append(string(data_ + off, size_ - off));
        }
        std::size_t n = std::strlen(s);
        if (n == 0) return *this;
        ensure(size_ + n);
        std::memcpy(data_ + size_, s, n);
        size_ += n;
        data_[size_] = '\0';
        return *this;
    }

    string& append(char c) {
        // 不能借道 append(const char*)：那是 strlen 语义，'\0' 会被当成空串丢掉
        ensure(size_ + 1);
        data_[size_] = c;
        ++size_;
        data_[size_] = '\0';
        return *this;
    }

    string& operator+=(const string& other) { return append(other); }
    string& operator+=(const char* s) { return append(s); }
    string& operator+=(char c) { return append(c); }

    void swap(string& other) noexcept {
        std::swap(data_, other.data_);
        std::swap(size_, other.size_);
        std::swap(cap_, other.cap_);
    }

    // ---------------------------------------------------------------- 查找与比较
    std::size_t find(char c, std::size_t from = 0) const {
        for (std::size_t i = from; i < size_; ++i) {
            if (data_[i] == c) return i;
        }
        return npos;
    }

    std::size_t find(const char* needle) const {
        std::size_t n = std::strlen(needle);
        if (n == 0) return 0;
        if (n > size_) return npos;
        for (std::size_t i = 0; i + n <= size_; ++i) {
            if (std::memcmp(data_ + i, needle, n) == 0) return i;
        }
        return npos;
    }

    string substr(std::size_t pos, std::size_t n = npos) const {
        if (pos > size_) throw std::out_of_range("mini::string::substr");
        std::size_t len = (n == npos || n > size_ - pos) ? size_ - pos : n;
        if (len == 0) return string();
        return string(data_ + pos, len);
    }

    friend bool operator==(const string& a, const string& b) {
        if (a.size_ != b.size_) return false;
        return a.size_ == 0 || std::memcmp(a.data_, b.data_, a.size_) == 0;
    }
    friend bool operator!=(const string& a, const string& b) { return !(a == b); }

    friend bool operator<(const string& a, const string& b) {
        std::size_t n = a.size_ < b.size_ ? a.size_ : b.size_;
        int c = n == 0 ? 0 : std::memcmp(a.data_, b.data_, n);
        if (c != 0) return c < 0;
        return a.size_ < b.size_;       // 前缀关系：短的更小
    }
    friend bool operator>(const string& a, const string& b) { return b < a; }
    friend bool operator<=(const string& a, const string& b) { return !(b < a); }
    friend bool operator>=(const string& a, const string& b) { return !(a < b); }

    friend string operator+(string a, const string& b) { return a.append(b); }

private:
    char* data_ = nullptr;
    std::size_t size_ = 0;
    std::size_t cap_ = 0;               // 已分配可存字符数（不含结尾 '\0'）

    static char* allocate(std::size_t n) {
        return static_cast<char*>(::operator new(n + 1));
    }

    void ensure(std::size_t need) {
        if (need <= cap_) return;
        grow(need);
    }

    void grow(std::size_t need) {
        std::size_t newcap = cap_ ? cap_ : 16;
        while (newcap < need) newcap *= 2;
        char* buf = allocate(newcap);
        if (size_ > 0) std::memcpy(buf, data_, size_);
        buf[size_] = '\0';
        ::operator delete(data_);
        data_ = buf;
        cap_ = newcap;
    }

    void release() {
        ::operator delete(data_);
        data_ = nullptr;
        size_ = 0;
        cap_ = 0;
    }
};

inline void swap(string& a, string& b) noexcept {
    a.swap(b);
}

}  // namespace mini
