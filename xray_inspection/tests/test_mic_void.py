"""Test MIC void: phán định OK/NG theo spec cho vết rỗ khí MIC."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from core.mic_void import evaluate_mic_voids, judge_mic, annotate_void, build_solder_mask


def make_image():
    """Vùng hàn tối 100x100, có 1 lỗ rỗ sáng 20x20 (=4% diện tích)."""
    img = np.full((200, 200, 3), 60, np.uint8)
    img[50:150, 50:150] = 80
    img[90:110, 90:110] = 200
    return img


class MicVoidSpecTests(unittest.TestCase):
    def setUp(self):
        self.img = make_image()
        self.dets = [([50, 50, 150, 150], 0.8)]

    def spec(self, **kw):
        cfg = dict(mic_void_threshold_percent=10.0, mic_void_polarity='bright',
                   mic_void_roi=None, mic_void_min_pixels=5)
        cfg.update(kw)
        return cfg

    def test_threshold_changes_result(self):
        r_hi = evaluate_mic_voids(self.img, self.dets, self.spec(mic_void_threshold_percent=10))[0]
        r_lo = evaluate_mic_voids(self.img, self.dets, self.spec(mic_void_threshold_percent=2))[0]
        self.assertAlmostEqual(r_hi.void_percent, 100 * 400 / 108 ** 2, delta=0.1)
        self.assertEqual(r_hi.status, 'OK')
        self.assertEqual(r_lo.status, 'NG')
        self.assertFalse(judge_mic([r_hi], True))
        self.assertTrue(judge_mic([r_lo], True))

    def test_without_void_decision_any_detection_is_ng(self):
        r = evaluate_mic_voids(self.img, self.dets, self.spec())
        self.assertTrue(judge_mic(r, False))
        self.assertFalse(judge_mic([], False))

    def test_roi_used_when_set(self):
        r = evaluate_mic_voids(self.img, [([85, 85, 115, 115], 0.8)], self.spec(mic_void_roi=[80, 80, 40, 40]))[0]
        self.assertAlmostEqual(r.void_percent, 25.0, delta=1)

    def test_detection_outside_roi_is_measured_in_box(self):
        """Rỗ khí MIC nằm ngoài ROI MIC: vẫn đo trong khung YOLO và phán định theo ngưỡng spec."""
        dets = [([85, 85, 115, 115], 0.9)]
        # ROI nằm ở chỗ khác: [10, 10, 30, 30]
        r_ok = evaluate_mic_voids(self.img, dets, self.spec(mic_void_roi=[10, 10, 30, 30], mic_void_threshold_percent=50))
        r_ng = evaluate_mic_voids(self.img, dets, self.spec(mic_void_roi=[10, 10, 30, 30], mic_void_threshold_percent=5))
        self.assertEqual(r_ok[0].status, 'OK')
        self.assertEqual(r_ng[0].status, 'NG')
        self.assertFalse(judge_mic(r_ok, True))
        self.assertTrue(judge_mic(r_ng, True))

    def test_min_pixels_filters_noise(self):
        r = evaluate_mic_voids(self.img, self.dets, self.spec(mic_void_min_pixels=500))[0]
        self.assertEqual(r.void_percent, 0.0)

    def test_annotate_does_not_crash(self):
        frame = self.img.copy()
        res = evaluate_mic_voids(self.img, self.dets, self.spec())[0]
        annotate_void(frame, self.dets[0][0], res, 10.0)
        self.assertFalse(np.array_equal(frame, self.img))

    def test_box_mask(self):
        mask, src = build_solder_mask(self.img.shape, None, [10, 10, 30, 30], padding=0)
        self.assertEqual(src, 'BOX')
        self.assertEqual(int((mask > 0).sum()), 400)


class MicVoidDialogTests(unittest.TestCase):
    def test_dialog_preview_updates_with_spec(self):
        from PyQt5.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from ui.mic_void_dialog import MicVoidDialog
        with patch("config.load_config", return_value={"mic_void_roi": [50, 50, 150, 150]}):
            d = MicVoidDialog()
        d.test_image = make_image()
        d.test_dets = [([50, 50, 150, 150], 0.8)]
        d.use_void.setChecked(True)
        d.threshold.setValue(10); d.update_preview()
        self.assertIn("MIC OK", d.lbl_result.text())
        d.threshold.setValue(1.0); d.update_preview()
        self.assertIn("MIC NG", d.lbl_result.text())
        d.conf.setValue(0.9); d.update_preview()
        self.assertIn("MIC OK", d.lbl_result.text())
        d.close()

    def test_dialog_preview_updates_with_outside_spec(self):
        from PyQt5.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from ui.mic_void_dialog import MicVoidDialog
        with patch("config.load_config", return_value={"mic_void_roi": [0, 0, 10, 10]}):
            d = MicVoidDialog()
        d.test_image = make_image()
        d.test_dets = [([50, 50, 150, 150], 0.8)]
        d.use_void.setChecked(True)
        d.threshold_outside.setValue(10); d.update_preview()
        self.assertIn("MIC OK", d.lbl_result.text())
        d.threshold_outside.setValue(2); d.update_preview()
        self.assertIn("MIC NG", d.lbl_result.text())
        d.close()


if __name__ == "__main__":
    unittest.main()

