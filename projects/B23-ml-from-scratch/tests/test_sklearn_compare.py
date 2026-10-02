"""B23×⑤ 对拍测试：与 scikit-learn 的同参对照（口径先写死在 docs/sklearn-compare-spec.md）

两类断言：
    - **正面**：五组对照按声明容差通过（违规即抛 ComparisonFailed——检查器自带牙齿）；
    - **负面**：故意错参的 sklearn 必须让对拍台**红在该红的原因上**（报错名逐条断言）。
      这是对"对拍只对得齐不报错"的正面防御：没有这一组，容差和检查器都是摆设。

**sklearn 缺失时整文件 SkipTest**（给可操作的安装指引）——33 项核心测试保持
纯标准库、不依赖它；本机交付态 sklearn 1.9.1 在位，因此这里全部实跑。

时间与内存数字**不做断言**（防 flaky，规格 §三.5）：曲线只测结构与值域合法性。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from ml import compare_sklearn as cmp
    from sklearn.linear_model import LinearRegression as SkLinearRegression
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.neural_network import MLPClassifier
    from sklearn.tree import DecisionTreeClassifier
    IMPORT_ERROR = None
except ImportError as exc:                       # pragma: no cover - 交付机上有装
    IMPORT_ERROR = exc


def setUpModule():                               # noqa: N802
    if IMPORT_ERROR is not None:
        raise unittest.SkipTest(
            f"scikit-learn 未安装（{IMPORT_ERROR}）——本文件跳过；"
            "安装：python -m pip install scikit-learn（体积口径见 README）")


class TestPositiveComparisons(unittest.TestCase):
    """正面：五组对照全部通过（差值都远小于容差，读数进 README 实测表）。"""

    def test_linear_coefficients_match(self):
        check = cmp.compare_linear()
        self.assertEqual(check.name, "线性回归系数")
        self.assertLessEqual(check.diff, check.tolerance)

    def test_knn_predictions_and_distances_match(self):
        check = cmp.compare_knn()
        self.assertLessEqual(check.diff, cmp.TOL_NEIGHBOR)

    def test_tree_accuracy_and_xor(self):
        check = cmp.compare_tree()
        self.assertLessEqual(check.diff, cmp.TOL_ACC_DIFF)

    def test_mlp_accuracy_within_tolerance(self):
        check = cmp.compare_mlp()                 # 双侧 iris 1500 轮（规格 §二）
        self.assertLessEqual(check.diff, cmp.TOL_ACC_DIFF)
        self.assertIn("1500 轮", check.note)

    def test_metric_formulas_match(self):
        check = cmp.compare_metrics()
        self.assertLessEqual(check.diff, cmp.TOL_LOG_LOSS)

    def test_check_verdict_raises_with_name(self):
        """检查器本身的行为：超差必抛、消息带 [对照名]（负面对照按名断言的前提）。"""
        with self.assertRaises(cmp.ComparisonFailed) as caught:
            cmp.Check("某个对照", diff=0.5, tolerance=0.1, note="说明").verdict()
        self.assertIn("[某个对照]", str(caught.exception))
        self.assertIsInstance(caught.exception, AssertionError)


class TestNegativeControls(unittest.TestCase):
    """负面：错参必须红在该红的原因上（文件名/对照名逐条钉死）。"""

    def test_linear_shuffled_labels_turns_red(self):
        def bad(A, b):
            return SkLinearRegression().fit(A, list(reversed(b)))
        with self.assertRaises(cmp.ComparisonFailed) as caught:
            cmp.compare_linear(sk_fit=bad)
        self.assertIn("线性回归系数", str(caught.exception))

    def test_tree_depth1_on_xor_turns_red(self):
        def bad(A, b):
            return DecisionTreeClassifier(criterion="entropy", max_depth=1,
                                          random_state=0).fit(A, b)
        with self.assertRaises(cmp.ComparisonFailed) as caught:
            cmp.compare_tree(sk_fit=bad)
        self.assertIn("树", str(caught.exception))

    def test_knn_wrong_k_turns_red(self):
        # 构造平票场景：查询点身边 1 个 B（更近）+ 2 个 A（稍远）——
        # k=1 选 B、k=3 选 A（多数），预测必然不一致
        dataset = ([[0.3, 0.0], [-0.3, 0.0], [0.05, 0.0]], [[0.0, 0.0]],
                   [0, 0, 1], [0])

        def bad(A, b):
            return KNeighborsClassifier(n_neighbors=1).fit(A, b)
        with self.assertRaises(cmp.ComparisonFailed) as caught:
            cmp.compare_knn(sk_fit=bad, dataset=dataset)
        self.assertIn("KNN 预测", str(caught.exception))
        self.assertIn("预测不一致", str(caught.exception))

    def test_mlp_wrong_hidden_turns_red(self):
        """故意错参：单隐元 + 学习率 0.001（实测测试精度 0.267——容量与步长都错）。
        注意单隐元 lr=0.1 其实能到 0.93，这个负面对照是用**实测**选出来的，
        不是拍脑袋写的（第一版选"单隐元"就被自己的对拍台放行了）。"""
        def bad(A, b):
            return cmp._fit_silent(MLPClassifier(
                hidden_layer_sizes=(1,), activation="tanh", solver="sgd",
                learning_rate_init=0.001, learning_rate="constant", momentum=0.0,
                max_iter=600, random_state=0, batch_size=120,
                tol=0.0, n_iter_no_change=10 ** 9), A, b)
        with self.assertRaises(cmp.ComparisonFailed) as caught:
            cmp.compare_mlp(sk_fit=bad, epochs=600)     # 负面对照用短预算省时间
        self.assertIn("MLP", str(caught.exception))


class TestScaleCurveShape(unittest.TestCase):
    """曲线与内存探针：测结构与值域合法性；**时间/内存数字不做断言**（规格 §三.5）。"""

    def test_scale_curve_small_grid(self):
        rows = cmp.scale_curve(sizes=(200,), bp_sizes=(200,), bp_epochs=5)
        self.assertEqual(len(rows), 4)                       # 3 算法 + BP
        for row in rows:
            self.assertGreater(row["ours_ms"], 0.0)
            self.assertGreaterEqual(row["sk_ms"], 0.0)
            self.assertEqual(row["n"], 200)
        algos = {row["algo"] for row in rows}
        self.assertEqual(len(algos), 4)

    def test_memory_probe_quick_shape(self):
        mem = cmp.memory_probe(quick=True)
        self.assertEqual(len(mem), 1)
        row = mem[0]
        self.assertGreater(row["ours_peak"], 0)              # 我们侧是全量口径
        self.assertGreaterEqual(row["sk_peak"], 0)           # sklearn 侧是下界


if __name__ == "__main__":
    unittest.main(verbosity=2)
