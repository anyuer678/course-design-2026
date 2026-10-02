// ds/bst.hpp —— 二叉搜索树：插入 / 查找 / 删除（三种情形都在）/ 中序遍历
//
// 课程要点：
//   - BST 的**有序性靠不变量维持**：左子树 < 根 < 右子树。中序遍历天然升序——
//     测试就拿它当"全树有序"的整树检查；
//   - 删除是三分支题：叶（直接摘）、单子（子树上提）、双子（用**中序后继**替换值再删后继）；
//   - 升序插入会退化成长链（高度 = n）——"随机插入高度 ≈ 1.39·log2(n)"是实测对照，
//     不是背来的（演示里两种插入顺序各算一次高度）；
//   - 本实现不做平衡（AVL/红黑树是 PLAN 的选做项），`height()` 就是给退化现象量尺子的。
#pragma once

#include <cstddef>
#include <stdexcept>
#include <utility>

#include "ds/seqlist.hpp"

namespace ds {

template <class T>
class BST {
    struct Node {
        T value;
        Node* left = nullptr;
        Node* right = nullptr;
        explicit Node(const T& v) : value(v) {}
    };

public:
    BST() = default;
    BST(const BST& other) { copy_from(other.root_); }
    BST& operator=(const BST& other) {
        if (this != &other) {
            BST tmp(other);
            swap(tmp);
        }
        return *this;
    }
    ~BST() { release(root_); }

    bool empty() const { return size_ == 0; }
    std::size_t size() const { return size_; }

    // 插入：重复值不插（返回 false）——教学版策略，写清楚比默默多插一个好
    bool insert(const T& v) {
        Node** link = &root_;
        while (*link) {
            ++comparisons_;
            if (v < (*link)->value) {
                link = &(*link)->left;
            } else if ((*link)->value < v) {
                link = &(*link)->right;
            } else {
                return false;
            }
        }
        *link = new Node(v);
        ++size_;
        return true;
    }

    bool contains(const T& v) const {
        const Node* cur = root_;
        while (cur) {
            ++comparisons_;
            if (v < cur->value) cur = cur->left;
            else if (cur->value < v) cur = cur->right;
            else return true;
        }
        return false;
    }

    bool erase(const T& v) {
        Node** link = &root_;
        while (*link) {
            Node* cur = *link;
            ++comparisons_;
            if (v < cur->value) {
                link = &cur->left;
            } else if (cur->value < v) {
                link = &cur->right;
            } else {
                remove_node(cur, link);
                --size_;
                return true;
            }
        }
        return false;
    }

    // 中序遍历：**追加**到调用者的容器（不清空 out——递归写法天然是追加，
    // 复用同一容器前请自行 clear；演示/菜单每次都开新容器，不受影响）
    void in_order(SeqList<T>& out) const { in_order(root_, out); }
    void pre_order(SeqList<T>& out) const { pre_order(root_, out); }

    // 高度：空树 0、单结点 1（口径写明，避免和"边数计法"混淆）
    std::size_t height() const { return height(root_); }

    const T& min() const {
        if (!root_) throw std::out_of_range("ds::BST::min 空树");
        return leftmost(root_)->value;
    }
    const T& max() const {
        if (!root_) throw std::out_of_range("ds::BST::max 空树");
        return rightmost(root_)->value;
    }

    std::size_t comparisons() const { return comparisons_; }
    void reset_counters() { comparisons_ = 0; }

    void swap(BST& other) noexcept {
        std::swap(root_, other.root_);
        std::swap(size_, other.size_);
    }

private:
    Node* root_ = nullptr;
    std::size_t size_ = 0;
    mutable std::size_t comparisons_ = 0;

    static Node* leftmost(Node* n) {
        while (n->left) n = n->left;
        return n;
    }
    static Node* rightmost(Node* n) {
        while (n->right) n = n->right;
        return n;
    }

    // link 指向"指向 cur 的指针"，替换/摘除都在这里落刀
    void remove_node(Node* cur, Node** link) {
        if (!cur->left) {
            *link = cur->right;               // 叶与单子（右）合并处理
            delete cur;
        } else if (!cur->right) {
            *link = cur->left;
            delete cur;
        } else {
            // 双子：找到右子树最左（中序后继），把它的值搬上来，再删后继（后继必无左子）
            Node** succ_link = &cur->right;
            Node* succ = cur->right;
            while (succ->left) {
                ++comparisons_;
                succ_link = &succ->left;
                succ = succ->left;
            }
            cur->value = succ->value;
            *succ_link = succ->right;
            delete succ;
        }
    }

    static void in_order(const Node* n, SeqList<T>& out) {
        if (!n) return;
        in_order(n->left, out);
        out.push_back(n->value);
        in_order(n->right, out);
    }
    static void pre_order(const Node* n, SeqList<T>& out) {
        if (!n) return;
        out.push_back(n->value);
        pre_order(n->left, out);
        pre_order(n->right, out);
    }
    static std::size_t height(const Node* n) {
        if (!n) return 0;
        std::size_t l = height(n->left);
        std::size_t r = height(n->right);
        return 1 + (l > r ? l : r);
    }

    void copy_from(const Node* n) {
        if (!n) return;
        insert(n->value);                     // 前序重建即可（值唯一）
        copy_from(n->left);
        copy_from(n->right);
    }

    static void release(Node* n) {
        if (!n) return;
        release(n->left);
        release(n->right);
        delete n;
    }
};

}  // namespace ds
