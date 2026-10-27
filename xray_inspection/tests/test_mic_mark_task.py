import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import ultralytics  # noqa: F401  # import torch TRƯỚC PyQt5 để tránh xung đột DLL trên Windows
import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication
from core.mic_void import evaluate_mic_voids, validate_mic_task, judge_mic
from ui.roi_dialog import ROIConfigDialog


class MicMarkTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.golden = np.full((240, 320, 3), 220, np.uint8)
        rng = np.random.default_rng(20)
        mark = rng.integers(0, 255, (24, 28), dtype=np.uint8)
        self.golden[35:59, 40:68] = np.repeat(mark[:, :, None], 3, axis=2)
        self.golden[90:170, 130:210] = 60
        self.golden[110:126, 150:166] = 200
        self.path = str(Path(self.tmp.name) / 'mic.png')
        cv2.imwrite(self.path, self.golden)
        self.cfg = dict(mic_void_golden_path=self.path, mic_void_roi=[130, 90, 80, 80],
                        mic_void_mark_roi=[40, 35, 28, 24], mic_void_mark_align_enabled=True,
                        mic_void_threshold_percent=10, mic_void_save_crop=False, mic_void_save_csv=False,
                        golden_path='wrong-ic-golden.png', pos1_roi=[1, 1, 10, 10], mark_roi=[1, 1, 8, 8])
        self.dets = [([150, 110, 166, 126], .8)]

    def tearDown(self):
        self.tmp.cleanup()

    def shifted_dets(self, dx, dy):
        """Khung YOLO dịch cùng ảnh (YOLO luôn bắt rỗ khí ở vị trí thực tế trên ảnh lệch)."""
        return [([x1 + dx, y1 + dy, x2 + dx, y2 + dy], c) for (x1, y1, x2, y2), c in self.dets]

    def shift(self, dx, dy):
        return cv2.warpAffine(self.golden, np.float32([[1, 0, dx], [0, 1, dy]]), (320, 240), borderValue=(220, 220, 220))

    def test_roi_tracks_mark_both_directions(self):
        validate_mic_task(self.cfg)
        for dx, dy in [(30, 20), (-25, -20), (0, 0)]:
            r = evaluate_mic_voids(self.shift(dx, dy), self.shifted_dets(dx, dy), self.cfg)[0]
            self.assertEqual(r.aligned_roi, (130+dx, 90+dy, 80, 80))
            self.assertEqual(r.alignment['offset'], (dx, dy))
            self.assertEqual(r.void_percent, 4)
            self.assertEqual(r.status, 'OK')

    def test_missing_repeated_and_outside_mark_never_use_old_roi(self):
        missing = self.golden.copy(); missing[35:59, 40:68] = 220
        repeated = self.golden.copy(); repeated[180:204, 20:48] = self.golden[35:59, 40:68]
        for image in [missing, repeated, self.shift(120, 0)]:
            r = evaluate_mic_voids(image, self.dets, self.cfg)[0]
            self.assertEqual(r.status, 'REVIEW')
            self.assertIsNone(r.void_percent)
            self.assertIsNone(r.aligned_roi)
            self.assertTrue(judge_mic([r], True))

    def test_missing_mic_golden_does_not_fall_back_to_ic(self):
        cfg = dict(self.cfg, mic_void_golden_path='', golden_path=self.path)
        self.assertEqual(evaluate_mic_voids(self.golden, self.dets, cfg)[0].status, 'REVIEW')

    def test_wrong_size_rejected(self):
        image = cv2.resize(self.golden, (640, 480))
        self.assertEqual(evaluate_mic_voids(image, self.dets, self.cfg)[0].status, 'REVIEW')

    def test_ui_tasks_independent_and_preview_aligned(self):
        with patch('config.load_config', return_value=self.cfg.copy()):
            d = ROIConfigDialog()
        m = d.mic_settings
        self.assertEqual(d.current_image_path, 'wrong-ic-golden.png')
        self.assertEqual(m.golden_path, self.path)
        self.assertIsNone(m.golden_canvas.current_roi)
        self.assertIsNone(d.img_label.current_mic)
        m.test_image = self.shift(30, 20); m.test_dets = self.shifted_dets(30, 20)
        m.update_preview()
        self.assertIn('dX=+30, dY=+20', m.lbl_result.text())
        m.set_golden_path(self.path)
        self.assertIsNone(m.mark_roi); self.assertIsNone(m._parse_roi())
        self.assertEqual(d.current_roi, (1, 1, 10, 10))
        d.close()

    def test_mic_saves_without_valid_ic_golden(self):
        with patch('config.load_config', return_value=self.cfg.copy()):
            d = ROIConfigDialog()
        d.tabs.setCurrentIndex(1)
        with patch('config.load_config', return_value=self.cfg.copy()), patch('config.save_config', return_value=True) as save, patch('ui.roi_dialog.QMessageBox.information'):
            d.save_and_close()
        saved = save.call_args.args[0]
        self.assertEqual(saved['golden_path'], 'wrong-ic-golden.png')
        self.assertEqual(saved['mic_void_golden_path'], self.path)
        self.assertTrue(saved['mic_void_mark_align_enabled'])
        d.close()

    def test_worker_uses_mic_mark_on_position_two(self):
        from core.worker import XRayWorkerThread
        shifted = self.shift(30, 20)
        path = str(Path(self.tmp.name) / 'test.png'); cv2.imwrite(path, shifted)
        box = SimpleNamespace(cls=[0], conf=[.8], xyxy=np.array([[180, 130, 196, 146]]))
        result = SimpleNamespace(boxes=[box], names={0: 'air_bubbles_mic'}, orig_img=shifted)
        model = SimpleNamespace(predict=lambda **kw: [result])
        with patch('config.load_config', return_value=self.cfg.copy()):
            worker = XRayWorkerThread('', self.tmp.name, self.tmp.name)
            worker.current_batch_dir = self.tmp.name
            status, info, _ = worker._process_auto(model, path, 'test.png', 2)
        self.assertEqual(status, 'OK')
        self.assertIn('dX=30, dY=20', info)
        self.assertIn('4.0%', info)


if __name__ == '__main__':
    unittest.main()
