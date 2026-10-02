// ds/seqlist.hpp —— 顺序表：动态数组 + 按位插入/删除（数据结构的第一个 ADT）
//
// 课程要点：
//   - 顺序表的**代价在"搬"**：按下标寻址 O(1)，但在头部插入/删除要挪动其余全部元素——
//     本类把"搬了多少步"记成可读的计数（`moves()`），复杂度对照的演示全靠它；
//   - 扩容（×2）本身也要搬元素：计数把这些搬动一并记入，所以实验前先 `reserve`
//     把扩容排除掉，量到的才是纯插入/删除的移动（演示里明确注明口径）；
//   - 查找是**线性扫描**：`find` 把比较次数记入 `comparisons()`——"顺序表查找 O(n)"
//     这句话是从这个计数里量出来的，不是背出来的。
#pragma once

#include <cstddef>
#include <stdexcept>
#include <utility>

namespace ds {

template <class T>
class SeqList {
public:
    static constexpr std::size_t npos = static_cast<std::size_t>(-1);

    SeqList() = default;

    SeqList(const SeqList& other) { copy_from(other); }

    SeqList& operator=(const SeqList& other) {
        if (this != &other) {
            SeqList tmp(other);
            swap(tmp);
        }
        return *this;
    }

    ~SeqList() { release(); }

    bool empty() const { return size_ == 0; }
    std::size_t size() const { return size_; }
    std::size_t capacity() const { return cap_; }

    T& at(std::size_t i) {
        if (i >= size_) throw std::out_of_range("ds::SeqList::at");
        return data_[i];
    }
    const T& at(std::size_t i) const {
        if (i >= size_) throw std::out_of_range("ds::SeqList::at");
        return data_[i];
    }
    T& operator[](std::size_t i) { return data_[i]; }
    const T& operator[](std::size_t i) const { return data_[i]; }

    void reserve(std::size_t n) {
        if (n > cap_) grow(n);
    }

    void clear() {
        for (std::size_t i = 0; i < size_; ++i) data_[i].~T();
        size_ = 0;
    }

    void push_back(const T& v) {
        if (size_ == cap_) grow(size_ + 1);
        new (data_ + size_) T(v);
        ++size_;
    }

    // 在下标 pos 处插入（pos ∈ [0, size]）：后面的元素整体后移一步
    void insert(std::size_t pos, const T& v) {
        if (pos > size_) throw std::out_of_range("ds::SeqList::insert");
        if (size_ == cap_) grow(size_ + 1);
        if (pos == size_) {                  // 尾部（含空表）：就是追加，不必搬
            new (data_ + size_) T(v);
            ++size_;
            return;
        }
        new (data_ + size_) T(data_[size_ - 1]);
        ++moves_;                            // 末尾元素先搬到新位
        for (std::size_t i = size_ - 1; i > pos; --i) {
            data_[i] = data_[i - 1];          // 每挪一步记一次
            ++moves_;
        }
        data_[pos] = v;
        ++size_;
    }

    // 删除下标 pos：后面的元素整体前移一步
    void erase(std::size_t pos) {
        if (pos >= size_) throw std::out_of_range("ds::SeqList::erase");
        for (std::size_t i = pos; i + 1 < size_; ++i) {
            data_[i] = data_[i + 1];
            ++moves_;
        }
        --size_;
        data_[size_].~T();
    }

    // 线性查找：返回下标或 npos；比较次数进计数
    std::size_t find(const T& v) const {
        for (std::size_t i = 0; i < size_; ++i) {
            ++comparisons_;
            if (data_[i] == v) return i;
        }
        return npos;
    }

    std::size_t moves() const { return moves_; }
    std::size_t comparisons() const { return comparisons_; }
    void reset_counters() {
        moves_ = 0;
        comparisons_ = 0;
    }

    void swap(SeqList& other) noexcept {
        std::swap(data_, other.data_);
        std::swap(size_, other.size_);
        std::swap(cap_, other.cap_);
    }

private:
    T* data_ = nullptr;
    std::size_t size_ = 0;
    std::size_t cap_ = 0;
    mutable std::size_t moves_ = 0;          // 元素搬动步数（插入/删除的移位 + 扩容拷贝）
    mutable std::size_t comparisons_ = 0;    // find 的比较次数

    void copy_from(const SeqList& other) {
        reserve(other.size_);
        for (std::size_t i = 0; i < other.size_; ++i) push_back(other.data_[i]);
    }

    static T* allocate(std::size_t n) {
        return n ? static_cast<T*>(::operator new(n * sizeof(T))) : nullptr;
    }

    void grow(std::size_t need) {
        std::size_t newcap = cap_ ? cap_ : 4;
        while (newcap < need) newcap *= 2;
        T* buf = allocate(newcap);
        for (std::size_t i = 0; i < size_; ++i) {
            new (buf + i) T(data_[i]);
            ++moves_;                        // 扩容的搬动也记（口径见文件头）
        }
        for (std::size_t i = 0; i < size_; ++i) data_[i].~T();
        ::operator delete(data_);
        data_ = buf;
        cap_ = newcap;
    }

    void release() {
        clear();
        ::operator delete(data_);
        data_ = nullptr;
        cap_ = 0;
    }
};

}  // namespace ds
