# programs/loop.asm —— 最小循环：验证分支跳转与冲刷（run.bat 末尾提示用它）
    addi r1, r0, 3
loop:
    addi r1, r1, -1
    bne  r1, r0, loop
    halt
