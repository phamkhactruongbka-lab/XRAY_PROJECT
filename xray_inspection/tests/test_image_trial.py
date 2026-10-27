"""Test nút 'Thử ảnh' trong cửa sổ cấu hình ROI (không mở popup, chỉ test logic evaluate_image)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ultralytics  # noqa: F401  # import torch TRƯỚC PyQt5 để tránh xung đột DLL trên Windows

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication
from ui.roi_dialog import ROIConfigDialog


class ImageTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.golden = np.full((320, 420), 220, np.uint8)
        self.mark = (120, 110, 28, 24)
        self.roi = (175, 150, 40, 30)
        rng = np.random.default_rng(10)
        self.golden[110:134, 120:148] = rng.integers(0, 255, (24, 28), dtype=np.uint8)
        self.golden[150:180, 175:215] = 50
        self.tmp = tempfile.TemporaryDirectory()
        self.golden_path = str(Path(self.tmp.name) / "golden.png")
        cv2.imwrite(self.golden_path, self.golden)

        with patch("config.load_config", return_value={}):
            self.dialog = ROIConfigDialog()
        self.dialog.current_image_path = self.golden_path
        self.dialog.current_roi = self.roi
        self.dialog.current_mark = self.mark
        self.dialog.spin_dark.setValue(115)
        self.dialog.spin_solder.setValue(0.05)

    def tearDown(self):
        self.dialog.close()
        self.tmp.cleanup()

    def shifted(self, dx, dy):
        return cv2.warpAffine(self.golden, np.float32([[1, 0, dx], [0, 1, dy]]),
                              (420, 320), borderValue=220)

    def save(self, img, name="test.png"):
        path = str(Path(self.tmp.name) / name)
        cv2.imwrite(path, img)
        return path

    def test_ok_with_mark(self):
        self.dialog.chk_align.setChecked(True)
        r = self.dialog.evaluate_image(self.save(self.shifted(60, -40)))
        self.assertEqual(r["state"], "OK")
        self.assertIn("dX=+60, dY=-40", r["detail"])
        self.assertEqual(r["frame"].shape, (320, 420, 3))

    def test_missing_ic_with_mark(self):
        self.dialog.chk_align.setChecked(True)
        img = self.shifted(60, -40)
        img[110:140, 235:275] = 220            # ROI (175,150)+(60,-40) -> (235,110)
        r = self.dialog.evaluate_image(self.save(img))
        self.assertEqual(r["state"], "NG")

    def test_alignment_error_reported(self):
        self.dialog.chk_align.setChecked(True)
        r = self.dialog.evaluate_image(self.save(np.full((320, 420), 220, np.uint8)))
        self.assertEqual(r["state"], "ERROR")
        self.assertIn("CĂN CHỈNH", r["message"])

    def test_mark_enabled_but_not_drawn_is_error(self):
        self.dialog.chk_align.setChecked(True)
        self.dialog.current_mark = None
        r = self.dialog.evaluate_image(self.save(self.golden))
        self.assertEqual(r["state"], "ERROR")

    def test_without_mark_uses_ecc(self):
        self.dialog.chk_align.setChecked(False)
        r = self.dialog.evaluate_image(self.save(self.golden))
        self.assertEqual(r["state"], "OK")
        self.assertIn("ECC", r["detail"])

    def test_unreadable_image_returns_none(self):
        self.assertIsNone(self.dialog.evaluate_image(str(Path(self.tmp.name) / "khong_ton_tai.png")))

    def test_unicode_path(self):
        self.dialog.chk_align.setChecked(True)
        path = str(Path(self.tmp.name) / "ảnh thử.png")
        cv2.imencode(".png", self.golden)[1].tofile(path)
        self.assertEqual(self.dialog.evaluate_image(path)["state"], "OK")

    def test_uses_unsaved_dialog_values(self):
        """Thông số đang chỉnh (chưa lưu) phải được dùng: đặt tỷ lệ tối thiểu 0.99 -> NG."""
        self.dialog.chk_align.setChecked(True)
        self.dialog.spin_solder.setValue(0.99)
        self.dialog.spin_dark.setValue(30)       # ROI xám 50 > 30 => không còn "tối"
        r = self.dialog.evaluate_image(self.save(self.golden))
        self.assertEqual(r["state"], "NG")


if __name__ == "__main__":
    unittest.main()
