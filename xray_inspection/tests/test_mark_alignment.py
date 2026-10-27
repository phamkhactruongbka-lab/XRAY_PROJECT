import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

# Cho phép chạy từ bất kỳ đâu: thêm thư mục gốc project vào sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import ultralytics  # noqa: F401  # import torch TRƯỚC PyQt5 để tránh xung đột DLL trên Windows (giống main.py)
import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication
from core.ic_checker import RobustSolderICChecker
from core.mark_alignment import MarkAligner, AlignmentError
from core.worker import XRayWorkerThread
from ui.roi_dialog import ROIConfigDialog


class MarkAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.golden = np.full((320, 420), 220, np.uint8)
        self.mark = (120, 110, 28, 24)
        self.roi = (175, 150, 40, 30)
        rng = np.random.default_rng(10)
        self.golden[110:134, 120:148] = rng.integers(0, 255, (24, 28), dtype=np.uint8)
        self.golden[150:180, 175:215] = 50
        self.aligner = MarkAligner(self.golden, self.mark, self.roi)

    def shift(self, dx, dy):
        return cv2.warpAffine(self.golden, np.float32([[1, 0, dx], [0, 1, dy]]),
                              (420, 320), borderValue=220)

    def test_large_translations_both_directions(self):
        for dx, dy in [(100, 75), (-95, -80), (0, 0)]:
            with self.subTest(offset=(dx, dy)):
                result = self.aligner.locate(self.shift(dx, dy))
                self.assertEqual(result["offset"], (dx, dy))
                self.assertEqual(result["roi"], (175+dx, 150+dy, 40, 30))
                self.assertEqual(result["master_center"], (134.0, 122.0))
                self.assertEqual(result["mark_center"], (134.0+dx, 122.0+dy))

    def test_missing_mark_rejected(self):
        with self.assertRaises(AlignmentError):
            self.aligner.locate(np.full_like(self.golden, 220))

    def test_repeated_mark_rejected(self):
        img = self.golden.copy()
        img[40:64, 30:58] = self.golden[110:134, 120:148]
        with self.assertRaisesRegex(AlignmentError, "trùng"):
            self.aligner.locate(img)

    def test_search_limit_and_unique_local_match(self):
        aligner = MarkAligner(self.golden, self.mark, self.roi, search_margin=30)
        self.assertEqual(aligner.locate(self.shift(15, -10))["offset"], (15, -10))
        with self.assertRaises(AlignmentError):
            aligner.locate(self.shift(100, 75))

    def test_roi_outside_image_rejected(self):
        with self.assertRaisesRegex(AlignmentError, "ngoài ảnh"):
            self.aligner.locate(self.shift(240, 0))

    def test_invalid_golden_mark_rejected(self):
        for mark in [None, (410, 10, 28, 24), (0, 0, 28, 24)]:
            with self.subTest(mark=mark), self.assertRaises(AlignmentError):
                MarkAligner(self.golden, mark, self.roi)

    def test_missing_ic_does_not_move_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "ảnh chuẩn.png")
            cv2.imencode('.png', self.golden)[1].tofile(path)
            checker = RobustSolderICChecker(path, self.roi, 115, .05, True, self.mark)
            img = self.shift(100, 75)
            missing, _ = checker.check_missing_ic(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
            self.assertFalse(missing)
            self.assertIsNone(checker.last_error)
            img[225:255, 275:315] = 220
            missing, boxes = checker.check_missing_ic(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
            self.assertTrue(missing)
            self.assertEqual(boxes, [(275, 225, 315, 255)])
            self.assertEqual(checker.last_alignment['offset'], (100, 75))
            checker.check_missing_ic(np.full((320, 420, 3), 220, np.uint8))
            self.assertIsNotNone(checker.last_error)
            self.assertIsNone(checker.last_roi)

    def test_enabled_without_mark_is_error(self):
        checker = RobustSolderICChecker('', self.roi, mark_align_enabled=True)
        checker.check_missing_ic(cv2.cvtColor(self.golden, cv2.COLOR_GRAY2BGR))
        self.assertIsNotNone(checker.last_error)

    def test_legacy_yolo_only_still_works(self):
        checker = RobustSolderICChecker('', self.roi)
        self.assertEqual(checker.check_missing_ic(cv2.cvtColor(self.golden, cv2.COLOR_GRAY2BGR)), (False, []))
        self.assertIsNone(checker.last_error)

    def test_configuration_draw_modes(self):
        app = QApplication.instance() or QApplication([])
        dialog = ROIConfigDialog()
        original = dialog.current_roi
        dialog.combo_draw.setCurrentIndex(1)
        dialog.on_roi_drawn(self.mark)
        self.assertEqual(dialog.current_mark, self.mark)
        self.assertEqual(dialog.current_roi, original)
        self.assertTrue(dialog.chk_align.isChecked())
        dialog.combo_draw.setCurrentIndex(0)
        dialog.on_roi_drawn(self.roi)
        self.assertEqual(dialog.current_roi, self.roi)
        self.assertEqual(dialog.current_mark, self.mark)
        dialog.close()

    def test_worker_marks_alignment_failure_ng_even_when_yolo_clean(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            watch = root / 'watch'
            watch.mkdir()
            golden_path = root / 'golden.png'
            cv2.imwrite(str(golden_path), self.golden)
            blank = np.full((320, 420, 3), 220, np.uint8)
            cv2.imwrite(str(watch / 'image.png'), blank)
            cfg = dict(golden_path=str(golden_path), pos1_roi=list(self.roi),
                       mark_align_enabled=True, mark_roi=list(self.mark))
            result = SimpleNamespace(boxes=[], plot=lambda: blank.copy())
            model = SimpleNamespace(predict=lambda **kwargs: [result])
            received = []
            with patch('config.load_config', return_value=cfg), \
                 patch('core.worker.YOLO', return_value=model):
                worker = XRayWorkerThread('fake.pt', str(watch), str(root / 'storage'))
                def on_image(*args):
                    received.append(args)
                    worker.is_running = False
                worker.image_processed.connect(on_image)
                worker.run()
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0][2], 'NG')
            self.assertIn('Lỗi căn chỉnh/ROI', received[0][3])
            self.assertTrue(worker.batch_has_ng)

    def test_mark_settings_saved_and_loaded_by_worker(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'golden.png')
            cv2.imwrite(path, self.golden)
            dialog = ROIConfigDialog()
            dialog.current_image_path = path
            dialog.current_roi = self.roi
            dialog.current_mark = self.mark
            dialog.chk_align.setChecked(True)
            dialog.spin_mark_margin.setValue(100)
            with patch('config.save_config', return_value=True) as save, \
                 patch('ui.roi_dialog.QMessageBox.information'):
                dialog.save_and_close()
            config = save.call_args[0][0]
            self.assertEqual(config['mark_roi'], list(self.mark))
            with patch('config.load_config', return_value=config):
                worker = XRayWorkerThread('', directory)
            self.assertIsNone(worker.ic_checker_pos1.config_error)
            self.assertEqual(worker.ic_checker_pos1.aligner.search_margin, 100)
            self.assertTrue(worker.ic_checker_pos1.mark_align_enabled)


if __name__ == '__main__':
    unittest.main()
