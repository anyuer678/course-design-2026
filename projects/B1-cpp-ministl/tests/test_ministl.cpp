// tests/test_ministl.cpp —— B1 自测：与 std 容器对拍 + 边界 + RAII + 待办回读
//
// 纪律（和本仓库其它项目一致）：
//   1. 期望值来自手算或独立参照：手算的小表逐条写死；大批量行为交给
//      `mini/fuzz.hpp` 的随机对拍（种子固定，失败可复现）；
//   2. 每条断言都能回答"被什么改动弄红"；
//   3. 临时文件只写**系统临时目录**，并断言不在工作目录里（事故后加的纪律），
//      用完即删；RAII 那条专门用"删除成功"来证明句柄真的关了。
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <list>
#include <stdexcept>
#include <string>
#include <vector>

#include "mini/check.hpp"
#include "mini/fuzz.hpp"
#include "mini/list.hpp"
#include "mini/string.hpp"
#include "mini/todo.hpp"
#include "mini/vector.hpp"

// ---------------------------------------------------------------- 工具

static int g_temp_counter = 0;

// 临时文件路径：必须在系统临时目录、且**不在工作目录（仓库）里面**
static std::filesystem::path temp_path(const char* tag) {
    std::filesystem::path dir = std::filesystem::temp_directory_path();
    std::filesystem::path cwd = std::filesystem::current_path();
    std::string d = dir.string();
    std::string c = cwd.string();
    bool inside_cwd = d.size() >= c.size() && d.compare(0, c.size(), c) == 0;
    if (inside_cwd) {
        throw std::runtime_error("临时目录意外落在工作目录里: " + d);
    }
    return dir / (std::string("b1-ministl-") + tag + "-" + std::to_string(++g_temp_counter) + ".tmp");
}

static void write_raw(const std::filesystem::path& p, const std::string& content) {
    std::FILE* f = std::fopen(p.string().c_str(), "wb");
    if (!f) throw std::runtime_error("write_raw 打不开: " + p.string());
    std::fwrite(content.data(), 1, content.size(), f);
    std::fclose(f);
}

static std::string read_raw(const std::filesystem::path& p) {
    std::FILE* f = std::fopen(p.string().c_str(), "rb");
    if (!f) return {};
    std::string out;
    int ch;
    while ((ch = std::fgetc(f)) != EOF) out.push_back(static_cast<char>(ch));
    std::fclose(f);
    return out;
}

static std::size_t count_lines(const std::string& s) {
    std::size_t n = 0;
    for (char c : s) {
        if (c == '\n') ++n;
    }
    return n;
}

// 生命周期探针：静态计数器数"现在还活着几个"
struct Tracker {
    static int live;
    int v;
    explicit Tracker(int value = 0) : v(value) { ++live; }
    Tracker(const Tracker& o) : v(o.v) { ++live; }
    Tracker(Tracker&& o) noexcept : v(o.v) { ++live; }
    Tracker& operator=(const Tracker&) = default;
    Tracker& operator=(Tracker&&) = default;
    ~Tracker() { --live; }
};
int Tracker::live = 0;

// ---------------------------------------------------------------- vector 边界

static void test_vector_edges() {
    long long m0 = mini::checker().mark();

    mini::vector<int> v;
    CHECK(v.empty());
    CHECK(v.size() == 0);
    CHECK(v.begin() == v.end());

    for (int i = 1; i <= 8; ++i) v.push_back(i * 10);
    CHECK(v.size() == 8);
    CHECK(v.capacity() == 8);           // 实现自证：4 → 8 的翻倍增长
    CHECK(v.front() == 10 && v.back() == 80);
    CHECK(v[0] == 10 && v[7] == 80);
    bool order_ok = true;
    for (std::size_t i = 0; i < v.size(); ++i) order_ok = order_ok && (v[i] == static_cast<int>((i + 1) * 10));
    CHECK(order_ok);

    mini::vector<int> lit{1, 2, 3};
    CHECK(lit.size() == 3 && lit[0] == 1 && lit[2] == 3);

    bool threw = false;
    try {
        (void)v.at(8);
    } catch (const std::out_of_range&) {
        threw = true;
    }
    CHECK(threw);
    threw = false;
    mini::vector<int> empty_v;
    try {
        (void)empty_v.at(0);
    } catch (const std::out_of_range&) {
        threw = true;
    }
    CHECK(threw);

    // insert：头、中、尾三处，逐元素核对
    v.insert(v.begin(), 5);                      // 5 10 20 ... 80
    CHECK(v.size() == 9 && v.front() == 5);
    v.insert(v.begin() + 5, 999);                // 5 10 20 30 40 999 50 ...
    CHECK(v[5] == 999 && v[4] == 40 && v[6] == 50);
    v.insert(v.end(), 111);                      // 尾部
    CHECK(v.back() == 111 && v.size() == 11);

    // erase 返回下一个位置的迭代器
    auto it = v.erase(v.begin() + 5);            // 删掉 999
    CHECK(*it == 50);
    it = v.erase(v.begin());                     // 删掉 5
    CHECK(*it == 10);
    it = v.erase(v.end() - 1);                   // 删掉 111 → 返回 end()
    CHECK(it == v.end());
    CHECK(v.size() == 8);

    // resize：变小析构、变大补默认值/填充值
    v.resize(3);
    CHECK(v.size() == 3 && v[2] == 30);
    v.resize(5);
    CHECK(v.size() == 5 && v[3] == 0 && v[4] == 0);
    v.resize(6, 7);
    CHECK(v.size() == 6 && v[5] == 7);

    // 拷贝独立性 + 自赋值
    mini::vector<int> copy(v);
    v[0] = -1;
    CHECK(copy[0] == 10 && v[0] == -1);
    mini::vector<int>& self = v;
    v = self;
    CHECK(v[0] == -1 && v.size() == 6);

    // 移动：偷缓冲，源变空但仍可安全析构/复用
    mini::vector<int> moved(std::move(v));
    CHECK(moved.size() == 6 && moved[0] == -1);
    CHECK(v.empty() && v.capacity() == 0);
    v.push_back(42);                             // 移动后的源可以继续用
    CHECK(v.size() == 1 && v[0] == 42);

    // clear 不还容量（实现自证），pop 到空
    mini::vector<int> cap_check{1, 2, 3, 4, 5};
    std::size_t cap_before = cap_check.capacity();
    cap_check.clear();
    CHECK(cap_check.empty());
    CHECK(cap_check.capacity() == cap_before);
    while (!cap_check.empty()) cap_check.pop_back();
    CHECK(cap_check.size() == 0);

    std::printf("  [vector 边界] %lld 项\n", mini::checker().mark() - m0);
}

// ---------------------------------------------------------------- list 边界

static void test_list_edges() {
    long long m0 = mini::checker().mark();

    mini::list<int> l;
    CHECK(l.empty() && l.size() == 0);
    CHECK(l.begin() == l.end());

    for (int i = 1; i <= 5; ++i) l.push_back(i);      // 1 2 3 4 5
    l.push_front(0);                                   // 0 1 2 3 4 5
    CHECK(l.size() == 6);
    CHECK(l.front() == 0 && l.back() == 5);

    // 迭代器稳定性：插了头尾之后，指到中间的迭代器仍指同一元素
    auto mid = l.begin();
    for (int i = 0; i < 3; ++i) ++mid;                 // 0 1 2 3 4 5，begin+3 → 3
    CHECK(*mid == 3);
    l.push_front(-1);
    l.push_back(6);
    CHECK(*mid == 3);                                  // 其余迭代器不失效，这正是链表的意义

    // 反向走：--end 是最后一个元素
    auto backward = l.end();
    --backward;
    CHECK(*backward == 6);

    // insert/erase 的返回值
    auto pos = l.begin();
    ++pos;                                             // → 0（-1 之后）
    auto inserted = l.insert(pos, 99);                 // -1 99 0 1 2 3 4 5 6
    CHECK(*inserted == 99);
    CHECK(l.size() == 9);
    auto nxt = l.erase(inserted);
    CHECK(*nxt == 0);                                  // erase 返回下一个
    CHECK(l.size() == 8);

    l.pop_front();
    l.pop_back();
    CHECK(l.front() == 0 && l.back() == 5);

    // 范围 for 与手写求和
    int sum = 0;
    for (int x : l) sum += x;
    CHECK(sum == 0 + 1 + 2 + 3 + 4 + 5);

    // 拷贝独立 + 移动把源清空
    mini::list<int> copy(l);
    l.push_back(777);
    CHECK(copy.size() == 6 && l.size() == 7);
    mini::list<int> moved(std::move(l));
    CHECK(moved.size() == 7 && moved.back() == 777);
    CHECK(l.empty());
    l.push_back(1);                                    // 移动后的源可以继续用
    CHECK(l.size() == 1);

    // const 遍历（const_iterator）
    const mini::list<int>& cl = copy;
    int csum = 0;
    for (mini::list<int>::const_iterator it = cl.begin(); it != cl.end(); ++it) csum += *it;
    CHECK(csum == 15);

    // clear 后复用
    l.clear();
    CHECK(l.empty() && l.begin() == l.end());
    l.push_front(3);
    CHECK(l.size() == 1 && l.front() == 3);

    std::printf("  [list 边界] %lld 项\n", mini::checker().mark() - m0);
}

// ---------------------------------------------------------------- string 边界

static void test_string_edges() {
    long long m0 = mini::checker().mark();

    mini::string s("hello");
    CHECK(s.size() == 5 && s.length() == 5 && !s.empty());
    CHECK(std::strcmp(s.c_str(), "hello") == 0);
    CHECK(s[0] == 'h' && s.at(4) == 'o');

    bool threw = false;
    try {
        (void)s.at(5);
    } catch (const std::out_of_range&) {
        threw = true;
    }
    CHECK(threw);

    s += ", world";
    CHECK(s.size() == 12 && std::strcmp(s.c_str(), "hello, world") == 0);
    s.append('!');
    s.append("!");
    CHECK(s == mini::string("hello, world!!"));

    mini::string joined = s + mini::string("?");
    CHECK(joined.size() == 15 && joined[14] == '?');
    CHECK(s.size() == 14);                              // operator+ 不改原串

    // 比较：前缀关系、相等、大小
    CHECK(mini::string("ab") < mini::string("abc"));
    CHECK(mini::string("") < mini::string("a"));
    CHECK(mini::string("abc") < mini::string("abd"));
    CHECK(mini::string("abc") == mini::string("abc"));
    CHECK(mini::string("abc") != mini::string("ab"));
    CHECK(mini::string("b") > mini::string("abc"));
    CHECK(mini::string("abc") <= mini::string("abc"));

    // find
    mini::string hay("abcabc");
    CHECK(hay.find('b') == 1);
    CHECK(hay.find('b', 2) == 4);
    CHECK(hay.find('z') == mini::string::npos);
    CHECK(hay.find("cab") == 2);
    CHECK(hay.find("zz") == mini::string::npos);
    CHECK(hay.find("") == 0);

    // substr：截断、越界的两种情形
    CHECK(hay.substr(2, 3) == mini::string("cab"));
    CHECK(hay.substr(4, 100) == mini::string("bc"));    // n 超长自动截断
    CHECK(hay.substr(6, 1).empty());                    // pos == size 合法，得空串
    threw = false;
    try {
        (void)hay.substr(7, 1);
    } catch (const std::out_of_range&) {
        threw = true;
    }
    CHECK(threw);

    // 自追加两型：s += s（走 append(const string&)）与 s += s.c_str()（走 const char* 路径）
    mini::string d("ab");
    d += d;
    CHECK(d == mini::string("abab"));
    d += d;
    CHECK(d.size() == 8 && d == mini::string("abababab"));
    mini::string e("xy");
    e.append(e.c_str());
    CHECK(e == mini::string("xyxy"));
    e += e.c_str();
    CHECK(e.size() == 8 && e == mini::string("xyxyxyxy"));

    // 内嵌 '\0'：长度记账与字节保真
    mini::string raw("a\0b", 3);
    CHECK(raw.size() == 3 && raw[1] == '\0' && raw[2] == 'b');
    mini::string raw_copy(raw);
    CHECK(raw_copy.size() == 3 && raw_copy == raw);
    mini::string raw_moved(std::move(raw));
    CHECK(raw_moved.size() == 3 && raw_moved[1] == '\0');
    CHECK(raw.empty());                                 // 移动后的源为空但仍可用
    raw += 'z';
    CHECK(raw.size() == 1 && raw[0] == 'z');

    // 自赋值
    mini::string& self = raw_copy;
    raw_copy = self;
    CHECK(raw_copy.size() == 3 && raw_copy[2] == 'b');

    // clear 后复用
    raw_copy.clear();
    CHECK(raw_copy.empty() && std::strcmp(raw_copy.c_str(), "") == 0);
    raw_copy += "again";
    CHECK(raw_copy == mini::string("again"));

    std::printf("  [string 边界] %lld 项\n", mini::checker().mark() - m0);
}

// ---------------------------------------------------------------- RAII

static void test_raii() {
    long long m0 = mini::checker().mark();

    // 元素生命周期：push 之后活着 20 个；clear 之后归零；离开作用域整体归零
    {
        mini::vector<Tracker> tv;
        for (int i = 0; i < 20; ++i) tv.push_back(Tracker(i));
        CHECK(Tracker::live == 20);
        int live_before_move = Tracker::live;
        mini::vector<Tracker> borrowed(std::move(tv));
        CHECK(Tracker::live == live_before_move);       // 移动不新建对象
        CHECK(tv.empty());
        borrowed.clear();
        CHECK(Tracker::live == 0);
    }
    CHECK(Tracker::live == 0);                          // 析构把账还清

    // 文件句柄：离开作用域后 fclose 一定发生——用"能不能删除"来取证
    std::filesystem::path p = temp_path("raii");
    {
        mini::FileHandle f(p.string(), "wb");
        std::fputs("probe", f.get());
    }
    std::error_code ec;
    bool removed = std::filesystem::remove(p, ec);
    CHECK(removed && !ec);                              // 句柄没关的话，Windows 上这步会失败

    // 中途抛异常也要关：作用域里 throw，catch 之后同样应该能删
    std::filesystem::path p2 = temp_path("raii-throw");
    try {
        mini::FileHandle f(p2.string(), "wb");
        std::fputs("x", f.get());
        throw std::runtime_error("演示用异常");
    } catch (const std::runtime_error&) {
        // 吞掉：这里验证的是析构
    }
    removed = std::filesystem::remove(p2, ec);
    CHECK(removed && !ec);

    // 打不开时必须抛错，而不是给个"坏句柄"继续
    bool threw = false;
    try {
        mini::FileHandle bad((std::filesystem::temp_directory_path() / "b1-no-such-dir-xyz" / "f.txt").string(), "rb");
    } catch (const std::runtime_error&) {
        threw = true;
    }
    CHECK(threw);

    // 临时路径纪律自证：临时文件不在工作目录里
    CHECK(p.string().find(std::filesystem::current_path().string()) != 0);

    std::printf("  [RAII] %lld 项\n", mini::checker().mark() - m0);
}

// ---------------------------------------------------------------- 待办：CRUD + 回读

static void test_todo() {
    long long m0 = mini::checker().mark();

    mini::TodoList list;
    long a = list.add("买牛奶");
    long b = list.add("写 README");
    long c = list.add("复习离散");
    CHECK(a == 1 && b == 2 && c == 3);
    CHECK(list.size() == 3);
    CHECK(list.find(a) != nullptr && list.find(a)->text == mini::string("买牛奶"));
    CHECK(list.find(99) == nullptr);

    CHECK(list.toggle(a));
    CHECK(list.find(a)->done);
    CHECK(list.update(b, "写 README\n第二行"));
    CHECK(list.find(b)->text == mini::string("写 README\n第二行"));   // 含换行的文本原样保存
    CHECK(list.remove(c));
    CHECK(list.find(c) == nullptr);
    CHECK(list.size() == 2);
    CHECK(!list.update(99, "不存在"));
    CHECK(!list.toggle(99));
    CHECK(!list.remove(99));

    // 回读对账：save → load 逐字段相等（含 \n、|、\\、'0' 等转义字符与空串）
    mini::TodoList tricky;
    tricky.add("带|竖线");
    tricky.add("反斜杠\\结尾");
    tricky.add("换行\n在中间");
    tricky.add("");
    tricky.add("普通");
    long last = tricky.add("末尾无换行");
    tricky.toggle(2);

    std::filesystem::path p = temp_path("todo");
    tricky.save(p.string());
    std::string raw = read_raw(p);
    CHECK(count_lines(raw) == 6);                       // 6 条记录 = 6 个换行

    mini::TodoList back = mini::TodoList::load(p.string());
    CHECK(back.size() == tricky.size());
    bool same = true;
    for (std::size_t i = 0; i < back.size(); ++i) {
        const mini::TodoItem& x = tricky.items()[i];
        const mini::TodoItem& y = back.items()[i];
        same = same && (x.id == y.id) && (x.done == y.done) && (x.text == y.text);
    }
    CHECK(same);
    CHECK(back.find(2)->done);

    // 回读之后继续 add：id 不重复
    long nid = back.add("新增");
    CHECK(nid == last + 1);
    std::error_code ec;
    std::filesystem::remove(p, ec);

    // 加载不存在的文件 = 空清单（首次运行）
    mini::TodoList missing = mini::TodoList::load(temp_path("todo-missing").string());
    CHECK(missing.empty());

    // 坏格式必须抛错、且报行号
    auto expect_load_error = [](const std::string& content, const char* needle) {
        std::filesystem::path bad = temp_path("todo-bad");
        write_raw(bad, content);
        bool threw = false;
        std::string msg;
        try {
            mini::TodoList::load(bad.string());
        } catch (const std::runtime_error& e) {
            threw = true;
            msg = e.what();
        }
        std::error_code ec2;
        std::filesystem::remove(bad, ec2);
        CHECK(threw);
        CHECK(msg.find(needle) != std::string::npos);
    };
    expect_load_error("abc|def\n", "第 1 行格式错误");
    expect_load_error("1|0|ok\nx9|1|t\n", "第 2 行 id 不是数字");
    expect_load_error("1|0|ok\n2|5|t\n", "第 2 行 done 字段不是 0/1");
    expect_load_error("1|0|a\\q\n", "未知转义");
    expect_load_error("1|0|tail\\\n", "转义符后没有字符");

    // 内嵌 '\0' 的文本也要能回读
    mini::TodoList nul;
    mini::string with_nul("a\0b", 3);
    nul.add(with_nul);
    std::filesystem::path pn = temp_path("todo-nul");
    nul.save(pn.string());
    mini::TodoList nul_back = mini::TodoList::load(pn.string());
    CHECK(nul_back.size() == 1 && nul_back.items()[0].text.size() == 3);
    CHECK(nul_back.items()[0].text[1] == '\0');
    std::filesystem::remove(pn, ec);

    std::printf("  [待办 CRUD/回读] %lld 项\n", mini::checker().mark() - m0);
}

// ---------------------------------------------------------------- 与 std 对拍

static void test_crosscheck() {
    long long m0 = mini::checker().mark();
    long long total = 0;

    for (unsigned seed = 1; seed <= 60; ++seed) {
        mini::OpReport r = mini::crosscheck_vector(seed, 60);
        total += r.checks;
        CHECK(r.failures == 0);
        if (r.failures) std::printf("    vector 首处失败: %s\n", r.first_failure.c_str());
    }
    for (unsigned seed = 1; seed <= 40; ++seed) {
        mini::OpReport r = mini::crosscheck_list(seed, 60);
        total += r.checks;
        CHECK(r.failures == 0);
        if (r.failures) std::printf("    list 首处失败: %s\n", r.first_failure.c_str());
    }
    for (unsigned seed = 1; seed <= 40; ++seed) {
        mini::OpReport r = mini::crosscheck_string(seed, 60);
        total += r.checks;
        CHECK(r.failures == 0);
        if (r.failures) std::printf("    string 首处失败: %s\n", r.first_failure.c_str());
    }

    CHECK(total > 20000);                               // 对拍确实跑了"几万项"而不是几十项
    std::printf("  [与 std 容器对拍] 共 %lld 项检查（向量/链表/字符串三类随机操作序列）\n", total);
    std::printf("  [与 std 容器对拍] 断言 %lld 项\n", mini::checker().mark() - m0);
}

int main() {
    std::printf("B1-cpp-ministl 自测：边界 + RAII + 待办回读 + 与 std 容器对拍\n");
    test_vector_edges();
    test_list_edges();
    test_string_edges();
    test_raii();
    test_todo();
    test_crosscheck();
    return mini::checker().report("B1 自测");
}
