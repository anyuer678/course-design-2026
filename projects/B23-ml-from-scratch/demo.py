"""B23-ml-from-scratch 五段演示：数据 -> 线性回归 -> 感知机 -> KNN/决策树 -> BP

run.bat 的演示步跑的就是这个文件。全程只用标准库与仓库内的 Iris 数据，
不写任何文件（演示退出后目录快照无新增）。每段末尾的断言失败会计入退出码
——演示错了等于没演示。
"""
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import data as mldata
from ml.knn import KNN
from ml.linear import LinearRegression, accuracy, r2_score
from ml.neuralnet import MLP
from ml.perceptron import Perceptron
from ml.tree import DecisionTree

FAILS = []


def check(cond, msg):
    print(f"    {'✔' if cond else '✘'} {msg}")
    if not cond:
        FAILS.append(msg)


def show(title):
    print(f"\n{'=' * 62}\n {title}\n{'=' * 62}")


def pm(labels):                                   # 0/1 -> ±1
    return [1 if v == 1 else -1 for v in labels]


# ---------------------------------------------------------------- 1
def demo_data():
    show("第一段：数据完整性与泄漏检查（Iris + 合成月牙）")
    X, y = mldata.load_iris()
    print(f"    Iris: {len(X)} 行，分布 {mldata.class_distribution(y)}")
    check(len(X) == 150 and mldata.class_distribution(y) ==
          {"setosa": 50, "versicolor": 50, "virginica": 50}, "150 行三类均衡")
    tr, te = mldata.train_test_split(len(X), 0.2, seed=42)
    check(len(set(tr) & set(te)) == 0 and len(tr) + len(te) == 150,
          "切分互斥且完备（固定种子 42，可复现）")
    # 泄漏检查：标准化只用训练集统计量
    Xtr, Xte = mldata.standardize([X[i] for i in tr], [X[i] for i in te])
    tr_mean = sum(r[0] for r in Xtr) / len(Xtr)
    check(abs(tr_mean) < 1e-9, f"训练集标准化后均值 ≈ 0（实测 {tr_mean:.2e}）")
    far = max(abs(v) for v in Xte[0])
    print(f"    测试集第一行最大标准化值 {far:.2f}——仍用训练集的均值/方差，")
    print("    离群点不会把统计量拉走：这就是'不许用全量数据算标准化'的原因")


# ---------------------------------------------------------------- 2
def demo_linear():
    show("第二段：线性回归 —— 闭式解与梯度下降是同一个答案的两条路")
    X, _ = mldata.load_iris()
    X2 = [[row[0], row[1]] for row in X]          # 花萼长/宽
    y = [row[2] for row in X]                     # 预测花瓣长
    tr, te = mldata.train_test_split(len(X), 0.2, seed=42)
    # 先标准化：特征尺度差异会拖慢梯度下降（原始量纲下 8000 轮都差 1e-3 量级）
    Xtr, Xte = mldata.standardize([X2[i] for i in tr], [X2[i] for i in te])
    ytr = [y[i] for i in tr]
    yte = [y[i] for i in te]

    cf = LinearRegression().fit_closed_form(Xtr, ytr)
    gd = LinearRegression().fit_gd(Xtr, ytr, lr=0.1, epochs=8000)
    print(f"    闭式解: w=({cf.coef_[0]:.4f}, {cf.coef_[1]:.4f}) b={cf.intercept_:.4f}")
    print(f"    梯度下降: w=({gd.coef_[0]:.4f}, {gd.coef_[1]:.4f}) b={gd.intercept_:.4f}")
    diff = max(abs(a - b) for a, b in zip(cf.coef_, gd.coef_))
    check(diff < 1e-6 and abs(cf.intercept_ - gd.intercept_) < 1e-6,
          f"两条路得到同一个解（最大差 {diff:.1e}）")
    r2 = r2_score(yte, cf.predict(Xte))
    print(f"    测试集 R² = {r2:.3f}（只用花萼两特征预测花瓣长的实测水平）")
    check(r2 > 0.75, "R² > 0.75")


# ---------------------------------------------------------------- 3
def demo_perceptron():
    show("第三段：感知机 —— 可分数据收敛，XOR/月牙是它的边界")
    Xb, yb = mldata.make_blobs(100, seed=3)
    p1 = Perceptron().fit(Xb, pm(yb))
    print(f"    高斯团块（线性可分）: 收敛={p1.converged_}, "
          f"更新 {p1.updates_} 次, 精度 {accuracy(pm(yb), p1.predict(Xb)):.2f}")
    check(p1.converged_ and accuracy(pm(yb), p1.predict(Xb)) == 1.0,
          "Novikoff 定理兑现：可分数据有限步收敛")

    Xx = [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]]
    yx = [-1, 1, 1, -1]
    p2 = Perceptron(max_epochs=200).fit(Xx, yx)
    acc = accuracy(yx, p2.predict(Xx))
    print(f"    XOR（线性不可分）: 精度 {acc:.2f}——任何直线最多 75%")
    check(acc <= 0.75, "感知机在 XOR 上被封死在 75%")

    Xm, ym = mldata.make_moons(200, noise=0.15, seed=7)
    p3 = Perceptron(max_epochs=300).fit(Xm, pm(ym))
    accm = accuracy(pm(ym), p3.predict(Xm))
    print(f"    双月牙: 精度 {accm:.2f}（跑满轮数仍到不了 100% → 不可分）")
    check(accm < 1.0, "月牙数据不可分")


# ---------------------------------------------------------------- 4
def demo_knn_tree():
    show("第四段：KNN 与决策树 —— Iris 三分类")
    X, y = mldata.load_iris()
    tr, te = mldata.train_test_split(len(X), 0.2, seed=42)
    Xtr, Xte = mldata.standardize([X[i] for i in tr], [X[i] for i in te])
    ytr = [y[i] for i in tr]
    yte = [y[i] for i in te]

    knn = KNN(k=3).fit(Xtr, ytr)
    acc_knn = accuracy(yte, knn.predict(Xte))
    tree = DecisionTree(criterion="entropy", max_depth=4).fit(Xtr, ytr)
    acc_tree = accuracy(yte, tree.predict(Xte))
    print(f"    KNN(k=3, 标准化)        测试精度 {acc_knn:.2f}")
    print(f"    决策树(熵, depth=4)     测试精度 {acc_tree:.2f}")

    wrong = [(i, t, p) for i, t, p in zip(te, yte, knn.predict(Xte)) if t != p]
    if wrong:
        i, t, p = wrong[0]
        print(f"    抽一个错例：测试样本 #{i} 真值 {t} 判成 {p}——看得出错在类边界")
    check(acc_knn >= 0.9 and acc_tree >= 0.9, "两模型测试精度 ≥ 0.9（固定种子实测阈值）")

    # 决策树可解释性：打印根分裂
    r = tree.root_
    print(f"    决策树根分裂: {mldata.IRIS_FEATURES[r.feature]} <= {r.threshold:.2f}")
    print("    （一棵树就是一组嵌套的 if-else，每个内部节点都能读成人话）")


# ---------------------------------------------------------------- 5
def demo_bp():
    show("第五段：BP 网络 —— 梯度检查、XOR 翻案、Iris 与月牙")
    # 梯度检查：数值梯度（中心差分）vs 手写反向传播
    rng = __import__("random").Random(11)
    Xg = [[rng.uniform(-1, 1), rng.uniform(-1, 1)] for _ in range(12)]
    yg = ["L" if x[0] + x[1] > 0 else "R" for x in Xg]
    net = MLP([2, 3, 2], seed=1, lr=0.5, epochs=100)
    net.fit(Xg, yg, classes=["L", "R"])
    Y1h = [[1.0 if c == lab else 0.0 for c in ["L", "R"]] for lab in yg]
    gW, gB = net.backprop(Xg, Y1h)
    eps = 1e-6
    worst = 0.0
    for l in range(len(net.W)):
        for j in range(len(net.W[l])):
            for i in range(len(net.W[l][j])):
                orig = net.W[l][j][i]
                net.W[l][j][i] = orig + eps
                lp = net.loss(Xg, Y1h)
                net.W[l][j][i] = orig - eps
                lm = net.loss(Xg, Y1h)
                net.W[l][j][i] = orig
                num = (lp - lm) / (2 * eps)
                worst = max(worst, abs(num - gW[l][j][i]) /
                            max(1e-8, abs(num) + abs(gW[l][j][i])))
    print(f"    梯度检查（数值 vs 反传）最大相对误差 {worst:.2e}（< 1e-5 即手写 BP 正确）")
    check(worst < 1e-5, "手写反向传播通过数值梯度检查")

    # XOR：感知机封顶 75% 的地方，一层隐单元全对
    Xx = [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]]
    yx = ["A", "B", "B", "A"]
    xor = MLP([2, 4, 2], seed=3, lr=0.5, epochs=2000).fit(Xx, yx)
    acc_xor = accuracy(yx, xor.predict(Xx))
    print(f"    XOR: BP 网络精度 {acc_xor:.2f}（对比第三段感知机的 0.75）")
    check(acc_xor == 1.0, "一层隐单元解出 XOR——非线性激活的价值")

    # Iris
    X, y = mldata.load_iris()
    tr, te = mldata.train_test_split(len(X), 0.2, seed=42)
    Xtr, Xte = mldata.standardize([X[i] for i in tr], [X[i] for i in te])
    ytr = [y[i] for i in tr]
    yte = [y[i] for i in te]
    iris_net = MLP([4, 8, 3], seed=42, lr=0.1, epochs=300, batch_size=16)
    iris_net.fit(Xtr, ytr)
    acc = accuracy(yte, iris_net.predict(Xte))
    print(f"    Iris（4-8-3 softmax）: 测试精度 {acc:.2f}，"
          f"损失 {net.loss_history_[0]:.3f} -> {iris_net.loss_history_[-1]:.3f}")
    check(acc >= 0.9, "Iris 测试精度 ≥ 0.9（固定种子实测阈值）")

    # 月牙
    Xm, ym = mldata.make_moons(200, noise=0.15, seed=7)
    moon_net = MLP([2, 16, 2], seed=5, lr=0.5, epochs=800).fit(Xm, ym)
    acc_m = accuracy(ym, moon_net.predict(Xm))
    print(f"    双月牙: 精度 {acc_m:.2f}（对比感知机的 {accuracy(pm(ym), Perceptron(max_epochs=300).fit(Xm, pm(ym)).predict(Xm)):.2f}）")
    check(acc_m >= 0.98, "BP 在月牙上 ≥ 0.98（固定种子实测 1.00）")


def main() -> int:
    print("B23-ml-from-scratch 演示（纯标准库手写，无 NumPy）")
    demo_data()
    demo_linear()
    demo_perceptron()
    demo_knn_tree()
    demo_bp()
    print(f"\n{'=' * 62}")
    if FAILS:
        print(f"演示存在 {len(FAILS)} 处失败：")
        for f in FAILS:
            print(f"  ✘ {f}")
        return 1
    print("五段演示全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
