// include/isa.hpp —— 指令集与汇编器（B5 教学 CPU 的公共底座）
//
// 课程要点（数字设计与计算机原理 / 计组）：
//   - 指令 = 操作码 + 操作数编码；本实现用**结构体而不是位域**（教学优先，
//     但编码函数给出真实 32 位形态，可以对照 MIPS 的 OP/RS/RT/RD/SHAMT/FUNCT 划分）；
//   - 汇编器是**两遍**扫描：第一遍收集标签地址，第二遍把标签换成绝对地址——
//     这正是"分支偏移为什么在一遍扫描里算不对"的答案；
//   - r0 恒为零：汇编器与两个模型都必须把它当**硬约束**（写 r0 被丢弃）。
#pragma once

#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace b5 {

// ---------------------------------------------------------------- 指令
enum class Op {
    ADD, SUB, AND, OR, SLT, SLL, SRL,      // R 型
    ADDI, ANDI, ORI,                       // I 型算术
    LW, SW,                                // 访存
    BEQ, BNE, J,                           // 控制
    HALT                                   // 停机
};

struct Instr {
    Op op = Op::HALT;
    int rd = 0, rs = 0, rt = 0;
    int imm = 0;                           // I 型立即数 / 访存偏移
    int target = 0;                        // J 型绝对地址（标签）
    std::string label;                     // 反汇编时的可读标注
};

inline const char* op_name(Op op) {
    switch (op) {
        case Op::ADD: return "add";
        case Op::SUB: return "sub";
        case Op::AND: return "and";
        case Op::OR: return "or";
        case Op::SLT: return "slt";
        case Op::SLL: return "sll";
        case Op::SRL: return "srl";
        case Op::ADDI: return "addi";
        case Op::ANDI: return "andi";
        case Op::ORI: return "ori";
        case Op::LW: return "lw";
        case Op::SW: return "sw";
        case Op::BEQ: return "beq";
        case Op::BNE: return "bne";
        case Op::J: return "j";
        case Op::HALT: return "halt";
    }
    return "?";
}

// 32 位编码：R 型 (op=0, rs, rt, rd, shamt, funct)，I 型 (op, rs, rt, imm)，
// J 型 (op, target)。这里只用于打印与"同一指令两条路径编码相同"的断言。
inline uint32_t encode(const Instr& in) {
    auto r = [](int i) { return (uint32_t)(i & 0x1F); };
    switch (in.op) {
        case Op::ADD: return (r(in.rs) << 21) | (r(in.rt) << 16) | (r(in.rd) << 11) | 0x20;
        case Op::SUB: return (r(in.rs) << 21) | (r(in.rt) << 16) | (r(in.rd) << 11) | 0x22;
        case Op::AND: return (r(in.rs) << 21) | (r(in.rt) << 16) | (r(in.rd) << 11) | 0x24;
        case Op::OR:  return (r(in.rs) << 21) | (r(in.rt) << 16) | (r(in.rd) << 11) | 0x25;
        case Op::SLT: return (r(in.rs) << 21) | (r(in.rt) << 16) | (r(in.rd) << 11) | 0x2A;
        case Op::SLL: return (r(in.rt) << 16) | (r(in.rd) << 11) | (r(in.imm) << 6);
        case Op::SRL: return (r(in.rt) << 16) | (r(in.rd) << 11) | (r(in.imm) << 6) | 0x02;
        case Op::ADDI: return (0x08u << 26) | (r(in.rs) << 21) | (r(in.rt) << 16) |
                              (uint32_t)(in.imm & 0xFFFF);
        case Op::ANDI: return (0x0Cu << 26) | (r(in.rs) << 21) | (r(in.rt) << 16) |
                              (uint32_t)(in.imm & 0xFFFF);
        case Op::ORI:  return (0x0Du << 26) | (r(in.rs) << 21) | (r(in.rt) << 16) |
                              (uint32_t)(in.imm & 0xFFFF);
        case Op::LW:   return (0x23u << 26) | (r(in.rs) << 21) | (r(in.rt) << 16) |
                              (uint32_t)(in.imm & 0xFFFF);
        case Op::SW:   return (0x2Bu << 26) | (r(in.rs) << 21) | (r(in.rt) << 16) |
                              (uint32_t)(in.imm & 0xFFFF);
        case Op::BEQ:  return (0x04u << 26) | (r(in.rs) << 21) | (r(in.rt) << 16) |
                              (uint32_t)(in.imm & 0xFFFF);
        case Op::BNE:  return (0x05u << 26) | (r(in.rs) << 21) | (r(in.rt) << 16) |
                              (uint32_t)(in.imm & 0xFFFF);
        case Op::J:    return (0x02u << 26) | (uint32_t)(in.target & 0x03FFFFFF);
        case Op::HALT: return 0xFC000000u;      // 教学约定：halt 独占一个 opcode
    }
    return 0;
}

// ---------------------------------------------------------------- 寄存器与内存
struct RegFile {
    int32_t r[32] = {0};
    int writes = 0;                            // 累计写入次数（含写 r0 被丢弃的那次也要数）

    int32_t read(int i) const { return i == 0 ? 0 : r[i & 31]; }
    void write(int i, int32_t value) {
        ++writes;
        if (i == 0) return;                    // r0 恒零：写入被丢弃
        r[i & 31] = value;
    }
};

struct DataMem {
    std::vector<int32_t> words;
    int loads = 0, stores = 0;
    explicit DataMem(int n = 64) : words(n, 0) {}
    int32_t load(int addr) const {
        if (addr < 0 || addr + 1 > (int)words.size())
            throw std::runtime_error("数据地址越界（load）");
        return words[addr];
    }
    void store(int addr, int32_t v) {
        if (addr < 0 || addr + 1 > (int)words.size())
            throw std::runtime_error("数据地址越界（store）");
        words[addr] = v;
    }
};

struct Machine {
    RegFile regs;
    DataMem mem;
    int pc = 0;
    bool halted = false;
    int cycles = 0;
    std::vector<std::string> trace;            // 每周期一行（教学用，可打印）
    explicit Machine(int mem_words = 64) : mem(mem_words) {}
};

}  // namespace b5
