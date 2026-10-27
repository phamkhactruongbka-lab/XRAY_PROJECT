import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import ultralytics  # noqa: F401
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import cv2
from PyQt5.QtWidgets import QApplication
from ui.roi_dialog import ROIConfigDialog


class RoiMicIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.golden = str(Path(self.tmp.name) / 'golden.png')
        self.image = np.full((200, 200, 3), 60, np.uint8)
        self.image[50:150, 50:150] = 80
        self.image[90:110, 90:110] = 200
        cv2.imwrite(self.golden, self.image)
        self.cfg = dict(golden_path=self.golden, pos1_roi=[20, 20, 40, 40],
                        mic_void_golden_path=self.golden, mic_void_threshold_percent=49, mic_void_roi=[50, 50, 100, 100])
        with patch('config.load_config', return_value=self.cfg.copy()):
            self.dialog = ROIConfigDialog()

    def tearDown(self):
        self.dialog.close()
        self.tmp.cleanup()

    def test_embedded_controls_and_drawing(self):
        d = self.dialog
        self.assertEqual(d.tabs.count(), 2)
        self.assertEqual(d.mic_settings.threshold.value(), 49)
        old = d.current_roi
        self.assertEqual(d.combo_draw.count(), 2)
        d.mic_settings.draw_mode.setCurrentIndex(0)
        self.assertEqual(d.mic_settings.golden_canvas.draw_target, 'mic')
        d.mic_settings.on_golden_drawn((40, 50, 100, 100))
        self.assertEqual(d.current_roi, old)
        self.assertEqual(d.mic_settings._parse_roi(), [40, 50, 100, 100])
        self.assertEqual(d.mic_settings.golden_canvas.current_mic, [40, 50, 100, 100])
        self.assertIsNone(d.img_label.current_mic)
        d.mic_settings.roi.clear()
        self.assertIsNone(d.mic_settings.golden_canvas.current_mic)

    def test_single_save_contains_both_configs(self):
        d = self.dialog
        d.tabs.setCurrentIndex(1)
        d.current_roi = (0, 0, 15, 15)  # unsaved IC change must not leak into MIC save
        d.mic_settings.threshold.setValue(80)
        d.mic_settings.conf.setValue(.15)
        with patch('config.load_config', return_value=self.cfg.copy()), patch('config.save_config', return_value=True) as save, patch('ui.roi_dialog.QMessageBox.information'):
            d.save_and_close()
        save.assert_called_once()
        cfg = save.call_args.args[0]
        self.assertEqual(cfg['mic_void_threshold_percent'], 80)
        self.assertEqual(cfg['mic_void_confidence'], .15)
        self.assertEqual(cfg['mic_void_roi'], [50, 50, 100, 100])
        self.assertEqual(cfg['pos1_roi'], [20, 20, 40, 40])
        self.assertFalse(cfg['mic_void_validated'])
        with patch('config.load_config', return_value=cfg):
            reopened = ROIConfigDialog()
        self.assertEqual(reopened.mic_settings.threshold.value(), 80)
        reopened.close()

    def test_cancel_never_persists(self):
        with patch('config.save_config') as save:
            self.dialog.mic_settings.threshold.setValue(90)
            self.dialog.reject()
        save.assert_not_called()

    def test_invalid_mic_roi_blocks_combined_save(self):
        self.dialog.tabs.setCurrentIndex(1)
        for text in ['a,2,3,4', '190,190,50,50', '10,10,2,2']:
            self.dialog.mic_settings.roi.setText(text)
            with patch('config.save_config') as save, patch('ui.roi_dialog.QMessageBox.warning') as warning:
                self.dialog.save_and_close()
            save.assert_not_called()
            warning.assert_called_once()

    def test_preview_uses_unsaved_spec(self):
        m = self.dialog.mic_settings
        m.test_image = self.image
        m.test_dets = [([50, 50, 150, 150], .8)]
        m.use_void.setChecked(True)
        m.threshold.setValue(10); m.update_preview()
        self.assertIn('MIC OK', m.lbl_result.text())
        m.threshold.setValue(2); m.update_preview()
        self.assertIn('MIC NG', m.lbl_result.text())


if __name__ == '__main__':
    unittest.main()
