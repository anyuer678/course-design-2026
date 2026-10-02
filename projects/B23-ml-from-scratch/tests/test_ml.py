"""B23-ml-from-scratch 自测（unittest / pytest 双入口可用）

"期望值必须有出处"在本项目的落法：
    1. BP 的解析梯度 <-- 数值梯度（中心差分）——梯度检查是手写反传的第一道验收
    2. 线性回归闭式解 <-- 梯度下降 + 手算三点拟合
    3. 感知机 <-- 完整手算轨迹（权重/偏置/更新次数逐数断言）
    4. 决策树 <-- 测试里独立重写的熵与增益（不 import ml.tree）
    5. KNN <-- 测试里独立排序的距离表
    6. Iris 转写质量 <-- Fisher 数据集公开的各类均值（±0.06 锚点）
    7. 端到端精度阈值 <-- 固定种子下的实测值（README 注明非理论界）
"""
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import data as mldata
from ml.knn import KNN, euclidean
from ml.linear import (LinearRegression, accuracy, mse_gradient, mse_loss,
                       r2_score, solve_linear_system)
from ml.neuralnet import MLP
from ml.perceptron import Perceptron
from ml.tree import DecisionTree


# ---------------------------------------------------------------- 数据
class TestData(unittest.TestCase):
    def setUp(self):
        self.X, self.y = mldata.load_iris()

    def test_iris_shape_and_balance(self):
        self.assertEqual(len(self.X), 150)
        self.assertEqual(len(self.X[0]), 4)
        dist = mldata.class_distribution(self.y)
        self.assertEqual(dist, {"setosa": 50, "versicolor": 50, "virginica": 50})

    def test_iris_ranges(self):
        """Fisher 数据集的已知取值范围：SL 4.3-7.9, SW 2.0-4.4, PL 1.0-6.9, PW 0.1-2.5"""
        lo = [min(row[j] for row in self.X) for j in range(4)]
        hi = [max(row[j] for row in self.X) for j in range(4)]
        self.assertTrue(all(a <= v for a, v in zip(lo, [4.3, 2.0, 1.0, 0.1])))
        self.assertTrue(all(v <= b for v, b in zip(hi, [7.9, 4.4, 6.9, 2.5])))

    def test_iris_class_means_anchor(self):
        """转写质量锚点：与 Fisher 数据集公开的各类均值逐一对照（±0.06）。
        这些均值广泛见于教材与 UCI 文档，是转写是否出错的独立参照。"""
        anchor = {
            "setosa": [5.006, 3.418, 1.464, 0.246],
            "versicolor": [5.936, 2.770, 4.260, 1.326],
            "virginica": [6.588, 2.974, 5.552, 2.026],
        }
        for cls, wants in anchor.items():
            rows = [x for x, lab in zip(self.X, self.y) if lab == cls]
            means = [sum(col) / len(col) for col in zip(*rows)]
            for got, want in zip(means, wants):
                self.assertAlmostEqual(got, want, delta=0.06,
                                       msg=f"{cls} 均值 {got} vs 公开值 {want}")

    def test_split_disjoint_complete(self):
        tr, te = mldata.train_test_split(150, 0.2, seed=42)
        self.assertEqual(len(tr) + len(te), 150)
        self.assertEqual(len(set(tr) & set(te)), 0)
        tr2, te2 = mldata.train_test_split(150, 0.2, seed=42)
        self.assertEqual((tr, te), (tr2, te2))          # 同种子必须同结果

    def test_standardize_no_leakage(self):
        train = [[0.0, 0.0], [2.0, 2.0], [4.0, 4.0]]
        test = [[100.0, 100.0]]                          # 测试集里的离群点
        tr, te = mldata.standardize(train, test)
        train_mean = sum(r[0] for r in tr) / 3
        self.assertAlmostEqual(train_mean, 0.0, places=9)  # 训练集均值恰为 0
        self.assertGreater(abs(te[0][0]), 40)              # 用训练集统计量，测试集保持离群

    def test_moons_not_linearly_separable(self):
        X, y = mldata.make_moons(200, seed=7)
        # 用感知机当"线性可分探测器"：跑满轮数仍达不到 100% -> 不可分
        # （make_moons 的标签是 0/1，感知机要求 ±1）
        y_pm = [1 if v == 1 else -1 for v in y]
        p = Perceptron(max_epochs=200).fit(X, y_pm)
        acc = accuracy(y_pm, p.predict(X))
        self.assertLess(acc, 1.0)


# ---------------------------------------------------------------- 线性回归
class TestLinear(unittest.TestCase):
    def test_exact_three_points(self):
        """y = 2x + 1 的三点完全拟合：闭式解必须精确给出 w=2, b=1。"""
        X = [[0.0], [1.0], [2.0]]
        y = [1.0, 3.0, 5.0]
        m = LinearRegression().fit_closed_form(X, y)
        self.assertAlmostEqual(m.coef_[0], 2.0, places=8)
        self.assertAlmostEqual(m.intercept_, 1.0, places=8)
        self.assertAlmostEqual(mse_loss([[0.0], [1.0], [2.0]], y,
                                        m.coef_ + [m.intercept_]), 0.0, places=12)

    def test_closed_form_matches_gd(self):
        rng = random.Random(1)
        X = [[rng.uniform(-2, 2)] for _ in range(60)]
        y = [3 * r[0] - 2 + rng.gauss(0, 0.3) for r in X]
        m1 = LinearRegression().fit_closed_form(X, y)
        m2 = LinearRegression().fit_gd(X, y, lr=0.05, epochs=8000)
        self.assertAlmostEqual(m1.coef_[0], m2.coef_[0], delta=1e-3)
        self.assertAlmostEqual(m1.intercept_, m2.intercept_, delta=1e-3)

    def test_gradient_matches_numeric(self):
        rng = random.Random(2)
        X = [[rng.uniform(-1, 1), rng.uniform(-1, 1)] for _ in range(20)]
        y = [rng.uniform(-1, 1) for _ in range(20)]
        params = [0.3, -0.7, 0.1]
        analytic = mse_gradient(X, y, params)
        for i in range(len(params)):
            eps = 1e-6
            hi = params[:]; lo = params[:]
            hi[i] += eps
            lo[i] -= eps
            num = (mse_loss(X, y, hi) - mse_loss(X, y, lo)) / (2 * eps)
            self.assertLess(abs(num - analytic[i]) / max(1.0, abs(num)), 1e-6)

    def test_solve_linear_system(self):
        # [[2,1],[1,3]] x = [5,10] 的解是 x=[1,3]
        self.assertTrue(all(abs(a - b) < 1e-9 for a, b in
                            zip(solve_linear_system([[2.0, 1.0], [1.0, 3.0]],
                                                    [5.0, 10.0]), [1.0, 3.0])))

    def test_r2(self):
        self.assertAlmostEqual(r2_score([1, 2, 3], [1, 2, 3]), 1.0)
        self.assertAlmostEqual(r2_score([2, 2, 2], [2, 2, 2]), 0.0)   # 均值预测 -> 0
        self.assertLess(r2_score([1, 2, 3], [3, 2, 1]), 0.0)          # 反向 -> 负


# ---------------------------------------------------------------- 感知机
class TestPerceptron(unittest.TestCase):
    def test_hand_traced_trajectory(self):
        """两点数据集（(0,-1),(1,+1)），lr=1，约定 sign(0)=-1。
        更新条件是严格间隔：y·(w·x+b) > 0 才算对（Novikoff 收敛证明的约定，
        score 恰为 0 也算错）。逐轮推演：
          epoch1: (0,-1) score=0 -> 错，w=0,b=-1；(1,+1) score=-1 -> 错，w=1,b=0
          epoch2: (0,-1) score=0 -> 错，b=-1；(1,+1) score=0 -> 错，w=2,b=0
          epoch3: (0,-1) score=0 -> 错，b=-1；(1,+1) score=1 -> 对
          epoch4: (0,-1) score=-1 -> 对；(1,+1) score=1 -> 对。收敛。
        最终 w=[2.0], b=-1.0，恰好 5 次更新、4 轮。"""
        p = Perceptron(lr=1.0, max_epochs=100)
        p.fit([[0.0], [1.0]], [-1, 1])
        self.assertEqual(p.w, [2.0])
        self.assertEqual(p.b, -1.0)
        self.assertEqual(p.updates_, 5)
        self.assertEqual(p.epochs_, 4)
        self.assertTrue(p.converged_)
        # 最终判别面 2x-1>0：边界在两样本中点，且间隔严格为正
        self.assertEqual(p.predict([[0.0], [1.0]]), [-1, 1])

    def test_and_gate(self):
        X = [[0, 0], [0, 1], [1, 0], [1, 1]]
        y = [-1, -1, -1, 1]
        p = Perceptron(max_epochs=100).fit(X, y)
        self.assertTrue(p.converged_)
        self.assertEqual(accuracy(y, p.predict(X)), 1.0)

    def test_blobs_converge(self):
        X, y = mldata.make_blobs(100, seed=3)
        y_pm = [1 if v == 1 else -1 for v in y]      # 0/1 -> ±1
        p = Perceptron(max_epochs=200).fit(X, y_pm)
        self.assertTrue(p.converged_)
        self.assertEqual(accuracy(y_pm, p.predict(X)), 1.0)

    def test_xor_capped_at_75(self):
        """XOR 线性不可分：任何线性判别面最多 75%——这正是多层网络的出发点。"""
        X = [[0, 0], [0, 1], [1, 0], [1, 1]]
        y = [-1, 1, 1, -1]
        accs = []
        for seed in range(10):
            p = Perceptron(lr=0.5, max_epochs=200)
            # 复制 fit 的循环以记录每轮精度（直接用最终模型断言即可）
            p.fit(X, y)
            accs.append(accuracy(y, p.predict(X)))
        self.assertTrue(all(a <= 0.75 for a in accs),
                        f"XOR 上感知机精度不应超过 75%：{accs}")


# ---------------------------------------------------------------- KNN
class TestKNN(unittest.TestCase):
    def test_kneighbors_matches_reference_sort(self):
        """与"全量算距离再排序"的朴素参照实现逐一对照。"""
        rng = random.Random(5)
        X = [[rng.uniform(-5, 5), rng.uniform(-5, 5)] for _ in range(50)]
        y = [rng.choice("AB") for _ in range(50)]
        knn = KNN(k=5).fit(X, y)
        q = [0.3, -1.2]
        dists = [(euclidean(q, x), i) for i, x in enumerate(X)]
        dists.sort(key=lambda p: (p[0], p[1]))
        want = [(d, y[i]) for d, i in dists[:5]]
        self.assertEqual(knn.kneighbors(q), want)

    def test_hand_case_votes(self):
        X = [[0.0], [1.0], [10.0]]
        y = ["A", "A", "B"]
        self.assertEqual(KNN(k=1).fit(X, y).predict_one([0.1]), "A")
        # k=3 的邻居是 A(距离9.5) A(8.5) B(0.5)：最近的是 B，但多数票 2:1 -> A。
        # 这正是"k 增大后被多数类淹没"的教学实例。
        self.assertEqual(KNN(k=3).fit(X, y).predict_one([0.1]), "A")
        self.assertEqual(KNN(k=3).fit(X, y).predict_one([9.5]), "A")  # 2:1 多数派
        self.assertEqual(KNN(k=1).fit(X, y).predict_one([9.5]), "B")  # k=1 才跟最近邻

    def test_tie_break_deterministic(self):
        # 2:2 平局：两次预测必须同答案（平局按总距离更小的类）
        X = [[0.0], [0.2], [10.0], [10.1]]
        y = ["A", "B", "A", "B"]
        k = KNN(k=4).fit(X, y)
        self.assertEqual(k.predict_one([5.0]), k.predict_one([5.0]))


# ---------------------------------------------------------------- 决策树
def independent_gain(X, y, feature, threshold):
    """测试里独立实现的信息增益（不 import ml.tree）——决策树的参照答案。"""
    def ent(labels):
        n = len(labels)
        if n == 0:
            return 0.0
        total = 0.0
        for c in set(labels):
            p = labels.count(c) / n
            total -= p * math.log2(p)
        return total

    left = [lab for row, lab in zip(X, y) if row[feature] <= threshold]
    right = [lab for row, lab in zip(X, y) if row[feature] > threshold]
    parent = ent(y)
    return parent - (len(left) * ent(left) + len(right) * ent(right)) / len(y)


class TestTree(unittest.TestCase):
    def setUp(self):
        # 带一点噪声的可分数据
        rng = random.Random(9)
        self.X = [[rng.uniform(0, 1), rng.uniform(0, 1)] for _ in range(60)]
        self.y = ["P" if (x[0] + x[1]) > 1.0 else "N" for x in self.X]

    def test_root_split_matches_independent_gain(self):
        tree = DecisionTree(criterion="entropy", max_depth=1).fit(self.X, self.y)
        # 测试端独立穷举所有分裂，取增益最大者
        best = (-1.0, None, None)
        for f in range(2):
            vals = sorted({row[f] for row in self.X})
            for a, b in zip(vals, vals[1:]):
                t = (a + b) / 2
                g = independent_gain(self.X, self.y, f, t)
                if g > best[0]:
                    best = (g, f, t)
        self.assertEqual(tree.root_.feature, best[1])
        self.assertAlmostEqual(tree.root_.threshold, best[2], places=9)

    def test_separable_data_perfect(self):
        tree = DecisionTree(max_depth=10).fit(self.X, self.y)
        self.assertEqual(accuracy(self.y, tree.predict(self.X)), 1.0)

    def test_xor_tree_solves_but_depth1_cannot(self):
        """与感知机对照：决策树两棵分裂就能解 XOR（轴平行的两次切割）。"""
        X = [[0, 0], [0, 1], [1, 0], [1, 1]]
        y = ["A", "B", "B", "A"]
        full = DecisionTree(max_depth=5).fit(X, y)
        self.assertEqual(accuracy(y, full.predict(X)), 1.0)
        shallow = DecisionTree(max_depth=1).fit(X, y)
        self.assertLess(accuracy(y, shallow.predict(X)), 1.0)

    def test_determinism(self):
        a = DecisionTree().fit(self.X, self.y).predict(self.X)
        b = DecisionTree().fit(self.X, self.y).predict(self.X)
        self.assertEqual(a, b)

    def test_proba_sums_to_one(self):
        tree = DecisionTree(max_depth=3).fit(self.X, self.y)
        for x in self.X[:10]:
            self.assertAlmostEqual(sum(tree.predict_proba_one(x).values()), 1.0)


# ---------------------------------------------------------------- BP 网络
class TestNeuralNet(unittest.TestCase):
    def _small_net(self):
        rng = random.Random(11)
        X = [[rng.uniform(-1, 1), rng.uniform(-1, 1)] for _ in range(12)]
        y = ["L" if x[0] + x[1] > 0 else "R" for x in X]
        return MLP([2, 3, 2], hidden_act="tanh", seed=1, lr=0.5, epochs=100), X, y

    def test_gradient_check(self):
        """数值梯度（中心差分）vs 反向传播的解析梯度——手写 BP 的第一道验收。"""
        net, X, y = self._small_net()
        net.fit(X, y, classes=["L", "R"])
        classes = ["L", "R"]
        Y1h = [[1.0 if c == lab else 0.0 for c in classes] for lab in y]
        gradW, gradB = net.backprop(X, Y1h)
        eps = 1e-6
        worst = 0.0
        checked = 0
        # 抽查：每层前 3 个权重 + 全部偏置
        for l in range(len(net.W)):
            for j in range(len(net.W[l])):
                for i in range(len(net.W[l][j])):
                    if (l + j + i) % 3 and checked > 24:
                        continue
                    orig = net.W[l][j][i]
                    net.W[l][j][i] = orig + eps
                    lp = net.loss(X, Y1h)
                    net.W[l][j][i] = orig - eps
                    lm = net.loss(X, Y1h)
                    net.W[l][j][i] = orig
                    num = (lp - lm) / (2 * eps)
                    denom = max(1e-8, abs(num) + abs(gradW[l][j][i]))
                    worst = max(worst, abs(num - gradW[l][j][i]) / denom)
                    checked += 1
            for j in range(len(net.b[l])):
                orig = net.b[l][j]
                net.b[l][j] = orig + eps
                lp = net.loss(X, Y1h)
                net.b[l][j] = orig - eps
                lm = net.loss(X, Y1h)
                net.b[l][j] = orig
                num = (lp - lm) / (2 * eps)
                denom = max(1e-8, abs(num) + abs(gradB[l][j]))
                worst = max(worst, abs(num - gradB[l][j]) / denom)
                checked += 1
        self.assertLess(worst, 1e-5,
                        f"梯度检查最大相对误差 {worst}——反传实现有错")

    def test_loss_decreases(self):
        net, X, y = self._small_net()
        net.fit(X, y, classes=["L", "R"])
        self.assertLess(net.loss_history_[-1], net.loss_history_[0])

    def test_xor_bp_solves(self):
        """感知机封顶 75% 的 XOR，一个 2-4-2 的 BP 网络应该全对。"""
        X = [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]]
        y = ["A", "B", "B", "A"]
        net = MLP([2, 4, 2], hidden_act="tanh", seed=3, lr=0.5, epochs=2000)
        net.fit(X, y)
        self.assertEqual(accuracy(y, net.predict(X)), 1.0)

    def test_moons_bp_beats_linear(self):
        X, y = mldata.make_moons(200, noise=0.15, seed=7)
        net = MLP([2, 16, 2], hidden_act="tanh", seed=5, lr=0.5, epochs=800)
        net.fit(X, y)
        # 固定种子实测 1.000；阈值 0.98 留余量。注意 noise=0.15 时两月牙有重叠，
        # 贝叶斯最优本身 <100%，"测不满"不代表没训好。
        self.assertGreaterEqual(accuracy(y, net.predict(X)), 0.98)

    def test_proba_sums_to_one(self):
        net, X, y = self._small_net()
        for p in net.predict_proba(X[:5]):
            self.assertAlmostEqual(sum(p), 1.0, places=9)


# ---------------------------------------------------------------- Iris 端到端
class TestIrisEndToEnd(unittest.TestCase):
    """阈值是固定种子下的实测值（README 注明），不是理论保证。"""

    @classmethod
    def setUpClass(cls):
        cls.X, cls.y = mldata.load_iris()
        cls.tr, cls.te = mldata.train_test_split(150, 0.2, seed=42)
        cls.Xtr, cls.Xte = mldata.standardize([cls.X[i] for i in cls.tr],
                                              [cls.X[i] for i in cls.te])
        cls.ytr = [cls.y[i] for i in cls.tr]
        cls.yte = [cls.y[i] for i in cls.te]

    def test_knn(self):
        knn = KNN(k=3).fit(self.Xtr, self.ytr)
        acc = accuracy(self.yte, knn.predict(self.Xte))
        self.assertGreaterEqual(acc, 0.9)

    def test_tree(self):
        tree = DecisionTree(criterion="entropy", max_depth=4).fit(self.Xtr, self.ytr)
        acc = accuracy(self.yte, tree.predict(self.Xte))
        self.assertGreaterEqual(acc, 0.9)

    def test_perceptron_setosa_binary(self):
        """setosa 线性可分（petal 特征就能分开）：二分类感知机应当接近全对。"""
        Xtr = [[x[2], x[3]] for x in self.Xtr]
        Xte = [[x[2], x[3]] for x in self.Xte]
        ytr = [1 if lab == "setosa" else -1 for lab in self.ytr]
        yte = [1 if lab == "setosa" else -1 for lab in self.yte]
        p = Perceptron(max_epochs=200).fit(Xtr, ytr)
        self.assertGreaterEqual(accuracy(yte, p.predict(Xte)), 0.9)

    def test_neuralnet(self):
        net = MLP([4, 8, 3], hidden_act="tanh", seed=42, lr=0.1, epochs=300,
                  batch_size=16)
        net.fit(self.Xtr, self.ytr)
        acc = accuracy(self.yte, net.predict(self.Xte))
        self.assertGreaterEqual(acc, 0.9)

    def test_linear_regression_petals(self):
        """回归任务：用花萼两特征预测花瓣长度。阈值为实测。"""
        Xtr = [[self.X[i][0], self.X[i][1]] for i in self.tr]
        Xte = [[self.X[i][0], self.X[i][1]] for i in self.te]
        ytr = [self.X[i][2] for i in self.tr]
        yte = [self.X[i][2] for i in self.te]
        m = LinearRegression().fit_closed_form(Xtr, ytr)
        r2 = r2_score(yte, m.predict(Xte))
        self.assertGreaterEqual(r2, 0.75)


if __name__ == "__main__":
    unittest.main(verbosity=2)
