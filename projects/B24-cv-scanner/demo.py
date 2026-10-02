"""demo.py —— B24 六段演示：真值都来自合成器，数字全部运行时现算。

 1) 环境与真值：cv2 版本、生成"文档照片"、打印摆好的四角真值
 2) 检测：检测角点 vs 真值的逐角距离（像素级误差）
 3) 透视还原：还原图 vs 原始顶视图的 MAD 与掩码一致率
 4) 二值化对照：Otsu vs 自适应各自的真值一致率 + 两法一致率
 5) 失败样例对照：五类拒识原因（不崩、不硬猜）
 6) 批量统计 + 产物：20 个种子的成功率与最差值；把输入/还原/二值写成 PNG 到 build/

固定种子、不打印耗时；PNG 落在 build/（构建产物目录），供你直接打开肉眼核对。
"""
from __future__ import annotations

import pathlib
import sys

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from cvscan import binarize, pipeline, synth   # noqa: E402

LINE = "=" * 78


def section(no: int, title: str) -> None:
    print(f"\n{LINE}\n  {no}) {title}\n{LINE}")


def show(label: str, value: object) -> None:
    print(f"  {label:<24}{value}")


def main() -> int:
    print("B24-cv-scanner 演示：文档边缘检测 → 透视变换 → 二值化（真值来自合成器）")
    show("OpenCV 版本", cv2.__version__)

    # ------------------------------------------------------------------ 1
    section(1, "环境与真值：程序生成\"文档照片\"，四角是我们摆好的")
    rng = np.random.default_rng(3)
    doc = synth.render_document(rng=rng)
    photo = synth.photograph(doc, rng=rng)
    show("照片画布", f"{photo.image.shape[1]}x{photo.image.shape[0]} 灰度")
    show("文档暗像素占比（真值）", f"{doc.dark_ratio:.4f}")
    for name, (x, y) in zip(("左上", "右上", "右下", "左下"), photo.true_corners):
        show(f"真值角点·{name}", f"({x:.1f}, {y:.1f})")

    # ------------------------------------------------------------------ 2
    section(2, "检测：Canny → 形态学闭 → 轮廓 → 四边形逼近 → 角点排序")
    result = pipeline.scan(photo.image)
    show("检测成功", result.ok)
    errs = pipeline.corner_errors(result.corners, photo.true_corners)
    for name, e in zip(("左上", "右上", "右下", "左下"), errs):
        show(f"角点误差·{name}", f"{e:.2f} px")
    show("最大误差", f"{float(errs.max()):.2f} px")
    show("诊断（候选数/最大面积比）",
         f"{result.metrics.get('candidate_count')} / {result.metrics.get('best_area_ratio'):.3f}")

    # ------------------------------------------------------------------ 3
    section(3, "透视还原：拉正 vs 原始顶视图（像素级对账）")
    cmp_ = pipeline.compare_rectified(result.warped, doc)
    show("MAD（平均绝对差）", f"{cmp_['mad']:.2f} 灰阶")
    show("掩码像素一致率", f"{cmp_['pixel_accuracy']:.4f}")
    show("前景 IoU", f"{cmp_['iou']:.4f}")

    # ------------------------------------------------------------------ 4
    section(4, "二值化对照：Otsu 全局阈值 vs 自适应局部阈值")
    otsu_stats = binarize.agreement(result.binary_otsu, doc.text_mask)
    adaptive_stats = binarize.agreement(result.binary_adaptive, doc.text_mask)
    show("Otsu 阈值", f"{result.otsu_threshold:.0f}")
    show("Otsu 与真值一致率", f"{otsu_stats['pixel_accuracy']:.4f}")
    show("自适应与真值一致率", f"{adaptive_stats['pixel_accuracy']:.4f}")
    show("两法彼此一致率", f"{result.metrics['otsu_adaptive_agreement']:.4f}")

    # ------------------------------------------------------------------ 5
    section(5, "失败样例对照：拒识要带原因")
    rng2 = np.random.default_rng(99)
    doc2 = synth.render_document(rng=rng2)
    cases = [
        ("纯背景", synth.blank_scene(rng=rng2)),
        ("纯噪声", synth.noise_scene(rng=rng2)),
        ("低对比场景", synth.photograph(doc2, low_contrast=True, rng=rng2).image),
        ("文档太小", synth.photograph(doc2, doc_scale=0.15, rng=rng2).image),
        ("图像太小", np.zeros((100, 120), np.uint8)),
    ]
    for name, image in cases:
        r = pipeline.scan(image)
        show(f"{name}（应拒识）", f"ok={r.ok}；原因：{r.reason or '（无）'}")

    # ------------------------------------------------------------------ 6
    section(6, "批量统计（20 种子）+ 产物 PNG")
    ok_count = 0
    worst_err = 0.0
    worst_mad = 0.0
    worst_acc = 1.0
    for seed in range(1, 21):
        rng = np.random.default_rng(seed)
        d = synth.render_document(rng=rng)
        p = synth.photograph(d, rng=rng)
        r = pipeline.scan(p.image)
        if not r.ok:
            continue
        ok_count += 1
        worst_err = max(worst_err, float(pipeline.corner_errors(r.corners, p.true_corners).max()))
        c = pipeline.compare_rectified(r.warped, d)
        worst_mad = max(worst_mad, c["mad"])
        worst_acc = min(worst_acc, c["pixel_accuracy"])
    show("成功率", f"{ok_count}/20")
    show("角点最大误差（最差种子）", f"{worst_err:.2f} px")
    show("MAD（最差种子）", f"{worst_mad:.2f}")
    show("掩码一致率（最差种子）", f"{worst_acc:.4f}")

    out_dir = ROOT / "build"
    out_dir.mkdir(exist_ok=True)
    from cvscan import io as cvio
    sizes = []
    sizes.append(cvio.save_png(out_dir / "demo_input.png", photo.image))
    sizes.append(cvio.save_png(out_dir / "demo_rectified.png", result.warped))
    sizes.append(cvio.save_png(out_dir / "demo_binary.png",
                               result.binary_otsu.astype(np.uint8) * 255))
    show("产物", "build/demo_input.png、demo_rectified.png、demo_binary.png"
                 f"（{sizes[0]}/{sizes[1]}/{sizes[2]} 字节，可直接打开核对）")

    print("\n" + LINE)
    if ok_count != 20 or worst_err > 3.0 or not all(s > 0 for s in sizes):
        print("结果异常：有种子未通过、误差超限，或 PNG 没写成功！")
        return 1
    print("完成：6 段演示全部跑通。固定种子，两遍运行应逐字相同。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
