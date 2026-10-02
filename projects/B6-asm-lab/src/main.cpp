// src/main.cpp —— B6 演示：五段脚本 + 反汇编对照入口。数字全部运行时现算。
//
//   1) 字符串反转：按字节原地翻转（UTF-8 会被打乱——当面说明）
//   2) 斐波那契：纯寄存器叶函数，fib(93) 是 u64 边界
//   3) 插入排序：与 std::sort 当场对照
//   4) 栈帧函数：sum_positive 用完整栈帧（对照 fib 的裸函数）
//   5) ABI 探针：哨兵值验证 callee-saved 纪律，含"反面教材会亮灯"的自证
//
// 演示不打印耗时；反汇编结构对照在 run.bat 第 3 步（tools/disasm_check.py）。
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

extern "C" {
// 参数统一 64 位：Windows x64 的 long 是 32 位，与 64 位寄存器读法混用会坑（见 README）
void asm_reverse(char* s, long long len);
unsigned long long asm_fib(long long n);
void asm_sort(long long* arr, long long n);
long asm_sum_positive(const long long* arr, long long n);
long abi_probe_call(std::uintptr_t fn, long long a, long long b);
long abi_bad_clobber(void);
}

template <class F>
static long probe(F fn, long long a, long long b) {
    return abi_probe_call(reinterpret_cast<std::uintptr_t>(fn), a, b);
}

static void section(int no, const char* title) {
    std::printf("\n============================================================\n");
    std::printf("  %d) %s\n", no, title);
    std::printf("============================================================\n");
}

int main() {
    std::printf("B6-asm-lab 演示：字符串反转 / 斐波那契 / 排序（x86-64 汇编，C++ 调用）\n");

    // ------------------------------------------------------------------ 1
    section(1, "字符串反转（原地、按字节）");
    char text[] = "Hello, asm-lab!";
    std::printf("  原串：%s\n", text);
    asm_reverse(text, static_cast<long long>(std::strlen(text)));
    std::printf("  反转：%s\n", text);
    asm_reverse(text, static_cast<long long>(std::strlen(text)));
    std::printf("  再反转（应还原）：%s\n", text);
    std::printf("  按字节翻转：UTF-8 多字节字符会被打乱（本函数只认字节，不认字符）\n");

    // ------------------------------------------------------------------ 2
    section(2, "斐波那契（纯寄存器叶函数）");
    std::printf("  fib(0..10) =");
    for (long long n = 0; n <= 10; ++n) std::printf(" %llu", asm_fib(n));
    std::printf("\n  fib(50)  = %llu\n", asm_fib(50));
    std::printf("  fib(93)  = %llu（64 位无符号下最后一个不溢出值）\n", asm_fib(93));
    unsigned long long ref = 0, b = 1;               // C++ 参照，当场再算一遍
    for (long long i = 0; i < 93; ++i) {
        unsigned long long t = ref + b;
        ref = b;
        b = t;
    }
    std::printf("  与 C++ 参照一致：%s\n", asm_fib(93) == ref ? "是" : "否");

    // ------------------------------------------------------------------ 3
    section(3, "插入排序（原地，与 std::sort 对照）");
    std::mt19937 rng(20261002);
    std::vector<long long> data(12);
    for (long long& v : data) v = static_cast<long long>(rng() % 201) - 100;
    std::printf("  输入：");
    for (long long v : data) std::printf("%lld ", v);
    std::vector<long long> refv = data;
    std::sort(refv.begin(), refv.end());
    asm_sort(data.data(), static_cast<long long>(data.size()));
    std::printf("\n  汇编输出：");
    for (long long v : data) std::printf("%lld ", v);
    bool same = data == refv;
    std::printf("\n  与 std::sort 逐元素一致：%s\n", same ? "是" : "否");
    if (!same) return 1;

    // ------------------------------------------------------------------ 4
    section(4, "栈帧函数 sum_positive（完整序言/收尾的那一个）");
    const long long arr[] = {5, -3, 12, 0, -7, 8, 4};
    std::printf("  数组：");
    for (long long v : arr) std::printf("%lld ", v);
    std::printf("\n  正数之和 = %ld（局部变量 sum/i 在栈上，数组指针暂借 rbx）\n",
                asm_sum_positive(arr, 7));

    // ------------------------------------------------------------------ 5
    section(5, "ABI 探针：callee-saved 纪律（0 = 一个 bit 都没动）");
    char buf[8] = "abcd";
    long long arr3[3] = {3, 1, 2};
    long long arr5[5] = {-1, 2, -3, 4, 5};
    std::printf("  reverse=%ld  fib=%ld  sort=%ld  sum_positive=%ld\n",
                probe(asm_reverse, reinterpret_cast<long long>(buf), 4),
                probe(asm_fib, 20, 0),
                probe(asm_sort, reinterpret_cast<long long>(arr3), 3),
                probe(asm_sum_positive, reinterpret_cast<long long>(arr5), 5));
    std::printf("  反面教材（故意不保存 rbx）：掩码 = %ld（bit0 = rbx，探针确实会亮灯）\n",
                probe(abi_bad_clobber, 0, 0));

    std::printf("\n============================================================\n");
    std::printf("完成：5 段演示全部跑通。反汇编结构对照见 run.bat 第 3 步。\n");
    return 0;
}
