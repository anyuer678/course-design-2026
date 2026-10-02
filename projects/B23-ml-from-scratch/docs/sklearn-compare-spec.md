# 与 scikit-learn 对拍：先定死的比较口径（B41 候选⑤）

这份文档**先于实现**写出（2026-10-02）。要回答的问题（B41 候选⑤的三条验收）：
① 同数据同超参下，手写实现 vs sklearn 的精度/损失差在**声明的容差**内；
② 规模曲线（n=200→2000）两类实现的时间与内存对照；
③ 反向：把 sklearn 换成**故意错参**，对拍台必须变红（防「对拍只对得齐不报错」）。

种子风险评估里最重的一条：**sklearn 的版本行为差异（默认参、随机种子）会制造假分歧，
必须写死全部随机源**。所以本规格的一半是"什么**不**比"——先划清楚，实现只做翻译。

环境登记（安装时实测，双口径）：下载 **8.7 MB**（scikit-learn 7.88 + joblib 0.29 +
threadpoolctl 0.03 + narwhals 0.45 + cloudpickle 0.02）；安装 **47.0 MB**；
scipy 1.17.1 与 numpy 2.4.6 **本已在位、安装未动**（pip 输出逐包核对：只有上述 5 个新包）。
版本钉死：Python 3.12.3 / sklearn 1.9.1 / scipy 1.17.1 / numpy 2.4.6——行为结论以本机版本为准。

## 一、边界与放置

- `ml/compare_sklearn.py` 是**唯一** import sklearn/numpy 的模块；五个手写核心模块
  （linear/perceptron/knn/tree/neuralnet）保持**纯标准库**不动。
- `tests/test_sklearn_compare.py`：sklearn 缺失时**整文件 SkipTest**（给安装指引进消息）；
  `demo.py` 的对拍段要求 sklearn 在位（缺了给出可操作错误、退出码非 0）——交付机上是齐的。
- 随机源全钉：我们侧 seed=42/7/3/11 等照旧；sklearn 侧 **所有** random_state=0 显式写。

## 二、四组模型对拍 + 指标对拍（容差 = 全量探针最差 + 余量）

| 对照 | 口径（比什么） | 容差 | 本轮实测 |
|---|---|---|---|
| 线性回归闭式解 vs `LinearRegression`（OLS） | 系数与截距逐分量；iris 花瓣长回归、标准化后 | ≤ 1e-6 | 差 1.2e-12 |
| `r2_score` / `accuracy` vs sklearn 同名指标 | 同一份预测喂两边公式 | ≤ 1e-12 | 完全相等（0.851713513828531 逐位同） |
| 交叉熵 vs `sklearn.metrics.log_loss` | 同一概率矩阵（我们模型的输出喂两边） | ≤ 1e-8 | 差 1.4e-12 |
| KNN(k=3) vs `KNeighborsClassifier` | 测试集 30 点预测逐个相等 + 每点最近邻距离 | 预测 0 处不等；距离 ≤ 1e-9 | 0/30 不等；距离逐位同 |
| 决策树（同参：entropy/max_depth=4/min_samples 对 min_samples_split=2） | 测试精度之差 + XOR 满分性 | 精度差 ≤ 0.1 | iris: 0.9 vs 0.9 |
| MLP（同参：tanh / hidden=8 / lr=0.1 / sgd / momentum=0 / batch、轮数打通） | iris 1500 轮：双方 ≥ 0.90 且精度差 ≤ 0.10 | ≤ 0.10 | 0.933 vs 0.967（差 0.033）；moons 16/2500 离线：1.000 vs 1.000 |

## 三、不可比项（写清楚，防止"假分歧"被当缺陷追）

1. **决策树结构不平比**：分裂平局的选择规则两边不同。实测 iris 根分裂
   ours=`petal_length ≤ 2.45` vs sklearn=`petal_width ≤ 0.7`——两者都完美分离 setosa、
   信息增益并列，**都对**。只比行为（精度），不比树形。
2. **熵的底数**：sklearn 的不纯度用自然对数（值差 ln2 系数），我们写的是 log2；
   分裂选择（argmax）不受底数影响，所以同样只比选择结果、不比数值。
3. **MLP 参数与损失逐值不平比**：初始化范围同构但洗牌序列、损失内部缩放不同；
   只比"收敛后的精度"与指标公式（见二表）。
4. **`log_loss` 平滑口径**：我们损失里 `log(p + 1e-12)`；sklearn 1.9 的 log_loss
   **没有 eps 参数**（内部裁剪 1e-15）——差值实测 1.4e-12，容差按 1e-8 留余量。
5. **时间与内存数字不平比**：只进演示与 README【实测】，**不进测试断言**（防 flaky）。

## 四、sklearn 侧必须显式写死的"陷阱参数"（本轮实测校准）

- **`MLPClassifier` 的默认早停会截胡**：默认 `n_iter_no_change=10` 时，
  300/1000/3000 轮结果**一模一样**且卡在 loss≈0.351（它早在第 ~10 轮就停了）。
  对拍参数必须 `tol=0.0` + 极大 `n_iter_no_change`，把轮数真正打通——
  这条写进规格是因为它是本轮的实测发现，不写就会得到"sklearn 学不动"的假结论。
- `momentum=0.0`、`learning_rate="constant"`、`solver="sgd"` 显式写死；
  `batch_size` 固定；`max_iter` 固定。
- 数据切分、标准化统计量全部来自现有 `ml/data.py`（不与 sklearn 的预处理混用）。

## 五、负面对照（每条必须红在该红的原因上）

| 注入的坏参 | 期望红的对照 | 报错须包含 |
|---|---|---|
| sklearn LR 在**打乱标签**上拟合 | 系数对照 | "系数差"与实测差值 |
| sklearn 树 `max_depth=1`（XOR 数据） | 精度对照 | "精度差"与实测差值 |
| sklearn KNN `n_neighbors=1` vs 我们 k=3（构造平票场景） | 预测对照 | "预测不一致"计数 |
| sklearn MLP `hidden=(1,)` | 收敛底线 | "低于底线"与实测精度 |

对拍台 API：`run_comparison(...) -> Report`（含每个对照的实测差值），
`Report.check()` 违规即抛 `ComparisonFailed`（带对照名与差值）；负面对照抓的就是它。

## 六、规模曲线口径

- 幅面：LR/KNN/树到 **n=2000**；BP 到 **n=1000**（纯 Python 成本要如实展示：
  实测 moons 200×800≈12 s、16/2500≈40 s——量级本身就是结论的一部分；
  曲线用固定小 epochs，质量结论另由"收敛预算"对照承担）。
- 指标：训练耗时（ms，每点多次取中位数）+ 内存增量（Windows `K32GetProcessMemoryInfo`
  的 WorkingSet 差值口径；`tracemalloc` 只对纯 Python 侧准确，作辅助列并**如实声明**）。
- sklearn 侧同网格、同轮数跑一遍；数字全部现算。
- **时间盒**：demo 对拍段目标 ≤ 30 s；超了就把网格下调并在 README 登记（不悄悄裁剪）。

## 七、明确不做

- 不做 sklearn 版本兼容矩阵（只钉本机 1.9.1）；不测 GPU/多线程后端；
  不做超参搜索（GridSearchCV）——那会引入大量"哪边调参更多"的噪声；
  不做 MNIST/大数据集（维持 KNOWN 局限：千级样本）。
