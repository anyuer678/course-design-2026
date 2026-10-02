#pragma once
// ============================================================================
// ossim/fat.hpp —— FAT 文件系统模拟（内存版）
// 对应课程内容：FAT 表（链接分配的"显式"形式）、簇分配、目录项、
//               文件增长/截断、外部碎片与块复用
//
// 结构：
//   blocks_  ：物理磁盘，每块固定 4 字节负载（小到能看清楚链）
//   fat_     ：FAT 表，fat_[b] = 下一块；EOF 表示结尾；FREE 表示空闲
//   目录     ：名字 -> {首块, 大小(字节)}
// 读写都沿 FAT 链走——这正是"FAT 表 = 链表指针数组"的含义。
// ============================================================================
#include <algorithm>
#include <array>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace ossim {

class FatFs {
public:
    static constexpr int BLOCK_SIZE = 4;
    static constexpr uint32_t FREE = 0xFFFFFFFF;
    static constexpr uint32_t EOF_MARK = 0xFFFFFFFE;

    explicit FatFs(int total_blocks) : blocks_(total_blocks), fat_(total_blocks, FREE) {}

    struct DirEntry {
        uint32_t start = EOF_MARK;
        uint32_t size = 0;               // 字节
    };

    // 写文件（覆盖写语义：先建新链、再释放旧链，失败时旧内容必须完好）
    void write(const std::string& name, const std::string& content) {
        uint32_t size = (uint32_t)content.size();
        uint32_t first = EOF_MARK;
        if (size > 0) first = alloc_chain((size + BLOCK_SIZE - 1) / BLOCK_SIZE);
        auto old = dir_.find(name);
        if (old != dir_.end()) free_chain(old->second.start);
        dir_[name] = {first, size};
        uint32_t cur = first;                     // 沿链填充数据
        for (uint32_t off = 0; off < size; off += BLOCK_SIZE) {
            for (int i = 0; i < BLOCK_SIZE; ++i) {
                size_t idx = off + i;
                blocks_[cur][i] = idx < content.size() ? content[idx] : '\0';
            }
            cur = fat_[cur];
        }
    }

    // 读文件：沿 FAT 链收集整链内容
    std::string read(const std::string& name) const {
        auto it = dir_.find(name);
        if (it == dir_.end()) throw std::runtime_error("文件不存在: " + name);
        std::string out;
        uint32_t cur = it->second.start;
        uint32_t remaining = it->second.size;
        while (remaining > 0) {
            if (cur == EOF_MARK || cur == FREE)
                throw std::runtime_error("FAT 链断裂（文件系统损坏）");
            uint32_t take = std::min<uint32_t>(BLOCK_SIZE, remaining);
            out.append(blocks_[cur].data(), take);
            remaining -= take;
            cur = fat_[cur];
        }
        return out;
    }

    // 追加：找到链尾，能塞进末块残缺空间就先塞，其余续接新链
    void append(const std::string& name, const std::string& extra) {
        auto it = dir_.find(name);
        if (it == dir_.end()) return write(name, extra);
        if (it->second.start == EOF_MARK) return write(name, extra);   // 空文件没有链尾可找
        uint32_t cur = it->second.start;
        while (fat_[cur] != EOF_MARK) cur = fat_[cur];
        uint32_t used_last = it->second.size % BLOCK_SIZE;
        size_t off = 0;
        if (used_last != 0) {                     // 末块还有空位
            for (uint32_t i = used_last; i < BLOCK_SIZE && off < extra.size(); ++i, ++off)
                blocks_[cur][i] = extra[off];
        }
        if (off < extra.size()) {
            uint32_t need = (uint32_t(extra.size()) - off + BLOCK_SIZE - 1) / BLOCK_SIZE;
            uint32_t first_new = alloc_chain(need);   // 失败时旧链与文件大小都不变
            fat_[cur] = first_new;                // 新链接到旧链尾
            cur = first_new;
            for (; off < extra.size(); off += BLOCK_SIZE) {
                for (int i = 0; i < BLOCK_SIZE; ++i) {
                    size_t idx = off + i;
                    blocks_[cur][i] = idx < extra.size() ? extra[idx] : '\0';
                }
                cur = fat_[cur];
            }
        }
        it->second.size += (uint32_t)extra.size();
    }

    // 删除：整条链归还空闲表
    void remove(const std::string& name) {
        auto it = dir_.find(name);
        if (it == dir_.end()) throw std::runtime_error("文件不存在: " + name);
        free_chain(it->second.start);
        dir_.erase(it);
    }

    bool exists(const std::string& name) const { return dir_.count(name) != 0; }
    int free_blocks() const {
        int c = 0;
        for (uint32_t f : fat_) if (f == FREE) ++c;
        return c;
    }
    int total_blocks() const { return (int)fat_.size(); }
    // 文件占用的块号序列（看"链"长什么样：连续还是跳着走）
    std::vector<uint32_t> chain_of(const std::string& name) const {
        auto it = dir_.find(name);
        if (it == dir_.end()) return {};
        std::vector<uint32_t> chain;
        uint32_t cur = it->second.start;
        while (cur != EOF_MARK && cur != FREE) {
            chain.push_back(cur);
            cur = fat_[cur];
        }
        return chain;
    }

private:
    uint32_t alloc_one() {
        for (uint32_t b = 0; b < fat_.size(); ++b)
            if (fat_[b] == FREE) {
                fat_[b] = EOF_MARK;            // 立刻占位，否则同一块会被分给两个文件
                return b;
            }
        throw std::runtime_error("磁盘已满");
    }
    // 分配 n 块并串成链（返回首块，尾块标 EOF）；中途失败则整条新链回滚
    uint32_t alloc_chain(uint32_t n) {
        uint32_t first = alloc_one();
        uint32_t cur = first;
        try {
            for (uint32_t i = 1; i < n; ++i) {
                uint32_t nxt = alloc_one();
                fat_[cur] = nxt;
                cur = nxt;
            }
        } catch (...) {
            free_chain(first);                    // 半条链不能留在盘上，否则块永久泄漏
            throw;
        }
        fat_[cur] = EOF_MARK;
        return first;
    }
    void free_chain(uint32_t start) {
        uint32_t cur = start;
        while (cur != EOF_MARK && cur != FREE) {
            uint32_t nxt = fat_[cur];
            fat_[cur] = FREE;
            cur = nxt;
        }
    }

    std::vector<std::array<char, BLOCK_SIZE>> blocks_;
    std::vector<uint32_t> fat_;
    std::map<std::string, DirEntry> dir_;
};

} // namespace ossim
