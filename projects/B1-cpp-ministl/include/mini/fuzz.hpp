// mini/fuzz.hpp —— 随机操作对拍引擎：同一串操作分别施加到 mini 容器与 std 容器
//
// 课程要点（也是本项目的核心验收手法）：
//   - "与标准容器对拍"不能靠手写几个用例，要靠**同一段随机操作序列**分别喂给两边，
//     每一步之后逐元素比对——差异是"被操作序列找出来的"，不是我"想出来的"；
//   - 随机必须**种子固定**：`std::mt19937 rng(seed)`，分布用手写取模不用
//     `uniform_int_distribution`（后者的实现细节不保证跨编译器一致，复现性会漂）；
//   - 引擎被测试与演示**共用同一份**：测试拿它当几万项断言，演示拿它当汇总读数，
//     两边不可能出现"测的和演的其实不是一个对拍"（复用纪律，同 B19）。
#pragma once

#include <algorithm>
#include <cstddef>
#include <list>
#include <random>
#include <string>
#include <vector>

#include "mini/list.hpp"
#include "mini/string.hpp"
#include "mini/vector.hpp"

namespace mini {

struct OpReport {
    long long checks = 0;
    long long failures = 0;
    std::string first_failure;

    void fail(const std::string& what) {
        ++failures;
        if (first_failure.empty()) first_failure = what;
    }
};

inline OpReport crosscheck_vector(unsigned seed, int steps) {
    OpReport rep;
    std::mt19937 rng(seed);
    vector<int> a;
    std::vector<int> b;

    auto compare = [&](int step) {
        ++rep.checks;
        if (a.size() != b.size()) {
            rep.fail("vector seed=" + std::to_string(seed) + " step=" + std::to_string(step) +
                     " size " + std::to_string(a.size()) + " != " + std::to_string(b.size()));
        }
        ++rep.checks;
        if (a.capacity() < a.size()) {
            rep.fail("vector seed=" + std::to_string(seed) + " step=" + std::to_string(step) +
                     " capacity < size");
        }
        for (std::size_t i = 0; i < b.size(); ++i) {
            ++rep.checks;
            if (a[i] != b[i]) {
                rep.fail("vector seed=" + std::to_string(seed) + " step=" + std::to_string(step) +
                         " a[" + std::to_string(i) + "] != b[" + std::to_string(i) + "]");
                break;
            }
        }
    };

    for (int s = 0; s < steps; ++s) {
        unsigned op = rng() % 100;
        if (op < 35) {
            int v = static_cast<int>(rng() % 1000);
            a.push_back(v);
            b.push_back(v);
        } else if (op < 50) {
            if (!b.empty()) {
                a.pop_back();
                b.pop_back();
            }
        } else if (op < 62) {
            int v = static_cast<int>(rng() % 1000);
            std::size_t idx = rng() % (b.size() + 1);
            a.insert(a.begin() + static_cast<std::ptrdiff_t>(idx), v);
            b.insert(b.begin() + static_cast<std::ptrdiff_t>(idx), v);
        } else if (op < 72) {
            if (!b.empty()) {
                std::size_t idx = rng() % b.size();
                a.erase(a.begin() + static_cast<std::ptrdiff_t>(idx));
                b.erase(b.begin() + static_cast<std::ptrdiff_t>(idx));
            }
        } else if (op < 82) {
            if (!b.empty()) {
                std::size_t idx = rng() % b.size();
                int v = static_cast<int>(rng() % 1000);
                a[idx] = v;
                b[idx] = v;
            }
        } else if (op < 90) {
            std::size_t n = rng() % 40;
            a.resize(n);
            b.resize(n);
        } else if (op < 94) {
            a.reserve(a.capacity() + 1 + rng() % 16);
        } else if (op < 97) {
            std::size_t n = rng() % 8;
            int v = static_cast<int>(rng() % 1000);
            a.resize(n, v);
            b.resize(n, v);
        } else {
            if (b.size() > 5) {
                a.clear();
                b.clear();
            }
        }
        compare(s);
    }
    return rep;
}

inline OpReport crosscheck_list(unsigned seed, int steps) {
    OpReport rep;
    std::mt19937 rng(seed);
    list<int> a;
    std::list<int> b;

    auto at_std = [](std::list<int>& lst, std::size_t idx) {
        auto it = lst.begin();
        while (idx-- > 0) ++it;
        return it;
    };
    auto at_mini = [](list<int>& lst, std::size_t idx) {
        list<int>::iterator it = lst.begin();
        while (idx-- > 0) ++it;
        return it;
    };

    auto compare = [&](int step) {
        ++rep.checks;
        if (a.size() != b.size()) {
            rep.fail("list seed=" + std::to_string(seed) + " step=" + std::to_string(step) +
                     " size " + std::to_string(a.size()) + " != " + std::to_string(b.size()));
            return;
        }
        {
            list<int>::iterator ia = a.begin();
            auto ib = b.begin();
            std::size_t i = 0;
            for (; ib != b.end(); ++ib, ++ia, ++i) {
                ++rep.checks;
                if (*ia != *ib) {
                    rep.fail("list seed=" + std::to_string(seed) + " step=" + std::to_string(step) +
                             " 正向第 " + std::to_string(i) + " 个不同");
                    break;
                }
            }
        }
        {
            list<int>::iterator ia = a.end();
            auto ib = b.end();
            std::size_t i = b.size();
            while (ib != b.begin()) {
                --ib;
                --ia;
                --i;
                ++rep.checks;
                if (*ia != *ib) {
                    rep.fail("list seed=" + std::to_string(seed) + " step=" + std::to_string(step) +
                             " 反向第 " + std::to_string(i) + " 个不同");
                    break;
                }
            }
        }
    };

    for (int s = 0; s < steps; ++s) {
        unsigned op = rng() % 100;
        if (op < 30) {
            int v = static_cast<int>(rng() % 1000);
            a.push_back(v);
            b.push_back(v);
        } else if (op < 55) {
            int v = static_cast<int>(rng() % 1000);
            a.push_front(v);
            b.push_front(v);
        } else if (op < 70) {
            if (!b.empty()) {
                a.pop_back();
                b.pop_back();
            }
        } else if (op < 78) {
            if (!b.empty()) {
                a.pop_front();
                b.pop_front();
            }
        } else if (op < 90) {
            int v = static_cast<int>(rng() % 1000);
            std::size_t idx = rng() % (b.size() + 1);
            a.insert(at_mini(a, idx), v);
            b.insert(at_std(b, idx), v);
        } else {
            if (!b.empty()) {
                std::size_t idx = rng() % b.size();
                a.erase(at_mini(a, idx));
                b.erase(at_std(b, idx));
            }
        }
        compare(s);
    }
    return rep;
}

inline OpReport crosscheck_string(unsigned seed, int steps) {
    OpReport rep;
    std::mt19937 rng(seed);
    const char pool[] = "abcXYZ019_ |\\";     // 故意放进转义用的 '|' 与 '\\'
    const std::size_t pool_n = sizeof(pool) - 1;

    mini::string a("hello");
    std::string b("hello");

    auto compare = [&](int step) {
        ++rep.checks;
        if (a.size() != b.size()) {
            rep.fail("string seed=" + std::to_string(seed) + " step=" + std::to_string(step) +
                     " size " + std::to_string(a.size()) + " != " + std::to_string(b.size()));
            return;
        }
        ++rep.checks;
        if (std::string(a.c_str(), a.size()) != b) {
            rep.fail("string seed=" + std::to_string(seed) + " step=" + std::to_string(step) +
                     " c_str 视图不一致");
        }
        for (std::size_t i = 0; i < b.size(); ++i) {
            ++rep.checks;
            if (a[i] != b[i]) {
                rep.fail("string seed=" + std::to_string(seed) + " step=" + std::to_string(step) +
                         " 第 " + std::to_string(i) + " 个字符不同");
                break;
            }
        }
    };

    for (int s = 0; s < steps; ++s) {
        unsigned op = rng() % 100;
        if (op < 30) {
            std::string chunk;
            std::size_t n = rng() % 6;
            for (std::size_t i = 0; i < n; ++i) chunk += pool[rng() % pool_n];
            a.append(chunk.c_str());
            b.append(chunk);
        } else if (op < 40) {
            char c = pool[rng() % pool_n];
            a += c;
            b += c;
        } else if (op < 50) {
            char c = pool[rng() % pool_n];
            std::size_t from = rng() % (b.size() + 2);
            std::size_t fa = a.find(c, from);
            std::size_t fb = b.find(c, from);
            ++rep.checks;
            if ((fa == mini::string::npos) != (fb == std::string::npos) || fa != fb) {
                rep.fail("string seed=" + std::to_string(seed) + " step=" + std::to_string(s) +
                         " find(char) 不一致");
            }
        } else if (op < 58) {
            std::string needle;
            std::size_t n = 1 + rng() % 3;
            for (std::size_t i = 0; i < n; ++i) needle += pool[rng() % pool_n];
            std::size_t fa = a.find(needle.c_str());
            std::size_t fb = b.find(needle);
            ++rep.checks;
            if ((fa == mini::string::npos) != (fb == std::string::npos) || fa != fb) {
                rep.fail("string seed=" + std::to_string(seed) + " step=" + std::to_string(s) +
                         " find(串) 不一致");
            }
        } else if (op < 72) {
            std::size_t pos = rng() % (b.size() + 1);
            std::size_t n = rng() % (b.size() + 2);
            mini::string sa = a.substr(pos, n);
            std::string sb = b.substr(pos, n);
            ++rep.checks;
            if (std::string(sa.c_str(), sa.size()) != sb) {
                rep.fail("string seed=" + std::to_string(seed) + " step=" + std::to_string(s) +
                         " substr 不一致");
            }
        } else if (op < 80) {
            a += a;                          // 自追加：经典悬垂坑
            b += b;
        } else if (op < 88) {
            std::string other;
            std::size_t n = rng() % 5;
            for (std::size_t i = 0; i < n; ++i) other += pool[rng() % pool_n];
            mini::string ma(other.c_str());
            ++rep.checks;
            if ((a == ma) != (b == other)) {
                rep.fail("string seed=" + std::to_string(seed) + " step=" + std::to_string(s) +
                         " == 判定不一致");
            }
            ++rep.checks;
            if ((a < ma) != (b < other)) {
                rep.fail("string seed=" + std::to_string(seed) + " step=" + std::to_string(s) +
                         " < 判定不一致");
            }
        } else {
            if (b.size() > 10 && rng() % 4 == 0) {
                a.clear();
                b.clear();
            }
        }
        compare(s);
    }
    return rep;
}

}  // namespace mini
