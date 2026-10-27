"""Khung xem ảnh X-Ray có phóng to / thu nhỏ / kéo di chuyển."""
from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

class ZoomImageView(QGraphicsView):
    """Lăn chuột: phóng to/thu nhỏ tại vị trí con trỏ | Kéo chuột: di chuyển | Nháy đúp: vừa khung."""

    zoom_changed = pyqtSignal(float)         # mức zoom hiện tại, đơn vị % so với kích thước thật (100% = 1:1)

    MIN_SCALE = 0.02
    MAX_SCALE = 40.0
    STEP = 1.25                              # mỗi nấc lăn chuột / mỗi lần bấm nút
    KEEP_ZOOM_ON_NEW_IMAGE = True            # chuyển sang ảnh khác cùng kích thước thì giữ nguyên zoom + vị trí đang xem
    PIXEL_VIEW_SCALE = 3.0                   # từ mức zoom này trở lên hiện từng điểm ảnh (không làm mờ)

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._fit_mode = True                # True: ảnh luôn vừa khung (kể cả khi đổi kích thước cửa sổ)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)

        self.setStyleSheet("border: 2px dashed #2d3342; background-color: #0b0c0e;")
        self.setDragMode(QGraphicsView.ScrollHandDrag)           # kéo chuột để di chuyển ảnh
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)                          # không cướp phím mũi tên của bảng PCB
        self.setToolTip("Lăn chuột: phóng to / thu nhỏ\nKéo chuột: di chuyển ảnh\nNháy đúp: vừa khung")

    # ------------------------------------------------------------------
    def has_image(self):
        return not self._item.pixmap().isNull()

    def set_frame(self, frame_rgb):
        """Hiển thị ảnh numpy RGB (h, w, 3)."""
        h, w, ch = frame_rgb.shape
        pixmap = QPixmap.fromImage(QImage(frame_rgb.data, w, h, ch * w, QImage.Format_RGB888))
        old = self._item.pixmap()
        same_size = (not old.isNull()) and old.size() == pixmap.size()

        self._item.setPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        if self._fit_mode or not same_size or not self.KEEP_ZOOM_ON_NEW_IMAGE:
            self.fit_to_view()
        else:
            self._notify_zoom()

    def clear_image(self, placeholder=None):
        self._item.setPixmap(QPixmap())
        if placeholder is not None:
            self._placeholder = placeholder
        self._fit_mode = True
        self.resetTransform()
        self._notify_zoom()
        self.viewport().update()

    # ------------------------------------------------------------------
    def fit_to_view(self):
        """Vừa khung: toàn bộ ảnh nằm trong khung."""
        self._fit_mode = True
        if not self.has_image():
            return
        self.resetTransform()
        self.fitInView(self._item, Qt.KeepAspectRatio)
        self._notify_zoom()

    def actual_size(self):
        """1:1 - mỗi điểm ảnh bằng một điểm trên màn hình."""
        if not self.has_image():
            return
        self._fit_mode = False
        self.resetTransform()
        self.centerOn(self._item)
        self._notify_zoom()

    def zoom_in(self):
        self.zoom_by(self.STEP)

    def zoom_out(self):
        self.zoom_by(1.0 / self.STEP)

    def zoom_by(self, factor, at_cursor=False):
        if not self.has_image():
            return
        current = self.transform().m11()
        target = max(self.MIN_SCALE, min(self.MAX_SCALE, current * factor))
        factor = target / current
        if abs(factor - 1.0) < 1e-9:
            return
        self._fit_mode = False
        self.setTransformationAnchor(
            QGraphicsView.AnchorUnderMouse if at_cursor else QGraphicsView.AnchorViewCenter)
        self.scale(factor, factor)
        self._notify_zoom()

    def _notify_zoom(self):
        scale = self.transform().m11()
        self._item.setTransformationMode(
            Qt.FastTransformation if scale >= self.PIXEL_VIEW_SCALE else Qt.SmoothTransformation)
        self.zoom_changed.emit(scale * 100.0)

    # ------------------------------------------------------------------
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta and self.has_image():
            self.zoom_by(self.STEP if delta > 0 else 1.0 / self.STEP, at_cursor=True)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.fit_to_view()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_mode:
            self.fit_to_view()               # đổi kích thước cửa sổ: ảnh vẫn vừa khung

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.has_image() and self._placeholder:
            painter = QPainter(self.viewport())
            painter.setPen(QColor("#6e7681"))
            painter.drawText(self.viewport().rect(), Qt.AlignCenter, self._placeholder)
            painter.end()