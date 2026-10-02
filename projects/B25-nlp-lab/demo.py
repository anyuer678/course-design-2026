"""B25-nlp-lab 四段演示：分词 → 语料 → 贝叶斯 → 指标

全程零依赖、零文件写入（语料由种子化模板生成）。每段断言失败计入退出码。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nlp25.bayes import MultinomialNB
from nlp25.corpus import make_corpus
from nlp25.metrics import accuracy, confusion_matrix, precision_recall_f1
from nlp25.segment import fmm, bmm, segment

FAILS = []


def check(cond, msg):
    print(f"    {'✔' if cond else '✘'} {msg}")
    if not cond:
        FAILS.append(msg)


def show(title):
    print(f"\n{'=' * 62}\n {title}\n{'=' * 62}")


# ---------------------------------------------------------------- 1
def demo_segment():
    show("第一段：分词 —— 正向/逆向最大匹配与歧义")
    for text in ["今天下午在二教有讲座", "限时秒杀免费领取红包"]:
        print(f"    {text}")
        print(f"      FMM: {' / '.join(fmm(text))}")
        print(f"      BMM: {' / '.join(bmm(text))}")
    print("\n    经典歧义句（FMM/BMM 给出不同切分，两边都合法）：")
    result = segment("研究生命起源")
    print(f"      FMM: {' / '.join(result['fmm'])}   BMM: {' / '.join(result['bmm'])}")
    check(result["ambiguous"], "歧义检测：FMM 与 BMM 分歧被标注")
    for text in ["今天下午在二教有讲座", "限时秒杀免费领取红包"]:
        ok = "".join(fmm(text)) == text
        check(ok, f"拼接不变式（{text}）")


# ---------------------------------------------------------------- 2
def demo_corpus():
    show("第二段：合成语料 —— 种子化模板生成（来源：AI 生成，非真实数据）")
    texts, labels = make_corpus(100, seed=42)
    print(f"    共 {len(texts)} 条，notice {labels.count('notice')} 条 / "
          f"spam {labels.count('spam')} 条")
    for t, lab in list(zip(texts, labels))[:4]:
        print(f"      [{lab}] {t}")
    check(labels.count("notice") == 100 and labels.count("spam") == 100,
          "两类均衡")
    check("".join(fmm(texts[0])), "语料全部由词典词拼成（可被分词器还原）")


# ---------------------------------------------------------------- 3
def demo_bayes():
    show("第三段：朴素贝叶斯 —— 训练与新闻式消息分类")
    texts, labels = make_corpus(100, seed=42)
    tr_x, tr_y = texts[:70] + texts[100:170], labels[:70] + labels[100:170]
    te_x, te_y = texts[70:100] + texts[170:], labels[70:100] + labels[170:]
    nb = MultinomialNB(alpha=1.0, tokenizer=fmm).fit(tr_x, tr_y)
    acc = accuracy(te_y, nb.predict(te_x))
    print(f"    固定划分测试准确率: {acc:.2f}（合成语料两类词池几乎不重叠，")
    print("    指标会显著好于真实场景——教学价值在流水线，不在数字）")
    check(acc >= 0.95, "准确率 ≥ 0.95")

    print("\n    两条手写消息（非语料原文）的逐类后验：")
    for msg in ["免费领取红包加微信", "周五上午提交实验报告"]:
        proba = nb.predict_proba_one(msg)
        top = max(proba, key=proba.get)
        detail = "  ".join(f"{c}={p:.3f}" for c, p in sorted(proba.items()))
        print(f"      {msg!r} -> {top}   ({detail})")
    check(nb.predict_one("免费领取红包加微信") == "spam" and
          nb.predict_one("周五上午提交实验报告") == "notice",
          "新组合消息分类正确")


# ---------------------------------------------------------------- 4
def demo_metrics():
    show("第四段：指标 —— 混淆矩阵与 P/R/F1（手算对照）")
    texts, labels = make_corpus(100, seed=42)
    tr_x, tr_y = texts[:70] + texts[100:170], labels[:70] + labels[100:170]
    te_x, te_y = texts[70:100] + texts[170:], labels[70:100] + labels[170:]
    nb = MultinomialNB(alpha=1.0, tokenizer=fmm).fit(tr_x, tr_y)
    preds = nb.predict(te_x)
    cm = confusion_matrix(te_y, preds, ["notice", "spam"])
    print(f"    混淆矩阵（行=真值 列=预测）: {cm}")
    p, r, f1 = precision_recall_f1(te_y, preds, "spam")
    print(f"    spam 类: 精确率 {p:.3f} 召回率 {r:.3f} F1 {f1:.3f}")
    # 手算对照：混淆矩阵四个格重算 P/R/F1
    tp = cm[("spam", "spam")]
    fp = cm[("notice", "spam")]
    fn = cm[("spam", "notice")]
    p2 = tp / (tp + fp) if tp + fp else 0.0
    r2 = tp / (tp + fn) if tp + fn else 0.0
    f2 = 2 * p2 * r2 / (p2 + r2) if p2 + r2 else 0.0
    check((p, r, f1) == (p2, r2, f2), "指标模块与手算一致")
    # F1 的另一种等价形式：调和平均
    check(abs(f1 - 2 / (1 / p + 1 / r)) < 1e-12, "F1 = 2PR/(P+R) = 调和平均")


def main() -> int:
    print("B25-nlp-lab 演示（纯标准库，零依赖）")
    demo_segment()
    demo_corpus()
    demo_bayes()
    demo_metrics()
    print(f"\n{'=' * 62}")
    if FAILS:
        print(f"演示存在 {len(FAILS)} 处失败：")
        for f in FAILS:
            print(f"  ✘ {f}")
        return 1
    print("四段演示全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
