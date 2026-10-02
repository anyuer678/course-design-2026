"""nlp25/segment.py —— 中文分词：正向/逆向最大匹配（FMM / BMM）

课程要点：
    - 最大匹配是**贪心**算法：每步取"词典里能匹配的最长前缀"。
      贪心不保证全局最优——经典反例"研究生命起源"：
        FMM: 研究生 / 命 / 起源   （最长优先，把"生命"拆坏了）
        BMM: 研究 / 生命 / 起源   （从右往左扫描，碰巧切对）
      两个结果都合法，分歧本身就是"歧义检测"信号。
    - 未登录词（词典没有的词）回退成单字——这是最大匹配的天然行为，
      也是它精度上限的来源（真正的分词器用统计模型解决，见 HMM 扩展）。

约定（写死，测试按此对拍）：
    - 词典命中与否区分大小写与全半角（本实现不做归一化，输入须预处理）；
    - 单字永远合法（回退通道），因此任何输入都能被完整切分；
    - 平局不存在：同一位置同长度只有一种匹配（词典是集合）。
"""
from __future__ import annotations

from .dictionary import DICTIONARY


def fmm(text: str, dictionary: frozenset[str] = DICTIONARY) -> list[str]:
    """正向最大匹配：从左到右，每步取最长词典前缀，未命中回退单字。"""
    out: list[str] = []
    i = 0
    max_len = max((len(w) for w in dictionary), default=1)
    while i < len(text):
        # 从最长的候选往下找，找到即取（贪心）
        for length in range(min(max_len, len(text) - i), 1, -1):
            cand = text[i:i + length]
            if cand in dictionary:
                out.append(cand)
                i += length
                break
        else:
            out.append(text[i])               # 单字回退
            i += 1
    return out


def bmm(text: str, dictionary: frozenset[str] = DICTIONARY) -> list[str]:
    """逆向最大匹配：从右到左做同样的贪心。与 FMM 互为歧义探针。"""
    out: list[str] = []
    i = len(text)
    max_len = max((len(w) for w in dictionary), default=1)
    while i > 0:
        for length in range(min(max_len, i), 1, -1):
            cand = text[i - length:i]
            if cand in dictionary:
                out.append(cand)
                i -= length
                break
        else:
            out.append(text[i - 1])
            i -= 1
    out.reverse()
    return out


def is_valid(tokens: list[str], dictionary: frozenset[str] = DICTIONARY) -> bool:
    """切分合法性：每个词要么在词典里，要么是单字（回退通道）。"""
    return all(t in dictionary or len(t) == 1 for t in tokens)


def segment(text: str) -> dict:
    """双向切分 + 歧义标注。返回 {'fmm', 'bmm', 'ambiguous'}。"""
    fwd, bwd = fmm(text), bmm(text)
    return {"fmm": fwd, "bmm": bwd, "ambiguous": fwd != bwd}
