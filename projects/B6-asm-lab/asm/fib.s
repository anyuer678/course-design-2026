# asm/fib.s —— 斐波那契（迭代，纯寄存器）
#
# 课程要点：
#   - 迭代版只需要三个寄存器：a、b 与"a+b"的临时量——不递归、不压栈；
#   - 这是**叶函数**：全程不 push/pop、不动 callee-saved，
#     反汇编里一条 `push` 都找不到（对照 stackframe.s 的完整栈帧）；
#   - 64 位无符号下 fib(93) = 12200160415121876738 是最后一个不溢出的值——
#     测试拿 0..93 与 C++ 参照逐数对拍，把"溢出边界"钉住。
#
# 调用约定：n = rcx；返回 u64 = rax。fib(n<=0) = 0。

    .intel_syntax noprefix
    .text
    .globl asm_fib
asm_fib:
    xor eax, eax                # a = fib(0) = 0
    mov r8, 1                   # b = fib(1) = 1
    test rcx, rcx
    jle .Lfib_done
.Lfib_loop:
    mov r9, rax
    add r9, r8                  # t = a + b
    mov rax, r8                 # a = b
    mov r8, r9                  # b = t
    dec rcx
    jnz .Lfib_loop
.Lfib_done:
    ret
