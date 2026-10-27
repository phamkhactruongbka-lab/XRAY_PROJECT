"""Editable MIC void configuration. Changes only while AUTO worker is stopped.

Hỗ trợ tối đa 10 vùng ROI MIC (Multi-ROI).
Giao diện nền sáng / chữ đen, có danh sách quản lý 10 ROI và khung "Thử spec trên ảnh".
"""
import os

import cv2
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap, QColor
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QDoubleSpinBox,
                             QSpinBox, QCheckBox, QLabel, QMessageBox, QComboBox, QLineEdit,
                             QPushButton, QGroupBox, QFileDialog, QSizePolicy, QTabWidget, QWidget,
                             QListWidget, QListWidgetItem)

import config
from core.mark_alignment import read_image
from core.mic_void import (
    ROI_PALETTE, ROI_TYPE_VOID, ROI_TYPE_TIN_BALL, get_mic_roi_items,MIC_CLASS_NAME, evaluate_mic_voids, judge_mic, annotate_void,
                           validate_mic_task, get_mic_rois)
from ui.roi_label import ROISelectionLabel

LIGHT_QSS = """
QDialog { background-color: #f4f6f9; }
QWidget { color: #000000; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
QGroupBox {
    background-color: #ffffff; border: 1px solid #c5ccd6; border-radius: 8px;
    margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #0b3d91; }
QLabel { color: #000000; background: transparent; }
QLabel#note { color: #8a4b00; font-size: 12px; }
QLabel#hint { color: #444444; font-size: 12px; }
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {
    background-color: #ffffff; color: #000000; border: 1px solid #8f9bb0;
    border-radius: 5px; padding: 4px 8px; min-height: 24px; font-weight: normal;
}
QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus, QComboBox:focus { border: 2px solid #1a73e8; }
QComboBox QAbstractItemView { background-color: #ffffff; color: #000000;
    selection-background-color: #d2e3fc; selection-color: #000000; }
QCheckBox { color: #000000; spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QPushButton {
    background-color: #e8ebf0; color: #000000; border: 1px solid #8f9bb0;
    border-radius: 6px; padding: 6px 14px; font-weight: 600; min-height: 24px;
}
QPushButton:hover { background-color: #d9dee6; }
QPushButton#primary { background-color: #1a73e8; color: #ffffff; border: 1px solid #1557b0; }
QPushButton#primary:hover { background-color: #1557b0; }
QPushButton#danger { background-color: #fce8e6; color: #c5221f; border: 1px solid #ea4335; }
QPushButton#danger:hover { background-color: #fad2cf; }
QListWidget {
    background-color: #ffffff; border: 1px solid #8f9bb0; border-radius: 5px;
    color: #000000; font-weight: normal; padding: 2px;
}
QListWidget::item { padding: 4px; border-bottom: 1px solid #edf0f5; }
QListWidget::item:selected { background-color: #1a73e8; color: #ffffff; }
"""

RESULT_STYLE = {
    'OK': "background:#e6f4ea; color:#0d652d; border:2px solid #34a853;",
    'NG': "background:#fce8e6; color:#a50e0e; border:2px solid #ea4335;",
    'INFO': "background:#eef1f5; color:#000000; border:1px solid #c5ccd6;",
}


class MicVoidDialog(QDialog):
    _model_cache = {}          # model_path -> YOLO (dùng chung giữa các lần mở cửa sổ)

    def __init__(self, parent=None, initial_config=None, embedded=False):
        super().__init__(parent)
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.Widget)
        self.setWindowTitle("MIC VOID SETTINGS – Spec bắt rỗ khí MIC (Tối đa 10 ROI)")
        self.setStyleSheet(LIGHT_QSS)
        self.setMinimumSize(940 if embedded else 1020, 600 if embedded else 650)
        self.model_path = getattr(parent, 'model_path', '') or ''
        self.test_image = None         # ảnh BGR đang thử
        self.test_name = ''
        self.test_dets = []            # [(xyxy, conf)] của lớp MIC

        cfg = config.load_config() if initial_config is None else initial_config
        self.golden_path = cfg.get("mic_void_golden_path", "")
        self.mark_roi = cfg.get("mic_void_mark_roi")

        # Nạp danh sách tối đa 10 ROI
        self.rois_list = get_mic_roi_items(cfg)

        root = QHBoxLayout(self)
        root.setSpacing(12)

        # ---------------- Cột trái: thông số spec + quản lý ROI ----------------
        left = QVBoxLayout()
        left.setSpacing(8)

        box_spec = QGroupBox("Spec phán định")
        form = QFormLayout(box_spec)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setVerticalSpacing(8)

        self.threshold = QDoubleSpinBox(); self.threshold.setRange(0, 100); self.threshold.setDecimals(1)
        self.threshold.setSingleStep(.5); self.threshold.setSuffix(' %')
        self.threshold.setValue(float(cfg.get('mic_void_threshold_percent', 10)))
        self.threshold_outside = QDoubleSpinBox(); self.threshold_outside.setRange(0, 100); self.threshold_outside.setDecimals(1)
        self.threshold_outside.setSingleStep(.5); self.threshold_outside.setSuffix(' %')
        self.threshold_outside.setValue(float(cfg.get('mic_void_outside_threshold_percent', 20)))
        self.conf = QDoubleSpinBox(); self.conf.setRange(.05, .95); self.conf.setDecimals(2); self.conf.setSingleStep(.05)
        self.conf.setValue(float(cfg.get('mic_void_confidence', .25)))
        self.min_pixels = QSpinBox(); self.min_pixels.setRange(1, 10000); self.min_pixels.setSuffix(' px')
        self.min_pixels.setValue(int(cfg.get('mic_void_min_pixels', 5)))
        self.polarity = QComboBox(); self.polarity.addItem('Sáng (bright)', 'bright'); self.polarity.addItem('Tối (dark)', 'dark')
        self.polarity.setCurrentIndex(0 if cfg.get('mic_void_polarity', 'bright') == 'bright' else 1)
        self.use_void = QCheckBox("Phán định OK/NG theo Void %")
        self.use_void.setChecked(bool(cfg.get('mic_void_use_for_decision', True)))

        form.addRow("Ngưỡng Void trong ROI (NG >):", self.threshold)
        form.addRow("Ngưỡng Void ngoài ROI (NG >):", self.threshold_outside)
        form.addRow("YOLO confidence (MIC):", self.conf)
        form.addRow("Bỏ qua rỗ nhỏ hơn:", self.min_pixels)
        form.addRow("Màu vùng rỗ trên ảnh:", self.polarity)
        form.addRow("", self.use_void)
        left.addWidget(box_spec)

        # Khối quản lý đa ROI MIC (Tối đa 10 vùng)
        box_rois = QGroupBox("Danh sách ROI MIC (Tối đa 10 vùng ROI)")
        rois_vbox = QVBoxLayout(box_rois)
        rois_vbox.setSpacing(6)

        self.list_rois = QListWidget()
        self.list_rois.setMaximumHeight(130)
        self.list_rois.currentRowChanged.connect(self.on_roi_selection_changed)
        rois_vbox.addWidget(self.list_rois)

        roi_edit_row = QHBoxLayout()
        roi_edit_row.addWidget(QLabel("Tọa độ:"))
        self.roi_input = QLineEdit()
        self.roi_input.setPlaceholderText("x, y, width, height")
        self.roi_input.textChanged.connect(self.on_roi_input_changed)
        roi_edit_row.addWidget(self.roi_input, 1)
        self.roi = self.roi_input  # Thuộc tính tương thích ngược với các test cũ
        rois_vbox.addLayout(roi_edit_row)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Mục đích ROI:"))
        self.combo_roi_type = QComboBox()
        self.combo_roi_type.addItem("🫧 Rỗ khí hàn (air_bubbles_mic)", "air_bubbles_mic")
        self.combo_roi_type.addItem("🔘 Bi thiếc lỗ MIC (tin_ball_mic_hole)", "tin_ball_mic_hole")
        self.combo_roi_type.currentIndexChanged.connect(self.on_roi_type_changed)
        type_row.addWidget(self.combo_roi_type, 1)
        rois_vbox.addLayout(type_row)

        roi_btn_row = QHBoxLayout()
        self.btn_add_roi = QPushButton("➕ Thêm ROI")
        self.btn_add_roi.clicked.connect(self.add_roi_slot)
        self.btn_del_roi = QPushButton("➖ Xóa ROI")
        self.btn_del_roi.setObjectName("danger")
        self.btn_del_roi.clicked.connect(self.remove_selected_roi)
        roi_btn_row.addWidget(self.btn_add_roi)
        roi_btn_row.addWidget(self.btn_del_roi)
        rois_vbox.addLayout(roi_btn_row)

        left.addWidget(box_rois)

        # Lưu dữ liệu
        box_save = QGroupBox("Lưu dữ liệu")
        save_row = QHBoxLayout(box_save)
        self.crop = QCheckBox("Lưu ảnh crop"); self.crop.setChecked(bool(cfg.get('mic_void_save_crop', True)))
        self.csv = QCheckBox("Lưu CSV"); self.csv.setChecked(bool(cfg.get('mic_void_save_csv', True)))
        save_row.addWidget(self.crop); save_row.addWidget(self.csv); save_row.addStretch()
        left.addWidget(box_save)

        note = QLabel("• Đa ROI: hỗ trợ vẽ đến 10 vùng ROI. Chọn vùng trong danh sách để vẽ lại.\n"
                      "• Vết rỗ nằm trong ROI nào sẽ áp dụng Ngưỡng trong ROI.\n"
                      "• Vết rỗ ngoài tất cả ROI áp dụng Ngưỡng ngoài ROI.")
        note.setObjectName("note"); note.setWordWrap(True)
        left.addWidget(note)
        left.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Hủy"); btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("💾 Lưu spec"); btn_save.setObjectName("primary"); btn_save.clicked.connect(self.save)
        btn_row.addWidget(btn_cancel); btn_row.addWidget(btn_save)
        left.addLayout(btn_row)
        if embedded:
            btn_cancel.hide()
            btn_save.hide()
        root.addLayout(left, stretch=4)

        # ---------------- Cột phải: Tabs Golden & Thử spec ----------------
        self.image_tabs = QTabWidget()
        self.image_tabs.setStyleSheet("QTabBar::tab { background:#dce6f2; color:#172b43; padding:8px; } QTabBar::tab:selected { background:#1a73e8; color:white; }")
        golden_page = QWidget()
        golden_layout = QVBoxLayout(golden_page)
        golden_button = QPushButton("Chọn Golden MIC riêng")
        golden_button.clicked.connect(self.select_golden)
        golden_layout.addWidget(golden_button)
        self.lbl_golden = QLabel(self.golden_path or 'Chưa chọn Golden MIC – không dùng Golden IC')
        self.lbl_golden.setWordWrap(True)
        golden_layout.addWidget(self.lbl_golden)
        self.golden_canvas = ROISelectionLabel()
        self.golden_canvas.setAlignment(Qt.AlignCenter)
        self.golden_canvas.setMinimumSize(420, 240)
        self.golden_canvas.setStyleSheet('background:#20242c;')
        self.golden_canvas.roi_selected.connect(self.on_golden_drawn)
        golden_layout.addWidget(self.golden_canvas, 1)

        draw_row = QHBoxLayout()
        self.draw_mode = QComboBox()
        self.draw_mode.addItems(['ROI MIC đang chọn (vàng)', 'MARK MIC (xanh)'])
        self.draw_mode.currentIndexChanged.connect(lambda i: self.golden_canvas.set_draw_target('mark' if i else 'mic'))
        self.golden_canvas.set_draw_target('mic')
        draw_row.addWidget(self.draw_mode)
        self.align_mark = QCheckBox('Tự căn chỉnh ROI theo MARK MIC')
        self.align_mark.setChecked(bool(cfg.get('mic_void_mark_align_enabled', False)))
        draw_row.addWidget(self.align_mark)
        golden_layout.addLayout(draw_row)

        mark_form = QFormLayout()
        self.mark_score = QDoubleSpinBox(); self.mark_score.setRange(.1, 1); self.mark_score.setSingleStep(.05)
        self.mark_score.setValue(float(cfg.get('mic_void_mark_min_score', .75)))
        self.mark_margin = QSpinBox(); self.mark_margin.setRange(0, 5000); self.mark_margin.setSpecialValueText('Toàn ảnh')
        self.mark_margin.setValue(int(cfg.get('mic_void_mark_search_margin', 0)))
        mark_form.addRow('Điểm MARK tối thiểu:', self.mark_score)
        mark_form.addRow('Phạm vi tìm MARK (px):', self.mark_margin)
        golden_layout.addLayout(mark_form)
        self.lbl_mark = QLabel()
        self.lbl_mark.setWordWrap(True)
        golden_layout.addWidget(self.lbl_mark)
        self.image_tabs.addTab(golden_page, 'Golden / ROI / MARK MIC')

        # Tab Thử spec trên ảnh
        box_test = QGroupBox("Thử spec trên ảnh (kết quả cập nhật ngay khi đổi spec)")
        right = QVBoxLayout(box_test)
        top = QHBoxLayout()
        self.btn_pick = QPushButton("📂 Chọn ảnh thử...")
        self.btn_pick.clicked.connect(self.pick_test_image)
        self.lbl_file = QLabel("Chưa chọn ảnh"); self.lbl_file.setObjectName("hint")
        top.addWidget(self.btn_pick); top.addWidget(self.lbl_file, stretch=1)
        right.addLayout(top)

        self.lbl_image = QLabel("Ảnh X-Ray sẽ hiển thị ở đây")
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setMinimumSize(420, 300)
        self.lbl_image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.lbl_image.setStyleSheet("background:#20242c; color:#cfd6df; border-radius:6px;")
        right.addWidget(self.lbl_image, stretch=1)

        self.lbl_result = QLabel("—")
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setStyleSheet(RESULT_STYLE['INFO'] + "border-radius:6px; padding:8px; font-size:15px;")
        right.addWidget(self.lbl_result)
        self.image_tabs.addTab(box_test, 'Thử spec trên ảnh')

        root.addWidget(self.image_tabs, stretch=6)

        # Timer debounce cập nhật
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(150)
        self._timer.timeout.connect(self.update_preview)
        for sig in (self.threshold.valueChanged, self.threshold_outside.valueChanged, self.conf.valueChanged,
                    self.min_pixels.valueChanged, self.polarity.currentIndexChanged, self.use_void.toggled,
                    self.align_mark.toggled, self.mark_score.valueChanged, self.mark_margin.valueChanged):
            sig.connect(lambda *_: self._timer.start())

        # Đồng bộ danh sách ROI ban đầu
        self.refresh_rois_ui()
        if self.golden_path:
            self.golden_canvas.set_golden_image(QPixmap(self.golden_path))
        self.refresh_golden()

    # ---------------- Quản lý danh sách ROI ----------------
    def refresh_rois_ui(self):
        curr_row = self.list_rois.currentRow()
        self.list_rois.blockSignals(True)
        self.list_rois.clear()
        for idx, item_data in enumerate(self.rois_list, start=1):
            r = item_data['rect'] if isinstance(item_data, dict) else item_data[:4]
            t = item_data.get('type', 'air_bubbles_mic') if isinstance(item_data, dict) else (item_data[4] if len(item_data) > 4 else 'air_bubbles_mic')
            color = ROI_PALETTE[(idx - 1) % len(ROI_PALETTE)]
            tag = "RỖ KHÍ" if t == 'air_bubbles_mic' else "BI THIẾC"
            item = QListWidgetItem(f"ROI #{idx} [{tag}]:  {r[0]}, {r[1]}, {r[2]}, {r[3]}")
            item.setForeground(QColor(*color))
            self.list_rois.addItem(item)
        self.list_rois.blockSignals(False)

        if 0 <= curr_row < len(self.rois_list):
            self.list_rois.setCurrentRow(curr_row)
        elif self.rois_list:
            self.list_rois.setCurrentRow(0)
        else:
            self.roi_input.blockSignals(True)
            self.roi_input.clear()
            self.roi_input.blockSignals(False)

    def on_roi_selection_changed(self, row):
        if 0 <= row < len(self.rois_list):
            item_data = self.rois_list[row]
            r = item_data['rect'] if isinstance(item_data, dict) else item_data[:4]
            t = item_data.get('type', 'air_bubbles_mic') if isinstance(item_data, dict) else (item_data[4] if len(item_data) > 4 else 'air_bubbles_mic')
            self.roi_input.blockSignals(True)
            self.roi_input.setText(', '.join(map(str, r)))
            self.roi_input.blockSignals(False)

            if hasattr(self, 'combo_roi_type'):
                self.combo_roi_type.blockSignals(True)
                self.combo_roi_type.setCurrentIndex(1 if t == 'tin_ball_mic_hole' else 0)
                self.combo_roi_type.blockSignals(False)

            self.golden_canvas.active_roi_idx = row
        else:
            self.roi_input.blockSignals(True)
            self.roi_input.clear()
            self.roi_input.blockSignals(False)
            self.golden_canvas.active_roi_idx = 0

    def on_roi_type_changed(self, idx):
        row = self.list_rois.currentRow()
        if 0 <= row < len(self.rois_list):
            new_type = self.combo_roi_type.currentData()
            if isinstance(self.rois_list[row], dict):
                self.rois_list[row]['type'] = new_type
            else:
                self.rois_list[row] = {'rect': list(self.rois_list[row][:4]), 'type': new_type}
            self.refresh_rois_ui()
            self.refresh_golden()
            self._timer.start()

    def on_roi_input_changed(self, text):
        text = text.strip()
        row = self.list_rois.currentRow()
        if row < 0 and self.rois_list:
            row = 0
        if not text:
            if 0 <= row < len(self.rois_list):
                self.rois_list.pop(row)
                self.refresh_rois_ui()
            self.refresh_golden()
            self._timer.start()
            return
        parts = [p.strip() for p in text.split(',') if p.strip()]
        if len(parts) == 4:
            try:
                vals = [int(p) for p in parts]
                if vals[0] >= 0 and vals[1] >= 0 and vals[2] > 0 and vals[3] > 0:
                    t = self.combo_roi_type.currentData() if hasattr(self, 'combo_roi_type') else 'air_bubbles_mic'
                    if 0 <= row < len(self.rois_list):
                        if isinstance(self.rois_list[row], dict):
                            self.rois_list[row]['rect'] = vals
                        else:
                            self.rois_list[row] = {'rect': vals, 'type': t}
                    else:
                        if len(self.rois_list) < 10:
                            self.rois_list.append({'rect': vals, 'type': t})
                            row = len(self.rois_list) - 1
                    self.refresh_rois_ui()
                    self.refresh_golden()
                    self._timer.start()
            except ValueError:
                pass

    def add_roi_slot(self):
        if len(self.rois_list) >= 10:
            QMessageBox.warning(self, "Giới hạn ROI", "Số lượng ROI tối đa cho MIC là 10 vùng.")
            return
        has_void = any((r.get('type') if isinstance(r, dict) else 'air_bubbles_mic') == 'air_bubbles_mic' for r in self.rois_list)
        default_type = 'tin_ball_mic_hole' if has_void else 'air_bubbles_mic'
        new_roi = {'rect': [100, 100, 150, 150], 'type': default_type}
        self.rois_list.append(new_roi)
        self.refresh_rois_ui()
        self.list_rois.setCurrentRow(len(self.rois_list) - 1)
        self.refresh_golden()
        self._timer.start()

    def remove_selected_roi(self):
        row = self.list_rois.currentRow()
        if 0 <= row < len(self.rois_list):
            self.rois_list.pop(row)
            self.refresh_rois_ui()
            self.refresh_golden()
            self._timer.start()

    def select_golden(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Chọn Golden riêng cho task MIC', '', 'Images (*.jpg *.jpeg *.png *.bmp *.tif)')
        if path:
            self.set_golden_path(path)

    def set_golden_path(self, path):
        if read_image(path) is None:
            QMessageBox.warning(self, 'Golden MIC', 'Không đọc được ảnh Golden MIC.')
            return
        self.golden_path = path
        self.lbl_golden.setText(path)
        self.mark_roi = None
        self.align_mark.setChecked(True)
        self.golden_canvas.set_golden_image(QPixmap(path))
        self.rois_list.clear()
        self.refresh_rois_ui()
        self.refresh_golden()
        self._timer.start()

    def on_golden_drawn(self, rect):
        if self.draw_mode.currentIndex() == 1:
            self.mark_roi = list(rect)
            self.align_mark.setChecked(True)
        else:
            row = self.list_rois.currentRow()
            t = self.combo_roi_type.currentData() if hasattr(self, 'combo_roi_type') else 'air_bubbles_mic'
            item_obj = {'rect': list(rect), 'type': t}
            if 0 <= row < len(self.rois_list):
                old_type = self.rois_list[row].get('type', t) if isinstance(self.rois_list[row], dict) else t
                self.rois_list[row] = {'rect': list(rect), 'type': old_type}
            else:
                if len(self.rois_list) < 10:
                    self.rois_list.append(item_obj)
                else:
                    self.rois_list[-1] = item_obj
            self.refresh_rois_ui()
        self.refresh_golden()
        self._timer.start()

    def _parse_roi(self):
        """Hàm tương thích ngược trả về ROI từ ô input (hoặc từ ROI đang chọn nếu ô trống)."""
        text = self.roi_input.text().strip()
        if text:
            parts = [p.strip() for p in text.split(',')]
            if len(parts) != 4:
                raise ValueError(f"Tọa độ ROI không hợp lệ: '{text}' (cần 4 số: x, y, w, h)")
            try:
                roi = [int(v) for v in parts]
            except ValueError:
                raise ValueError(f"Tọa độ ROI phải là số nguyên: '{text}'")
            if roi[0] < 0 or roi[1] < 0 or roi[2] <= 0 or roi[3] <= 0:
                raise ValueError(f"Tọa độ ROI không hợp lệ: {roi}")
            return roi
        if self.rois_list:
            row = self.list_rois.currentRow()
            if 0 <= row < len(self.rois_list):
                item = self.rois_list[row]
                return list(item['rect'] if isinstance(item, dict) else item[:4])
            first = self.rois_list[0]
            return list(first['rect'] if isinstance(first, dict) else first[:4])
        return None

    def refresh_golden(self):
        self.golden_canvas.current_mic_rois = list(self.rois_list)
        if self.rois_list:
            first = self.rois_list[0]
            self.golden_canvas.current_mic = list(first['rect'] if isinstance(first, dict) else first[:4])
        else:
            self.golden_canvas.current_mic = None
        self.golden_canvas.current_mark = self.mark_roi
        self.golden_canvas.current_roi = None
        self.lbl_mark.setText(f'MARK MIC: {self.mark_roi}' if self.mark_roi else 'Chưa vẽ MARK MIC. ROI/MARK IC không xuất hiện tại đây.')
        self.golden_canvas.update()

    def current_spec(self):
        """Spec đang chỉnh trên giao diện (chưa cần lưu)."""
        first_roi = (self.rois_list[0]['rect'] if isinstance(self.rois_list[0], dict) else self.rois_list[0][:4]) if self.rois_list else None
        return dict(mic_void_threshold_percent=self.threshold.value(),
                    mic_void_outside_threshold_percent=self.threshold_outside.value(),
                    mic_void_confidence=self.conf.value(),
                    mic_void_min_pixels=self.min_pixels.value(),
                    mic_void_polarity=self.polarity.currentData(),
                    mic_void_use_for_decision=self.use_void.isChecked(),
                    mic_void_save_crop=self.crop.isChecked(),
                    mic_void_save_csv=self.csv.isChecked(),
                    mic_void_golden_path=self.golden_path,
                    mic_void_mark_roi=self.mark_roi,
                    mic_void_mark_align_enabled=self.align_mark.isChecked(),
                    mic_void_mark_min_score=self.mark_score.value(),
                    mic_void_mark_search_margin=self.mark_margin.value(),
                    mic_void_roi=first_roi,
                    mic_void_rois=list(self.rois_list))

    def draft_config(self):
        """Return the unsaved spec; the containing ROI dialog owns persistence."""
        return dict(self.current_spec(), mic_void_validated=False)

    def _get_model(self):
        if not self.model_path or not os.path.exists(self.model_path):
            raise RuntimeError("Chưa nạp Model AI (bấm '🧠 Model AI' ở màn hình chính).")
        model = self._model_cache.get(self.model_path)
        if model is None:
            from ultralytics import YOLO
            model = YOLO(self.model_path, task="detect")
            self._model_cache[self.model_path] = model
        return model

    def pick_test_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh X-Ray để thử spec", "",
                                              "Images (*.jpg *.jpeg *.png *.bmp *.tif)")
        if not path:
            return
        img = read_image(path)
        if img is None:
            QMessageBox.warning(self, "Lỗi", "Không đọc được ảnh."); return
        self.setCursor(Qt.WaitCursor)
        try:
            result = self._get_model().predict(source=path, conf=0.05, imgsz=config.YOLO_IMGSZ, verbose=False)[0]
            self.test_dets = [(b.xyxy[0].tolist(), float(b.conf[0])) for b in result.boxes
                              if str(result.names[int(b.cls[0])]) == MIC_CLASS_NAME]
        except Exception as e:
            QMessageBox.warning(self, "Lỗi YOLO", str(e)); return
        finally:
            self.unsetCursor()
        self.test_image, self.test_name = img, os.path.basename(path)
        self.lbl_file.setText(self.test_name)
        self.update_preview()

    def update_preview(self):
        if self.test_image is None:
            return
        spec = self.current_spec()
        dets = [d for d in self.test_dets if d[1] >= spec['mic_void_confidence']]
        results = evaluate_mic_voids(self.test_image, dets, spec)
        frame = self.test_image.copy()

        # Vẽ các ROI nếu không dùng mark align
        if self.rois_list and not spec["mic_void_mark_align_enabled"]:
            for r_idx, item in enumerate(self.rois_list, start=1):
                x, y, w, h = item['rect'] if isinstance(item, dict) else item[:4]
                color_bgr = ROI_PALETTE[(r_idx - 1) % len(ROI_PALETTE)][::-1]
                t_label = "TIN" if (isinstance(item, dict) and item.get('type') == ROI_TYPE_TIN_BALL) else "VOID"
                cv2.rectangle(frame, (x, y), (x + w, y + h), color_bgr, 2)
                cv2.putText(frame, f"#{r_idx} [{t_label}]", (x + 2, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color_bgr, 1, cv2.LINE_AA)

        for (xyxy, _), res in zip(dets, results):
            annotate_void(frame, xyxy, res, spec['mic_void_threshold_percent'])
        self._show_frame(frame)

        if not dets:
            self._show_result('OK', f"✅ MIC OK – không có rỗ khí MIC nào có confidence ≥ {spec['mic_void_confidence']:.2f}")
            return
        ng = judge_mic(results, spec['mic_void_use_for_decision'])
        lines = []
        for i, ((_, c), r) in enumerate(zip(dets, results), 1):
            val = f"{r.void_percent:.1f}%" if r.void_percent is not None else "không đo được"
            th_used = getattr(r, 'applied_threshold', spec['mic_void_threshold_percent'])
            lines.append(f"#{i}: conf {c:.2f} – Void {val} / {th_used:.1f}% → {r.status}")
            if r.alignment:
                a = r.alignment
                lines.append(f"MARK MIC: dX={a['offset'][0]:+d}, dY={a['offset'][1]:+d} px")
            elif r.status == 'REVIEW':
                lines.append(r.reason)
        head = "❌ MIC NG" if ng else "✅ MIC OK"
        self._show_result('NG' if ng else 'OK', f"{head}\n" + "\n".join(lines))

    def _show_result(self, state, text):
        self.lbl_result.setStyleSheet(RESULT_STYLE[state] + "border-radius:6px; padding:8px; font-size:15px; font-weight:bold;")
        self.lbl_result.setText(text)

    def _show_frame(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.lbl_image.setPixmap(QPixmap.fromImage(qimg).scaled(
            self.lbl_image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def save(self):
        if self.save_task():
            self.accept()

    def save_task(self):
        try:
            draft = self.draft_config()
            validate_mic_task(draft)
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, 'Task MIC chưa hợp lệ', str(exc) or 'Cấu hình ROI MIC chưa hợp lệ.')
            return False
        cfg = config.load_config()
        cfg.update(draft)
        if config.save_config(cfg):
            return True
        QMessageBox.critical(self, 'Lỗi', 'Không lưu được cấu hình.')
        return False
