// tests/test_asm.cpp —— B6 自测：汇编函数的边界 + 对拍 + ABI 探针
//
// 纪律（和本仓库其它项目一致）：
//   1. 期望值来自手算或独立参照：fib 对 C++ 迭代参照逐数对拍、sort 对 std::sort 对拍、
//      反转对 std::reverse 对拍（全部固定种子）；
//   2. ABI 探针是"调用约定"的直接证据：哨兵值进、比较后出掩码——且反面教材
//      （故意破坏 rbx 的 abi_bad_clobber）必须被探针抓住，否则探针本身不算数；
//   3. 越界写用哨兵字节围栏验证（reverse 只许动它该动的那段内存）。
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

#include "check.hpp"

extern "C" {
// 参数一律 64 位：Windows x64 的 C++ `long` 是 32 位，而汇编按 64 位寄存器读——
// 宽度写岔了，-3 会以 0xfffffffd（40 亿）的样子进函数（重建时被 gdb 当场逮住）
void asm_reverse(char* s, long long len);
unsigned long long asm_fib(long long n);
void asm_sort(long long* arr, long long n);
long asm_sum_positive(const long long* arr, long long n);
long abi_probe_call(std::uintptr_t fn, long long a, long long b);
long abi_bad_clobber(void);
}

// 探针统一走"函数指针 → uintptr_t"（x64 上 long 只有 32 位，装不下指针；
// 函数指针转整数再由汇编 call，绕开 -Wcast-function-type 的告警噪音）
template <class F>
static long probe(F fn, long long a, long long b) {
    return abi_probe_call(reinterpret_cast<std::uintptr_t>(fn), a, b);
}

// ---------------------------------------------------------------- 反转

static void test_reverse() {
    long long m0 = asmlab::checker().mark();

    struct Case {
        const char* in;
        const char* want;
    };
    const Case cases[] = {
        {"", ""},           {"a", "a"},     {"ab", "ba"},
        {"abc", "cba"},     {"abcd", "dcba"},
        {"hello", "olleh"}, {"12345", "54321"},
    };
    for (const Case& c : cases) {
        char buf[64];
        std::strcpy(buf, c.in);
        asm_reverse(buf, static_cast<long long>(std::strlen(c.in)));
        CHECK(std::strcmp(buf, c.want) == 0);
    }

    // len <= 0：什么都不许动
    {
        char buf[8] = "keep";
        asm_reverse(buf, 0);
        asm_reverse(buf, -3);
        CHECK(std::strcmp(buf, "keep") == 0);
    }

    // 越界哨兵：只反 middle 段，两侧字节必须完好
    {
        char buf[10] = {'L', 'a', 'b', 'c', 'd', 'e', 'R', '\0', 'x', 'y'};
        asm_reverse(buf + 1, 5);            // 反转 abcde
        CHECK(buf[0] == 'L' && buf[6] == 'R' && buf[7] == '\0' &&
              buf[8] == 'x' && buf[9] == 'y');
        CHECK(std::memcmp(buf + 1, "edcba", 5) == 0);
    }

    // 对拍：与 std::reverse 逐字节一致（60 组固定种子），并验证"翻两次 = 原样"
    std::mt19937 rng(20261002);
    for (int round = 0; round < 60; ++round) {
        std::size_t len = rng() % 65;
        std::vector<char> mine(len), ref(len), orig(len);
        for (std::size_t i = 0; i < len; ++i) {
            char c = static_cast<char>('a' + rng() % 26);
            mine[i] = c;
            orig[i] = c;
        }
        ref = orig;
        std::reverse(ref.begin(), ref.end());
        asm_reverse(mine.data(), static_cast<long long>(len));
        CHECK(mine == ref);                          // 与 std::reverse 一致
        asm_reverse(mine.data(), static_cast<long long>(len));
        CHECK(mine == orig);                         // 翻两次回到原样
    }

    std::printf("  [字符串反转] %lld 项\n", asmlab::checker().mark() - m0);
}

// ---------------------------------------------------------------- 斐波那契

static unsigned long long fib_ref(long n) {
    unsigned long long a = 0, b = 1;
    for (long i = 0; i < n; ++i) {
        unsigned long long t = a + b;
        a = b;
        b = t;
    }
    return a;
}

static void test_fib() {
    long long m0 = asmlab::checker().mark();

    const unsigned long long hand[11] = {0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55};
    for (long n = 0; n <= 10; ++n) CHECK(asm_fib(n) == hand[n]);
    CHECK(asm_fib(20) == 6765ULL);
    CHECK(asm_fib(50) == 12586269025ULL);
    CHECK(asm_fib(93) == 12200160415121876738ULL);   // u64 下最后一个不溢出值

    // 对拍 0..93 全量（参照 = C++ 迭代版）
    for (long n = 0; n <= 93; ++n) CHECK(asm_fib(n) == fib_ref(n));
    CHECK(asm_fib(-1) == 0 && asm_fib(-100) == 0);   // 负数 = 0

    std::printf("  [斐波那契] %lld 项\n", asmlab::checker().mark() - m0);
}

// ---------------------------------------------------------------- 排序

static void test_sort() {
    long long m0 = asmlab::checker().mark();

    {
        long long a[] = {3, 1, 2};
        asm_sort(a, 3);
        CHECK(a[0] == 1 && a[1] == 2 && a[2] == 3);
    }
    {
        long long a[] = {5};
        asm_sort(a, 1);
        CHECK(a[0] == 5);
    }
    asm_sort(nullptr, 0);                          // n=0：不解引用指针
    {
        long long a[] = {9, 7, 7, 3, 7, 1, -2, 0, -5};
        asm_sort(a, 9);
        bool sorted = true;
        for (int i = 1; i < 9; ++i) sorted = sorted && a[i - 1] <= a[i];
        CHECK(sorted);
        CHECK(a[0] == -5 && a[1] == -2 && a[2] == 0 && a[8] == 9);
    }
    {
        long long a[] = {4, 3, 2, 1};
        asm_sort(a, 4);
        CHECK(a[0] == 1 && a[3] == 4);
    }

    // 对拍：与 std::sort 逐元素一致（60 组固定种子，含大量重复值）
    std::mt19937 rng(7);
    for (int round = 0; round < 60; ++round) {
        std::size_t n = rng() % 41;
        std::vector<long long> mine(n), ref(n);
        for (std::size_t i = 0; i < n; ++i) {
            long long v = static_cast<long long>(rng() % 21) - 10;   // -10..10：重复多
            mine[i] = v;
            ref[i] = v;
        }
        std::sort(ref.begin(), ref.end());
        asm_sort(mine.data(), static_cast<long long>(n));
        bool same = true;
        for (std::size_t i = 0; i < n; ++i) same = same && mine[i] == ref[i];
        CHECK(same);
    }

    std::printf("  [排序] %lld 项\n", asmlab::checker().mark() - m0);
}

// ---------------------------------------------------------------- 栈帧函数

static long long sum_ref(const long long* arr, long long n) {
    long long s = 0;
    for (long i = 0; i < n; ++i) {
        if (arr[i] > 0) s += arr[i];
    }
    return s;
}

static void test_sum_positive() {
    long long m0 = asmlab::checker().mark();

    CHECK(asm_sum_positive(nullptr, 0) == 0);
    {
        long long a[] = {-1, -2, -3};
        CHECK(asm_sum_positive(a, 3) == 0);
    }
    {
        long long a[] = {1, -2, 3, 0, 5};
        CHECK(asm_sum_positive(a, 5) == 9);
    }
    {
        long long a[] = {7};
        CHECK(asm_sum_positive(a, 1) == 7);
    }

    std::mt19937 rng(99);
    for (int round = 0; round < 60; ++round) {
        std::size_t n = rng() % 41;
        std::vector<long long> arr(n);
        for (std::size_t i = 0; i < n; ++i) arr[i] = static_cast<long long>(rng() % 201) - 100;
        CHECK(asm_sum_positive(arr.data(), static_cast<long long>(n)) == sum_ref(arr.data(), static_cast<long long>(n)));
    }

    std::printf("  [栈帧函数 sum_positive] %lld 项\n", asmlab::checker().mark() - m0);
}

// ---------------------------------------------------------------- ABI 探针

static void test_abi_probe() {
    long long m0 = asmlab::checker().mark();

    char buf[8] = "abcd";
    long long arr3[3] = {3, 1, 2};
    long long arr5[5] = {-1, 2, -3, 4, 5};

    CHECK(probe(asm_reverse, reinterpret_cast<long long>(buf), 4) == 0);
    CHECK(probe(asm_fib, 20, 0) == 0);
    CHECK(probe(asm_sort, reinterpret_cast<long long>(arr3), 3) == 0);
    CHECK(probe(asm_sum_positive, reinterpret_cast<long long>(arr5), 5) == 0);

    // 反面自证：探针必须抓住"故意不保存 rbx"的 abi_bad_clobber（bit0）
    long bad = probe(abi_bad_clobber, 0, 0);
    CHECK(bad == 1);
    std::printf("    探针掩码（0=干净）：reverse=%ld fib=%ld sort=%ld sum=%ld 反面教材=%ld\n",
                probe(asm_reverse, reinterpret_cast<long long>(buf), 4),
                probe(asm_fib, 20, 0),
                probe(asm_sort, reinterpret_cast<long long>(arr3), 3),
                probe(asm_sum_positive, reinterpret_cast<long long>(arr5), 5),
                bad);

    std::printf("  [ABI 探针] %lld 项\n", asmlab::checker().mark() - m0);
}

int main() {
    std::printf("B6-asm-lab 自测：汇编函数边界 + 与 C++ 参照对拍 + ABI 探针\n");
    test_reverse();
    test_fib();
    test_sort();
    test_sum_positive();
    test_abi_probe();
    return asmlab::checker().report("B6 自测");
}
