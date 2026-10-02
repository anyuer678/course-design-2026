# asm/sort.s —— 插入排序（原地，64 位整数数组）
#
# 课程要点：
#   - 插入排序的循环不是"嵌套两层的花架子"：外层取 key、内层把比 key 大的元素**后移一格**，
#     找到位置放 key——每一步都可以在内存里用指针验算；
#   - 寻址用比例变址 `[rcx + r9*8]`：数组下标 → 字节偏移的乘法由地址生成单元免费做；
#     **步长 8 是契约的一部分**：C++ 侧必须传 64 位整数数组（`long long`）——
#     传 32 位 `long` 数组会被 8 字节步长写出界（重建时踩过，见 README）；
#   - 与 C++ 的 std::sort 逐元素对拍（60 组固定种子随机数组）：汇编正确性不靠"看着像"。
#
# 调用约定：long long* arr = rcx，long long n = rdx；void。

    .intel_syntax noprefix
    .text
    .globl asm_sort
asm_sort:
    mov r8, 1                   # i = 1
.Lsort_outer:
    cmp r8, rdx
    jge .Lsort_done             # i >= n：完成（n <= 1 时直接到这里）
    mov rax, [rcx + r8*8]       # key = arr[i]
    mov r9, r8                  # j = i
.Lsort_inner:
    test r9, r9
    jle .Lsort_place            # j == 0：key 属于位置 0
    mov r10, [rcx + r9*8 - 8]   # arr[j-1]
    cmp r10, rax
    jle .Lsort_place            # arr[j-1] <= key：找到位置
    mov [rcx + r9*8], r10       # arr[j] = arr[j-1]（大的后移）
    dec r9
    jmp .Lsort_inner
.Lsort_place:
    mov [rcx + r9*8], rax       # arr[j] = key
    inc r8
    jmp .Lsort_outer
.Lsort_done:
    ret
