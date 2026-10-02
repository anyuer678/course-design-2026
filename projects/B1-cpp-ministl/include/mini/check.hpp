// mini/check.hpp —— 极简断言计数器：给"几万项断言"一个诚实的数法
//
// 设计说明（课程要点：把验证本身也当作工程对象）：
//   - 断言不是"抛异常就崩"，而是**计数 + 只印前若干条失败**：38244 这种量级的检查
//     不可能靠眼睛看，能看的是"通过多少、失败多少、第一处失败在哪";
//   - 失败里带 `文件:行` 与表达式原文——和标准断言一致的最小信息集；
//   - report() 返回进程退出码（0/1），run.bat 只认退出码。
#pragma once

#include <cstdio>

namespace mini {

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

}  // namespace mini

#define CHECK(cond) ::mini::checker().check((cond), #cond, __FILE__, __LINE__)
