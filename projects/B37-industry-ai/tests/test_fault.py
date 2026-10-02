"""tests/test_fault.py —— B37 自测：账本对账 + 特征/标签边界 + 梯度检查 + 误报解剖。

纪律（和本仓库其它项目一致）：
  1. 期望值来自手算、独立参照或**全量探针实测 + 余量**（每个界都注明实测值）；
  2. 复用不是声明是断言：树必须是 B23 的类实例、跨项目路径必须真存在；
  3. 负面自证：标签打乱后 AUC 必须跌回随机附近、错位后必须掉；
  4. 复用边界也要钉：B35 模拟器长时线饱和这一**实测事实**由测试固定，
     B35 若变会在这里被提醒（README 的偏离声明挂在这条上）。
"""
from __future__ import annotations

import random
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fault import telemetry, features as F, models, metrics as M, report as R   # noqa: E402
from fault.config import Config                                                 # noqa: E402
from ml.tree import DecisionTree                                                # noqa: E402 (复用 B23；import 成功本身即断言)

_CACHE: dict = {}


def case() -> dict:
    """全量算例只跑一次（训练 LR/树 ~2s），所有测试共享。"""
    if "case" not in _CACHE:
        cfg = Config()
        fleet = telemetry.generate_fleet(cfg)
        ds = F.build_dataset(cfg, fleet)
        tr, te = F.split_by_device(cfg, ds)
        Xtr, ytr = F.take(ds["X"], ds["y"], tr)
        Xte, yte = F.take(ds["X"], ds["y"], te)
        res = models.fit_two(Xtr, Xte, ytr, cfg)
        tree = models.fit_tree(Xtr, ytr, cfg)
        _CACHE["case"] = {"cfg": cfg, "fleet": fleet, "ds": ds, "tr": tr, "te": te,
                          "Xtr": Xtr, "ytr": ytr, "Xte": Xte, "yte": yte,
                          "res": res, "tree": tree,
                          "tree_scores": models.tree_scores(tree, Xte),
                          "meta_te": [ds["meta"][i] for i in te],
                          "fail_te": [f for f in fleet["failures"]
                                      if f["device"] in cfg.test_devices]}
    return _CACHE["case"]


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b37-{name}-"))
    if str(base.resolve()).lower().startswith(str(ROOT.parent.parent.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


class TestTelemetry(unittest.TestCase):
    def test_fleet_shape_and_ledger_exact(self):
        c = case()
        fleet, cfg = c["fleet"], c["cfg"]
        self.assertEqual(len(fleet["rows"]), cfg.n_devices * cfg.steps)
        self.assertEqual(fleet["sensor_ledger"],
                         {"spike": 147, "freeze": 142, "dropout": 0, "sent": 4800})
        self.assertEqual(sum(1 for r in fleet["rows"] if r["spike"]), 147)
        self.assertEqual(sum(1 for r in fleet["rows"] if r["freeze"]), 142)
        self.assertEqual(len(fleet["failures"]),
                         cfg.n_devices * cfg.failures_per_device)

    def test_ou_walk_stationary(self):
        rng = random.Random(5)
        base, value = 70.0, 70.0
        vals = [value := telemetry._step_ou(value, base, 0.05, 1.2, 0.0, 160.0, rng)
                for _ in range(2000)]
        self.assertLess(abs(sum(vals) / len(vals) - base), 1.2)   # 实测均值偏差 < 0.4
        self.assertTrue(all(0.0 <= v <= 160.0 for v in vals))

    def test_failure_schedule_deterministic_and_spaced(self):
        cfg = Config()
        for d in (0, 3, 9):
            a = telemetry.failure_schedule(cfg, d)
            self.assertEqual(a, telemetry.failure_schedule(cfg, d))
            self.assertEqual(len(a), cfg.failures_per_device)
            for (f1, _k1), (f2, _k2) in zip(a, a[1:]):
                self.assertGreaterEqual(f2 - f1, cfg.min_gap)
            self.assertTrue(all(cfg.first_failure_min <= f <= cfg.steps - 10
                                for f, _k in a))

    def test_effect_ramp_and_decay(self):
        cfg = Config()
        events = [(100, "overheat")]
        self.assertEqual(telemetry._effect(100 - cfg.ramp, events, cfg, "overheat"), 0.0)
        peak = cfg.ramp * cfg.overheat_rate
        self.assertAlmostEqual(telemetry._effect(100, events, cfg, "overheat"), peak)
        self.assertAlmostEqual(telemetry._effect(50, events, cfg, "overheat"), 0.0)
        self.assertAlmostEqual(telemetry._effect(100 + cfg.decay, events, cfg, "overheat"), 0.0)
        mid = telemetry._effect(100 - cfg.ramp // 2, events, cfg, "overheat")
        self.assertTrue(0.0 < mid < peak)                          # 爬升中
        post = telemetry._effect(100 + 1, events, cfg, "overheat")
        self.assertTrue(0.0 < post < peak)                         # 恢复中
        self.assertEqual(telemetry._effect(90, events, cfg, "wear"), 0.0)  # 类型不串

    def test_dropout_guard_raises(self):
        with self.assertRaises(ValueError):
            telemetry.generate_fleet(Config(dropout_p=0.01))

    def test_b35_simulator_saturates_on_long_runs(self):
        """复用边界钉：B35 的 spike 是持久偏移 + 150 上限，480 步温度整体漂高。
        本测试固定这个实测事实（5 种子：均值 131.5..147.3、夹取 15.6%..22.8%）——
        B37 因此只复用它的事务分类学与账本，信号生成换成 OU（见 README）。"""
        from mqttlite.sensors import SensorSimulator
        means, clamps = [], []
        for s in range(5):
            sim = SensorSimulator(f"d{s}", seed=70 + s)
            temps = [r["temp"] for r in (sim.next_reading() for _ in range(480)) if r]
            means.append(sum(temps) / len(temps))
            clamps.append(sum(1 for t in temps if t >= 149.99) / len(temps))
        self.assertGreater(min(means), 120.0)                      # 实测最低 131.5
        self.assertGreater(min(clamps), 0.10)                      # 实测最低 0.156


class TestFeatures(unittest.TestCase):
    def test_label_boundaries(self):
        cfg = Config()
        events = [(100, "wear")]
        self.assertEqual(F.window_label(76, events, cfg), (1, "wear"))   # f-end = 24 = horizon
        self.assertEqual(F.window_label(75, events, cfg), (0, None))     # 25 > horizon
        self.assertEqual(F.window_label(99, events, cfg), (1, "wear"))   # 还剩 1 步
        self.assertEqual(F.window_label(100, events, cfg), (None, None))  # 已发生：排除
        self.assertEqual(F.window_label(100 + cfg.window + cfg.decay - 1, events, cfg),
                         (None, None))                                   # 暂态最后一格仍排除
        self.assertEqual(F.window_label(100 + cfg.window + cfg.decay, events, cfg),
                         (0, None))                                      # 之后回到负样本

    def test_no_future_leak(self):
        c = case()
        cfg, fleet = c["cfg"], c["fleet"]
        device, end = cfg.test_devices[0], 200
        ds_before = F.build_dataset(cfg, fleet)
        idx = next(i for i, m in enumerate(ds_before["meta"])
                   if m["device"] == device and m["end"] == end)

        corrupted = {"rows": [dict(r) for r in fleet["rows"]],
                     "failures": fleet["failures"]}
        for r in corrupted["rows"]:
            if r["device"] == device and r["step"] > end:
                r["temp"] += 1000.0
                r["vib"] += 100.0
        ds_after = F.build_dataset(cfg, corrupted)
        self.assertEqual(ds_before["X"][idx], ds_after["X"][idx])       # 该窗口不被未来污染
        later = next(i for i, m in enumerate(ds_after["meta"])
                     if m["device"] == device and m["end"] > end + 30)
        self.assertNotEqual(ds_before["X"][later], ds_after["X"][later])  # 污染确实生效

    def test_window_features_hand_computed(self):
        rows = [{"temp": 70.0 + 2 * i, "vib": 1.0} for i in range(8)]
        f = F.window_features(rows)
        self.assertAlmostEqual(f[0], 77.0)          # temp_mean
        self.assertAlmostEqual(f[1], 2.0)           # temp_slope（严格线性则 2）
        self.assertAlmostEqual(f[2], 14.0)          # range
        # 70..84 步长 2：偏差 ±1,±3,±5,±7 → 平方和 168 → 方差 21 → std=√21
        self.assertAlmostEqual(f[3], 21 ** 0.5, places=9)
        self.assertAlmostEqual(f[4], 1.0)           # vib_mean
        self.assertAlmostEqual(f[5], 0.0)           # vib_slope
        self.assertAlmostEqual(f[6], 1.0)           # vib_max
        self.assertAlmostEqual(f[7], 0.0)           # vib_std

    def test_split_disjoint_and_complete(self):
        c = case()
        cfg, ds = c["cfg"], c["ds"]
        tr, te = F.split_by_device(cfg, ds)
        self.assertEqual(set(tr) & set(te), set())
        self.assertEqual(sorted(tr + te), list(range(len(ds["X"]))))
        self.assertTrue(all(ds["meta"][i]["device"] in cfg.test_devices for i in te))
        self.assertFalse(any(ds["meta"][i]["device"] in cfg.test_devices for i in tr))


class TestModels(unittest.TestCase):
    def test_sigmoid_properties(self):
        self.assertAlmostEqual(models.sigmoid(0.0), 0.5)
        self.assertLess(models.sigmoid(-3.0), models.sigmoid(-1.0))
        self.assertLess(models.sigmoid(1.0), models.sigmoid(3.0))
        self.assertEqual(models.sigmoid(1e4), 1.0)                 # 两侧都不溢出
        self.assertGreaterEqual(models.sigmoid(-1e4), 0.0)         # 极端负值下溢为 0，不抛异常
        self.assertGreater(models.sigmoid(-40.0), 0.0)             # 正常负值仍有正值输出

    def test_gradient_matches_numeric(self):
        rng = random.Random(3)
        X = [[rng.uniform(-2, 2) for _ in range(3)] for _ in range(30)]
        y = [1 if sum(x) + rng.uniform(-1, 1) > 0 else 0 for x in X]
        w, b = [0.1, -0.2, 0.3], 0.05
        gw, gb = models.gradient(X, y, w, b)
        ngw, ngb = models.numeric_gradient(X, y, w, b)
        err = max([abs(a - c) for a, c in zip(gw, ngw)] + [abs(gb - ngb)])
        self.assertLess(err, 1e-6, msg=f"解析梯度与数值梯度差 {err:.3e}（实测 2.8e-11）")

    def test_gd_newton_parity(self):
        c = case()
        self.assertLess(c["res"]["max_weight_gap"], 1e-2)          # 实测 1.9e-3
        gd, nt = c["res"]["gd"], c["res"]["newton"]
        from ml.data import standardize
        tr_std, _ = standardize(c["Xtr"], c["Xte"])
        l_gd = models.cross_entropy(tr_std, c["ytr"], gd.w, gd.b)
        l_nt = models.cross_entropy(tr_std, c["ytr"], nt.w, nt.b)
        self.assertLess(l_nt, l_gd + 1e-6, msg="Newton 应到达最优附近（实测比 GD 低 8e-6）")

    def test_model_never_sees_test_features(self):
        c = case()
        cfg = c["cfg"]
        Xte2 = [[v * 1000.0 for v in row] for row in c["Xte"]]
        res2 = models.fit_two(c["Xtr"], Xte2, c["ytr"], cfg)
        self.assertEqual(c["res"]["gd"].w, res2["gd"].w)           # 测试特征改了，权重分毫不动
        self.assertEqual(c["res"]["gd"].b, res2["gd"].b)

    def test_tree_is_reused_from_b23(self):
        c = case()
        self.assertIsInstance(c["tree"], DecisionTree)

    def test_cross_project_paths_exist(self):
        from fault import B23_DIR, B35_DIR
        self.assertTrue((B23_DIR / "ml" / "tree.py").is_file())
        self.assertTrue((B35_DIR / "mqttlite" / "svgplot.py").is_file())
        self.assertTrue(str(B23_DIR).endswith("B23-ml-from-scratch"))
        self.assertTrue(str(B35_DIR).endswith("B35-iot-mqtt"))


class TestMetrics(unittest.TestCase):
    def test_confusion_and_prf_hand(self):
        scores = [0.9, 0.8, 0.4, 0.3, 0.2]
        y = [1, 0, 1, 1, 0]
        cm = M.confusion(scores, y, 0.5)
        self.assertEqual(cm, {"tp": 1, "fp": 1, "fn": 2, "tn": 1})
        prf = M.prf(cm)
        self.assertAlmostEqual(prf["precision"], 0.5)
        self.assertAlmostEqual(prf["recall"], 1 / 3)
        self.assertAlmostEqual(prf["f1"], 0.4)

    def test_sweep_monotonic_and_rows(self):
        c = case()
        rows = M.sweep(c["res"]["scores_newton"], c["yte"], c["cfg"].sweep_step)
        self.assertEqual(len(rows), 51)
        rec = [r["recall"] for r in rows]
        al = [r["alerts"] for r in rows]
        self.assertTrue(all(a >= b - 1e-12 for a, b in zip(rec, rec[1:])))
        self.assertTrue(all(a >= b - 1e-12 for a, b in zip(al, al[1:])))
        self.assertEqual(rows[0]["threshold"], 0.0)                # 阈值最低 = 全报警

    def test_roc_auc_perfect_and_error(self):
        y = [1, 1, 0, 0]
        self.assertAlmostEqual(M.auc([0.9, 0.8, 0.2, 0.1], y), 1.0)
        pts = M.roc_points([0.9, 0.8, 0.2, 0.1], y)
        self.assertEqual(pts[0], (0.0, 0.0))
        self.assertEqual(pts[-1], (1.0, 1.0))
        with self.assertRaises(ValueError):
            M.auc([0.5, 0.6], [1, 1])

    def test_auc_shuffle_control(self):
        """负面自证：标签打乱后 AUC 必须跌回随机附近（10 种子实测 [0.328, 0.561]）。"""
        c = case()
        for s in range(10):
            sh = list(c["yte"])
            random.Random(s).shuffle(sh)
            a = M.auc(c["res"]["scores_newton"], sh)
            self.assertTrue(0.28 <= a <= 0.65, msg=f"seed={s} shuffled AUC={a:.3f}")

    def test_lead_times_hand(self):
        meta = [{"device": 0, "end": e, "kind": None} for e in (10, 20, 30, 40)]
        alarms = [False, True, True, False]
        failures = [{"device": 0, "step": 45, "kind": "wear"},
                    {"device": 0, "step": 100, "kind": "wear"}]
        out = M.lead_times(alarms, meta, failures, horizon=25)
        self.assertEqual(out["leads"][(0, 45)], 25)               # 最早报警 end=20 得 45-20（horizon 边界）
        self.assertIsNone(out["leads"][(0, 100)])                 # [75, 99] 内无报警则漏掉
        self.assertEqual(out["caught"], 1)

    def test_rule_baseline_exact(self):
        """固定阈值基线的实测账（种子固定则精确钉）：全车队 4 项 + 误报解剖。"""
        c = case()
        rule = M.rule_alarms(c["cfg"], c["fleet"]["rows"], c["meta_te"],
                             M.PLATE_TEMP_LIMIT, M.PLATE_VIB_LIMIT)
        cm = M.confusion([1.0 if a else 0.0 for a in rule], c["yte"], 0.5)
        self.assertEqual(cm, {"tp": 9, "fp": 20, "fn": 15, "tn": 100})
        ctx = M.fp_context(rule, c["yte"], c["meta_te"], c["fleet"]["rows"],
                           c["cfg"].window)
        self.assertEqual(ctx["fp"], 20)
        self.assertEqual(ctx["fp_with_quality_event"], 20)         # 20/20 = 全被数据质量问题骗

    def test_tree_operating_point_and_leads(self):
        """树在 best-F1 运营点的实测账（种子固定则精确钉）+ 提前量逐故障。"""
        c = case()
        best = max(M.sweep(c["tree_scores"], c["yte"], c["cfg"].sweep_step),
                   key=lambda r: r["f1"])
        self.assertAlmostEqual(best["threshold"], 0.14)
        self.assertEqual((best["tp"], best["fp"], best["fn"]), (19, 1, 5))
        alarm = [s >= best["threshold"] for s in c["tree_scores"]]
        out = M.lead_times(alarm, c["meta_te"], c["fail_te"], c["cfg"].horizon)
        self.assertEqual(out["caught"], out["total"])              # 6/6 全接住
        self.assertEqual(out["leads"], {(8, 91): 17, (8, 219): 19, (8, 348): 16,
                                        (9, 74): 18, (9, 252): 16, (9, 422): 18})

    def test_aligned_vs_misaligned_labels(self):
        """负面自证：标签整体错位一格，AUC 必须明显掉（实测 0.926 → 0.774）。"""
        c = case()
        aligned = M.auc(c["res"]["scores_newton"], c["yte"])
        rolled = M.auc(c["res"]["scores_newton"], c["yte"][1:] + c["yte"][:1])
        self.assertGreaterEqual(aligned, 0.85)                     # 实测 0.926
        self.assertLessEqual(rolled, 0.85)                         # 实测 0.774


class TestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = make_tmp("viz")
        c = case()
        cls.rows = M.sweep(c["res"]["scores_newton"], c["yte"], c["cfg"].sweep_step)
        cls.fleet = c["fleet"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_alert_chart_deterministic(self):
        size1 = R.alert_budget_chart(self.rows, self.tmp / "a1.svg")
        R.alert_budget_chart(self.rows, self.tmp / "a2.svg")
        b1 = (self.tmp / "a1.svg").read_bytes()
        b2 = (self.tmp / "a2.svg").read_bytes()
        self.assertEqual(b1, b2)
        self.assertGreater(size1, 2500)                            # 实测 3066
        text = b1.decode("utf-8")
        self.assertIn("<polyline", text)
        self.assertTrue(text.rstrip().endswith("</svg>"))

    def test_device_charts_have_failure_marks(self):
        out = R.device_charts(self.fleet, 8, self.tmp)
        self.assertEqual(sorted(out), ["temp", "vib"])
        text = (self.tmp / "dev08_temp.svg").read_text(encoding="utf-8")
        self.assertEqual(text.count("<circle"), 3)                 # dev08 有 3 次故障


class TestIntegration(unittest.TestCase):
    def test_pipeline_deterministic(self):
        """整条链两遍逐值一致（种子化的应收敛到逐位相同）。"""
        cfg = Config()
        f1 = telemetry.generate_fleet(cfg)
        f2 = telemetry.generate_fleet(cfg)
        self.assertEqual(f1["rows"][:200], f2["rows"][:200])
        self.assertEqual(f1["sensor_ledger"], f2["sensor_ledger"])
        d1 = F.build_dataset(cfg, f1)
        d2 = F.build_dataset(cfg, f2)
        self.assertEqual(d1["X"], d2["X"])
        tr, te = F.split_by_device(cfg, d1)
        Xtr, ytr = F.take(d1["X"], d1["y"], tr)
        Xte, _ = F.take(d1["X"], d1["y"], te)
        a = models.fit_two(Xtr, Xte, ytr, cfg)
        b = models.fit_two(Xtr, Xte, ytr, cfg)
        self.assertEqual(a["scores_newton"], b["scores_newton"])


if __name__ == "__main__":
    unittest.main()
