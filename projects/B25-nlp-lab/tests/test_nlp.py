"""B25-nlp-lab 自测。

"期望值必须有出处"的落法：
    1. 朴素贝叶斯后验 <-- 两词表迷你语料的完整手算（含拉普拉斯平滑项）
    2. 指标 <-- 手算混淆矩阵（TP/FN/FP/TN 与 P/R/F1 逐数断言）
    3. 分词合法性 <-- 逐词 ∈ 词典或单字 + 拼接不变式
    4. 贪心性质 <-- FMM 首词 = 最长词典前缀（独立计算）；短句穷举全部
       合法切分，断言 FMM/BMM 结果都在其中
    5. 语料回切不变式 <-- 分词结果还原成生成时的词序列（词典/词池同源担保）
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nlp25.bayes import MultinomialNB
from nlp25.corpus import make_corpus
from nlp25.dictionary import (AMBIGUITY_WORDS, DICTIONARY, NEUTRAL_POOL,
                              NOTICE_POOL, SPAM_POOL)
from nlp25.metrics import (accuracy, confusion_matrix,
                           precision_recall_f1)
from nlp25.segment import bmm, fmm, is_valid, segment


# ---------------------------------------------------------------- 分词
class TestSegment(unittest.TestCase):
    def test_fmm_greedy_longest_first_token(self):
        """FMM 的贪心性质：首词 = 从首字符开始的最长词典前缀（独立计算）。"""
        for text in ["研究生命起源", "今天下午在图书馆", "免费领取优惠券"]:
            longest = ""
            for length in range(1, len(text) + 1):
                if text[:length] in DICTIONARY:
                    longest = text[:length]
            got = fmm(text)[0]
            self.assertEqual(got, longest, msg=text)

    def test_concatenation_invariant(self):
        """拼接不变式：切分结果拼回去必须等于原文（一个字符都不丢）。"""
        cases = ["研究生命起源", "今天下午在图书馆有讲座", "免费领取红包",
                 "xyz", "", "考试安排已发布"]
        for text in cases:
            self.assertEqual("".join(fmm(text)), text)
            self.assertEqual("".join(bmm(text)), text)

    def test_validity_and_determinism(self):
        for text in ["研究生命起源", "限时秒杀抽奖", "各位同学请准时参加"]:
            for tokens in (fmm(text), bmm(text)):
                self.assertTrue(is_valid(tokens))
            self.assertEqual(fmm(text), fmm(text))
            self.assertEqual(bmm(text), bmm(text))

    def test_ambiguity_fmm_vs_bmm(self):
        """经典歧义句：两个结果都合法，但切分不同——这就是歧义信号。"""
        text = "研究生命起源"
        result = segment(text)
        self.assertTrue(result["ambiguous"])
        self.assertEqual(result["fmm"], ["研究生", "命", "起源"])
        self.assertEqual(result["bmm"], ["研究", "生命", "起源"])
        for tokens in (result["fmm"], result["bmm"]):
            self.assertTrue(is_valid(tokens))

    def test_exhaustive_membership_for_short_sentences(self):
        """短句穷举：FMM 与 BMM 的结果必须都在"全部合法切分"集合里。
        穷举用独立实现的递归（不 import segment 的内部函数）。"""
        def all_segmentations(text, dictionary, pos=0, prefix=()):
            if pos == len(text):
                yield list(prefix)
                return
            for length in range(1, len(text) - pos + 1):
                cand = text[pos:pos + length]
                if cand in dictionary or length == 1:
                    yield from all_segmentations(text, dictionary,
                                                 pos + length,
                                                 prefix + (cand,))

        for text in ["研究生命起源", "免费领取红包", "明天下午提交作业"]:
            valid = set(tuple(s) for s in all_segmentations(text, DICTIONARY))
            self.assertIn(tuple(fmm(text)), valid, msg=text)
            self.assertIn(tuple(bmm(text)), valid, msg=text)

    def test_single_char_fallback(self):
        tokens = fmm("xyz失效词")
        self.assertEqual("".join(tokens), "xyz失效词")
        self.assertIn("x", tokens)                # 未登录内容回退单字
        self.assertIn("失", tokens)


# ---------------------------------------------------------------- 指标
class TestMetrics(unittest.TestCase):
    def test_hand_computed_prf(self):
        y_true = ["P", "P", "N", "N"]
        y_pred = ["P", "N", "N", "N"]
        # TP=1, FN=1, FP=0, TN=2
        p, r, f1 = precision_recall_f1(y_true, y_pred, "P")
        self.assertEqual((p, r), (1.0, 0.5))
        self.assertAlmostEqual(f1, 2 / 3)
        cm = confusion_matrix(y_true, y_pred, ["P", "N"])
        self.assertEqual(cm[("P", "P")], 1)
        self.assertEqual(cm[("P", "N")], 1)
        self.assertEqual(cm[("N", "N")], 2)
        self.assertAlmostEqual(accuracy(y_true, y_pred), 0.75)

    def test_zero_division_convention(self):
        # 正类从未被预测 -> precision 分母为 0，按约定记 0.0
        p, r, f1 = precision_recall_f1(["P", "N"], ["N", "N"], "P")
        self.assertEqual((p, r, f1), (0.0, 0.0, 0.0))

    def test_unknown_label_rejected(self):
        with self.assertRaises(ValueError):
            confusion_matrix(["P"], ["Q"], ["P", "N"])


# ---------------------------------------------------------------- 贝叶斯
class TestBayes(unittest.TestCase):
    def test_hand_computed_posterior(self):
        """两词表迷你语料的完整手算（α=1，V=2）：
        spam: "发票 发票"、"发票 通知" -> count(发票|spam)=3, count(通知|spam)=1, 总词数 4
        ham : "通知 通知"、"通知"       -> count(通知|ham)=3,  总词数 3
        先验各 1/2。查询"发票"：
          P(发票|spam) = (3+1)/(4+2·1) = 2/3；P(发票|ham) = (0+1)/(3+2) = 1/5
          后验 spam : ham = (1/2·2/3) : (1/2·1/5) = 1/3 : 1/10 = 10 : 3
          归一化 P(spam) = 10/13 ≈ 0.7692
        """
        texts = ["发票 发票", "发票 通知", "通知 通知", "通知"]
        labels = ["spam", "spam", "ham", "ham"]
        nb = MultinomialNB(alpha=1.0, tokenizer=str.split).fit(texts, labels)
        self.assertEqual(nb.predict_one("发票"), "spam")
        proba = nb.predict_proba_one("发票")
        self.assertAlmostEqual(proba["spam"], 10 / 13, places=9)
        self.assertAlmostEqual(proba["ham"], 3 / 13, places=9)
        self.assertAlmostEqual(sum(proba.values()), 1.0)

    def test_unseen_word_ignored(self):
        texts = ["发票 发票", "发票 通知", "通知 通知", "通知"]
        labels = ["spam", "spam", "ham", "ham"]
        nb = MultinomialNB(alpha=1.0, tokenizer=str.split).fit(texts, labels)
        # "比特币" 不在训练词表：对两类的似然贡献同为平滑常数，不影响判别
        self.assertEqual(nb.predict_one("发票 比特币"), "spam")
        proba = nb.predict_proba_one("发票")
        self.assertAlmostEqual(proba["spam"],
                               nb.predict_proba_one("发票 比特币")["spam"],
                               places=12)

    def test_alpha_must_be_positive(self):
        with self.assertRaises(ValueError):
            MultinomialNB(alpha=0)

    def test_smoothing_changes_confidence_not_direction(self):
        """大 α 把概率推向先验（数据被稀释），但不改变本例的判别方向。"""
        texts = ["发票 发票", "发票 通知", "通知 通知", "通知"]
        labels = ["spam", "spam", "ham", "ham"]
        small = MultinomialNB(alpha=0.1, tokenizer=str.split).fit(texts, labels)
        big = MultinomialNB(alpha=100.0, tokenizer=str.split).fit(texts, labels)
        self.assertGreater(small.predict_proba_one("发票")["spam"],
                           big.predict_proba_one("发票")["spam"])
        self.assertEqual(big.predict_one("发票"), "spam")


# ---------------------------------------------------------------- 语料与端到端
class TestCorpusAndEndToEnd(unittest.TestCase):
    def test_corpus_roundtrip_invariant(self):
        """回切不变式：每条合成消息经 FMM 分词后必须还原成生成时的词序列。
        这条测试担保"词池/词典/生成器"三方没有悄悄漂移。"""
        texts, labels = make_corpus(100, seed=42)
        self.assertEqual(len(texts), 200)
        self.assertEqual(labels.count("notice"), 100)
        self.assertEqual(labels.count("spam"), 100)
        # 生成器逐词重放（同种子同序列），比对分词结果
        import random
        rng = random.Random(42)
        pools = {"notice": NOTICE_POOL, "spam": SPAM_POOL}
        for cls in ("notice", "spam"):
            for _ in range(100):
                words = rng.sample(pools[cls], rng.randint(3, 5))
                if rng.random() < 0.4:
                    words.insert(rng.randint(0, len(words)),
                                 rng.choice(NEUTRAL_POOL))
                text = "".join(words)
                self.assertEqual(fmm(text), words, msg=text)

    def test_corpus_determinism(self):
        self.assertEqual(make_corpus(50, seed=1), make_corpus(50, seed=1))

    def test_end_to_end_accuracy(self):
        from nlp25.segment import fmm
        texts, labels = make_corpus(100, seed=42)
        tr_x, tr_y = texts[:70] + texts[100:170], labels[:70] + labels[100:170]
        te_x, te_y = texts[70:100] + texts[170:], labels[70:100] + labels[170:]
        nb = MultinomialNB(alpha=1.0, tokenizer=fmm).fit(tr_x, tr_y)
        preds = nb.predict(te_x)
        acc = accuracy(te_y, preds)
        # 合成语料两类词池几乎不重叠，准确率应接近 1；阈值实测 1.00，钉 0.95
        self.assertGreaterEqual(acc, 0.95)
        # 两条手写消息（新组合，非语料原文）分类正确
        self.assertEqual(nb.predict_one("免费领取红包"), "spam")
        self.assertEqual(nb.predict_one("周五上午提交实验报告"), "notice")


if __name__ == "__main__":
    unittest.main(verbosity=2)
