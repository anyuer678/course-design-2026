"""tests/test_cv.py —— B24 自测：合成图像当参照，全部期望值有出处。

纪律（和本仓库其它项目一致）：
  1. 期望值来自**已知真值**：四角是拍摄时摆好的、文字掩码是渲染时记下的——
     检测/还原/二值化的每一次打分都对着它们算；
  2. 容差不是拍的：下文常量旁注明本轮实测值，留 2–3 倍余量；
  3. 种子固定、逐例可复现；不用外部图片、不写文件（PNG 只在 demo 里落 build/）。

实测基准（40 个种子的全量探针，2026-10-02；容差取"实测最差 + 余量"）：
    角点最大误差 0.51~2.00px、MAD 5.7~11.2、掩码像素一致率 0.961~0.999、
    IoU 0.791~0.997、Otsu 与自适应一致率 0.988~0.998。
"""
from __future__ import annotations

import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cvscan import binarize, detect, pipeline, rectify, synth   # noqa: E402

# 容差（旁注数字是 40 种子的实测最差值，阈值在其上留余量）
MAX_CORNER_ERR_PX = 3.0        # 实测最差 2.00
MAX_MAD = 15.0                 # 实测最差 11.2（还原 vs 原始顶视图）
MIN_PIXEL_ACC = 0.95           # 实测最差 0.961
MIN_IOU = 0.75                 # 实测最差 0.791
MIN_OTSU_ADAPTIVE_AGREE = 0.98  # 实测最差 0.9879


def make_scene(seed: int, **photo_kw):
    rng = np.random.default_rng(seed)
    doc = synth.render_document(rng=rng)
    photo = synth.photograph(doc, rng=rng, **photo_kw)
    return doc, photo


class TestOrderPoints(unittest.TestCase):
    def test_hand_derived_order(self):
        # 手摆四个点（打乱顺序），期望排成 TL, TR, BR, BL
        pts = np.array([[88, 80], [10, 10], [9, 78], [90, 12]], dtype=np.float32)
        ordered = detect.order_points(pts)
        self.assertTrue(np.allclose(ordered[0], [10, 10]))   # 左上：和最小
        self.assertTrue(np.allclose(ordered[1], [90, 12]))   # 右上：y−x 最小
        self.assertTrue(np.allclose(ordered[2], [88, 80]))   # 右下：和最大
        self.assertTrue(np.allclose(ordered[3], [9, 78]))    # 左下：y−x 最大

    def test_rotated_quad(self):
        pts = np.array([[50, 120], [130, 60], [120, 10], [40, 70]], dtype=np.float32)
        ordered = detect.order_points(pts)
        # 结构关系：上边两点 y 小于下边两点、左边两点 x 小于右边两点
        self.assertLess(ordered[0][1], ordered[3][1])
        self.assertLess(ordered[1][1], ordered[2][1])
        self.assertLess(ordered[0][0], ordered[1][0])
        self.assertLess(ordered[3][0], ordered[2][0])


class TestDetection(unittest.TestCase):
    def test_clean_scenes_detected_accurately(self):
        for seed in range(1, 21):
            doc, photo = make_scene(seed)
            r = pipeline.scan(photo.image)
            self.assertTrue(r.ok, msg=f"seed={seed}: {r.reason}")
            errs = pipeline.corner_errors(r.corners, photo.true_corners)
            self.assertLess(float(errs.max()), MAX_CORNER_ERR_PX, msg=f"seed={seed} 角点误差")

    def test_corner_naming_is_structural(self):
        for seed in (3, 7, 11):
            _doc, photo = make_scene(seed)
            r = pipeline.scan(photo.image)
            tl, tr, br, bl = r.corners
            self.assertLess(tl[0], tr[0])       # 左上在右上左边
            self.assertLess(tl[1], bl[1])       # 左上在左下上边
            self.assertLess(bl[0], br[0])       # 左下在右下左边
            self.assertLess(tr[1], br[1])       # 右上在右下上边

    def test_result_is_deterministic(self):
        _doc1, photo1 = make_scene(5)
        _doc2, photo2 = make_scene(5)
        self.assertTrue(np.array_equal(photo1.image, photo2.image))
        r1 = pipeline.scan(photo1.image)
        r2 = pipeline.scan(photo2.image)
        self.assertTrue(np.array_equal(r1.corners, r2.corners))
        self.assertTrue(np.array_equal(r1.binary_otsu, r2.binary_otsu))


class TestRectify(unittest.TestCase):
    def test_warp_restores_document_pixels(self):
        for seed in range(1, 11):
            doc, photo = make_scene(seed)
            r = pipeline.scan(photo.image)
            self.assertTrue(r.ok, msg=f"seed={seed}")
            cmp_ = pipeline.compare_rectified(r.warped, doc)
            self.assertLess(cmp_["mad"], MAX_MAD, msg=f"seed={seed} MAD")
            # 二值化对真值掩码的像素一致率（还原质量的"结构化"读数）
            self.assertGreater(cmp_["pixel_accuracy"], MIN_PIXEL_ACC, msg=f"seed={seed} 一致率")
            self.assertGreater(cmp_["iou"], MIN_IOU, msg=f"seed={seed} IoU")

    def test_warp_output_size(self):
        _doc, photo = make_scene(2)
        r = pipeline.scan(photo.image, out_size=(800, 1000))
        self.assertEqual(r.warped.shape, (1000, 800))

    def test_mismatched_shapes_refused(self):
        _doc, photo = make_scene(2)
        r = pipeline.scan(photo.image)
        with self.assertRaises(ValueError):
            pipeline.compare_rectified(r.warped, synth.render_document(width=10, height=10))


class TestBinarize(unittest.TestCase):
    def test_both_methods_match_truth_mask(self):
        for seed in range(1, 11):
            doc, photo = make_scene(seed)
            r = pipeline.scan(photo.image)
            otsu_stats = binarize.agreement(r.binary_otsu, doc.text_mask)
            adaptive_stats = binarize.agreement(r.binary_adaptive, doc.text_mask)
            self.assertGreater(otsu_stats["pixel_accuracy"], MIN_PIXEL_ACC, msg=f"seed={seed} Otsu")
            self.assertGreater(adaptive_stats["pixel_accuracy"], MIN_PIXEL_ACC, msg=f"seed={seed} 自适应")
            self.assertGreater(r.metrics["otsu_adaptive_agreement"], MIN_OTSU_ADAPTIVE_AGREE,
                               msg=f"seed={seed} 两法一致率")

    def test_otsu_threshold_between_text_and_paper(self):
        # 纸 ~235、字 ~30、桌面 ~175：Otsu 阈值应落在纸与桌面/字之间（实测 ~139）
        doc, photo = make_scene(3)
        r = pipeline.scan(photo.image)
        self.assertTrue(30 < r.otsu_threshold < 220, msg=f"阈值={r.otsu_threshold}")


class TestFailurePaths(unittest.TestCase):
    """失败样例对照：拒识要**带原因**，而且五类原因各不相同。"""

    def _reasons(self):
        rng = np.random.default_rng(99)
        doc = synth.render_document(rng=rng)
        cases = {
            "blank": pipeline.scan(synth.blank_scene(rng=rng)),
            "noise": pipeline.scan(synth.noise_scene(rng=rng)),
            "low_contrast": pipeline.scan(synth.photograph(doc, low_contrast=True, rng=rng).image),
            "tiny": pipeline.scan(synth.photograph(doc, doc_scale=0.15, rng=rng).image),
            "small_image": pipeline.scan(np.zeros((100, 120), np.uint8)),
        }
        return cases

    def test_all_fail_with_distinct_reasons(self):
        cases = self._reasons()
        for name, r in cases.items():
            self.assertFalse(r.ok, msg=name)
            self.assertTrue(r.reason, msg=f"{name} 应有原因")
            self.assertIsNone(r.corners, msg=name)
        reasons = {name: r.reason for name, r in cases.items()}
        self.assertIn("边缘密度过高", reasons["noise"])
        self.assertIn("没有可用的边缘", reasons["low_contrast"])
        self.assertIn("没有可用的边缘", reasons["blank"])
        self.assertIn("面积达标", reasons["tiny"])
        self.assertIn("图像太小", reasons["small_image"])
        # 五类里至少四种不同原因（blank 与 low_contrast 共享"无边缘"是合理的）
        self.assertGreaterEqual(len(set(reasons.values())), 4)

    def test_empty_image_refused(self):
        r = pipeline.scan(np.zeros((0, 0), np.uint8))
        self.assertFalse(r.ok)
        self.assertIn("空", r.reason)


class TestIo(unittest.TestCase):
    """读写要走 cvscan.io：cv2.imwrite 对含中文的**绝对路径**会静默失败（实测）。"""

    def test_png_roundtrip_in_temp_dir(self):
        import shutil
        import tempfile
        from cvscan import io as cvio

        base = pathlib.Path(tempfile.mkdtemp(prefix="b24-io-"))
        self.addCleanup(shutil.rmtree, base, True)
        self.assertFalse(str(base.resolve()).lower().startswith(
            str(pathlib.Path(__file__).resolve().parents[3]).lower()))

        doc, photo = make_scene(3)
        r = pipeline.scan(photo.image)
        path = base / "out.png"
        written = cvio.save_png(path, r.warped)
        self.assertGreater(written, 100)
        back = cvio.load_png(path)
        self.assertTrue(np.array_equal(back, r.warped))

    def test_load_missing_file_raises_oserror(self):
        import tempfile
        from cvscan import io as cvio
        with tempfile.TemporaryDirectory(prefix="b24-io-") as tmp:
            # 缺文件是 Python 文件 API 的自然行为：FileNotFoundError（OSError 家族）
            with self.assertRaises(FileNotFoundError):
                cvio.load_png(pathlib.Path(tmp) / "does-not-exist.png")


class TestRobustness(unittest.TestCase):
    def test_shadowed_scene_still_detected(self):
        # 设计内的"没做去阴影"：温和阴影下检测仍成立（角点误差用同一容差）
        for seed in (4, 9):
            doc, photo = make_scene(seed, shadow=True)
            r = pipeline.scan(photo.image)
            self.assertTrue(r.ok, msg=f"seed={seed}: {r.reason}")
            errs = pipeline.corner_errors(r.corners, photo.true_corners)
            self.assertLess(float(errs.max()), MAX_CORNER_ERR_PX, msg=f"seed={seed}")

    def test_noisy_but_textured_scene(self):
        for seed in (6, 8):
            _doc, photo = make_scene(seed, noise_sigma=9.0, jitter_px=26.0)
            r = pipeline.scan(photo.image)
            self.assertTrue(r.ok, msg=f"seed={seed}: {r.reason}")
            errs = pipeline.corner_errors(r.corners, photo.true_corners)
            self.assertLess(float(errs.max()), MAX_CORNER_ERR_PX, msg=f"seed={seed}")


if __name__ == "__main__":
    unittest.main()
