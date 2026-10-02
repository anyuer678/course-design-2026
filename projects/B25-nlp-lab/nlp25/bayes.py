"""nlp25/bayes.py —— 多项式朴素贝叶斯（拉普拉斯平滑）

课程要点：
    - 生成式模型的"生成"二字：按类统计词的分布，预测时比的是
      P(词序列|类)·P(类) 谁大（取对数防下溢）。
    - **朴素**：给定类别，词与词条件独立——现实中几乎不成立，
      但朴素贝叶斯在文本分类上依然好用（决策面只需要相对大小对）。
    - 拉普拉斯平滑 α：没在训练集见过的词不该把概率打成 0。
      分母加 α·|V|（|V| 为训练词表大小），保证各类概率仍归一。
    - 未登录词（测试时新出现的词）：训练词表里没有，直接忽略——
      它不携带任何训练得来的类别信息（另一种做法是 UNK 特殊词，见练习）。

约定：tokenize 注入（默认按空白切）。手算测试用空白切分避开词典依赖；
真实语料传入 segment.fmm，与分词模块串联。
"""
from __future__ import annotations

import math


class MultinomialNB:
    def __init__(self, alpha: float = 1.0, tokenizer=None):
        if alpha <= 0:
            raise ValueError("alpha 必须为正（α=0 时未见词会导致 log(0)）")
        self.alpha = alpha
        self.tokenizer = tokenizer or (lambda s: s.split())
        self.classes_: list = []
        self.class_log_prior_: dict = {}
        self.word_counts_: dict[str, dict] = {}   # 类 -> {词: 次数}
        self.total_tokens_: dict = {}             # 类 -> 词例总数
        self.vocab_: set = set()                  # 训练词表

    def fit(self, texts: list[str], labels: list) -> "MultinomialNB":
        if len(texts) != len(labels):
            raise ValueError("texts 与 labels 数量不一致")
        self.classes_ = sorted(set(labels))
        for c in self.classes_:
            self.word_counts_[c] = {}
            self.total_tokens_[c] = 0
        doc_counts = {c: 0 for c in self.classes_}

        for text, label in zip(texts, labels):
            doc_counts[label] += 1
            for tok in self.tokenizer(text):
                self.word_counts_[label][tok] = \
                    self.word_counts_[label].get(tok, 0) + 1
                self.total_tokens_[label] += 1
                self.vocab_.add(tok)

        n = len(texts)
        self.class_log_prior_ = {c: math.log(doc_counts[c] / n)
                                 for c in self.classes_}
        return self

    def _log_scores(self, text: str) -> dict:
        """各类的 log P(类) + log P(词序列|类)（词独立假设下逐词求和）。
        未见词直接跳过：它没在训练词表里，对任何类的似然贡献都是平滑常数。"""
        tokens = [t for t in self.tokenizer(text) if t in self.vocab_]
        v = len(self.vocab_)
        out = {}
        for c in self.classes_:
            score = self.class_log_prior_[c]
            denom = self.total_tokens_[c] + self.alpha * v
            for t in tokens:
                num = self.word_counts_[c].get(t, 0) + self.alpha
                score += math.log(num / denom)
            out[c] = score
        return out

    def predict_one(self, text: str):
        scores = self._log_scores(text)
        return max(scores, key=scores.get)

    def predict_proba_one(self, text: str) -> dict:
        """把各类 log 分数做 softmax 归一（等价于后验归一，防下溢的常规写法）。"""
        scores = self._log_scores(text)
        m = max(scores.values())
        exps = {c: math.exp(s - m) for c, s in scores.items()}
        total = sum(exps.values())
        return {c: e / total for c, e in exps.items()}

    def predict(self, texts: list[str]) -> list:
        return [self.predict_one(t) for t in texts]
