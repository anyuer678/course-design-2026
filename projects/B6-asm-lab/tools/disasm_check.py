"""tools/disasm_check.py —— 反汇编结构对照：把"寄存器与栈帧"从口头承诺变成可跑的断言

对着 objdump -d -Mintel 的真实输出检查（不是看源码、不是猜）：
  1) 四个汇编函数都出现在自己的 .o 里；
  2) asm_sum_positive 有**完整栈帧**：push rbp / mov rbp,rsp / leave / pop rbp；
  3) asm_fib 是**纯寄存器叶函数**：整个函数体没有任何 push/pop（与 (2) 成对照）；
  4) asm_reverse / asm_sort 也不建帧（无 push rbp）——三种风格同框对比；
  5) abi_probe_call 里有间接 call（call r10：目标是寄存器里的函数指针）；
  6) 链接后的 demo 可执行文件里，C++ 确实 call 了这四个符号（"C++ 调用"的直接证据）。

全部通过返回 0；任何一条不满足打 [FAIL] 并返回 1。
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def objdump(cwd: pathlib.Path, name: str) -> str:
    # 相对路径 + cwd 调用：objdump 对含中文的绝对路径会报 "Illegal byte sequence"
    # （MinGW 工具链在 UTF-16 命令行转换上的老问题），相对路径绕开它
    result = subprocess.run(
        ["objdump", "-d", "--no-show-raw-insn", "-Mintel", name],
        cwd=str(cwd), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"objdump 失败：{name}\n{result.stderr}")
    return result.stdout


def body(text: str, symbol: str) -> str:
    """取出 `<symbol>:` 到下一个空行之间的指令区（objdump 逐函数分段）。"""
    match = re.search(rf"<{symbol}>:\n(.*?)(?=\n\s*\n|\Z)", text, re.S)
    return match.group(1) if match else ""


CHECKS: list[tuple[str, bool]] = []


def check(label: str, ok: bool) -> None:
    CHECKS.append((label, ok))
    print(f"  [{'OK' if ok else 'FAIL'}] {label}")


def has_instr(haystack: str, pattern: str) -> bool:
    """按 mnemonic+操作数匹配（objdump 用空格/制表符对齐，这里正则容忍空白）。"""
    return re.search(pattern, haystack) is not None


def main() -> int:
    objs = {name: objdump(BUILD / "asm", f"{name}.o")
            for name in ("reverse", "fib", "sort", "stackframe", "abi_probe")}

    print("反汇编结构对照（objdump -d -Mintel，对象文件在 build/asm/）")

    # 1) 符号都在
    for name, sym in (("reverse", "asm_reverse"), ("fib", "asm_fib"),
                      ("sort", "asm_sort"), ("stackframe", "asm_sum_positive"),
                      ("abi_probe", "abi_probe_call")):
        check(f"{sym} 出现在 {name}.o", f"<{sym}>:" in objs[name])

    # 2) 栈帧函数：完整序言与收尾
    frame = body(objs["stackframe"], "asm_sum_positive")
    check("sum_positive 序言 push rbp", has_instr(frame, r"\bpush\s+rbp\b"))
    check("sum_positive 序言 mov rbp,rsp", has_instr(frame, r"\bmov\s+rbp,rsp\b"))
    check("sum_positive 收尾 leave（= mov rsp,rbp + pop rbp，两条折一条）",
          has_instr(frame, r"\bleave\b"))
    check("sum_positive 收尾 ret", has_instr(frame, r"\bret\b"))
    check("sum_positive 借用 rbx 前有保存（push rbx）", has_instr(frame, r"\bpush\s+rbx\b"))
    check("sum_positive 归还 rbx（pop rbx）", has_instr(frame, r"\bpop\s+rbx\b"))

    # 3) 叶函数：fib 无 push/pop
    fib_body = body(objs["fib"], "asm_fib")
    check("fib 是纯寄存器叶函数（无 push）", not has_instr(fib_body, r"\bpush\b"))
    check("fib 是纯寄存器叶函数（无 pop）", not has_instr(fib_body, r"\bpop\b"))
    check("fib 无内存操作数（纯寄存器算术）", not has_instr(fib_body, r"\["))

    # 4) 另两个也不建帧（对照）
    rev_body = body(objs["reverse"], "asm_reverse")
    sort_body = body(objs["sort"], "asm_sort")
    check("reverse 不建帧（无 push rbp）", not has_instr(rev_body, r"\bpush\s+rbp\b"))
    check("sort 不建帧（无 push rbp）", not has_instr(sort_body, r"\bpush\s+rbp\b"))
    check("sort 用比例变址 [rcx + r8*8]", has_instr(sort_body, r"\[rcx\+r8\*8\]"))

    # 5) 探针里有间接调用
    probe_body = body(objs["abi_probe"], "abi_probe_call")
    check("abi_probe_call 里有间接 call r10", has_instr(probe_body, r"\bcall\s+r10\b"))
    check("反面教材里确实破坏 rbx（mov/movabs rbx,…）",
          has_instr(body(objs["abi_probe"], "abi_bad_clobber"), r"\bmov(?:abs)?\s+rbx,"))

    # 6) 链接后的 demo 里 C++ 真的 call 了这些符号
    exe_text = objdump(BUILD, "asm-lab.exe")
    for sym in ("asm_reverse", "asm_fib", "asm_sort", "asm_sum_positive"):
        called = any("call" in line and f"<{sym}>" in line
                     for line in exe_text.splitlines())
        check(f"demo.exe 里有 call 到 {sym} 的调用点", called)

    passed = sum(1 for _, ok in CHECKS if ok)
    failed = len(CHECKS) - passed
    print(f"\n反汇编结构对照：{passed} 项通过，{failed} 项失败")
    lines = frame.strip().splitlines()
    print("\nsum_positive 的序言与收尾（现场截取）：")
    for line in lines[:4]:
        print("   " + line.strip())
    print("   ...")
    for line in lines[-3:]:
        print("   " + line.strip())
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
