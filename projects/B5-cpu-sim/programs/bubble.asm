# programs/bubble.asm —— 冒泡排序（字地址内存：数组在 mem[0..n-1]）
# 演示：算术 / 访存 / 分支 / 跳转 全部用到；排序结果用"读内存"验证
    addi r1, r0, 0          # i = 0（外层已排好的趟数）
    addi r2, r0, 4          # n - 1 = 4
outer:
    slt  r10, r1, r2        # i < 4 ?
    beq  r10, r0, done
    addi r3, r0, 0          # j = 0
inner:
    sub  r11, r2, r1        # 内层上界 = (n-1) - i
    slt  r4, r3, r11
    beq  r4, r0, nextpass
    add  r5, r3, r0         # 地址 j
    lw   r6, 0(r5)          # mem[j]
    addi r7, r3, 1          # 地址 j+1
    lw   r8, 0(r7)          # mem[j+1]
    slt  r9, r8, r6         # mem[j+1] < mem[j] 就交换
    beq  r9, r0, noswap
    sw   r8, 0(r5)
    sw   r6, 0(r7)
noswap:
    addi r3, r3, 1
    j    inner
nextpass:
    addi r1, r1, 1
    j    outer
done:
    halt
