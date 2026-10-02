"""demo.py —— B37 六段演示：账本对账 → 特征口径 → 三模型对比 → 阈值敏感性 → 误报解剖 → 切分口径。

数字全部运行时现算；【实测】列（各模型耗时）两次运行有波动，其余由固定种子驱动、
逐字可复现（tools/logdiff.py 可核对两次 run.bat 日志）。
"""
from __future__ import annotations

import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fault import telemetry, features as F, models, metrics as M, report as R  # noqa: E402
from fault.config import Config                                                # noqa: E402
from ml.data import train_test_split                                           # noqa: E402


def section(no: int, title: str) -> None:
    print("\n" + "=" * 78 + f"\n  {no}) {title}\n" + "=" * 78)


def show(label: str, value: object) -> None:
    print(f"  {label:<28}{value}")


def main() -> int:
    print("B37-industry-ai 演示：设备故障预测基线 + 误报/漏报分析（模拟数据，不外推生产）")
    cfg = Config()

    # ------------------------------------------------------------------ 1
    section(1, "场景与数据：复用 B35 的异常分类学与账本口径（信号层已按实测换 OU）")
    fleet = telemetry.generate_fleet(cfg)
    by_kind = {"overheat": 0, "wear": 0}
    for f in fleet["failures"]:
        by_kind[f["kind"]] += 1
    show("车队/时间线", f"{cfg.n_devices} 台 × {cfg.steps} 步 = {len(fleet['rows'])} 条读数")
    show("故障注入", f"{len(fleet['failures'])} 次（overheat {by_kind['overheat']} / wear {by_kind['wear']}）")
    led = fleet["sensor_ledger"]
    spike_rows = sum(1 for r in fleet["rows"] if r["spike"])
    freeze_rows = sum(1 for r in fleet["rows"] if r["freeze"])
    show("数据质量账本", f"spike {led['spike']} / freeze {led['freeze']} / dropout 0")
    show("账本逐类对账", f"行数核对 spike={spike_rows} freeze={freeze_rows}（相等即对账过）")
    base_means = {}
    for r in fleet["rows"]:
        base_means.setdefault(r["device"], []).append(r["temp"])
    dev_means = {d: round(sum(v) / len(v), 1) for d, v in sorted(base_means.items())}
    show("各设备温度均值", f"min {min(dev_means.values())}°C / max {max(dev_means.values())}°C（安装点基线不同）")

    # ------------------------------------------------------------------ 2
    section(2, "特征与标签：只从过去看，只对未来标（口径显式）")
    ds = F.build_dataset(cfg, fleet)
    tr, te = F.split_by_device(cfg, ds)
    Xtr, ytr = F.take(ds["X"], ds["y"], tr)
    Xte, yte = F.take(ds["X"], ds["y"], te)
    meta_te = [ds["meta"][i] for i in te]
    show("窗口口径", f"W={cfg.window} 步进={cfg.stride} horizon={cfg.horizon}（标签=未来{cfg.horizon}步内故障）")
    show("样本与排除", f"{len(ds['X'])} 个窗口；排除故障后暂态 {ds['excluded']} 个（t≥f 到恢复结束）")
    show("正样本（将要故障）", f"训练 {sum(ytr)}/{len(tr)}；测试 {sum(yte)}/{len(te)}")
    show("切分", f"按设备：训练 {len(set(m['device'] for m in (ds['meta'][i] for i in tr)))} 台，"
                 f"测试 {len(cfg.test_devices)} 台（0..7 训练 / {cfg.test_devices} 测试）")

    # ------------------------------------------------------------------ 3
    section(3, "三个模型对比：固定阈值 / B23 决策树 / 手写逻辑回归（耗时列【实测】）")
    print(f"   {'模型':<20}{'阈值':>6}{'报警':>5}{'精确率':>8}{'召回率':>8}{'F1':>7}{'AUC':>7}{'耗时[实测]':>12}")
    t0 = time.perf_counter()
    rule = M.rule_alarms(cfg, fleet["rows"], meta_te, M.PLATE_TEMP_LIMIT, M.PLATE_VIB_LIMIT)
    rule_ms = (time.perf_counter() - t0) * 1000
    rule_scores = [1.0 if a else 0.0 for a in rule]
    rule_best = M.confusion(rule_scores, yte, 0.5)
    rb = M.prf(rule_best)
    print(f"   {'固定阈值(铭牌100/2.0)':<20}{'--':>6}{rule_best['tp'] + rule_best['fp']:>5}"
          f"{rb['precision']:>8.3f}{rb['recall']:>8.3f}{rb['f1']:>7.3f}{'--':>7}{rule_ms:>10.1f} ms")

    t0 = time.perf_counter()
    tree = models.fit_tree(Xtr, ytr, cfg)
    tree_ms = (time.perf_counter() - t0) * 1000
    ts = models.tree_scores(tree, Xte)

    t0 = time.perf_counter()
    res = models.fit_two(Xtr, Xte, ytr, cfg)
    lr_ms = (time.perf_counter() - t0) * 1000
    for name, sc, ms in (("B23 决策树", ts, tree_ms), ("手写逻辑回归(L2)", res["scores_newton"], lr_ms)):
        best = max(M.sweep(sc, yte, cfg.sweep_step), key=lambda r: r["f1"])
        print(f"   {name:<20}{best['threshold']:>6.2f}{best['alerts']:>5}"
              f"{best['precision']:>8.3f}{best['recall']:>8.3f}{best['f1']:>7.3f}"
              f"{M.auc(sc, yte):>7.3f}{ms:>10.1f} ms")
    show("双实现互拍", f"GD vs Newton 最大权差 {res['max_weight_gap']:.2e}（L2 保证唯一最优）")

    # ------------------------------------------------------------------ 4
    section(4, "阈值敏感性：同一个模型的代价曲线（点列由 sweep 现算）")
    sc = res["scores_newton"]
    rows = M.sweep(sc, yte, cfg.sweep_step)
    best_f1 = max(rows, key=lambda r: r["f1"])
    hi = [r for r in rows if r["recall"] >= 0.95]
    hi_recall = max(hi, key=lambda r: r["threshold"])
    budget = max((r for r in rows if r["alerts"] <= 24), key=lambda r: r["recall"])
    print(f"   {'口径':<14}{'阈值':>6}{'报警':>5}{'精确率':>8}{'召回率':>8}")
    for label, r in (("best-F1", best_f1), ("召回≥95%", hi_recall), ("告警预算≤24", budget)):
        print(f"   {label:<14}{r['threshold']:>6.2f}{r['alerts']:>5}{r['precision']:>8.3f}{r['recall']:>8.3f}")
    show("AUC（与阈值无关）", f"{M.auc(sc, yte):.3f}（排序质量；选点才是运营决策）")

    # ------------------------------------------------------------------ 5
    section(5, "误报解剖：固定阈值的误报全被数据质量问题骗；漏报看类型")
    ctx = M.fp_context(rule, yte, meta_te, fleet["rows"], cfg.window)
    show("固定阈值误报归因", f"{ctx['fp_with_quality_event']}/{ctx['fp']} 条误报窗内"
                             f"含 spike/freeze（share {ctx['share']:.2f}）")
    tree_best = max(M.sweep(ts, yte, cfg.sweep_step), key=lambda r: r["f1"])
    alarm = [s >= tree_best["threshold"] for s in ts]
    fail_te = [f for f in fleet["failures"] if f["device"] in cfg.test_devices]
    lt = M.lead_times(alarm, meta_te, fail_te, cfg.horizon)
    per_kind = {"overheat": [0, 0], "wear": [0, 0]}
    for f in fail_te:
        per_kind[f["kind"]][1] += 1
        if lt["leads"][(f["device"], f["step"])] is not None:
            per_kind[f["kind"]][0] += 1
    leads_txt = "、".join(f"{k[0]}-{k[1]}:{v}" for k, v in sorted(lt["leads"].items()))
    show("树运营点提前量", f"{lt['caught']}/{lt['total']} 接住；逐故障 {leads_txt}")
    show("按故障类型的接住率", f"overheat {per_kind['overheat'][0]}/{per_kind['overheat'][1]}；"
                               f"wear {per_kind['wear'][0]}/{per_kind['wear'][1]}")

    # ------------------------------------------------------------------ 6
    section(6, "切分口径对比 + 静态产物（可直接打开 build\\ 里的 SVG）")
    n = len(ds["X"])
    r_tr, r_te = train_test_split(n, 0.2, cfg.random_split_seed)     # 复用 B23 的切分
    rXtr, rytr = F.take(ds["X"], ds["y"], r_tr)
    rXte, ryte = F.take(ds["X"], ds["y"], r_te)
    rres = models.fit_two(rXtr, rXte, rytr, cfg)
    rtree = models.fit_tree(rXtr, rytr, cfg)
    show("按设备切（部署口径）", f"LR AUC {M.auc(res['scores_newton'], yte):.3f}；"
                                 f"树 AUC {M.auc(ts, yte):.3f}")
    show("随机切分（对照臂）", f"LR AUC {M.auc(rres['scores_newton'], ryte):.3f}；"
                               f"树 AUC {M.auc(models.tree_scores(rtree, rXte), ryte):.3f}")
    show("解释", "本数据上两口径接近——特征是设备无关统计量；但部署遇到的是新设备，口径仍按设备")
    (ROOT / "build").mkdir(parents=True, exist_ok=True)
    size1 = R.alert_budget_chart(rows, ROOT / "build" / "alert_budget.svg")
    charts = R.device_charts(fleet, 8, ROOT / "build")
    show("产物", f"build/alert_budget.svg（{size1} 字节）；"
                 f"build/dev08_temp.svg（{charts['temp']} 字节）；"
                 f"build/dev08_vib.svg（{charts['vib']} 字节）")

    print("\n" + "=" * 78)
    print("局限声明（必读）：全部数据为**模拟**（合成遥测 + 注入故障），此处的一切指标")
    print("只说明流水线与评估口径自洽，**不外推为真实产线的预测效果**。")
    print("可打开 build\\ 里的两张 dev08 时间线 SVG 与告警预算曲线查看（静态产物）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
