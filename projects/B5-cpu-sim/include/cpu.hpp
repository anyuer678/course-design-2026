// include/cpu.hpp —— 单周期 CPU：一条指令一个周期，逐条可追踪。
//
// 课程要点：
//   - 取指-译码-执行-访存-写回在单周期里"顺序发生"，所以周期数 = 执行的指令数；
//   - 分支与跳转在**执行阶段**改变 PC：下一条取哪条要看本条的结果；
//   - r0 恒零、访存越界要抛错——这两条是"模型的可信性"，不是细节。
#pragma once

#include <stdexcept>
#include <string>
#include <vector>

#include "asm.hpp"
#include "isa.hpp"

namespace b5 {

struct CpuStats {
    int cycles = 0;
    int instrs = 0;
    int loads = 0;
    int stores = 0;
    int branches = 0, branches_taken = 0;
    int reg_writes = 0;
};

class SingleCycleCpu {
public:
    explicit SingleCycleCpu(int mem_words = 64) : m_(mem_words) {}

    // 执行到 halt；返回统计。程序为空或跑飞（越界取指）会抛错。
    // 注意：run() **只重置控制状态**（pc/halted/trace/计数器），不动寄存器与内存——
    // 第一版把 Machine 整个重建，调用方预先写好的数组/初值当场被清空。
    CpuStats run(const std::vector<Instr>& program) {
        require_program(program);
        m_.pc = 0;
        m_.halted = false;
        m_.cycles = 0;
        m_.trace.clear();
        instrs_ = branches_ = taken_ = 0;
        m_.mem.loads = m_.mem.stores = 0;
        m_.regs.writes = 0;
        while (!m_.halted) step(program);
        CpuStats s;
        s.cycles = m_.cycles;
        s.instrs = instrs_;
        s.loads = m_.mem.loads;
        s.stores = m_.mem.stores;
        s.branches = branches_;
        s.branches_taken = taken_;
        s.reg_writes = m_.regs.writes;
        return s;
    }

    void step(const std::vector<Instr>& program) {
        if (m_.pc < 0 || m_.pc >= (int)program.size())
            throw std::runtime_error("取指越界：pc=" + std::to_string(m_.pc));
        const Instr& in = program[m_.pc];
        const int here = m_.pc;
        ++m_.cycles;
        ++instrs_;
        int next_pc = here + 1;
        std::string effect;
        switch (in.op) {
            case Op::ADD: case Op::SUB: case Op::AND: case Op::OR: case Op::SLT: {
                const int32_t a = m_.regs.read(in.rs), b = m_.regs.read(in.rt);
                int32_t v = 0;
                if (in.op == Op::ADD) v = a + b;
                if (in.op == Op::SUB) v = a - b;
                if (in.op == Op::AND) v = a & b;
                if (in.op == Op::OR)  v = a | b;
                if (in.op == Op::SLT) v = (a < b) ? 1 : 0;
                m_.regs.write(in.rd, v);
                effect = "r" + std::to_string(in.rd) + "=" + std::to_string(v);
                break;
            }
            case Op::SLL: { int32_t v = m_.regs.read(in.rt) << in.imm; m_.regs.write(in.rd, v);
                            effect = "r" + std::to_string(in.rd) + "=" + std::to_string(v); break; }
            case Op::SRL: { int32_t v = (int32_t)((uint32_t)m_.regs.read(in.rt) >> in.imm);
                            m_.regs.write(in.rd, v);
                            effect = "r" + std::to_string(in.rd) + "=" + std::to_string(v); break; }
            case Op::ADDI: case Op::ANDI: case Op::ORI: {
                int32_t a = m_.regs.read(in.rs), v = 0;
                if (in.op == Op::ADDI) v = a + in.imm;
                if (in.op == Op::ANDI) v = a & in.imm;
                if (in.op == Op::ORI) v = a | in.imm;
                m_.regs.write(in.rt, v);
                effect = "r" + std::to_string(in.rt) + "=" + std::to_string(v);
                break;
            }
            case Op::LW: {
                int32_t addr = m_.regs.read(in.rs) + in.imm;
                int32_t v = m_.mem.load(addr);
                ++m_.mem.loads;
                m_.regs.write(in.rt, v);
                effect = "r" + std::to_string(in.rt) + "=mem[" + std::to_string(addr) + "]";
                break;
            }
            case Op::SW: {
                int32_t addr = m_.regs.read(in.rs) + in.imm;
                m_.mem.store(addr, m_.regs.read(in.rt));
                ++m_.mem.stores;
                effect = "mem[" + std::to_string(addr) + "]=r" + std::to_string(in.rt);
                break;
            }
            case Op::BEQ: case Op::BNE: {
                ++branches_;
                const bool equal = m_.regs.read(in.rs) == m_.regs.read(in.rt);
                const bool take = (in.op == Op::BEQ) ? equal : !equal;
                if (take) { next_pc = in.target; ++taken_; effect = "taken"; }
                else effect = "not-taken";
                effect += " -> pc " + std::to_string(next_pc);
                break;
            }
            case Op::J: next_pc = in.target; effect = "jump -> pc " + std::to_string(next_pc); break;
            case Op::HALT: m_.halted = true; effect = "halt"; break;
        }
        m_.trace.push_back("cyc " + std::to_string(m_.cycles) + "  pc " + std::to_string(here) +
                           "  " + disasm(in) + "    [" + effect + "]");
        m_.pc = next_pc;
    }

    Machine& machine() { return m_; }

private:
    void require_program(const std::vector<Instr>& program) {
        if (program.empty()) throw std::runtime_error("程序为空");
    }
    Machine m_;
    int instrs_ = 0, branches_ = 0, taken_ = 0;
};

}  // namespace b5
