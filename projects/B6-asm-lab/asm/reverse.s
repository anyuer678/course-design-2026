# asm/reverse.s —— 字符串反转（原地，按字节）
#
# 课程要点：
#   - 两指针相向而行是反转的最省写法：一个从头、一个从尾，交换后各自前进一步；
#   - 长度是**参数**不是 strlen：调用方给多少就翻多少（"以 0 结尾"是 C 的约定，
#     汇编里没人替你查字符串——想要 strlen 得自己扫）；
#   - 本函数只碰 volatile 寄存器（rax/rcx/rdx/r8-r11），不建栈帧、不动 callee-saved——
#     反汇编对照里它和 stackframe.s 是"最小函数"与"完整栈帧"的两端；
#   - **按字节反转**：UTF-8 文本会被打乱（多字节字符被逐字节颠倒），演示里当面说明。
#
# 调用约定（Windows x64）：char* s = rcx，long long len = rdx；返回值不用，rax 置 0。

    .intel_syntax noprefix
    .text
    .globl asm_reverse
asm_reverse:
    xor eax, eax                # 返回值 = 0（void 也留个干净的 rax）
    test rdx, rdx
    jle .Lrev_done              # len <= 0：什么都不做
    mov rax, rcx                # left = s
    lea r8, [rcx + rdx - 1]     # right = s + len - 1
.Lrev_loop:
    cmp rax, r8
    jge .Lrev_done              # left >= right：翻完了
    mov r9b, [rax]              # 换一个字节
    mov r10b, [r8]
    mov [rax], r10b
    mov [r8], r9b
    inc rax
    dec r8
    jmp .Lrev_loop
.Lrev_done:
    ret
