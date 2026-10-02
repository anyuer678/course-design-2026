// src/main.cpp —— B1 演示：五段脚本，数字全部运行时现算，不抄文档
//
//   1) vector：增长曲线（何时换缓冲）、遍历、拷贝独立
//   2) list：头尾插入、正反向遍历（迭代器稳定性）
//   3) string：拼接、查找、子串、自追加（s += s）
//   4) 待办清单：CRUD → 存盘 → 回读逐字段对账 → 清理演示文件
//   5) 与 std::vector / std::list / std::string 的随机对拍汇总（种子固定）
//
// 演示不打印耗时（只有计数与内容），所以两次运行的输出应逐字相同。
#include <cstdio>
#include <filesystem>
#include <string>

#include "mini/fuzz.hpp"
#include "mini/list.hpp"
#include "mini/string.hpp"
#include "mini/todo.hpp"
#include "mini/vector.hpp"

static void section(int no, const char* title) {
    std::printf("\n============================================================\n");
    std::printf("  %d) %s\n", no, title);
    std::printf("============================================================\n");
}

static void dump_items(const mini::TodoList& list) {
    std::printf("   id  完成  文本\n");
    for (std::size_t i = 0; i < list.items().size(); ++i) {
        const mini::TodoItem& it = list.items()[i];
        std::printf("   %-4ld %-6s %s\n", it.id, it.done ? "是" : "否", it.text.c_str());
    }
}

int main() {
    std::printf("B1-cpp-ministl 演示：手写 vector / list / string + 待办清单 + 与标准库对拍\n");

    // ------------------------------------------------------------------ 1
    section(1, "vector：增长曲线、遍历、拷贝独立（RAII 管缓冲区）");
    mini::vector<int> v;
    std::size_t last_cap = v.capacity();
    for (int i = 1; i <= 10; ++i) {
        v.push_back(i * i);
        if (v.capacity() != last_cap) {
            std::printf("  第 %2d 次 push：size=%zu capacity=%zu（刚换了缓冲）\n",
                        i, v.size(), v.capacity());
            last_cap = v.capacity();
        }
    }
    std::printf("  内容：");
    for (std::size_t i = 0; i < v.size(); ++i) std::printf("%d ", v[i]);
    std::printf("（size=%zu，capacity=%zu）\n", v.size(), v.capacity());

    mini::vector<int> copy(v);
    v[0] = -1;
    std::printf("  改 v[0]=-1 之后：v[0]=%d，副本[0]=%d（深拷贝，互不影响）\n", v[0], copy[0]);

    // ------------------------------------------------------------------ 2
    section(2, "list：头尾插入、正反向遍历（插入不使其他迭代器失效）");
    mini::list<mini::string> tasks;
    tasks.push_back(mini::string("写代码"));
    tasks.push_back(mini::string("测试"));
    tasks.push_front(mini::string("列计划"));
    auto mid = tasks.begin();
    ++mid;                                            // → “写代码”
    std::printf("  正向：");
    for (auto it = tasks.begin(); it != tasks.end(); ++it) std::printf("%s / ", it->c_str());
    std::printf("\n  反向：");
    for (auto it = tasks.end(); it != tasks.begin();) {
        --it;
        std::printf("%s / ", it->c_str());
    }
    tasks.push_front(mini::string("开会"));
    std::printf("\n  头插“开会”后，之前指向中段的迭代器仍读作：%s\n", mid->c_str());

    // ------------------------------------------------------------------ 3
    section(3, "string：拼接、查找、子串、自追加（按字节记账）");
    mini::string s("离散");
    s += "结构：闭包";
    std::printf("  拼接后：%s（size=%zu 字节——UTF-8 下一个汉字 3 字节）\n", s.c_str(), s.size());
    std::printf("  find(\"闭\")=%zu（字节偏移）；substr(0,6)=%s（6 字节 = 两个汉字）\n",
                s.find("闭"), s.substr(0, 6).c_str());
    mini::string self("ab");
    self += self;                                     // 经典坑：自追加
    self += self;
    std::printf("  \"ab\" 自追加两次：%s（size=%zu，悬垂坑已被处理）\n",
                self.c_str(), self.size());

    // ------------------------------------------------------------------ 4
    section(4, "待办清单：CRUD → 存盘 → 回读逐字段对账 → 清理");
    mini::TodoList list;
    long id1 = list.add("买牛奶");
    long id2 = list.add("写课设 README");
    long id3 = list.add("复习离散：关系闭包|主范式");
    list.toggle(id1);
    list.update(id2, "写课设 README（补测试）");
    list.remove(id3);
    std::printf("  内存中（%zu 条；再删一条不存在的是否报错=%s）：\n",
                list.size(), list.remove(999) ? "是" : "否");
    dump_items(list);

    std::filesystem::path path = std::filesystem::path("build") / "todo_demo.txt";
    std::filesystem::create_directories(path.parent_path());
    list.save(path.string());
    std::printf("  存盘到 %s\n", path.string().c_str());

    mini::TodoList back = mini::TodoList::load(path.string());
    bool same = back.size() == list.size();
    for (std::size_t i = 0; same && i < back.size(); ++i) {
        const mini::TodoItem& x = list.items()[i];
        const mini::TodoItem& y = back.items()[i];
        same = (x.id == y.id) && (x.done == y.done) && (x.text == y.text);
    }
    std::printf("  回读 %zu 条，逐字段对账：%s\n", back.size(), same ? "一致" : "不一致！");
    std::printf("  回读后追加一条，id 从 %ld 继续（不重号）\n", back.add("演示新增"));

    std::error_code ec;
    bool cleaned = std::filesystem::remove(path, ec);
    std::printf("  演示文件已删除：%s\n", cleaned ? "是" : "否");
    if (!same || !cleaned) return 1;

    // ------------------------------------------------------------------ 5
    section(5, "与 std::vector / std::list / std::string 随机对拍（种子固定）");
    long long vec_checks = 0;
    for (unsigned seed = 1; seed <= 12; ++seed) {
        mini::OpReport r = mini::crosscheck_vector(seed, 80);
        vec_checks += r.checks;
        if (r.failures) { std::printf("  vector 有失败：%s\n", r.first_failure.c_str()); return 1; }
    }
    long long list_checks = 0;
    for (unsigned seed = 1; seed <= 8; ++seed) {
        mini::OpReport r = mini::crosscheck_list(seed, 80);
        list_checks += r.checks;
        if (r.failures) { std::printf("  list 有失败：%s\n", r.first_failure.c_str()); return 1; }
    }
    long long str_checks = 0;
    for (unsigned seed = 1; seed <= 8; ++seed) {
        mini::OpReport r = mini::crosscheck_string(seed, 80);
        str_checks += r.checks;
        if (r.failures) { std::printf("  string 有失败：%s\n", r.first_failure.c_str()); return 1; }
    }
    std::printf("  vector 对拍：12 种子 × 80 步 = %lld 项逐元素检查，0 失败\n", vec_checks);
    std::printf("  list   对拍： 8 种子 × 80 步 = %lld 项逐元素检查（含反向遍历），0 失败\n", list_checks);
    std::printf("  string 对拍： 8 种子 × 80 步 = %lld 项逐次对照（含自追加），0 失败\n", str_checks);
    std::printf("  合计 %lld 项检查\n", vec_checks + list_checks + str_checks);

    std::printf("\n============================================================\n");
    std::printf("完成：5 段演示全部跑通。演示无耗时输出，两遍运行应逐字相同。\n");
    return 0;
}
