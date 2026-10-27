"""Cửa sổ popup cấu hình ROI, MARK căn chỉnh và thông số bắt lỗi mất IC."""
import os

import cv2
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QTabWidget, QWidget,
)

import config
from core.ic_checker import RobustSolderICChecker, annotate_ic_check
from core.mark_alignment import AlignmentError, MarkAligner, read_image
from ui.roi_label import ROISelectionLabel
from ui.roi_test_dialog import ROITestResultDialog
from ui.styles import INDUSTRIAL_DARK_QSS
from ui.mic_void_dialog import MicVoidDialog
from core.mic_void import validate_mic_task

DRAW_ROI = 0     # chỉ số trong combo_draw
DRAW_MARK = 1


class ROIConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cấu Hình Vùng ROI, MARK & Thông Số Bắt Lỗi")
        self.resize(1100, 700)
        self.setStyleSheet(INDUSTRIAL_DARK_QSS)

        self.config_data = config.load_config()
        self.model_path = getattr(parent, 'model_path', '') or ''
        self.current_image_path = self.config_data.get("golden_path", "")
        self.current_roi = tuple(self.config_data.get("pos1_roi", [200, 200, 150, 150]))
        mark = self.config_data.get("mark_roi")
        self.current_mark = tuple(mark) if mark else None

        self.initUI()

    def initUI(self):
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab { background:#26344a; color:white; padding:9px 14px; } "
                                "QTabBar::tab:selected { background:#1a73e8; color:white; }")
        outer.addWidget(self.tabs)
        roi_page = QWidget()
        layout = QVBoxLayout(roi_page)
        self.tabs.addTab(roi_page, "Task IC / ROI & MARK")
        self.mic_settings = MicVoidDialog(self, initial_config=self.config_data, embedded=True)
        self.tabs.addTab(self.mic_settings, "Task MIC Void")

        # --- Chọn ảnh Golden ---
        top_layout = QHBoxLayout()
        self.btn_select_golden = QPushButton("📁 Chọn Ảnh Mẫu Golden (.jpg/.png)")
        self.btn_select_golden.clicked.connect(self.select_golden_image)
        self.lbl_path = QLabel(self.current_image_path if self.current_image_path else "Chưa chọn ảnh")
        self.lbl_path.setStyleSheet("color: #4da6ff; font-weight: bold;")

        top_layout.addWidget(self.btn_select_golden)
        top_layout.addWidget(self.lbl_path, stretch=1)
        layout.addLayout(top_layout)

        # --- Ảnh Golden + vẽ khung ---
        self.img_label = ROISelectionLabel()
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setStyleSheet("border: 2px dashed #4f5b72; background-color: #0d0f12;")
        self.img_label.setMinimumSize(600, 300)
        self.img_label.roi_selected.connect(self.on_roi_drawn)
        layout.addWidget(self.img_label, stretch=1)

        # --- Căn chỉnh theo MARK ---
        align_frame = QFrame()
        align_frame.setObjectName("cardFrame")
        align_layout = QHBoxLayout(align_frame)

        lbl_draw = QLabel("Đang vẽ:")
        lbl_draw.setFont(QFont("Arial", 10, QFont.Bold))
        self.combo_draw = QComboBox()
        self.combo_draw.addItems(["🟥 ROI kiểm tra IC", "🟦 MARK căn chỉnh"])
        self.combo_draw.currentIndexChanged.connect(self.on_draw_mode_changed)

        self.chk_align = QCheckBox("Bật căn chỉnh theo MARK")
        self.chk_align.setFont(QFont("Arial", 10, QFont.Bold))
        self.chk_align.setChecked(bool(self.config_data.get("mark_align_enabled", False)))

        lbl_margin = QLabel("Phạm vi tìm mark:")
        lbl_margin.setFont(QFont("Arial", 10, QFont.Bold))
        self.spin_mark_margin = QSpinBox()
        self.spin_mark_margin.setRange(0, 5000)
        self.spin_mark_margin.setSuffix(" px")
        self.spin_mark_margin.setSpecialValueText("Toàn ảnh")
        self.spin_mark_margin.setStyleSheet("background-color: #121418; padding: 4px;")
        self.spin_mark_margin.setValue(int(self.config_data.get("mark_search_margin", 0)))

        align_layout.addWidget(lbl_draw)
        align_layout.addWidget(self.combo_draw)
        align_layout.addSpacing(20)
        align_layout.addWidget(self.chk_align)
        align_layout.addSpacing(20)
        align_layout.addWidget(lbl_margin)
        align_layout.addWidget(self.spin_mark_margin)
        layout.addWidget(align_frame)

        # --- Thông số bắt lỗi ---
        param_frame = QFrame()
        param_frame.setObjectName("cardFrame")
        param_layout = QHBoxLayout(param_frame)

        lbl_dark = QLabel("1. Ngưỡng độ xám thiếc:")
        lbl_dark.setFont(QFont("Arial", 10, QFont.Bold))
        self.spin_dark = QSpinBox()
        self.spin_dark.setRange(0, 255)
        self.spin_dark.setStyleSheet("background-color: #121418; padding: 4px;")
        self.spin_dark.setValue(self.config_data.get("dark_threshold", 115))

        lbl_solder = QLabel("2. Tỷ lệ thiếc tối thiểu:")
        lbl_solder.setFont(QFont("Arial", 10, QFont.Bold))
        self.spin_solder = QDoubleSpinBox()
        self.spin_solder.setRange(0.01, 1.00)
        self.spin_solder.setSingleStep(0.01)
        self.spin_solder.setDecimals(2)
        self.spin_solder.setStyleSheet("background-color: #121418; padding: 4px;")
        self.spin_solder.setValue(self.config_data.get("min_solder_ratio", 0.05))

        param_layout.addWidget(lbl_dark)
        param_layout.addWidget(self.spin_dark)
        param_layout.addSpacing(20)
        param_layout.addWidget(lbl_solder)
        param_layout.addWidget(self.spin_solder)
        layout.addWidget(param_frame)

        # --- Thông tin toạ độ + nút lưu ---
        bot_layout = QHBoxLayout()
        info_layout = QVBoxLayout()
        self.lbl_roi_info = QLabel(self._roi_text(self.current_roi))
        self.lbl_roi_info.setFont(QFont("Arial", 10, QFont.Bold))
        self.lbl_mark_info = QLabel(self._mark_text(self.current_mark))
        self.lbl_mark_info.setFont(QFont("Arial", 10, QFont.Bold))
        info_layout.addWidget(self.lbl_roi_info)
        info_layout.addWidget(self.lbl_mark_info)

        self.btn_save = QPushButton("💾 LƯU CẤU HÌNH")
        self.btn_save.setStyleSheet("background-color: #2ea44f; color: white; font-weight: bold; padding: 10px; font-size: 13px;")
        self.btn_save.clicked.connect(self.save_and_close)

        self.btn_test = QPushButton("🧪 THỬ ẢNH")
        self.btn_test.setToolTip("Chọn một ảnh bất kỳ và chạy thử với các thông số đang chỉnh (chưa cần lưu)")
        self.btn_test.setStyleSheet("background-color: #1a4971; color: white; font-weight: bold; padding: 10px; font-size: 13px;")
        self.btn_test.clicked.connect(self.on_test_image_clicked)

        bot_layout.addLayout(info_layout)
        bot_layout.addStretch()
        bot_layout.addWidget(self.btn_test)
        layout.addLayout(bot_layout)
        actions = QHBoxLayout()
        hint = QLabel("Hai task độc lập: mỗi task có Golden / ROI / MARK riêng. Nút Lưu chỉ lưu task đang chọn.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#172b43; background:#e6edf5; padding:6px;")
        actions.addWidget(hint, 1)
        cancel = QPushButton("Hủy")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        actions.addWidget(self.btn_save)
        outer.addLayout(actions)

        if self.current_image_path and os.path.exists(self.current_image_path):
            self.img_label.set_golden_image(QPixmap(self.current_image_path))
        self._refresh_overlays()
        self.tabs.currentChanged.connect(lambda i: self.btn_save.setText("💾 LƯU TASK MIC" if i == 1 else "💾 LƯU TASK IC"))
        self.btn_save.setText("💾 LƯU TASK IC")

    # ------------------------------------------------------------------
    @staticmethod
    def _roi_text(roi):
        return f"ROI (đỏ): [x={roi[0]}, y={roi[1]}, w={roi[2]}, h={roi[3]}]"

    @staticmethod
    def _mark_text(mark):
        if not mark:
            return "MARK (xanh): chưa vẽ"
        return f"MARK (xanh): [x={mark[0]}, y={mark[1]}, w={mark[2]}, h={mark[3]}]"

    def _refresh_overlays(self):
        self.img_label.current_roi = self.current_roi
        self.img_label.current_mark = self.current_mark
        self.img_label.update()

    # ------------------------------------------------------------------
    def select_golden_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh mẫu chuẩn", "", "Ảnh (*.jpg *.png *.bmp)")
        if path:
            self.current_image_path = path
            self.lbl_path.setText(path)
            self.img_label.set_golden_image(QPixmap(path))
            self._refresh_overlays()

    def on_draw_mode_changed(self, index):
        self.img_label.set_draw_target("mark" if index == DRAW_MARK else "roi")

    def on_roi_drawn(self, roi):
        """Khung vừa vẽ xong: lưu vào ROI hoặc MARK tuỳ chế độ đang chọn."""
        roi = tuple(roi)
        if self.combo_draw.currentIndex() == DRAW_MARK:
            self.current_mark = roi
            self.lbl_mark_info.setText(self._mark_text(roi))
            self.chk_align.setChecked(True)      # vẽ mark xong thì tự bật căn chỉnh
        else:
            self.current_roi = roi
            self.lbl_roi_info.setText(self._roi_text(roi))
        self._refresh_overlays()

    # ------------------------------------------------------------------
    def _validate_mark(self):
        """Kiểm tra mark trên chính ảnh Golden. Trả về thông báo lỗi, hoặc None nếu hợp lệ."""
        golden = read_image(self.current_image_path, cv2.IMREAD_GRAYSCALE)
        try:
            aligner = MarkAligner(
                golden, self.current_mark, self.current_roi,
                self.config_data.get("mark_min_score", 0.75),
                self.spin_mark_margin.value())
            aligner.locate(golden)      # mark phải tìm thấy duy nhất, đúng tại chỗ trên ảnh Golden
        except AlignmentError as e:
            return str(e)
        return None

    # ------------------------------------------------------------------
    # THỬ ẢNH: chạy checker bằng thông số đang chỉnh trên cửa sổ (chưa lưu)
    # ------------------------------------------------------------------
    def _build_checker(self):
        return RobustSolderICChecker(
            golden_template_path=self.current_image_path,
            base_roi=self.current_roi,
            dark_threshold=self.spin_dark.value(),
            min_solder_ratio=self.spin_solder.value(),
            mark_align_enabled=self.chk_align.isChecked(),
            mark_roi=self.current_mark,
            mark_min_score=self.config_data.get("mark_min_score", 0.75),
            mark_search_margin=self.spin_mark_margin.value(),
            min_blobs=self.config_data.get("min_blobs", 0),
        )

    def evaluate_image(self, path):
        """Chạy thử 1 ảnh. Trả về dict (state, message, detail, frame), hoặc None nếu không đọc được ảnh.
        state: "OK" | "NG" | "ERROR"  (ERROR = không căn chỉnh được, ngoài sản xuất sẽ bị tính NG)."""
        img = read_image(path)
        if img is None:
            return None

        name = os.path.basename(path)
        if not self.current_image_path or not os.path.exists(self.current_image_path):
            return {"state": "ERROR", "message": "⚠️ Chưa chọn ảnh mẫu Golden hợp lệ",
                    "detail": f"Ảnh thử: {name}", "frame": img}

        checker = self._build_checker()
        is_missing, boxes = checker.check_missing_ic(img)

        frame = img.copy()
        annotate_ic_check(frame, checker, is_missing, boxes)

        lines = [f"Ảnh thử: {name}",
                 "Căn chỉnh: MARK" if checker.mark_align_enabled else "Căn chỉnh: ECC tự động (không dùng MARK)"]
        if checker.last_alignment:
            a = checker.last_alignment
            lines.append(f"Mark: score {a['score']:.3f} | lệch dX={a['offset'][0]:+d}, dY={a['offset'][1]:+d} px"
                         f" | ROI đã dịch: {tuple(a['roi'])}")
        if checker.last_ratio is not None:
            lines.append(f"Tỷ lệ pixel tối trong ROI: {checker.last_ratio:.3f} (tối thiểu {checker.min_solder_ratio:.2f})")
            if checker.min_blobs > 0:
                lines.append(f"Số điểm hàn: {checker.last_blobs} (tối thiểu {checker.min_blobs})")

        if checker.last_error:
            state, message = "ERROR", f"⚠️ LỖI CĂN CHỈNH/ROI (ngoài sản xuất sẽ bị tính NG): {checker.last_error}"
        elif is_missing:
            state, message = "NG", "🔴 NG: MẤT IC"
        else:
            state, message = "OK", "🟢 OK: Có IC"
        return {"state": state, "message": message, "detail": "\n".join(lines), "frame": frame}

    def on_test_image_clicked(self):
        if not self.current_image_path or not os.path.exists(self.current_image_path):
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn ảnh mẫu Golden hợp lệ trước khi thử!")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn ảnh cần thử", "", "Ảnh (*.jpg *.jpeg *.png *.bmp *.tif)")
        if not path:
            return
        result = self.evaluate_image(path)
        if result is None:
            QMessageBox.warning(self, "Cảnh báo", "Không đọc được ảnh đã chọn!")
            return
        ROITestResultDialog(result, self).exec_()

    def save_and_close(self):
        if self.tabs.currentIndex() == 1:
            try:
                if self.mic_settings.roi_input.text().strip():
                    parsed = self.mic_settings._parse_roi()
                    roi_type = self.mic_settings.combo_roi_type.currentData() if hasattr(self.mic_settings, 'combo_roi_type') else 'air_bubbles_mic'
                    row = self.mic_settings.list_rois.currentRow()
                    roi_item = {"rect": parsed, "type": roi_type}
                    if 0 <= row < len(self.mic_settings.rois_list):
                        self.mic_settings.rois_list[row] = roi_item
                    elif len(self.mic_settings.rois_list) < 10:
                        self.mic_settings.rois_list.append(roi_item)
                draft = self.mic_settings.draft_config()
                validate_mic_task(draft)
            except (ValueError, TypeError) as exc:
                QMessageBox.warning(self, "Task MIC chưa hợp lệ", str(exc) or "Cấu hình ROI MIC chưa hợp lệ.")
                return
            cfg = config.load_config()
            cfg.update(draft)
            if config.save_config(cfg):
                QMessageBox.information(self, "Thành công", "Đã lưu task MIC Void riêng. Task IC không thay đổi.")
            else:
                QMessageBox.critical(self, "Lỗi", "Không lưu được cấu hình.")
            return
        if not self.current_image_path or not os.path.exists(self.current_image_path):
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn ảnh mẫu Golden hợp lệ!")
            return

        golden = read_image(self.current_image_path)
        if golden is None:
            QMessageBox.warning(self, "Cảnh báo", "Không đọc được ảnh Golden.")
            return
        if self.chk_align.isChecked():
            error = self._validate_mark()
            if error:
                QMessageBox.warning(self, "Cảnh báo", f"Không thể bật căn chỉnh theo MARK:\n{error}")
                return

        self.config_data = config.load_config()
        self.config_data["golden_path"] = self.current_image_path
        self.config_data["pos1_roi"] = list(self.current_roi)
        self.config_data["dark_threshold"] = self.spin_dark.value()
        self.config_data["min_solder_ratio"] = round(self.spin_solder.value(), 3)
        self.config_data["mark_align_enabled"] = bool(self.chk_align.isChecked())
        self.config_data["mark_roi"] = list(self.current_mark) if self.current_mark else None
        self.config_data["mark_search_margin"] = self.spin_mark_margin.value()

        if config.save_config(self.config_data):
            QMessageBox.information(self, "Thành công", "Đã cập nhật cấu hình!")
