"""fault/metrics.py —— 误报/漏报的度量：混淆矩阵、阈值扫描、ROC/AUC、提前量、误报解剖

口径先写在这（行业报告最容易含糊的地方）：
    - **正类 = "未来 horizon 步内会发生故障"**，漏报(FN) = 故障前没能报警，
      误报(FP) = 报了警但 horizon 内什么都没发生；二者是同一个阈值的两个方向；
    - 阈值**从高到低**扫：报警数不降、召回不降（测试把这条单调性钉住）；
    - ROC/AUC 用测试集分数现算、梯形积分；AUC 是"排序质量"，
      与运营阈值无关——所以它和"告警预算选点"是两个问题；
    - 提前量(lead time) 只认 [f-horizon, f-1] 内的**首次**报警：
      比 horizon 更早的报警不由本窗口标签背书，不吹成"预警更早"。
"""
from __future__ import annotations

#: 固定阈值基线的"铭牌值"：温度上限 100°C、振动上限 2.0 mm/s。
#: 是**不动点**（行业惯例），不是从数据拟合的——对比它就是要把"固定阈值会被什么骗"显出来。
PLATE_TEMP_LIMIT = 100.0
PLATE_VIB_LIMIT = 2.0


def confusion(scores: list[float], y: list[int], threshold: float) -> dict:
    tp = fp = fn = tn = 0
    for s, lab in zip(scores, y):
        alarm = s >= threshold
        if lab == 1 and alarm:
            tp += 1
        elif lab == 1 and not alarm:
            fn += 1
        elif lab == 0 and alarm:
            fp += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def prf(cm: dict) -> dict:
    tp, fp, fn = cm["tp"], cm["fp"], cm["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def sweep(scores: list[float], y: list[int], step: float = 0.02) -> list[dict]:
    """阈值扫描表（含端点 0 与 1+ε 的语义：0 = 全报警，1 = 只报满置信）。"""
    rows = []
    k = 0
    while k * step <= 1.0 + 1e-12:
        thr = round(k * step, 10)
        cm = confusion(scores, y, thr)
        rows.append({"threshold": thr, **cm, **prf(cm), "alerts": cm["tp"] + cm["fp"]})
        k += 1
    return rows


def roc_points(scores: list[float], y: list[int]) -> list[tuple[float, float]]:
    """(FPR, TPR) 点列：按分数从高到低逐个作阈，含 (0,0) 起点。"""
    pos = sum(1 for lab in y if lab == 1)
    neg = sum(1 for lab in y if lab == 0)
    if pos == 0 or neg == 0:
        raise ValueError("ROC 需要正负样本都在场")
    pts = [(0.0, 0.0)]
    tp = fp = 0
    for s, lab in sorted(zip(scores, y), key=lambda p: -p[0]):
        if lab == 1:
            tp += 1
        else:
            fp += 1
        pts.append((fp / neg, tp / pos))
    return pts


def auc(scores: list[float], y: list[int]) -> float:
    pts = roc_points(scores, y)
    area = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        area += (x1 - x0) * (y0 + y1) / 2
    return area


def rule_alarms(cfg, rows: list[dict], meta: list[dict],
                temp_limit: float, vib_limit: float) -> list[bool]:
    """固定阈值基线：窗口内有任意读数 temp≥limit 或 vib≥limit 就报警。
    这是**铭牌值**（不是拟合出来的）——对比它就是要把"固定阈值会被什么骗"显出来。"""
    by_device: dict[int, list[dict]] = {}
    for r in rows:
        by_device.setdefault(r["device"], []).append(r)
    out = []
    for m in meta:
        span = by_device[m["device"]][m["end"] - cfg.window:m["end"]]
        out.append(any(r["temp"] >= temp_limit or r["vib"] >= vib_limit for r in span))
    return out


def lead_times(y_alarm: list[bool], meta: list[dict], failures: list[dict],
               horizon: int) -> dict:
    """每个故障的提前量：首次报警窗口末端 t ∈ [f-horizon, f-1]，lead = f - t。
    返回 {"leads": {故障键: lead 或 None}, "caught": k, "total": n}。"""
    alarm_by_device: dict[int, list[int]] = {}
    for alarm, m in zip(y_alarm, meta):
        if alarm:
            alarm_by_device.setdefault(m["device"], []).append(m["end"])
    leads = {}
    caught = 0
    for f in failures:
        key = (f["device"], f["step"])
        cands = [t for t in alarm_by_device.get(f["device"], [])
                 if f["step"] - horizon <= t <= f["step"] - 1]
        if cands:
            leads[key] = f["step"] - min(cands)
            caught += 1
        else:
            leads[key] = None
    return {"leads": leads, "caught": caught, "total": len(failures)}


def fp_context(y_alarm: list[bool], y: list[int], meta: list[dict],
               rows: list[dict], window: int) -> dict:
    """误报解剖：测试集里每个误报窗口，数一数窗口内有没有 spike/freeze 读数。
    返回 {"fp": n, "fp_with_quality_event": k, "share": k/n}。"""
    by_device: dict[int, list[dict]] = {}
    for r in rows:
        by_device.setdefault(r["device"], []).append(r)
    fp = share = 0
    for alarm, lab, m in zip(y_alarm, y, meta):
        if not alarm or lab != 0:
            continue
        fp += 1
        span = by_device[m["device"]][m["end"] - window:m["end"]]
        if any(r["spike"] or r["freeze"] for r in span):
            share += 1
    return {"fp": fp, "fp_with_quality_event": share,
            "share": share / fp if fp else 0.0}
