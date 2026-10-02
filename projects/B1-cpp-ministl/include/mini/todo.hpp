// mini/todo.hpp —— 待办清单：CRUD + 文件回读（B1 的"综合应用"部分）
//
// 课程要点：
//   - 这是"容器 + 字符串 + RAII"的综合练习：清单本体用 mini::vector，文本用 mini::string，
//     持久化用 FileHandle（RAII：离开作用域一定 fclose，中途抛异常也关）；
//   - **文件回读**要能对账：save 出来的格式，load 回来必须逐字段相等（round-trip）；
//     文件缺失 = 空清单（首次运行），格式坏 = 抛错带行号（不猜、不静默跳过）；
//   - 行格式 `id|done|text`，text 里的 `\\`、换行、`|`、`\0` 按固定规则转义——
//     转义存在的意义就是"分隔符不会在数据里出现"。
#pragma once

#include <cstdio>
#include <stdexcept>
#include <string>

#include "mini/string.hpp"
#include "mini/vector.hpp"

namespace mini {

// RAII：构造即打开（失败抛错），析构即关闭。禁止拷贝——两个对象管一个句柄 = 双重关闭。
class FileHandle {
public:
    FileHandle(const std::string& path, const char* mode) {
        file_ = std::fopen(path.c_str(), mode);
        if (!file_) throw std::runtime_error("无法打开文件: " + path);
    }

    // 接管一个已经打开的句柄（load 用它把"存在性判断"与"RAII"分开：
    // std::fopen 返回空表示"文件不存在"，这是流程语义；打开成功之后才需要 RAII）
    FileHandle(std::FILE* file, const std::string& path) : file_(file) {
        if (!file_) throw std::runtime_error("FileHandle 接管了空句柄: " + path);
    }

    ~FileHandle() {
        if (file_) std::fclose(file_);
    }

    FileHandle(const FileHandle&) = delete;
    FileHandle& operator=(const FileHandle&) = delete;

    std::FILE* get() const { return file_; }

private:
    std::FILE* file_ = nullptr;
};

struct TodoItem {
    long id = 0;
    string text;
    bool done = false;
};

class TodoList {
public:
    long add(const string& text) {
        TodoItem item;
        item.id = next_id_++;
        item.text = text;
        item.done = false;
        items_.push_back(item);
        return item.id;
    }

    bool update(long id, const string& text) {
        TodoItem* it = find(id);
        if (!it) return false;
        it->text = text;
        return true;
    }

    bool toggle(long id) {
        TodoItem* it = find(id);
        if (!it) return false;
        it->done = !it->done;
        return true;
    }

    bool remove(long id) {
        for (std::size_t i = 0; i < items_.size(); ++i) {
            if (items_[i].id == id) {
                items_.erase(items_.begin() + static_cast<std::ptrdiff_t>(i));
                return true;
            }
        }
        return false;
    }

    TodoItem* find(long id) {
        for (std::size_t i = 0; i < items_.size(); ++i) {
            if (items_[i].id == id) return &items_[i];
        }
        return nullptr;
    }

    const TodoItem* find(long id) const {
        for (std::size_t i = 0; i < items_.size(); ++i) {
            if (items_[i].id == id) return &items_[i];
        }
        return nullptr;
    }

    const vector<TodoItem>& items() const { return items_; }
    std::size_t size() const { return items_.size(); }
    bool empty() const { return items_.empty(); }

    void save(const std::string& path) const {
        FileHandle out(path, "wb");
        for (std::size_t i = 0; i < items_.size(); ++i) {
            const TodoItem& it = items_[i];
            std::string line = std::to_string(it.id) + "|" +
                               (it.done ? "1" : "0") + "|" + escape(it.text);
            std::fputs(line.c_str(), out.get());
            std::fputc('\n', out.get());
        }
    }

    static TodoList load(const std::string& path) {
        TodoList list;
        std::FILE* raw = std::fopen(path.c_str(), "rb");
        if (!raw) return list;                  // 首次运行：没有文件 = 空清单
        FileHandle in(raw, path);               // 从这里起，抛异常也会 fclose

        std::string line;
        long line_no = 0;
        int ch;
        while ((ch = std::fgetc(in.get())) != EOF) {
            if (ch == '\n') {
                ++line_no;
                if (!line.empty()) parse_line(list, line, line_no);
                line.clear();
            } else {
                line.push_back(static_cast<char>(ch));
            }
        }
        if (!line.empty()) {                    // 文件末尾没有换行也算一行
            ++line_no;
            parse_line(list, line, line_no);
        }
        return list;
    }

private:
    vector<TodoItem> items_;
    long next_id_ = 1;

    static std::string escape(const string& text) {
        std::string out;
        for (std::size_t i = 0; i < text.size(); ++i) {
            char c = text[i];
            if (c == '\\') out += "\\\\";
            else if (c == '\n') out += "\\n";
            else if (c == '|') out += "\\p";
            else if (c == '\0') out += "\\0";
            else out += c;
        }
        return out;
    }

    static string unescape(const std::string& raw, long line_no) {
        string out;
        for (std::size_t i = 0; i < raw.size(); ++i) {
            if (raw[i] != '\\') {
                out += raw[i];
                continue;
            }
            if (i + 1 >= raw.size()) {
                throw std::runtime_error("第 " + std::to_string(line_no) + " 行：转义符后没有字符");
            }
            char nxt = raw[++i];
            if (nxt == '\\') out += '\\';
            else if (nxt == 'n') out += '\n';
            else if (nxt == 'p') out += '|';
            else if (nxt == '0') out += '\0';
            else {
                throw std::runtime_error("第 " + std::to_string(line_no) +
                                         " 行：未知转义 \\" + nxt);
            }
        }
        return out;
    }

    static void parse_line(TodoList& list, const std::string& line, long line_no) {
        std::size_t p1 = line.find('|');
        std::size_t p2 = p1 == std::string::npos ? std::string::npos
                                                 : line.find('|', p1 + 1);
        if (p1 == std::string::npos || p2 == std::string::npos) {
            throw std::runtime_error("第 " + std::to_string(line_no) + " 行格式错误: " + line);
        }
        TodoItem item;
        try {
            item.id = std::stol(line.substr(0, p1));
        } catch (const std::exception&) {
            throw std::runtime_error("第 " + std::to_string(line_no) +
                                     " 行 id 不是数字: " + line.substr(0, p1));
        }
        std::string done = line.substr(p1 + 1, p2 - p1 - 1);
        if (done != "0" && done != "1") {
            throw std::runtime_error("第 " + std::to_string(line_no) +
                                     " 行 done 字段不是 0/1: " + done);
        }
        item.done = (done == "1");
        item.text = unescape(line.substr(p2 + 1), line_no);
        if (item.id >= list.next_id_) list.next_id_ = item.id + 1;
        list.items_.push_back(item);
    }
};

}  // namespace mini
