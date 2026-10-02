// include/asm.hpp —— 两遍扫描的汇编器（把 programs/*.asm 变成指令表）
//
// 语法（与 programs/bubble.asm 一致）：
//     # 注释
//     label:
//        addi r1, r0, 5        # R 型与 I 型都用 rN 写法，立即数可负
//        lw   r3, 0(r2)        # 访存：偏移(基址)
//        sw   r3, 4(r2)
//        beq  r1, r2, loop     # 分支目标写**标签**
//        j    end
//        halt
//
// 为什么必须两遍：第一遍只登记"标签 → 指令下标"，第二遍才能把标签换成地址。
// 一遍扫描时前向分支（跳到还没读到的标签）根本算不出来——这是汇编器的经典第一课。
#pragma once

#include <cctype>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "isa.hpp"

namespace b5 {

inline std::string strip_comment(const std::string& line) {
    std::string out;
    for (char ch : line) {
        if (ch == '#') break;
        out.push_back(ch);
    }
    return out;
}

inline std::string trim(const std::string& s) {
    std::size_t a = 0, b = s.size();
    while (a < b && std::isspace((unsigned char)s[a])) ++a;
    while (b > a && std::isspace((unsigned char)s[b - 1])) --b;
    return s.substr(a, b - a);
}

// 把 "r12," / "r3" / "0(r2)" / "label" 里的寄存器号取出来
inline int parse_reg(const std::string& token) {
    std::string t = trim(token);
    if (t.empty() || (t[0] != 'r' && t[0] != 'R'))
        throw std::runtime_error("不是寄存器：'" + t + "'");
    int value = std::stoi(t.substr(1));
    if (value < 0 || value > 31)
        throw std::runtime_error("寄存器编号越界：r" + std::to_string(value));
    return value;
}

struct Assembled {
    std::vector<Instr> program;
    std::map<std::string, int> labels;
};

inline Assembled assemble(const std::string& source) {
    Assembled out;
    // ---- 第一遍：拆行、登记标签
    std::vector<std::string> lines;
    std::istringstream stream(source);
    std::string raw;
    while (std::getline(stream, raw)) {
        std::string line = trim(strip_comment(raw));
        if (line.empty()) continue;
        // 一行里可能有 "label: 指令"
        std::size_t colon = line.find(':');
        if (colon != std::string::npos) {
            std::string label = trim(line.substr(0, colon));
            if (label.empty() || label.find(' ') != std::string::npos)
                throw std::runtime_error("非法标签：'" + label + "'");
            out.labels[label] = (int)lines.size();
            line = trim(line.substr(colon + 1));
        }
        if (!line.empty()) lines.push_back(line);
    }
    // ---- 第二遍：把每条指令解析成 Instr，标签换成绝对地址
    for (const std::string& line : lines) {
        std::istringstream ls(line);
        std::string mnemonic;
        ls >> mnemonic;
        std::vector<std::string> args;
        std::string token;
        while (std::getline(ls, token, ',')) args.push_back(trim(token));
        // 每个指令分支各自校验操作数个数——**halt 本来就没有操作数**，
        // 在分派之前做全局"必须至少一个操作数"的检查会把它误伤（实测过）。

        Instr in;
        auto num = [&](const std::string& text) {
            try { return std::stoi(trim(text)); }
            catch (...) { throw std::runtime_error("不是立即数：'" + trim(text) + "'"); }
        };
        auto label_addr = [&](const std::string& text) {
            auto it = out.labels.find(trim(text));
            if (it == out.labels.end())
                throw std::runtime_error("未定义的标签：'" + trim(text) + "'");
            return it->second;
        };
        // "0(r2)" → 偏移 0、基址 r2
        auto parse_mem = [&](const std::string& text, Instr& target) {
            std::string t = trim(text);
            std::size_t open = t.find('(');
            if (open == std::string::npos || t.back() != ')')
                throw std::runtime_error("访存操作数应形如 0(r2)：'" + t + "'");
            target.imm = std::stoi(trim(t.substr(0, open)));
            target.rs = parse_reg(t.substr(open + 1, t.size() - open - 2));
        };

        if (mnemonic == "add" || mnemonic == "sub" || mnemonic == "and" ||
            mnemonic == "or" || mnemonic == "slt") {
            if (args.size() != 3) throw std::runtime_error("R 型需要 3 个操作数：" + line);
            in.op = mnemonic == "add" ? Op::ADD : mnemonic == "sub" ? Op::SUB :
                    mnemonic == "and" ? Op::AND : mnemonic == "or" ? Op::OR : Op::SLT;
            in.rd = parse_reg(args[0]);
            in.rs = parse_reg(args[1]);
            in.rt = parse_reg(args[2]);
        } else if (mnemonic == "sll" || mnemonic == "srl") {
            if (args.size() != 3) throw std::runtime_error("移位需要 3 个操作数：" + line);
            in.op = mnemonic == "sll" ? Op::SLL : Op::SRL;
            in.rd = parse_reg(args[0]);
            in.rt = parse_reg(args[1]);
            in.imm = num(args[2]);
        } else if (mnemonic == "addi" || mnemonic == "andi" || mnemonic == "ori") {
            if (args.size() != 3) throw std::runtime_error("I 型需要 3 个操作数：" + line);
            in.op = mnemonic == "addi" ? Op::ADDI : mnemonic == "andi" ? Op::ANDI : Op::ORI;
            in.rt = parse_reg(args[0]);
            in.rs = parse_reg(args[1]);
            in.imm = num(args[2]);
        } else if (mnemonic == "lw" || mnemonic == "sw") {
            if (args.size() != 2) throw std::runtime_error("访存需要 2 个操作数：" + line);
            in.op = mnemonic == "lw" ? Op::LW : Op::SW;
            in.rt = parse_reg(args[0]);
            parse_mem(args[1], in);
        } else if (mnemonic == "beq" || mnemonic == "bne") {
            if (args.size() != 3) throw std::runtime_error("分支需要 3 个操作数：" + line);
            in.op = mnemonic == "beq" ? Op::BEQ : Op::BNE;
            in.rs = parse_reg(args[0]);
            in.rt = parse_reg(args[1]);
            in.target = label_addr(args[2]);
            in.label = trim(args[2]);
        } else if (mnemonic == "j") {
            if (args.size() != 1) throw std::runtime_error("j 需要 1 个操作数：" + line);
            in.op = Op::J;
            in.target = label_addr(args[0]);
            in.label = trim(args[0]);
        } else if (mnemonic == "halt") {
            in.op = Op::HALT;
        } else {
            throw std::runtime_error("未知指令：'" + mnemonic + "'");
        }
        out.program.push_back(in);
    }
    return out;
}

// 反汇编一行（trace 与 --chart 都用它，保证"看到的就是执行的"）
inline std::string disasm(const Instr& in) {
    std::string s = op_name(in.op);
    auto R = [](int i) { return "r" + std::to_string(i); };
    switch (in.op) {
        case Op::ADD: case Op::SUB: case Op::AND: case Op::OR: case Op::SLT:
            return s + " " + R(in.rd) + ", " + R(in.rs) + ", " + R(in.rt);
        case Op::SLL: case Op::SRL:
            return s + " " + R(in.rd) + ", " + R(in.rt) + ", " + std::to_string(in.imm);
        case Op::ADDI: case Op::ANDI: case Op::ORI:
            return s + " " + R(in.rt) + ", " + R(in.rs) + ", " + std::to_string(in.imm);
        case Op::LW: case Op::SW:
            return s + " " + R(in.rt) + ", " + std::to_string(in.imm) + "(" + R(in.rs) + ")";
        case Op::BEQ: case Op::BNE:
            return s + " " + R(in.rs) + ", " + R(in.rt) + ", " + in.label;
        case Op::J: return s + " " + in.label;
        case Op::HALT: return s;
    }
    return s;
}

}  // namespace b5
