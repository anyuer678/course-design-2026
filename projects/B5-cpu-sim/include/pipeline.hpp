// include/pipeline.hpp —— 五级流水线：冒险检测 + 转发 + 分支冲刷（B5 的选做做成了正题）
//
// 课程要点：
//   - 五级是 IF/ID/EX/MEM/WB；没有冒险时吞吐 = 1 条/周期，**但最终状态必须与单周期一致**——
//     "双模型对拍"就是拿这条做验收（测试里逐个程序比寄存器与内存）；
//   - 数据冒险：前递（EX/MEM → EX、MEM/WB → EX）解决算术类，**load-use 必须停顿**一周期
//     （装载的数据要到 MEM 之后才有，转发也来不及）；
//   - 控制冒险：分支在 EX 阶段才判定，预测**不跳**；一旦实际跳转，要把 IF/ID 两级的
//     年轻指令冲刷（flush）并按目标重取——测试里数冲刷次数，不是"看起来对"。
#pragma once

#include <sstream>
#include <string>
#include <vector>

#include "asm.hpp"
#include "cpu.hpp"
#include "isa.hpp"

namespace b5 {

struct Slot {
    bool valid = false;
    Instr in;
    int pc = -1;
    int32_t a = 0, b = 0;                  // EX/MEM 阶段用到的操作数快照
    int32_t result = 0;                    // ALU 结果 / 装载值
    int dest = 0;                          // 写回目标（0 表示不写）
    bool is_load = false;
    int mem_addr = 0;
};

struct PipeRow {
    int cycle = 0;
    std::string cols[5];                   // IF, ID, EX, MEM, WB
    bool stalled = false;
    bool flushed = false;
};

struct PipeResult {
    CpuStats stats;
    Machine machine;
    std::vector<PipeRow> chart;
    int stalls = 0;
    int flushes = 0;
};

class PipelineCpu {
public:
    explicit PipelineCpu(int mem_words = 64) : m_(mem_words) {}

    // 与单周期同样的约定：run() 只重置控制状态，寄存器与内存保留调用方写入的初值。
    Machine& machine() { return m_; }

    PipeResult run(const std::vector<Instr>& program) {
        if (program.empty()) throw std::runtime_error("程序为空");
        PipeResult out;
        m_.pc = 0;
        m_.halted = false;
        m_.cycles = 0;
        m_.trace.clear();
        m_.mem.loads = m_.mem.stores = 0;
        m_.regs.writes = 0;
        out.machine = m_;
        Slot if_id, id_ex, ex_mem, mem_wb;
        int pc = 0;
        bool halted = false;
        bool pc_frozen = false;                // 见过 halt：停止取指，只等流水线排空
        int cycle = 0;
        const int limit = 200000;           // 死循环保护：教学模型也要有上界

        while (!halted && cycle < limit) {
            ++cycle;
            PipeRow row;
            row.cycle = cycle;

            // ---- 1) WB：把 mem_wb 的结果写回寄存器堆
            if (mem_wb.valid) {
                row.cols[4] = short_name(mem_wb.in);
                if (mem_wb.dest != 0)
                    out.machine.regs.write(mem_wb.dest, mem_wb.result);
                if (mem_wb.in.op == Op::HALT) halted = true;
            }

            // ---- 2) MEM：装载取值 / 存储写内存（写内存放在这一级）
            Slot next_wb;
            if (ex_mem.valid) {
                row.cols[3] = short_name(ex_mem.in);
                next_wb = ex_mem;
                next_wb.valid = true;
                if (ex_mem.is_load) {
                    next_wb.result = out.machine.mem.load(ex_mem.mem_addr);
                    ++out.machine.mem.loads;
                }
                if (ex_mem.in.op == Op::SW) {
                    out.machine.mem.store(ex_mem.mem_addr, ex_mem.b);
                    ++out.machine.mem.stores;
                }
            }

            // ---- 3) EX：前递取操作数 → 算结果 / 判分支
            Slot next_mem;
            bool branch_taken = false;
            int branch_target = 0;
            if (id_ex.valid) {
                row.cols[2] = short_name(id_ex.in);
                const int32_t a = forward(id_ex.in.rs, id_ex.a, ex_mem, mem_wb);
                const int32_t b = forward(id_ex.in.rt, id_ex.b, ex_mem, mem_wb);
                next_mem.valid = true;
                next_mem.in = id_ex.in;
                next_mem.pc = id_ex.pc;
                next_mem.a = a;
                next_mem.b = b;
                next_mem.dest = dest_of(id_ex.in);
                switch (id_ex.in.op) {
                    case Op::ADD: next_mem.result = a + b; break;
                    case Op::SUB: next_mem.result = a - b; break;
                    case Op::AND: next_mem.result = a & b; break;
                    case Op::OR:  next_mem.result = a | b; break;
                    case Op::SLT: next_mem.result = (a < b) ? 1 : 0; break;
                    // 位移的源寄存器是 **rt**（`sll rd, rt, shamt`），不是 rs——
                    // 第一版用了 rs 的转发值（位移指令 rs=0）⇒ 结果恒为 0，双模型对拍当场抓住。
                    case Op::SLL: next_mem.result = b << id_ex.in.imm; break;
                    case Op::SRL: next_mem.result = (int32_t)((uint32_t)b >> id_ex.in.imm); break;
                    case Op::ADDI: next_mem.result = a + id_ex.in.imm; break;
                    case Op::ANDI: next_mem.result = a & id_ex.in.imm; break;
                    case Op::ORI:  next_mem.result = a | id_ex.in.imm; break;
                    case Op::LW: case Op::SW:
                        next_mem.mem_addr = a + id_ex.in.imm;
                        next_mem.is_load = (id_ex.in.op == Op::LW);
                        next_mem.result = a + id_ex.in.imm;      // SW 不需要写回
                        next_mem.dest = (id_ex.in.op == Op::LW) ? id_ex.in.rt : 0;
                        break;
                    case Op::BEQ: case Op::BNE: {
                        ++out.stats.branches;
                        const bool equal = (a == b);
                        branch_taken = (id_ex.in.op == Op::BEQ) ? equal : !equal;
                        branch_target = id_ex.in.target;
                        if (branch_taken) ++out.stats.branches_taken;
                        next_mem.dest = 0;
                        break;
                    }
                    case Op::J:
                        branch_taken = true;
                        branch_target = id_ex.in.target;
                        next_mem.dest = 0;
                        break;
                    case Op::HALT:
                        next_mem.dest = 0;
                        break;
                }
            }

            // ---- 4) ID：译码取数；load-use 冒险在这里停顿
            Slot next_ex;
            bool stall = false;
            if (if_id.valid) {
                row.cols[1] = short_name(if_id.in);
                const bool load_use =
                    id_ex.valid && id_ex.is_load && id_ex.dest != 0 &&
                    id_ex.dest != 0 &&
                    ((needs_rs(if_id.in) && id_ex.dest == if_id.in.rs) ||
                     (needs_rt(if_id.in) && id_ex.dest == if_id.in.rt));
                if (load_use) {
                    stall = true;
                    row.stalled = true;
                    ++out.stalls;
                } else {
                    next_ex.valid = true;
                    next_ex.in = if_id.in;
                    next_ex.pc = if_id.pc;
                    next_ex.a = out.machine.regs.read(if_id.in.rs);
                    next_ex.b = out.machine.regs.read(if_id.in.rt);
                    // is_load / dest 必须在**进入 EX 时就带上**：停顿检测看的是"此刻在 EX 的是不是装载"。
                    // 第一版把 is_load 留到 EX 阶段计算，装载在 EX 的那一周期标志还没置上，
                    // load-use 冒险于是完全没被检出（结果读到了旧值）。
                    next_ex.is_load = (if_id.in.op == Op::LW);
                    next_ex.dest = dest_of(if_id.in);
                }
            }

            // ---- 5) IF：按当前 pc 取指
            //
            // 两条**实测撞出来的**规矩：
            //   ① 分支跳转时本周期**不取指**：第一版"取了目标又把它当年轻指令冲掉"，
            //      可 pc 已经前进 ⇒ 目标指令被跳过，循环直接变成死循环；
            //   ② 取到 halt 就冻结取指：HALT 还要走完 MEM/WB，这期间再取就只剩越界可报。
            Slot next_if;
            if (branch_taken) {
                pc = branch_target;
                pc_frozen = false;             // 冲刷后从目标重新取指：**冻结标志必须清掉**，
                                               // 否则"跳转前恰好取到过 halt"会让流水线排空后永不再取指（假死）
                row.flushed = true;
                row.cols[0] = "F";             // 冲刷周期：IF 是气泡，下周期从目标取
                ++out.flushes;
            } else if (halted || pc_frozen) {
                // 排空阶段：不再取指
            } else if (pc >= 0 && pc < (int)program.size()) {
                next_if.valid = true;
                next_if.in = program[pc];
                next_if.pc = pc;
                row.cols[0] = short_name(program[pc]);
                if (!stall) {                  // 停顿：pc 不动，下周期重取同一条
                    if (program[pc].op == Op::HALT) pc_frozen = true;
                    else pc += 1;
                }
            } else {
                throw std::runtime_error("取指越界：pc=" + std::to_string(pc));
            }

            // ---- 提交状态：被冲刷的两级作废；停顿则 IF/ID 保持
            if (branch_taken) {
                next_ex = Slot();              // 冲掉 ID 阶段的年轻指令（IF 本周期没取指）
                row.cols[1] = "F";             // 画图时标出冲刷
            } else if (stall) {
                next_if = if_id;               // 停顿：IF/ID 不动（下周期再试）
                row.cols[0] = "S";             // 画图时标出停顿
            }
            mem_wb = next_wb;
            ex_mem = next_mem;
            id_ex = next_ex;
            if_id = next_if;
            if (id_ex.valid) ++out.stats.instrs;
            out.chart.push_back(row);
        }
        if (cycle >= limit) {
            // 把最后几个周期带进错误消息：调试这种"看起来在跑其实原地转"的模型时，
            // "哪几级在动、pc 是不是不动"比"超时了"有用得多。
            std::string diag = "超过周期上限：疑似死循环；pc=" + std::to_string(pc) +
                               "，最后 6 个周期：";
            for (std::size_t i = out.chart.size() > 6 ? out.chart.size() - 6 : 0;
                 i < out.chart.size(); ++i) {
                const PipeRow& r = out.chart[i];
                diag += "\n  cyc " + std::to_string(r.cycle) + "  IF=" + r.cols[0] +
                        " ID=" + r.cols[1] + " EX=" + r.cols[2] + " MEM=" + r.cols[3] +
                        " WB=" + r.cols[4];
            }
            throw std::runtime_error(diag);
        }
        out.stats.cycles = cycle;
        out.stats.reg_writes = out.machine.regs.writes;
        m_ = out.machine;                   // 把跑完的机器状态留在对象里，便于调用方对比
        return out;
    }

private:
    static bool needs_rs(const Instr& in) {
        switch (in.op) {
            case Op::BEQ: case Op::BNE: case Op::LW: case Op::SW:
            case Op::ADDI: case Op::ANDI: case Op::ORI:
            case Op::ADD: case Op::SUB: case Op::AND: case Op::OR: case Op::SLT:
                return true;
            default: return false;
        }
    }
    static bool needs_rt(const Instr& in) {
        switch (in.op) {
            case Op::BEQ: case Op::BNE:
            case Op::ADD: case Op::SUB: case Op::AND: case Op::OR: case Op::SLT:
            case Op::SLL: case Op::SRL:
                return true;
            case Op::SW: return true;          // sw 的 rt 是数据源
            default: return false;
        }
    }
    static int dest_of(const Instr& in) {
        switch (in.op) {
            case Op::ADD: case Op::SUB: case Op::AND: case Op::OR: case Op::SLT:
            case Op::SLL: case Op::SRL:
                return in.rd;
            case Op::ADDI: case Op::ANDI: case Op::ORI: case Op::LW:
                return in.rt;
            default: return 0;
        }
    }
    static std::string short_name(const Instr& in) {
        return op_name(in.op) + (in.label.empty() ? "" : " " + in.label);
    }
    static int32_t forward(int reg, int32_t value, const Slot& ex_mem, const Slot& mem_wb) {
        if (reg == 0) return 0;
        if (ex_mem.valid && ex_mem.dest == reg && !ex_mem.is_load)
            return ex_mem.result;              // EX/MEM → EX
        if (mem_wb.valid && mem_wb.dest == reg)
            return mem_wb.result;              // MEM/WB → EX（含刚从内存取到的装载值）
        return value;
    }

    Machine m_;
};

}  // namespace b5
