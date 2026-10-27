"""Test kiểm tra lỗi tin_ball_mic_hole:
- Nhận biết trực tiếp bằng YOLO trong phạm vi ROI MIC (hoặc ROI lỗ MIC).
- Giữ nguyên quy tắc phán định NG tuyệt đối khi nằm trong ROI MIC.
- Lọc bỏ / bỏ qua khi nằm ngoài ROI MIC (tránh bắt nhầm via, bóng thiếc ngoại vi).
- Phân biệt ROI air_bubbles_mic và ROI tin_ball_mic_hole theo loại và màu sắc.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

from core.mic_void import is_box_in_rois, get_aligned_mic_rois, get_mic_rois, get_mic_roi_items, ROI_TYPE_VOID, ROI_TYPE_TIN_BALL
from core.worker import XRayWorkerThread


class MockResult:
    def __init__(self, boxes, names, img):
        self.boxes = boxes
        self.names = names
        self.orig_img = img

    def __getitem__(self, idx):
        return self

    def plot(self):
        return self.orig_img.copy()


class TinBallRoiTests(unittest.TestCase):
    def test_is_box_in_rois_logic(self):
        # ROI: [100, 100, 80, 80] -> x: 100..180, y: 100..180
        rois = [[100, 100, 80, 80]]

        # 1. Box nằm hoàn toàn bên trong ROI -> True
        box_inside = [120, 120, 140, 140]
        self.assertTrue(is_box_in_rois(box_inside, rois))

        # 2. Box có tâm nằm trong ROI -> True
        box_center_inside = [95, 95, 115, 115]  # tâm = (105, 105)
        self.assertTrue(is_box_in_rois(box_center_inside, rois))

        # 3. Box nằm hoàn toàn ngoài ROI -> False
        box_outside = [10, 10, 30, 30]
        self.assertFalse(is_box_in_rois(box_outside, rois))

        # 4. Khi chưa có ROI nào -> True (fallback không chặn)
        self.assertTrue(is_box_in_rois(box_outside, []))

        # 5. Đa ROI: box nằm trong ROI thứ 2 -> True
        multi_rois = [[100, 100, 80, 80], [300, 300, 50, 50]]
        box_in_roi2 = [310, 310, 330, 330]
        self.assertTrue(is_box_in_rois(box_in_roi2, multi_rois))

    def test_tin_ball_inside_roi_is_judged_ng(self):
        """Bi thiếc nằm trong ROI MIC: Giữ nguyên quy tắc phán định NG ngay lập tức."""
        cfg = {
            "mic_void_rois": [[100, 100, 100, 100]],
            "mic_void_roi": [100, 100, 100, 100],
            "mic_void_mark_align_enabled": False,
        }
        # Box bi thiếc tại (130, 130, 150, 150) -> nằm trong ROI
        box = SimpleNamespace(cls=[4], conf=[0.62], xyxy=np.array([[130, 130, 150, 150]]))
        result = MockResult(boxes=[box], names={4: "tin_ball_mic_hole"}, img=np.full((300, 300, 3), 100, np.uint8))
        model = SimpleNamespace(predict=lambda **kw: [result])

        worker = XRayWorkerThread("", "", "")
        worker.current_batch_dir = "."
        with patch("core.worker.read_image", return_value=result.orig_img), \
             patch("config.load_config", return_value=cfg), \
             patch("cv2.imwrite"):
            status, info, _ = worker._process_auto(model, "dummy.png", "dummy.png", 2)

        self.assertEqual(status, "NG")
        self.assertIn("tin_ball_mic_hole", info)

    def test_tin_ball_outside_roi_is_filtered(self):
        """Bi thiếc nằm ngoài ROI MIC: Lọc bỏ, không gây NG ảo."""
        cfg = {
            "mic_void_rois": [[100, 100, 100, 100]],
            "mic_void_roi": [100, 100, 100, 100],
            "mic_void_mark_align_enabled": False,
        }
        # Box bi thiếc tại (10, 10, 30, 30) -> nằm ngoài ROI
        box = SimpleNamespace(cls=[4], conf=[0.62], xyxy=np.array([[10, 10, 30, 30]]))
        result = MockResult(boxes=[box], names={4: "tin_ball_mic_hole"}, img=np.full((300, 300, 3), 100, np.uint8))
        model = SimpleNamespace(predict=lambda **kw: [result])

        worker = XRayWorkerThread("", "", "")
        worker.current_batch_dir = "."
        with patch("core.worker.read_image", return_value=result.orig_img), \
             patch("config.load_config", return_value=cfg), \
             patch("cv2.imwrite"):
            status, info, _ = worker._process_auto(model, "dummy.png", "dummy.png", 2)

        self.assertEqual(status, "OK")
        self.assertIn("SẠCH", info)

    def test_differentiated_roi_types(self):
        """Phân biệt rõ ràng ROI tin_ball_mic_hole và ROI air_bubbles_mic."""
        cfg = {
            "mic_void_rois": [
                {"rect": [50, 50, 60, 60], "type": ROI_TYPE_VOID},
                {"rect": [200, 200, 40, 40], "type": ROI_TYPE_TIN_BALL}
            ]
        }
        void_rois = get_mic_rois(cfg, target_type=ROI_TYPE_VOID)
        tin_ball_rois = get_mic_rois(cfg, target_type=ROI_TYPE_TIN_BALL)

        self.assertEqual(len(void_rois), 1)
        self.assertEqual(void_rois[0], [50, 50, 60, 60])
        self.assertEqual(len(tin_ball_rois), 1)
        self.assertEqual(tin_ball_rois[0], [200, 200, 40, 40])


if __name__ == "__main__":
    unittest.main()
