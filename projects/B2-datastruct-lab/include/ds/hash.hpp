// ds/hash.hpp —— 哈希表：链地址法 与 开放定址（线性探测 + 墓碑）
//
// 课程要点：
//   - 哈希函数用除留余数法 `h(k) = k % m`（m 固定、教学版不做再哈希）；冲突处理是两半场对照：
//     链地址法把冲突挂成链，线性探测往后面找空位——`probes()` 把"找了多少格"记成账，
//     负载因子越高，两边的探测数怎么涨，用实测数字说话（演示第 4 段）；
//   - 线性探测的删除要用**墓碑**（tombstone）：直接清空会把探测链切断，后面的键就找不到了——
//     这是开放定址法最经典的坑，测试里专门有"删了中间键再查后面的键"；
//   - 两种实现的**对外行为必须一致**（同一键集合 → 同样的 contains 结果），
//     测试里用同一随机操作序列对拍它们，再和 std::unordered_set 三方对照。
#pragma once

#include <cstddef>
#include <stdexcept>
#include <vector>

#include "ds/linkedlist.hpp"

namespace ds {

class HashChaining {
public:
    explicit HashChaining(std::size_t buckets) : buckets_(buckets ? buckets : 1) {}

    // 返回 true = 新插入；false = 已存在（教学版不存重复键）
    bool insert(int key) {
        LinkedList<int>& chain = bucket(key);
        if (chain.find(key) != LinkedList<int>::npos) return false;
        chain.push_back(key);
        ++size_;
        return true;
    }

    bool contains(int key) const {
        return bucket(key).find(key) != LinkedList<int>::npos;
    }

    bool erase(int key) {
        LinkedList<int>& chain = bucket(key);
        std::size_t before = chain.size();
        chain.remove_all(key);
        std::size_t removed = before - chain.size();
        size_ -= removed;
        return removed > 0;
    }

    std::size_t size() const { return size_; }
    std::size_t buckets() const { return buckets_.size(); }

    // 探测量 = 各条链上"比较了几个键"的总和（与 HashLinear 的"看了几个槽"同口径）
    std::size_t probes() const {
        std::size_t total = 0;
        for (const LinkedList<int>& chain : buckets_) total += chain.comparisons();
        return total;
    }
    void reset_counters() {
        for (LinkedList<int>& chain : buckets_) chain.reset_counters();
    }

    // 最长链长度（冲突严重程度的直观读数）
    std::size_t longest_chain() const {
        std::size_t longest = 0;
        for (const LinkedList<int>& chain : buckets_) {
            std::size_t len = chain.size();
            if (len > longest) longest = len;
        }
        return longest;
    }

private:
    std::vector<LinkedList<int>> buckets_;
    std::size_t size_ = 0;

    std::size_t hash(int key) const {
        // 负数键也要落进 [0, m)
        long long h = static_cast<long long>(key) % static_cast<long long>(buckets_.size());
        if (h < 0) h += static_cast<long long>(buckets_.size());
        return static_cast<std::size_t>(h);
    }

    LinkedList<int>& bucket(int key) { return buckets_[hash(key)]; }
    const LinkedList<int>& bucket(int key) const { return buckets_[hash(key)]; }
};

class HashLinear {
public:
    enum class Slot : unsigned char { Empty, Used, Tombstone };

    explicit HashLinear(std::size_t capacity) : cap_(capacity ? capacity : 1) {
        slots_.assign(cap_, Slot::Empty);
        keys_.assign(cap_, 0);
    }

    bool insert(int key) {
        if (size_ * 4 >= cap_ * 3) {
            throw std::length_error("ds::HashLinear::insert 负载已达 3/4 上限（教学版固定容量）");
        }
        std::size_t idx = probe_for(key, /*stop_at_tombstone=*/true);
        if (slots_[idx] == Slot::Used) return false;
        if (slots_[idx] == Slot::Empty) {
            keys_[idx] = key;
            slots_[idx] = Slot::Used;
            ++size_;
            return true;
        }
        // 墓碑位：插进去（占掉墓碑，用/墓碑计数不变）
        keys_[idx] = key;
        slots_[idx] = Slot::Used;
        ++size_;
        return true;
    }

    bool contains(int key) const {
        std::size_t idx = probe_for(key, /*stop_at_tombstone=*/false);
        return slots_[idx] == Slot::Used && keys_[idx] == key;
    }

    bool erase(int key) {
        std::size_t idx = probe_for(key, /*stop_at_tombstone=*/false);
        if (slots_[idx] != Slot::Used || keys_[idx] != key) return false;
        slots_[idx] = Slot::Tombstone;         // 墓碑：链条照走，键已失效
        --size_;
        return true;
    }

    std::size_t size() const { return size_; }
    std::size_t capacity() const { return cap_; }
    std::size_t probes() const { return probes_; }
    void reset_counters() { probes_ = 0; }

    std::size_t tombstones() const {
        std::size_t n = 0;
        for (Slot s : slots_) {
            if (s == Slot::Tombstone) ++n;
        }
        return n;
    }

private:
    std::size_t cap_;
    std::vector<Slot> slots_;
    std::vector<int> keys_;
    std::size_t size_ = 0;
    mutable std::size_t probes_ = 0;

    std::size_t hash(int key) const {
        long long h = static_cast<long long>(key) % static_cast<long long>(cap_);
        if (h < 0) h += static_cast<long long>(cap_);
        return static_cast<std::size_t>(h);
    }

    // 从 h(k) 起线性探测；stop_at_tombstone=true 时遇到墓碑就停（插入可以复用墓碑位），
    // false 时越过墓碑继续（查找/删除必须走完整条被墓碑打断的链）
    std::size_t probe_for(int key, bool stop_at_tombstone) const {
        std::size_t idx = hash(key);
        while (true) {
            ++probes_;
            Slot s = slots_[idx];
            if (s == Slot::Empty) return idx;
            if (s == Slot::Used) {
                if (keys_[idx] == key) return idx;
            } else if (stop_at_tombstone) {
                return idx;
            }
            idx = (idx + 1) % cap_;
        }
    }
};

}  // namespace ds
