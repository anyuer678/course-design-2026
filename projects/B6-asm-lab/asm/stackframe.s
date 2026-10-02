# asm/stackframe.s —— 求正数之和：**完整栈帧**的示范函数
#
# 课程要点（与 fib.s / reverse.s 的"裸函数"对照着看）：
#   - 标准序言 `push rbp; mov rbp, rsp` 立稳帧指针，局部变量用 [rbp-8]、[rbp-16] 寻址；
#   - **callee-saved 的纪律**：本函数借用 rbx 保存数组指针，序言里 push、收尾时 pop——
#     反汇编探针（tests/abi_probe.s）会拿哨兵值验证"进出时 rbx 一个 bit 都不差"；
#   - 收尾用 `leave`（= mov rsp, rbp; pop rbp）恢复现场——教科书上的经典一条；
#   - 栈上局部与寄存器各留一半，是为了让"寄存器与栈帧"的对照有据可查：
#     sum/i 在栈上（可被调试器改），数组指针在 rbx（寄存器窗口里看）。
#
# 调用约定：const long long* arr = rcx，long long n = rdx；返回正数之和 = rax。

    .intel_syntax noprefix
    .text
    .globl asm_sum_positive
asm_sum_positive:
    push rbp                    # 序言：保存调用者的帧指针
    mov rbp, rsp
    sub rsp, 32                 # 局部区：sum 与 i 都在栈上
    push rbx                    # 借用 callee-saved 前先保存
    mov qword ptr [rbp - 8], 0  # long sum = 0
    mov qword ptr [rbp - 16], 0 # long i = 0
    mov rbx, rcx                # 数组指针放 rbx（本函数独占，退出时恢复）
.Lsum_loop:
    mov rax, [rbp - 16]         # rax = i
    cmp rax, rdx
    jge .Lsum_done              # i >= n：结束
    mov r10, [rbx + rax*8]      # arr[i]
    test r10, r10
    jle .Lsum_next              # 非正数：跳过
    add [rbp - 8], r10          # sum += arr[i]
.Lsum_next:
    inc qword ptr [rbp - 16]    # ++i
    jmp .Lsum_loop
.Lsum_done:
    mov rax, [rbp - 8]          # 返回值 = sum
    pop rbx                     # 恢复 callee-saved
    leave                       # = mov rsp, rbp; pop rbp
    ret
