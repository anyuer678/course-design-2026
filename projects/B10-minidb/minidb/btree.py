"""minidb/btree.py —— B+ 树（整数键，用于主键索引）

与 B 树的区别：数据只存叶子；叶子之间用链表串起来——
所以范围查询（BETWEEN / > / <）是"定位 + 顺序走链"，这是索引扫描的本质。

结构：阶 order：内部节点最多 order-1 个键；叶子最多 order-1 个 (key, value)。
实现采用教材常见写法：插入满则分裂（键上移），删除借用/合并。
"""
from __future__ import annotations


class _Leaf:
    __slots__ = ("keys", "vals", "next")

    def __init__(self):
        self.keys: list[int] = []
        self.vals: list = []
        self.next: "_Leaf | None" = None


class _Node:
    __slots__ = ("keys", "kids")

    def __init__(self):
        self.keys: list[int] = []
        self.kids: list = []      # _Node 或 _Leaf；len(kids) == len(keys)+1


class BPlusTree:
    def __init__(self, order: int = 8):
        if order < 4:
            raise ValueError("order >= 4")
        self.order = order
        self.root: _Node | _Leaf = _Leaf()

    # ------------------------------------------------ 查找
    def _find_leaf(self, key: int):
        node = self.root
        while isinstance(node, _Node):
            i = 0
            while i < len(node.keys) and key >= node.keys[i]:
                i += 1
            node = node.kids[i]
        return node

    def search(self, key: int):
        """精确查找；找到返回 value，否则 None。O(log n)。"""
        leaf = self._find_leaf(key)
        i = 0
        while i < len(leaf.keys) and leaf.keys[i] < key:
            i += 1
        if i < len(leaf.keys) and leaf.keys[i] == key:
            return leaf.vals[i]
        return None

    def range_scan(self, lo, hi):
        """[lo, hi] 范围扫描：定位叶子后沿叶子链走——索引扫描的原理。
        lo / hi 传 None 表示那一侧无界（只有 `pk < 5` 时不需要下界）。"""
        leaf = self._first_leaf() if lo is None else self._find_leaf(lo)
        out = []
        while leaf is not None:
            for k, v in zip(leaf.keys, leaf.vals):
                if hi is not None and k > hi:
                    return out
                if lo is None or k >= lo:
                    out.append((k, v))
            leaf = leaf.next
        return out

    def _first_leaf(self):
        node = self.root
        while isinstance(node, _Node):
            node = node.kids[0]
        return node

    def items(self):
        """全量按键有序遍历（叶子链）。"""
        node = self._first_leaf()
        out = []
        while node is not None:
            out.extend(zip(node.keys, node.vals))
            node = node.next
        return out

    # ------------------------------------------------ 插入
    def insert(self, key: int, value) -> None:
        leaf = self._find_leaf(key)
        i = 0
        while i < len(leaf.keys) and leaf.keys[i] < key:
            i += 1
        if i < len(leaf.keys) and leaf.keys[i] == key:
            leaf.vals[i] = value                # 覆盖（索引语义）
            return
        leaf.keys.insert(i, key)
        leaf.vals.insert(i, value)
        if len(leaf.keys) < self.order:
            return
        # 叶子分裂：右半移入新叶子，最小键上移（叶子里的键保留！B+树特点）
        mid = len(leaf.keys) // 2
        right = _Leaf()
        right.keys, right.vals = leaf.keys[mid:], leaf.vals[mid:]
        leaf.keys, leaf.vals = leaf.keys[:mid], leaf.vals[:mid]
        right.next, leaf.next = leaf.next, right
        self._grow(leaf, right.keys[0], right)

    def _grow(self, left, sep_key: int, right) -> None:
        """把 (left, sep_key, right) 上推到父层；根满则加高一层。"""
        parent = self._parent(self.root, left)
        if parent is None:                       # left 是根：加高一层
            new_root = _Node()
            new_root.keys = [sep_key]
            new_root.kids = [left, right]
            self.root = new_root
            return
        i = parent.kids.index(left)
        parent.keys.insert(i, sep_key)
        parent.kids.insert(i + 1, right)
        if len(parent.keys) >= self.order:
            # 内部节点分裂：中间键上移（内部键不下放！B 树家族共同点）
            mid = len(parent.keys) // 2
            up = parent.keys[mid]
            right_node = _Node()
            right_node.keys = parent.keys[mid + 1:]
            right_node.kids = parent.kids[mid + 1:]
            parent.keys = parent.keys[:mid]
            parent.kids = parent.kids[:mid + 1]
            self._grow(parent, up, right_node)

    def _parent(self, node, target):
        """在 node 子树中找 target 的父节点。"""
        if not isinstance(node, _Node):
            return None
        for kid in node.kids:
            if kid is target:
                return node
        for kid in node.kids:
            if isinstance(kid, _Node):
                found = self._parent(kid, target)
                if found is not None:
                    return found
        return None

    # ------------------------------------------------ 删除
    def delete(self, key: int) -> bool:
        leaf = self._find_leaf(key)
        i = 0
        while i < len(leaf.keys) and leaf.keys[i] < key:
            i += 1
        if i >= len(leaf.keys) or leaf.keys[i] != key:
            return False
        leaf.keys.pop(i)
        leaf.vals.pop(i)
        if len(leaf.keys) >= self.order // 2 - 1 or leaf is self.root:
            if not leaf.keys and leaf is self.root:
                pass                              # 空根，允许
            return True
        self._rebalance(leaf)
        return True

    def _rebalance(self, node) -> None:
        """节点欠满：先向兄弟借，借不到就合并，再向上递归修复。
        叶子与内部节点的借/合并规则不同：内部节点要"拉父键下来"。"""
        if node is self.root:
            if isinstance(node, _Node) and len(node.kids) == 1:
                self.root = node.kids[0]          # 根只剩一个孩子：树降高
            return
        parent = self._parent(self.root, node)
        i = parent.kids.index(node)
        min_keys = self.order // 2 - 1
        # --- 借左兄弟 ---
        if i > 0 and len(parent.kids[i - 1].keys) > min_keys:
            sib = parent.kids[i - 1]
            if isinstance(node, _Leaf):
                node.keys.insert(0, sib.keys.pop())
                node.vals.insert(0, sib.vals.pop())
                parent.keys[i - 1] = node.keys[0]
            else:
                node.keys.insert(0, parent.keys[i - 1])   # 父键下放
                parent.keys[i - 1] = sib.keys.pop()       # 兄弟键上位
                node.kids.insert(0, sib.kids.pop())
            return
        # --- 借右兄弟 ---
        if i < len(parent.kids) - 1 and len(parent.kids[i + 1].keys) > min_keys:
            sib = parent.kids[i + 1]
            if isinstance(node, _Leaf):
                node.keys.append(sib.keys.pop(0))
                node.vals.append(sib.vals.pop(0))
                parent.keys[i] = sib.keys[0]
            else:
                node.keys.append(parent.keys[i])
                parent.keys[i] = sib.keys.pop(0)
                node.kids.append(sib.kids.pop(0))
            return
        # --- 合并（优先左兄弟）---
        if i > 0:
            sib = parent.kids[i - 1]
            sep = parent.keys.pop(i - 1)
            if isinstance(node, _Leaf):
                sib.keys.extend(node.keys)
                sib.vals.extend(node.vals)
                sib.next = node.next
            else:
                sib.keys.append(sep)             # 分隔键并入左兄弟
                sib.keys.extend(node.keys)
                sib.kids.extend(node.kids)
            parent.kids.pop(i)
            under = sib
        else:
            sib = parent.kids[i + 1]
            sep = parent.keys.pop(i)
            if isinstance(node, _Leaf):
                node.keys.extend(sib.keys)
                node.vals.extend(sib.vals)
                node.next = sib.next
            else:
                node.keys.append(sep)
                node.keys.extend(sib.keys)
                node.kids.extend(sib.kids)
            parent.kids.pop(i + 1)
            under = node
        # 父节点可能也欠满；根欠满则整树降高
        if parent is self.root:
            if not parent.keys and len(parent.kids) == 1:
                self.root = parent.kids[0]
        elif len(parent.keys) < min_keys:
            self._rebalance(parent)
