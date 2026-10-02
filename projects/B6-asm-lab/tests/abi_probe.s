# tests/abi_probe.s —— 调用约定探针：拿哨兵值验证 callee-saved 纪律
#
# 干什么：把 8 个 callee-saved 寄存器（rbx/rbp/rsi/rdi/r12-r15）全填上哨兵值，
# 调用目标函数，回来后逐个比较——被改过的位进掩码（bit0=rbx ... bit7=r15）。
# 为什么这么做：caller 的 rbx 里可能存着整个循环的累加器，汇编函数忘了保存就
# 会炸在"看起来无关"的地方；**这个探针把"ABI 合规"变成一条可跑的断言**。
#
# 反面自证：abi_bad_clobber 故意破坏 rbx 不还原——测试拿它验证探针真的会亮灯
# （本仓库的纪律：检查器要先证明自己会失败）。
#
# 栈对齐（Windows x64）：入口 rsp≡8 (mod 16)；推 8 个寄存器后≡8；再 sub 8 → ≡0，
# 然后 `call` 才满足"调用指令处 rsp≡0"的约定。

    .intel_syntax noprefix
    .text
    .globl abi_probe_call
abi_probe_call:
    # long abi_probe_call(Fn2 fn in rcx, long a in rdx, long b in r8)
    push rbx
    push rbp
    push rsi
    push rdi
    push r12
    push r13
    push r14
    push r15
    sub rsp, 8
    mov r10, rcx                # fn
    mov r11, rdx                # a（先寄存到 r11）
    mov rcx, rdx                # 第 1 个参数 = a
    mov rdx, r8                 # 第 2 个参数 = b
    mov rbx, 0x1111111111111111
    mov rbp, 0x2222222222222222
    mov rsi, 0x3333333333333333
    mov rdi, 0x4444444444444444
    mov r12, 0x5555555555555555
    mov r13, 0x6666666666666666
    mov r14, 0x7777777777777777
    mov r15, 0x8888888888888888
    call r10
    xor eax, eax                # mask = 0
    mov r11, 0x1111111111111111
    cmp rbx, r11
    je .Labi_1
    or eax, 1
.Labi_1:
    mov r11, 0x2222222222222222
    cmp rbp, r11
    je .Labi_2
    or eax, 2
.Labi_2:
    mov r11, 0x3333333333333333
    cmp rsi, r11
    je .Labi_3
    or eax, 4
.Labi_3:
    mov r11, 0x4444444444444444
    cmp rdi, r11
    je .Labi_4
    or eax, 8
.Labi_4:
    mov r11, 0x5555555555555555
    cmp r12, r11
    je .Labi_5
    or eax, 16
.Labi_5:
    mov r11, 0x6666666666666666
    cmp r13, r11
    je .Labi_6
    or eax, 32
.Labi_6:
    mov r11, 0x7777777777777777
    cmp r14, r11
    je .Labi_7
    or eax, 64
.Labi_7:
    mov r11, 0x8888888888888888
    cmp r15, r11
    je .Labi_8
    or eax, 128
.Labi_8:
    add rsp, 8
    pop r15
    pop r14
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbp
    pop rbx
    ret

    .globl abi_bad_clobber
abi_bad_clobber:
    # 反面教材：破坏 rbx 且不保存——探针必须报出 bit0
    mov rbx, 0x9999999999999999
    xor eax, eax
    ret
