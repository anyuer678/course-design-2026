"""ml/compare_sklearn.py —— 与 scikit-learn 的同参对拍台（B41 候选⑤）

口径**先写死在** docs/sklearn-compare-spec.md（容差表/不可比项/陷阱参数/负面对照设计），
本模块只做翻译。这是项目里**唯一** import sklearn/numpy 的模块——五个手写核心模块
（linear/perceptron/knn/tree/neuralnet）保持纯标准库不动。

三条纪律：
1. **随机源全钉**：sklearn 侧所有 random_state 显式写死；我们侧种子照旧。
2. **不可比项不比**：树结构、熵的底数、MLP 参数逐值、损失内部缩放都不比（规格 §三）。
3. **违规即抛**：每个对照过 `_verdict()`，差值超过声明容差就抛 `ComparisonFailed`，
   消息带对照名与实测差值——负面对照抓的就是它（"对拍只对得齐不报错"是重点防御对象）。
"""
from __future__ import annotations

import gc
import math
import random
import time
import warnings

# 模块级 import：sklearn 缺失时本模块 import 即失败（调用方给安装指引；见规格 §一）
from sklearn.linear_model import LinearRegression as SkLinearRegression
from sklearn.metrics import accuracy_score as sk_accuracy
from sklearn.metrics import log_loss as sk_log_loss
from sklearn.metrics import r2_score as sk_r2
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.tree import DecisionTreeClassifier

from . import data as mldata
from .knn import KNN
from .linear import LinearRegression, accuracy, r2_score
from .neuralnet import MLP
from .tree import DecisionTree

try:                                    # sklearn 的"轮数打满"提醒（tol=0 时必然出现）：
    from sklearn.exceptions import ConvergenceWarning   # 是我们故意不收敛到早停阈值的产物，
except ImportError:                                     # 不是异常——统一吞掉保持输出干净
    ConvergenceWarning = Warning


def _fit_silent(model, X, y):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        return model.fit(X, y)

# 容差表（出处：docs/sklearn-compare-spec.md §二；实测值见各 Check.note）
TOL_COEF = 1e-6
TOL_METRIC = 1e-12
TOL_LOG_LOSS = 1e-8
TOL_NEIGHBOR = 1e-9
TOL_ACC_DIFF = 0.10
MLP_ACC_FLOOR = 0.90


class ComparisonFailed(AssertionError):
    """对拍不合格。消息格式固定带 [对照名]，负面对照按名断言。"""


class Check:
    """一条对照的读数。diff 与 tolerance 都可打印（审计用）。"""

    def __init__(self, name: str, diff: float, tolerance: float, note: str = ""):
        self.name = name
        self.diff = diff
        self.tolerance = tolerance
        self.note = note

    def verdict(self) -> "Check":
        if self.diff > self.tolerance:
            raise ComparisonFailed(
                f"[{self.name}] 差值 {self.diff:.3g} > 容差 {self.tolerance:.3g}：{self.note}")
        return self


def _our_cross_entropy(probs: list[list[float]], y: list, classes: list) -> float:
    """我们损失函数的同一公式（ml/neuralnet.py 的 CE，+1e-12 平滑）。"""
    total = 0.0
    for pr, lab in zip(probs, y):
        for c, p in zip(classes, pr):
            if c == lab:
                total -= math.log(p + 1e-12)
    return total / len(probs)


def _iris_split():
    X, y3 = mldata.load_iris()
    tr, te = mldata.train_test_split(len(X), 0.2, seed=42)
    Xtr, Xte = [X[i] for i in tr], [X[i] for i in te]
    return Xtr, Xte, [y3[i] for i in tr], [y3[i] for i in te]


# ---------------------------------------------------------------- 四组模型对照
def compare_linear(sk_fit=None) -> Check:
    """闭式解 vs sklearn OLS：系数与截距逐分量（规格 §二 第一行）。"""
    X, _ = mldata.load_iris()
    X2 = [[row[0], row[1]] for row in X]
    y = [row[2] for row in X]
    tr, te = mldata.train_test_split(len(X), 0.2, seed=42)
    Xtr, Xte = mldata.standardize([X2[i] for i in tr], [X2[i] for i in te])
    ytr = [y[i] for i in tr]
    if sk_fit is None:
        sk_fit = lambda A, b: SkLinearRegression().fit(A, b)     # noqa: E731
    ours = LinearRegression().fit_closed_form(Xtr, ytr)
    sk = sk_fit(Xtr, ytr)
    diff = max([abs(a - b) for a, b in zip(ours.coef_, list(sk.coef_))]
               + [abs(ours.intercept_ - float(sk.intercept_))])
    return Check("线性回归系数", diff, TOL_COEF,
                 f"ours=({ours.coef_[0]:.6f},{ours.coef_[1]:.6f}) "
                 f"sklearn=({float(sk.coef_[0]):.6f},{float(sk.coef_[1]):.6f})").verdict()


def compare_knn(sk_fit=None, dataset=None) -> Check:
    """KNN(k=3)：测试集预测逐个相等 + 最近邻距离（规格 §二 第四行）。"""
    if dataset is None:
        Xtr, Xte, ytr, yte = _iris_split()
    else:
        Xtr, Xte, ytr, yte = dataset
    if sk_fit is None:
        sk_fit = lambda A, b: KNeighborsClassifier(n_neighbors=3).fit(A, b)  # noqa: E731
    ours = KNN(3).fit(Xtr, ytr)
    sk = sk_fit(Xtr, ytr)
    p_ours = ours.predict(Xte)
    p_sk = [int(v) if isinstance(v, (int, float)) else v for v in sk.predict(Xte).tolist()]
    mismatches = sum(a != b for a, b in zip(p_ours, p_sk))
    if mismatches:
        raise ComparisonFailed(
            f"[KNN 预测] 预测不一致 {mismatches}/{len(Xte)} 处："
            f"ours={p_ours}\nsklearn={p_sk}")
    d_ours = [d for d, _ in ours.kneighbors(Xte[0])]
    d_sk, _ = sk.kneighbors([Xte[0]])
    dist_diff = max(abs(a - b) for a, b in zip(d_ours, d_sk[0].tolist()))
    return Check("KNN 邻居距离", dist_diff, TOL_NEIGHBOR,
                 f"预测 {len(Xte)} 点 0 处不一致；首样本邻居距离逐位比对").verdict()


def compare_tree(sk_fit=None) -> Check:
    """决策树：只比行为（精度差）与 XOR 满分性；**不比树结构**（平局规则不同，规格 §三.1）。"""
    if sk_fit is None:
        sk_fit = lambda A, b: DecisionTreeClassifier(               # noqa: E731
            criterion="entropy", max_depth=4, min_samples_split=2,
            random_state=0).fit(A, b)
    Xtr, Xte, ytr, yte = _iris_split()
    ours = DecisionTree(criterion="entropy", max_depth=4, min_samples=2).fit(Xtr, ytr)
    sk = sk_fit(Xtr, ytr)
    acc_o = accuracy(yte, ours.predict(Xte))
    acc_s = accuracy(yte, sk.predict(Xte).tolist())
    diff = abs(acc_o - acc_s)
    if diff > TOL_ACC_DIFF:
        raise ComparisonFailed(
            f"[树 精度差] |{acc_o:.3f} - {acc_s:.3f}| = {diff:.3f} > 容差 {TOL_ACC_DIFF}")
    # XOR：两边都该满分（深度 4），零增益分裂的坑两边都得跨过去
    Xx, yx = _xor_data()
    ours_x = DecisionTree(criterion="entropy", max_depth=4, min_samples=2).fit(Xx, yx)
    sk_x = sk_fit(Xx, yx)
    acc_ox = accuracy(yx, ours_x.predict(Xx))
    acc_sx = accuracy(yx, sk_x.predict(Xx).tolist())
    if min(acc_ox, acc_sx) < 1.0:
        raise ComparisonFailed(
            f"[树 XOR 满分] ours={acc_ox:.3f} sklearn={acc_sx:.3f}（双方都应 100%）")
    return Check("树 精度差", diff, TOL_ACC_DIFF,
                 f"iris {acc_o:.3f} vs {acc_s:.3f}；XOR 双方 100%").verdict()


def _xor_data():
    X = [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]]
    y = [0, 1, 1, 0]
    return X, y


def compare_mlp(sk_fit=None, epochs: int = 1500) -> Check:
    """MLP：同参（tanh/8 隐元/lr 0.1/sgd/momentum 0/batch 固定/轮数打通）只比精度（规格 §二 末行、§四）。"""
    Xtr, Xte, ytr, yte = _iris_split()
    if sk_fit is None:
        sk_fit = lambda A, b: _fit_silent(MLPClassifier(             # noqa: E731
            hidden_layer_sizes=(8,), activation="tanh", solver="sgd",
            learning_rate_init=0.1, learning_rate="constant", momentum=0.0,
            max_iter=epochs, random_state=0, batch_size=120,
            tol=0.0, n_iter_no_change=10 ** 9), A, b)
    ours = MLP([4, 8, 3], hidden_act="tanh", seed=42, lr=0.1, epochs=epochs).fit(Xtr, ytr)
    sk = sk_fit(Xtr, ytr)
    acc_o = accuracy(yte, ours.predict(Xte))
    acc_s = accuracy(yte, sk.predict(Xte).tolist())
    if min(acc_o, acc_s) < MLP_ACC_FLOOR:
        raise ComparisonFailed(
            f"[MLP 收敛底线] ours={acc_o:.3f} sklearn={acc_s:.3f}（双方都应 ≥ {MLP_ACC_FLOOR}）")
    return Check("MLP 精度差", abs(acc_o - acc_s), TOL_ACC_DIFF,
                 f"{epochs} 轮：ours={acc_o:.3f} sklearn={acc_s:.3f}").verdict()


def compare_metrics() -> Check:
    """指标公式对拍：r2 / accuracy / 交叉熵（同一份输入喂两边公式，规格 §二 第二三行）。"""
    Xtr, Xte, ytr, yte = _iris_split()
    model = MLP([4, 8, 3], hidden_act="tanh", seed=42, lr=0.1, epochs=300).fit(Xtr, ytr)
    probs = model.predict_proba(Xte)
    loss_o = _our_cross_entropy(probs, yte, model.classes_)
    loss_s = sk_log_loss(yte, probs, labels=model.classes_)
    if abs(loss_o - loss_s) > TOL_LOG_LOSS:
        raise ComparisonFailed(
            f"[交叉熵公式] ours={loss_o:.12f} sklearn={loss_s:.12f} "
            f"差 {abs(loss_o - loss_s):.3g} > {TOL_LOG_LOSS:.3g}")
    X, _ = mldata.load_iris()
    X2 = [[row[0], row[1]] for row in X]
    y = [row[2] for row in X]
    reg_tr, reg_te = mldata.train_test_split(len(X), 0.2, seed=42)
    Xr, Xt = mldata.standardize([X2[i] for i in reg_tr], [X2[i] for i in reg_te])
    cf = LinearRegression().fit_closed_form(Xr, [y[i] for i in reg_tr])
    pred = cf.predict(Xt)
    y_reg = [y[i] for i in reg_te]
    r2_diff = abs(r2_score(y_reg, pred) - float(sk_r2(y_reg, pred)))
    if r2_diff > TOL_METRIC:
        raise ComparisonFailed(f"[R^2 公式] 差 {r2_diff:.3g} > {TOL_METRIC:.3g}")
    acc_diff = abs(accuracy(yte, model.predict(Xte)) - float(sk_accuracy(yte, model.predict(Xte))))
    if acc_diff > TOL_METRIC:
        raise ComparisonFailed(f"[accuracy 公式] 差 {acc_diff:.3g} > {TOL_METRIC:.3g}")
    return Check("指标公式", max(r2_diff, acc_diff, abs(loss_o - loss_s)), TOL_LOG_LOSS,
                 f"CE 差 {abs(loss_o - loss_s):.3g}（log_loss 平滑口径见规格 §三.4）；"
                 f"r2/accuracy 差 {max(r2_diff, acc_diff):.3g}").verdict()


def run_comparison() -> list[Check]:
    """全套对拍（演示与测试共用的入口）。任一对照违规即抛。"""
    return [compare_linear(), compare_knn(), compare_tree(), compare_mlp(), compare_metrics()]


# ---------------------------------------------------------------- 规模曲线
def _measure(fn, reps: int) -> float:
    """毫秒中位数。reps=1 的点把"计时"与"RSS 观测"融合在同一次训练里省钱；
    reps>1 的便宜点单独计 reps 次取中位数。"""
    if reps <= 1:
        t0 = time.perf_counter()
        keep = fn()
        milliseconds = (time.perf_counter() - t0) * 1000.0
        del keep
        return milliseconds
    times = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    return times[len(times) // 2]


def memory_probe(quick: bool = False) -> list[dict]:
    """训练**峰值内存**（tracemalloc 口径）。数字只进演示/README【实测】。
    quick=True 用缩小网格（测试入口，省时间）；演示用全网格（三个代表点）。

    口径登记（为什么不是 RSS 差值）：RSS 前后差在小对象点上恒为 0（模型本身只有
    千级节点/几 MB），不产生信息量；tracemalloc 对纯 Python 侧是**全量**——
    我们实现的临时列表、激活缓存都看得见。**sklearn 的数字是下界**：
    numpy 的数值缓冲区在 C 层分配，不在 tracemalloc 视野内。这个口径差本身就是结论，
    README 里明确写出（不冒充"公平对比"）。
    """
    import tracemalloc

    X, y = mldata.make_blobs(2000, seed=11)
    Xt, yt = mldata.make_blobs(1000, seed=11)
    Xm, ym = mldata.make_moons(500, noise=0.2, seed=11)
    tr, _ = mldata.train_test_split(500, 0.2, seed=42)
    Xmtr, _ = mldata.standardize([Xm[i] for i in tr], [Xm[i] for i in tr])
    ymtr = [ym[i] for i in tr]

    # 网格收敛说明（登记在 README）：tracemalloc 会让纯 Python 训练慢一个量级，
    # 33.6s 的全网格探测超了演示时间盒——收敛为三个代表点（树的临时列表最大、
    # BP 的每样本激活缓存、KNN 的数据副本）。
    def knn_pair(X, y):
        model = KNN(3).fit(X, y)
        model.predict(X[:100])
        return model

    def sk_knn_pair(X, y):
        model = KNeighborsClassifier(n_neighbors=3).fit(X, y)
        model.predict(X[:100])
        return model

    cases = [
        ("决策树(d=4) @n=1000",
         lambda: DecisionTree(max_depth=4).fit(Xt, yt),
         lambda: DecisionTreeClassifier(criterion="entropy", max_depth=4,
                                        min_samples_split=2, random_state=0).fit(Xt, yt)),
        ("KNN(拟合+100 查询) @n=2000",
         lambda: knn_pair(X, y),
         lambda: sk_knn_pair(X, y)),
        ("BP(8 隐元/30 轮) @n=500",
         lambda: MLP([2, 8, 2], hidden_act="tanh", seed=42, lr=0.1, epochs=30).fit(Xmtr, ymtr),
         lambda: _fit_silent(MLPClassifier(
             hidden_layer_sizes=(8,), activation="tanh", solver="sgd",
             learning_rate_init=0.1, learning_rate="constant", momentum=0.0,
             max_iter=30, random_state=0, batch_size=160,
             tol=0.0, n_iter_no_change=10 ** 9), Xmtr, ymtr)),
    ]
    if quick:
        Xs, ys = mldata.make_blobs(300, seed=11)
        cases = cases[:1]
        cases[0] = ("决策树(d=4) @n=300（quick）",
                    lambda: DecisionTree(max_depth=4).fit(Xs, ys),
                    lambda: DecisionTreeClassifier(criterion="entropy", max_depth=4,
                                                   min_samples_split=2,
                                                   random_state=0).fit(Xs, ys))
    out = []
    for name, ours_fn, sk_fn in cases:
        row = {"algo": name}
        for side, fn in (("ours", ours_fn), ("sk", sk_fn)):
            gc.collect()
            tracemalloc.start()
            keep = fn()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            del keep
            row[f"{side}_peak"] = peak
        out.append(row)
    return out


def _regression_data(n: int, seed: int = 11):
    rng = random.Random(seed)
    X = [[rng.uniform(-3, 3), rng.uniform(-3, 3)] for _ in range(n)]
    y = [2.0 * x0 - 1.5 * x1 + 0.5 + rng.uniform(-0.2, 0.2) for x0, x1 in X]
    return X, y


def scale_curve(sizes=(200, 500, 1000, 2000), bp_sizes=(200, 500, 1000),
                bp_epochs: int = 60) -> list[dict]:
    """双实现规模曲线的**时间**行：每行 = {算法, n, ours_ms, sk_ms}。
    时间数字只进演示/README【实测】，**不进测试断言**（规格 §三.5、§六）。
    每点自适应重复：n<=500 取 3 次中位数，更大的点跑 1 次（纯 Python 贵，时间盒优先）。
    内存另由 memory_probe() 在最痛点单独测（口径见其 docstring）。
    """
    rows: list[dict] = []
    for n in sizes:
        X, y = mldata.make_blobs(n, seed=11)
        Xr, yr = _regression_data(n)

        def fit_ours_lr():
            return LinearRegression().fit_closed_form(Xr, yr)

        def fit_sk_lr():
            return SkLinearRegression().fit(Xr, yr)

        def fit_ours_knn():
            model = KNN(3).fit(X, y)
            model.predict(X[:100])          # 惰性学习：拟合只是"记住"，代价在预测
            return model

        def fit_sk_knn():
            model = KNeighborsClassifier(n_neighbors=3).fit(X, y)
            model.predict(X[:100])
            return model

        def fit_ours_tree():
            return DecisionTree(max_depth=4).fit(X, y)

        def fit_sk_tree():
            return DecisionTreeClassifier(criterion="entropy", max_depth=4,
                                          min_samples_split=2,
                                          random_state=0).fit(X, y)

        reps = 3 if n <= 500 else 1
        for name, fo, fs in (("线性回归(闭式)", fit_ours_lr, fit_sk_lr),
                             ("KNN(拟合+100 查询)", fit_ours_knn, fit_sk_knn),
                             ("决策树(d=4)", fit_ours_tree, fit_sk_tree)):
            rows.append({"algo": name, "n": n,
                         "ours_ms": _measure(fo, reps), "sk_ms": _measure(fs, reps)})

    for n in bp_sizes:
        Xm, ym = mldata.make_moons(n, noise=0.2, seed=11)
        tr, _ = mldata.train_test_split(n, 0.2, seed=42)
        Xtr, _ = mldata.standardize([Xm[i] for i in tr], [Xm[i] for i in tr])
        ytr = [ym[i] for i in tr]

        def fit_ours_bp():
            return MLP([2, 8, 2], hidden_act="tanh", seed=42, lr=0.1,
                       epochs=bp_epochs).fit(Xtr, ytr)

        def fit_sk_bp():
            return _fit_silent(MLPClassifier(
                hidden_layer_sizes=(8,), activation="tanh", solver="sgd",
                learning_rate_init=0.1, learning_rate="constant", momentum=0.0,
                max_iter=bp_epochs, random_state=0, batch_size=min(160, n),
                tol=0.0, n_iter_no_change=10 ** 9), Xtr, ytr)

        rows.append({"algo": f"BP(8 隐元/{bp_epochs} 轮)", "n": n,
                     "ours_ms": _measure(fit_ours_bp, 1), "sk_ms": _measure(fit_sk_bp, 3)})
    return rows
