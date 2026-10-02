// ds/check.hpp —— 极简断言计数器（与 B1 同款，各自项目自带：测试脚手架不跨项目引用）
//
// 设计说明：断言不是"抛异常就崩"，而是**计数 + 只印前若干条失败**——
// 几万项检查不可能靠眼睛看，能看的是"通过多少、失败多少、第一处失败在哪"。
#pragma once

#include <cstdio>

namespace ds {

struct Checker {
    long long passed = 0;
    long long failed = 0;
    int shown = 0;
    static constexpr int kMaxShown = 20;

    void check(bool ok, const char* expr, const char* file, int line) {
        if (ok) {
            ++passed;
            return;
        }
        ++failed;
        if (shown < kMaxShown) {
            std::printf("FAIL %s:%d  %s\n", file, line, expr);
            ++shown;
        } else if (shown == kMaxShown) {
            std::printf("...（更多失败略过；只看前 %d 条）\n", kMaxShown);
            ++shown;
        }
    }

    long long mark() const { return passed + failed; }

    int report(const char* name) const {
        std::printf("%s：%lld 项通过，%lld 项失败\n", name, passed, failed);
        return failed == 0 ? 0 : 1;
    }
};

inline Checker& checker() {
    static Checker c;
    return c;
}

}  // namespace ds

#define CHECK(cond) ::ds::checker().check((cond), #cond, __FILE__, __LINE__)
