// ds/stack.hpp —— 栈：基于顺序表；外加两个经典应用（括号匹配 / 中缀转后缀）
//
// 课程要点：
//   - 栈就是"只在一端动的顺序表"：push/pop/top 全在尾巴上 → 三个操作都是 O(1)；
//   - 括号匹配是栈的最小用例：遇左括号入栈、遇右括号比对栈顶——**后进先出**恰好就是嵌套结构；
//   - 中缀转后缀（调度场算法的单目版）：操作数直接输出、运算符按优先级与栈顶比较，
//     后缀（逆波兰）再从左到右用栈求值，不需要任何括号；
//   - 限定：本实现面向单字符操作数与 + - * /（教学过程版本，多字符表达式见 README 的练习）。
#pragma once

#include <cstddef>
#include <stdexcept>
#include <string>

#include "ds/seqlist.hpp"

namespace ds {

template <class T>
class Stack {
public:
    bool empty() const { return list_.empty(); }
    std::size_t size() const { return list_.size(); }

    void push(const T& v) { list_.push_back(v); }
    void pop() {
        if (empty()) throw std::out_of_range("ds::Stack::pop 空栈");
        list_.erase(list_.size() - 1);
    }
    T& top() {
        if (empty()) throw std::out_of_range("ds::Stack::top 空栈");
        return list_[list_.size() - 1];
    }
    const T& top() const {
        if (empty()) throw std::out_of_range("ds::Stack::top 空栈");
        return list_[list_.size() - 1];
    }
    void clear() { list_.clear(); }

private:
    SeqList<T> list_;
};

// ---------------------------------------------------------------- 应用一：括号匹配

// 支持三种括号；遇到不配对的立即返回 false，最后栈必须为空
inline bool brackets_match(const std::string& text) {
    Stack<char> st;
    for (char c : text) {
        if (c == '(' || c == '[' || c == '{') {
            st.push(c);
        } else if (c == ')' || c == ']' || c == '}') {
            if (st.empty()) return false;
            char open = st.top();
            st.pop();
            bool ok = (c == ')' && open == '(') ||
                      (c == ']' && open == '[') ||
                      (c == '}' && open == '{');
            if (!ok) return false;
        }
    }
    return st.empty();
}

// ---------------------------------------------------------------- 应用二：中缀→后缀→求值

namespace detail {
inline int prec(char op) {
    return (op == '+' || op == '-') ? 1 : (op == '*' || op == '/') ? 2 : 0;
}
}  // namespace detail

// 整数操作数（连续数字算一个词）、无空格；非法字符抛错
inline std::string infix_to_postfix(const std::string& expr) {
    Stack<char> ops;
    std::string out;
    for (std::size_t i = 0; i < expr.size(); ++i) {
        char c = expr[i];
        if (c >= '0' && c <= '9') {
            out.push_back(c);                 // 连续数字当一个整数词
            bool more_digits = i + 1 < expr.size() && expr[i + 1] >= '0' && expr[i + 1] <= '9';
            if (!more_digits) out.push_back(' ');
        } else if (c == '+' || c == '-' || c == '*' || c == '/') {
            while (!ops.empty() && detail::prec(ops.top()) >= detail::prec(c)) {
                out.push_back(ops.top());
                out.push_back(' ');
                ops.pop();
            }
            ops.push(c);
        } else if (c == '(') {
            ops.push(c);
        } else if (c == ')') {
            while (!ops.empty() && ops.top() != '(') {
                out.push_back(ops.top());
                out.push_back(' ');
                ops.pop();
            }
            if (ops.empty()) throw std::runtime_error("括号不匹配: " + expr);
            ops.pop();                        // 弹掉 '('
        } else if (c == ' ') {
            throw std::runtime_error("表达式不能含空格: " + expr);
        } else {
            throw std::runtime_error(std::string("非法字符: ") + c);
        }
    }
    while (!ops.empty()) {
        if (ops.top() == '(') throw std::runtime_error("括号不匹配: " + expr);
        out.push_back(ops.top());
        out.push_back(' ');
        ops.pop();
    }
    if (!out.empty()) out.pop_back();         // 去掉末尾空格
    return out;
}

// 后缀求值：从左到右，操作数入栈，遇运算符取两个操作数（注意减/除的顺序）
inline long eval_postfix(const std::string& postfix) {
    Stack<long> st;
    long value = 0;
    bool have_digit = false;
    for (std::size_t i = 0; i <= postfix.size(); ++i) {
        char c = i < postfix.size() ? postfix[i] : ' ';
        if (c >= '0' && c <= '9') {
            value = value * 10 + (c - '0');   // 支持多位数（数字串累加）
            have_digit = true;
            continue;
        }
        if (have_digit) {
            st.push(value);
            value = 0;
            have_digit = false;
        }
        if (c == '+' || c == '-' || c == '*' || c == '/') {
            if (st.size() < 2) throw std::runtime_error("后缀式缺操作数: " + postfix);
            long b = st.top();
            st.pop();
            long a = st.top();
            st.pop();
            if (c == '+') st.push(a + b);
            if (c == '-') st.push(a - b);
            if (c == '*') st.push(a * b);
            if (c == '/') {
                if (b == 0) throw std::runtime_error("除以零: " + postfix);
                st.push(a / b);
            }
        }
    }
    if (st.size() != 1) throw std::runtime_error("后缀式多出操作数: " + postfix);
    return st.top();
}

}  // namespace ds
