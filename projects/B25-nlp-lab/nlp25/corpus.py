"""nlp25/corpus.py —— 种子化合成语料（来源：AI 按模板生成，非真实数据）

生成规则（全部可复现）：
    每条消息 = 从类别词池随机抽 3~5 个词 + 可选 1 个中性词，按抽取顺序
    直接拼接（中文不加空格）。词池与分词词典同源（dictionary.py），
    所以每条消息都能被分词器还原成生成时的词序列——这条"回切不变式"
    是 tests/test_nlp.py 的一条正式测试。

诚实声明：这是合成语料，词池两类几乎不重叠，因此贝叶斯的准确率会
显著高于真实场景；教学价值在流水线与公式，不在指标数字。
"""
from __future__ import annotations

import random

from .dictionary import NOTICE_POOL, SPAM_POOL, NEUTRAL_POOL

LABEL_NOTICE = "notice"
LABEL_SPAM = "spam"


def make_corpus(n_per_class: int = 100, seed: int = 42):
    """返回 (texts, labels)：两类各 n_per_class 条，拼接后不含空格。"""
    rng = random.Random(seed)
    texts: list[str] = []
    labels: list[str] = []
    pools = {LABEL_NOTICE: NOTICE_POOL, LABEL_SPAM: SPAM_POOL}
    for cls in (LABEL_NOTICE, LABEL_SPAM):
        for _ in range(n_per_class):
            words = rng.sample(pools[cls], rng.randint(3, 5))
            if rng.random() < 0.4:                  # 四成消息插一个中性词
                pos = rng.randint(0, len(words))
                words.insert(pos, rng.choice(NEUTRAL_POOL))
            texts.append("".join(words))
            labels.append(cls)
    return texts, labels
