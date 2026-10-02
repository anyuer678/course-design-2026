// ds/menu.hpp —— 交互菜单：给"数据结构实验台"一个可点着玩的前台
//
// 设计说明（为什么菜单做成"函数"而不是 main 里的循环）：
//   - `run_menu(in, out)` 的输入输出是参数 → 测试可以拿 istringstream 当键盘，
//     把一整段菜单操作脚本喂进去并断言输出——**交互界面也能被自动化测**；
//   - 正式运行时 main 传 std::cin/std::cout；脚本演示（--demo）走的是另一条路径；
//   - 每个结构一个小灶台：输入命令与参数 → 打印结果 → 回到主菜单。
#pragma once

#include <istream>
#include <ostream>
#include <string>
#include <vector>

#include "ds/bst.hpp"
#include "ds/graph.hpp"
#include "ds/hash.hpp"
#include "ds/heap.hpp"
#include "ds/linkedlist.hpp"
#include "ds/queue.hpp"
#include "ds/seqlist.hpp"
#include "ds/stack.hpp"
#include "ds/unionfind.hpp"

namespace ds {

namespace detail {

inline void print_seqlist(std::ostream& out, const SeqList<int>& list) {
    out << "[";
    for (std::size_t i = 0; i < list.size(); ++i) {
        if (i) out << " ";
        out << list[i];
    }
    out << "] size=" << list.size() << " capacity=" << list.capacity()
        << " moves=" << list.moves() << " comparisons=" << list.comparisons() << "\n";
}

inline void print_linkedlist(std::ostream& out, const LinkedList<int>& list) {
    out << "[";
    for (std::size_t i = 0; i < list.size(); ++i) {
        if (i) out << " ";
        out << list.at(i);
    }
    out << "] size=" << list.size() << " hops=" << list.hops()
        << " links=" << list.links() << "\n";
}

inline bool read_int(std::istream& in, int& v) {
    if (in >> v) return true;
    in.clear();
    std::string junk;
    std::getline(in, junk);
    return false;
}

// 读一个"菜单选项"：EOF → false（调用者退出）；非法内容 → 丢掉该行、op=-1（显示无此选项后继续）
inline bool read_op(std::istream& in, int& op) {
    if (in >> op) return true;
    if (in.eof()) return false;
    in.clear();
    std::string junk;
    std::getline(in, junk);
    op = -1;
    return true;
}

}  // namespace detail

// 返回 0 = 正常退出（选 0 或输入流结束）
inline int run_menu(std::istream& in, std::ostream& out) {
    SeqList<int> seq;
    LinkedList<int> linked;
    ArrayQueue<int> queue(8);
    BST<int> tree;
    HashChaining hash(16);
    Heap<int> heap;
    UnionFind uf(10);
    Graph graph(8);

    out << "== B2 数据结构实验台 ==\n";
    while (true) {
        out << "\n 1) 顺序表   2) 单链表   3) 栈/表达式   4) 循环队列(容量8)\n"
               " 5) 二叉搜索树 6) 哈希表(16桶,链地址) 7) 堆   8) 并查集(10结点)\n"
               " 9) 图遍历(8结点)   0) 退出\n选择: ";
        int choice = -1;
        if (!detail::read_op(in, choice)) return 0;
        if (choice == 0) return 0;

        if (choice == 1) {
            while (true) {
                out << " 顺序表: 1 追加 2 下标插入 3 下标删除 4 查找 5 打印 6 计时清零 0 返回: ";
                int op = -1;
                if (!detail::read_op(in, op)) return 0;
                if (op == 0) break;
                if (op == 1 || op == 4) {
                    int v;
                    out << " 值: ";
                    if (!detail::read_int(in, v)) { out << " 非法输入\n"; continue; }
                    if (op == 1) { seq.push_back(v); out << " 已追加\n"; }
                    else {
                        std::size_t idx = seq.find(v);
                        out << (idx == SeqList<int>::npos ? " 未找到"
                                                          : " 找到于下标 " + std::to_string(idx))
                            << "\n";
                    }
                } else if (op == 2 || op == 3) {
                    int idx, v = 0;
                    out << " 下标: ";
                    if (!detail::read_int(in, idx)) { out << " 非法输入\n"; continue; }
                    if (op == 2) {
                        out << " 值: ";
                        if (!detail::read_int(in, v)) { out << " 非法输入\n"; continue; }
                    }
                    try {
                        if (op == 2) { seq.insert(static_cast<std::size_t>(idx), v); out << " 已插入\n"; }
                        else { seq.erase(static_cast<std::size_t>(idx)); out << " 已删除\n"; }
                    } catch (const std::exception& e) {
                        out << " 失败: " << e.what() << "\n";
                    }
                } else if (op == 5) {
                    detail::print_seqlist(out, seq);
                } else if (op == 6) {
                    seq.reset_counters();
                    out << " 计数已清零\n";
                }
            }
        } else if (choice == 2) {
            while (true) {
                out << " 单链表: 1 头插 2 尾插 3 按下标插 4 按下标删 5 反转 6 查找 7 打印 0 返回: ";
                int op = -1;
                if (!detail::read_op(in, op)) return 0;
                if (op == 0) break;
                int idx, v = 0;
                if (op == 1 || op == 2) {
                    out << " 值: ";
                    if (!detail::read_int(in, v)) { out << " 非法输入\n"; continue; }
                    if (op == 1) linked.push_front(v); else linked.push_back(v);
                    out << " 已插入\n";
                } else if (op == 3 || op == 4) {
                    out << " 下标: ";
                    if (!detail::read_int(in, idx)) { out << " 非法输入\n"; continue; }
                    if (op == 3) {
                        out << " 值: ";
                        if (!detail::read_int(in, v)) { out << " 非法输入\n"; continue; }
                    }
                    try {
                        if (op == 3) { linked.insert_at(static_cast<std::size_t>(idx), v); out << " 已插入\n"; }
                        else { linked.erase_at(static_cast<std::size_t>(idx)); out << " 已删除\n"; }
                    } catch (const std::exception& e) {
                        out << " 失败: " << e.what() << "\n";
                    }
                } else if (op == 5) {
                    linked.reverse();
                    out << " 已反转\n";
                } else if (op == 6) {
                    out << " 值: ";
                    if (!detail::read_int(in, v)) { out << " 非法输入\n"; continue; }
                    std::size_t at = linked.find(v);
                    out << (at == LinkedList<int>::npos ? " 未找到"
                                                        : " 找到于下标 " + std::to_string(at))
                        << "\n";
                } else if (op == 7) {
                    detail::print_linkedlist(out, linked);
                }
            }
        } else if (choice == 3) {
            while (true) {
                out << " 栈: 1 括号匹配（下一行输表达式） 2 中缀表达式求值（下一行，如 (1+2)*3) 0 返回: ";
                int op = -1;
                if (!detail::read_op(in, op)) return 0;
                if (op == 0) break;
                std::string line;
                std::getline(in, line);      // 吃掉 op 行的换行残留
                if (line.empty()) std::getline(in, line);   // 表达式在下一行
                while (!line.empty() && line[0] == ' ') line.erase(0, 1);
                if (op == 1) {
                    out << (brackets_match(line) ? " 括号匹配" : " 不匹配") << "\n";
                } else if (op == 2) {
                    try {
                        std::string post = infix_to_postfix(line);
                        out << " 后缀式: " << post << " ；求值 = " << eval_postfix(post) << "\n";
                    } catch (const std::exception& e) {
                        out << " 失败: " << e.what() << "\n";
                    }
                }
            }
        } else if (choice == 4) {
            while (true) {
                out << " 循环队列: 1 入队 2 出队 3 打印(含 head/tail) 0 返回: ";
                int op = -1;
                if (!detail::read_op(in, op)) return 0;
                if (op == 0) break;
                if (op == 1) {
                    int v;
                    out << " 值: ";
                    if (!detail::read_int(in, v)) { out << " 非法输入\n"; continue; }
                    try {
                        queue.push(v);
                        out << " 已入队（head=" << queue.head() << " tail=" << queue.tail()
                            << " size=" << queue.size() << "）\n";
                    } catch (const std::exception& e) {
                        out << " 失败: " << e.what() << "\n";
                    }
                } else if (op == 2) {
                    try {
                        int v = queue.front();
                        queue.pop();
                        out << " 出队 " << v << "（head=" << queue.head() << " tail=" << queue.tail()
                            << " size=" << queue.size() << "）\n";
                    } catch (const std::exception& e) {
                        out << " 失败: " << e.what() << "\n";
                    }
                } else if (op == 3) {
                    out << " head=" << queue.head() << " tail=" << queue.tail()
                        << " size=" << queue.size() << "/" << queue.capacity() << "\n";
                }
            }
        } else if (choice == 5) {
            while (true) {
                out << " BST: 1 插入 2 删除 3 查找 4 中序打印 5 高度 0 返回: ";
                int op = -1;
                if (!detail::read_op(in, op)) return 0;
                if (op == 0) break;
                int v = 0;
                if (op >= 1 && op <= 3) {
                    out << " 值: ";
                    if (!detail::read_int(in, v)) { out << " 非法输入\n"; continue; }
                }
                if (op == 1) out << (tree.insert(v) ? " 已插入" : " 已存在（未重复插入）") << "\n";
                else if (op == 2) out << (tree.erase(v) ? " 已删除" : " 不存在") << "\n";
                else if (op == 3) out << (tree.contains(v) ? " 在树中" : " 不在树中") << "\n";
                else if (op == 4) {
                    SeqList<int> order;
                    tree.in_order(order);
                    out << " 中序:";
                    for (std::size_t i = 0; i < order.size(); ++i) out << " " << order[i];
                    out << "（size=" << tree.size() << "）\n";
                } else if (op == 5) {
                    out << " 高度 = " << tree.height() << "（size=" << tree.size() << "）\n";
                }
            }
        } else if (choice == 6) {
            while (true) {
                out << " 哈希(链地址): 1 插入 2 查找 3 删除 4 统计 0 返回: ";
                int op = -1;
                if (!detail::read_op(in, op)) return 0;
                if (op == 0) break;
                if (op >= 1 && op <= 3) {
                    int v;
                    out << " 键: ";
                    if (!detail::read_int(in, v)) { out << " 非法输入\n"; continue; }
                    if (op == 1) out << (hash.insert(v) ? " 已插入" : " 已存在") << "\n";
                    else if (op == 2) out << (hash.contains(v) ? " 找到" : " 未找到") << "\n";
                    else out << (hash.erase(v) ? " 已删除" : " 不存在") << "\n";
                } else if (op == 4) {
                    out << " size=" << hash.size() << " buckets=" << hash.buckets()
                        << " longest_chain=" << hash.longest_chain()
                        << " probes=" << hash.probes() << "\n";
                }
            }
        } else if (choice == 7) {
            while (true) {
                out << " 堆(小顶): 1 插入 2 取顶 3 打印 0 返回: ";
                int op = -1;
                if (!detail::read_op(in, op)) return 0;
                if (op == 0) break;
                if (op == 1) {
                    int v;
                    out << " 值: ";
                    if (!detail::read_int(in, v)) { out << " 非法输入\n"; continue; }
                    heap.push(v);
                    out << " 已插入（top=" << heap.top() << "）\n";
                } else if (op == 2) {
                    if (heap.empty()) { out << " 空堆\n"; continue; }
                    int top = heap.top();
                    heap.pop();
                    out << " 取出 " << top << "\n";
                } else if (op == 3) {
                    out << " size=" << heap.size() << " 堆序完好="
                        << (heap.verify() ? "是" : "否") << "\n";
                }
            }
        } else if (choice == 8) {
            while (true) {
                out << " 并查集: 1 合并 a b 2 查询连通 a b 3 分量数 4 步数 0 返回: ";
                int op = -1;
                if (!detail::read_op(in, op)) return 0;
                if (op == 0) break;
                if (op == 1 || op == 2) {
                    int a, b;
                    out << " a b: ";
                    if (!(in >> a >> b)) { in.clear(); out << " 非法输入\n"; continue; }
                    try {
                        if (op == 1) {
                            out << (uf.unite(static_cast<std::size_t>(a), static_cast<std::size_t>(b))
                                        ? " 已合并" : " 本来就连通")
                                << "\n";
                        } else {
                            out << (uf.connected(static_cast<std::size_t>(a), static_cast<std::size_t>(b))
                                        ? " 连通" : " 不连通")
                                << "\n";
                        }
                    } catch (const std::exception& e) {
                        out << " 失败: " << e.what() << "\n";
                    }
                } else if (op == 3) {
                    out << " 分量数 = " << uf.components() << "\n";
                } else if (op == 4) {
                    out << " find 步数累计 = " << uf.steps() << "\n";
                }
            }
        } else if (choice == 9) {
            while (true) {
                out << " 图(8结点,无向): 1 加边 u v 2 BFS 3 DFS 4 连通分量 0 返回: ";
                int op = -1;
                if (!detail::read_op(in, op)) return 0;
                if (op == 0) break;
                if (op == 1) {
                    int u, v;
                    out << " u v: ";
                    if (!(in >> u >> v)) { in.clear(); out << " 非法输入\n"; continue; }
                    try {
                        graph.add_edge(u, v);
                        out << " 已加边\n";
                    } catch (const std::exception& e) {
                        out << " 失败: " << e.what() << "\n";
                    }
                } else if (op == 2 || op == 3) {
                    int s;
                    out << " 起点: ";
                    if (!detail::read_int(in, s)) { out << " 非法输入\n"; continue; }
                    try {
                        if (op == 2) {
                            std::vector<int> dist, order;
                            graph.bfs(s, dist, order);
                            out << " BFS 序:";
                            for (int u : order) out << " " << u;
                            out << " ；距离:";
                            for (std::size_t i = 0; i < dist.size(); ++i) {
                                out << " " << (dist[i] < 0 ? -1 : dist[i]);
                            }
                            out << "\n";
                        } else {
                            std::vector<int> order;
                            graph.dfs(s, order);
                            out << " DFS 序:";
                            for (int u : order) out << " " << u;
                            out << "\n";
                        }
                    } catch (const std::exception& e) {
                        out << " 失败: " << e.what() << "\n";
                    }
                } else if (op == 4) {
                    out << " 连通分量数 = " << graph.components() << "\n";
                }
            }
        } else {
            out << " 无此选项\n";
        }
    }
}

}  // namespace ds
