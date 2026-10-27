"""Cửa sổ hiển thị kết quả "Thử ảnh": ảnh đã vẽ mark/ROI + kết luận OK/NG + số liệu chi tiết."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout

import cv2

from ui.styles import INDUSTRIAL_DARK_QSS

STATE_COLORS = {"OK": "#2ea44f", "NG": "#f85149", "ERROR": "#ffaa00"}


def bgr_to_pixmap(frame_bgr):
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    q_img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
    return QPixmap.fromImage(q_img.copy())      # copy: tách khỏi bộ nhớ numpy tạm


class ROITestResultDialog(QDialog):
    def __init__(self, result, parent=None):
        """result: dict từ ROIConfigDialog.evaluate_image() (state, message, detail, frame)."""
        super().__init__(parent)
        self.setWindowTitle("Kết Quả Thử Ảnh")
        self.setGeometry(200, 80, 1000, 780)
        self.setStyleSheet(INDUSTRIAL_DARK_QSS)

        layout = QVBoxLayout(self)

        lbl_state = QLabel(result["message"])
        lbl_state.setFont(QFont("Segoe UI", 14, QFont.Bold))
        lbl_state.setStyleSheet(f"color: {STATE_COLORS.get(result['state'], '#ffffff')};")
        layout.addWidget(lbl_state)

        lbl_detail = QLabel(result["detail"])
        lbl_detail.setFont(QFont("Segoe UI", 10))
        lbl_detail.setStyleSheet("color: #9da8b6;")
        layout.addWidget(lbl_detail)

        self._pixmap = bgr_to_pixmap(result["frame"])
        self.lbl_image = QLabel()
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setMinimumSize(600, 450)
        self.lbl_image.setStyleSheet("border: 2px dashed #4f5b72; background-color: #0d0f12;")
        layout.addWidget(self.lbl_image, stretch=1)
        self._rescale()

    def _rescale(self):
        self.lbl_image.setPixmap(self._pixmap.scaled(
            self.lbl_image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()
