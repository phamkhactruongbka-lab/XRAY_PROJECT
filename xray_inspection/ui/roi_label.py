"""Label hiển thị ảnh mẫu Golden và cho phép vẽ ROI bằng chuột."""
from PyQt5.QtCore import Qt, pyqtSignal, QPoint, QRect
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QLabel


# Bảng 10 màu rực rỡ riêng biệt cho tối đa 10 vùng ROI
ROI_PALETTE = [
    (255, 190, 40),   # ROI 1: Vàng hổ phách (Amber)
    (220, 40, 220),   # ROI 2: Tím hồng (Magenta)
    (0, 215, 255),    # ROI 3: Xanh Cyan
    (40, 215, 100),   # ROI 4: Xanh lá (Green)
    (255, 110, 30),   # ROI 5: Cam rực rỡ (Orange)
    (255, 80, 180),   # ROI 6: Hồng tươi (Pink)
    (60, 140, 255),   # ROI 7: Xanh lam (Sky Blue)
    (230, 230, 30),   # ROI 8: Vàng chanh (Lime)
    (150, 80, 255),   # ROI 9: Tím Violet
    (255, 60, 80),    # ROI 10: Đỏ Coral
]

class ROISelectionLabel(QLabel):
    """Vẽ 2 loại khung trên ảnh Golden: ROI kiểm tra (đỏ) và MARK căn chỉnh (xanh dương)."""
    roi_selected = pyqtSignal(tuple)

    ROI_COLOR = (255, 0, 0)
    MARK_COLOR = (0, 200, 255)
    MIC_COLOR = (255, 190, 40)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.is_drawing = False
        self.orig_pixmap = None
        self.current_roi = None      # ROI kiểm tra (toạ độ ảnh gốc)
        self.current_mark = None     # MARK căn chỉnh (toạ độ ảnh gốc)
        self.current_mic = None
        self.current_mic_rois = []   # Danh sách tối đa 10 ROI MIC: list các [x,y,w,h] hoặc dict
        self.active_roi_idx = 0
        self.draw_target = "roi"     # "roi" hoặc "mark": khung đang được vẽ là loại nào

    def set_draw_target(self, target):
        self.draw_target = target if target in ("mark", "mic") else "roi"

    def set_golden_image(self, pixmap):
        """Đổi ảnh hiển thị. Khung ROI/MARK do cửa sổ cấu hình gán lại (current_roi, current_mark)."""
        self.orig_pixmap = None if pixmap is None or pixmap.isNull() else pixmap
        if self.orig_pixmap is None:
            self.clear()
        self.update_display()

    def update_display(self):
        if self.orig_pixmap:
            scaled = self.orig_pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            super().setPixmap(scaled)

    def resizeEvent(self, event):
        self.update_display()
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.orig_pixmap:
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.is_drawing = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            self.end_point = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drawing:
            self.end_point = event.pos()
            self.is_drawing = False
            self.calculate_orig_roi()
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.orig_pixmap:
            return

        painter = QPainter(self)

        def draw_box(rect, color, caption):
            painter.setPen(QPen(QColor(*color), 2, Qt.SolidLine))
            painter.drawRect(rect)
            painter.drawText(rect.topLeft() + QPoint(3, -4), caption)

        if self.current_mark:
            rect = self.map_orig_roi_to_display(self.current_mark)
            if rect:
                draw_box(rect, self.MARK_COLOR, "MARK")
        if self.current_roi:
            rect = self.map_orig_roi_to_display(self.current_roi)
            if rect:
                draw_box(rect, self.ROI_COLOR, "ROI")

        if self.current_mic_rois:
            for idx, item_data in enumerate(self.current_mic_rois, start=1):
                r = item_data['rect'] if isinstance(item_data, dict) else item_data[:4]
                t = item_data.get('type', 'air_bubbles_mic') if isinstance(item_data, dict) else (item_data[4] if len(item_data) > 4 else 'air_bubbles_mic')
                rect = self.map_orig_roi_to_display(r)
                if rect:
                    color = ROI_PALETTE[(idx - 1) % len(ROI_PALETTE)]
                    tag = "VOID" if t == 'air_bubbles_mic' else "TIN BALL"
                    draw_box(rect, color, f"#{idx} [{tag}]")
        elif self.current_mic:
            rect = self.map_orig_roi_to_display(self.current_mic)
            if rect:
                draw_box(rect, self.MIC_COLOR, "MIC VOID")

        if self.is_drawing:
            if self.draw_target == "mark":
                color = self.MARK_COLOR
            elif self.draw_target == "mic":
                idx = getattr(self, 'active_roi_idx', 0)
                color = ROI_PALETTE[idx % len(ROI_PALETTE)]
            else:
                color = self.ROI_COLOR
            painter.setPen(QPen(QColor(*color), 2, Qt.DashLine))
            painter.drawRect(QRect(self.start_point, self.end_point).normalized())

    def _display_geometry(self):
        """Trả về (scale, offset_x, offset_y) của ảnh đang hiển thị trong label."""
        w_orig = self.orig_pixmap.width()
        h_orig = self.orig_pixmap.height()
        w_lbl = self.width()
        h_lbl = self.height()

        scale = min(w_lbl / w_orig, h_lbl / h_orig)
        offset_x = (w_lbl - w_orig * scale) / 2.0
        offset_y = (h_lbl - h_orig * scale) / 2.0
        return scale, offset_x, offset_y

    def calculate_orig_roi(self):
        """Đổi khung vẽ trên màn hình sang toạ độ trên ảnh gốc."""
        if not self.orig_pixmap:
            return

        w_orig = self.orig_pixmap.width()
        h_orig = self.orig_pixmap.height()
        scale, offset_x, offset_y = self._display_geometry()

        rect = QRect(self.start_point, self.end_point).normalized()

        x1 = int(max(0, min(w_orig, (rect.left() - offset_x) / scale)))
        y1 = int(max(0, min(h_orig, (rect.top() - offset_y) / scale)))
        x2 = int(max(0, min(w_orig, (rect.right() - offset_x) / scale)))
        y2 = int(max(0, min(h_orig, (rect.bottom() - offset_y) / scale)))

        w = x2 - x1
        h = y2 - y1

        if w > 5 and h > 5:
            rect_tuple = (x1, y1, w, h)
            if self.draw_target == "mark":
                self.current_mark = rect_tuple
            elif self.draw_target == "mic":
                self.current_mic = rect_tuple
            else:
                self.current_roi = rect_tuple
            self.roi_selected.emit(rect_tuple)

    def map_orig_roi_to_display(self, roi):
        """Đổi ROI toạ độ ảnh gốc sang khung hiển thị trên màn hình."""
        if not self.orig_pixmap:
            return None
        x, y, w, h = roi
        scale, offset_x, offset_y = self._display_geometry()

        return QRect(int(offset_x + x * scale), int(offset_y + y * scale),
                     int(w * scale), int(h * scale))
