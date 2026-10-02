"""algo/divide.py —— 分治：归并排序顺便数出逆序对。

**为什么能分治**：数组 a 的逆序对分成三类——两元都在左半、都在右半、一左一右。
前两类是子问题，第三类在"合并两个有序块"时能一次算完：

    当右块的 a[j] 要先进结果时，它比左块剩下的 a[i..mid) 每一个都小，
    而这些元素在原数组里的下标都在 j 之前 → 这 mid-i 对全是逆序对，一次加进去。

**递归不变式**：`_sort(lo, hi)` 返回后 a[lo:hi] 有序，返回值是这一段内部的逆序对数
（按进入本层时的原始顺序计）。等号方向是这个不变式的命门：`a[i] <= a[j]` 让相等元素
保持"左块先出"，相等就不计数；写成 `a[i] < a[j]` 会把相等元素算成逆序对。
"""
from __future__ import annotations


def merge_sort_count(seq):
    """返回 (升序列表, 逆序对数)。"""
    items = list(seq)
    if len(items) < 2:
        return items, 0
    buffer = [0] * len(items)
    total = _sort(items, buffer, 0, len(items))
    return items, total


def count_inversions(seq) -> int:
    """逆序对数：满足 i < j 且 a[i] > a[j] 的下标对个数。"""
    items = list(seq)
    if len(items) < 2:
        return 0
    buffer = [0] * len(items)
    return _sort(items, buffer, 0, len(items))


def _sort(a, buffer, lo, hi) -> int:
    if hi - lo <= 1:
        return 0
    mid = (lo + hi) // 2
    total = _sort(a, buffer, lo, mid) + _sort(a, buffer, mid, hi)
    i, j, k = lo, mid, lo
    while i < mid and j < hi:
        if a[i] <= a[j]:
            buffer[k] = a[i]
            i += 1
        else:
            buffer[k] = a[j]
            j += 1
            total += mid - i          # 右块这个元素比左块剩下的每个都构成逆序对
        k += 1
    while i < mid:
        buffer[k] = a[i]
        i, k = i + 1, k + 1
    while j < hi:
        buffer[k] = a[j]
        j, k = j + 1, k + 1
    a[lo:hi] = buffer[lo:hi]
    return total


def brute_force_inversions(seq) -> int:
    """O(n^2) 参照实现：把定义直接翻译成代码，不含任何技巧。"""
    a = list(seq)
    return sum(1 for i in range(len(a))
               for j in range(i + 1, len(a)) if a[i] > a[j])
