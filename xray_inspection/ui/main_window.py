"""Giao diện chính của hệ thống soi X-Ray."""
import os
import time
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QImage, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
import config
from core.dobot_server import DobotTCPServer
from core.worker import XRayWorkerThread
from ui import styles
from ui.log_panel import LogPanel
from ui.roi_dialog import ROIConfigDialog
from ui.mic_void_dialog import MicVoidDialog
from ui.zoom_view import ZoomImageView

IMG_PLACEHOLDER = "KHU VỰC HIỂN THỊ ẢNH X-RAY"
IMG_INFO_EMPTY = "Thông tin ảnh: Chưa có dữ liệu"
START_TEXT = "▶ BẮT ĐẦU"
STOP_TEXT = "⏹ TẠM DỪNG"

def new_pcb_results():
    return {
        i: {"Pos1": "WAIT", "Pos2": "WAIT", "Pos3": "WAIT", "Status": "WAIT"}
        for i in range(1, config.PCB_COUNT + 1)
    }

class XRayInspectionApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HỆ THỐNG SOI X-RAY KIỂM TRA LỖI PCB - AI INSPECTION")
        self.setGeometry(80, 60, 1450, 900)
        self.setStyleSheet(styles.INDUSTRIAL_DARK_QSS)
        self.model_path = ""
        self.watch_folder = ""
        self.worker_thread = None
        self.batch_images = {}
        self.pcb_results = new_pcb_results()
        self.total_ok = 0
        self.total_ng = 0
        self.initUI()
        self.log("🟢 Hệ thống khởi động", "ok")
        self._autoload_model()
        self.dobot_state = "BUSY"     # BUSY | READY | WAIT_ACK
        self.pending_ok = []          # các phên OK đang chờ Dobot sẵn sàng để gắp
        self.ack_deadline = 0.0

        self.dobot = DobotTCPServer(
            port=config.DOBOT_PORT,
            host=config.DOBOT_HOST,
            allowed_ip_prefix=config.DOBOT_ALLOWED_IP_PREFIX,
            log_callback=self.log,
        )
        self.dobot_timer = QTimer()
        self.dobot_timer.timeout.connect(self.poll_dobot)
        self.dobot_timer.start(config.DOBOT_POLL_MS)

    def _autoload_model(self):
        for name in ("best.onnx", "best.pt"):
            path = os.path.join(config.BASE_DIR, name)
            if os.path.exists(path):
                self.model_path = path
                self.lbl_status.setText(f"✅ Đã tự động nạp Model: {name}")
                self.log(f"✅ Tự động nạp Model: {name}", "ok")
                return

    def log(self, text, level="info"):
        panel = getattr(self, "log_panel", None)
        if panel is None:          # giao diện chưa dựng xong: chỉ in ra terminal
            print(text)
            return
        panel.log(text, level)

    @staticmethod
    def _level_of(text):
        """Đoán mức log từ biểu tượng trong câu trạng thái."""
        if "❌" in text or "🔴" in text:
            return "ng"
        if "⚠️" in text:
            return "warn"
        if "🟢" in text or "✅" in text:
            return "ok"
        return "info"

    def on_worker_status(self, text):
        """Câu trạng thái từ worker: hiện lên nhãn trạng thái và ghi vào log."""
        self.lbl_status.setText(text)
        self.log(text, self._level_of(text))
    # ==================================================================
    # DỰNG GIAO DIỆN
    # ==================================================================
    def initUI(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        self.main_layout = main_layout
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # NỬA TRÁI: điều khiển + bảng + nhật ký
        left_panel = QVBoxLayout()
        left_panel.setSpacing(8)
        left_panel.addWidget(self._build_control_card())
        left_panel.addWidget(self._build_operator_card())
        left_panel.addWidget(self._build_stat_card())
        left_panel.addWidget(self._build_table(), stretch=3)
        self.log_panel = LogPanel()
        self.log_panel.setMinimumHeight(150)
        left_panel.addWidget(self.log_panel, stretch=2)
        main_layout.addLayout(left_panel, stretch=1)

        # NỬA PHẢI: chỉ có ảnh X-Ray
        main_layout.addLayout(self._build_image_panel(), stretch=1)

        self.update_mode_ui(is_auto=True)

    def _build_control_card(self):
        """Khối 1 (gọn): chế độ + các nút chức năng trên 1 hàng + 2 dòng trạng thái."""
        card = QFrame()
        card.setObjectName("cardFrame")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        mode_layout = QHBoxLayout()
        lbl_mode = QLabel("🎛️ Chế độ:")
        lbl_mode.setFont(QFont("Arial", 9, QFont.Bold))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["🤖 CHẾ ĐỘ TỰ ĐỘNG (AI DETECT)", "🖐 CHẾ ĐỘ THỦ CÔNG (MANUAL)"])
        self.combo_mode.currentIndexChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(lbl_mode)
        mode_layout.addWidget(self.combo_mode, stretch=1)
        layout.addLayout(mode_layout)

        btns_row = QHBoxLayout()
        btns_row.setSpacing(6)
        self.btn_load_model = QPushButton("🧠 Model AI")
        self.btn_load_model.clicked.connect(self.select_model)
        self.btn_select_folder = QPushButton("📂 Thư mục X-Ray")
        self.btn_select_folder.clicked.connect(self.select_folder)
        self.btn_config_roi = QPushButton("🎯 ROI")
        self.btn_config_roi.setStyleSheet(styles.ROI_BTN_STYLE)
        self.btn_config_roi.clicked.connect(self.open_roi_config)
        self.btn_mic_void = QPushButton("🫧 MIC Void")
        self.btn_mic_void.clicked.connect(self.open_mic_void_config)
        self.btn_start = QPushButton(START_TEXT)
        self.btn_start.setStyleSheet(styles.START_BTN_STYLE)
        self.btn_start.clicked.connect(self.toggle_monitoring)
        for btn in (self.btn_load_model, self.btn_select_folder, self.btn_config_roi, self.btn_mic_void, self.btn_start):
            btn.setFixedHeight(34)
            btns_row.addWidget(btn)
        layout.addLayout(btns_row)

        self.lbl_status = QLabel("Trạng thái: Đang chờ thiết lập...")
        self.lbl_status.setStyleSheet(styles.STATUS_LABEL_STYLE)
        self.lbl_status.setWordWrap(True)          # câu dài tự xuống dòng, không làm nửa trái bị nới rộng
        layout.addWidget(self.lbl_status)

        self.lbl_dobot_status = QLabel("🤖 Dobot MG400: Đang kiểm tra kết nối...")
        self.lbl_dobot_status.setStyleSheet(styles.DOBOT_WAIT_STYLE)
        self.lbl_dobot_status.setWordWrap(True)
        layout.addWidget(self.lbl_dobot_status)

        return card

    def _build_operator_card(self):
        """Khối 2 (gọn): nút XÁC NHẬN OK / NG của công nhân, cùng một hàng."""
        card = QFrame()
        card.setObjectName("cardFrame")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.btn_confirm_ok = QPushButton("✅ XÁC NHẬN OK (GẮP OK)")
        self.btn_confirm_ok.setFixedHeight(46)
        self.btn_confirm_ok.setEnabled(False)
        self.set_ok_button_style(active=False)
        self.btn_confirm_ok.clicked.connect(self.on_confirm_ok_clicked)

        self.btn_confirm_ng = QPushButton("⚠️ XÁC NHẬN NG (TỰ LẤY PHÊN RA)")
        self.btn_confirm_ng.setFixedHeight(46)
        self.btn_confirm_ng.setEnabled(False)
        self.set_ng_button_style(active=False)
        self.btn_confirm_ng.clicked.connect(self.on_confirm_ng_clicked)

        layout.addWidget(self.btn_confirm_ok)
        layout.addWidget(self.btn_confirm_ng)
        return card

    def _build_stat_card(self):
        """Khối 3 (gọn): thống kê phên OK / NG trên một dải mỏng."""
        card = QFrame()
        card.setObjectName("cardFrame")
        self.stat_card = card
        layout = QHBoxLayout(card)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        def make_box(bg, num_color, caption):
            box = QFrame()
            box.setStyleSheet(f"background-color: {bg}; border-radius: 6px;")
            box.setFixedHeight(38)
            box_layout = QHBoxLayout(box)
            box_layout.setContentsMargins(10, 2, 10, 2)
            lbl_txt = QLabel(caption)
            lbl_txt.setStyleSheet("color: #8f9ba8; font-size: 11px; font-weight: bold;")
            lbl_num = QLabel("0")
            lbl_num.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl_num.setStyleSheet(f"color: {num_color}; font-size: 20px; font-weight: bold;")
            box_layout.addWidget(lbl_txt)
            box_layout.addStretch()
            box_layout.addWidget(lbl_num)
            return box, lbl_num

        ok_box, self.lbl_ok_count = make_box("#1b2820", "#2ea44f", "PHÊN OK")
        ng_box, self.lbl_ng_count = make_box("#2d1a1e", "#f85149", "PHÊN NG")
        layout.addWidget(ok_box)
        layout.addWidget(ng_box)
        return card

    def _build_table(self):
        """Khối 4: bảng toạ độ các PCB."""
        self.table = QTableWidget(config.PCB_COUNT, 5)
        self.table.setHorizontalHeaderLabels(["PCB #", "Vị Trí 1", "Vị Trí 2", "Vị Trí 3", "Kết Quả"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setFont(QFont("Segoe UI", 10))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        for i in range(config.PCB_COUNT):
            self.table.setItem(i, 0, QTableWidgetItem(f"PCB {i + 1}"))
            for j in range(1, 5):
                item = QTableWidgetItem("CHỜ")
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, j, item)

        self.table.currentCellChanged.connect(self.on_current_cell_changed)
        return self.table

    def _build_image_panel(self):
        right_panel = QVBoxLayout()
        right_panel.setContentsMargins(0, 0, 0, 0)

        img_card = QFrame()
        img_card.setObjectName("cardFrame")
        img_layout = QVBoxLayout(img_card)
        img_layout.setContentsMargins(8, 8, 8, 8)
        img_layout.setSpacing(6)

        # Hàng đầu: thông tin ảnh (trái) + công cụ phóng to / thu nhỏ (phải)
        header = QHBoxLayout()
        header.setSpacing(6)

        self.lbl_img_info = QLabel(IMG_INFO_EMPTY)
        self.lbl_img_info.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_img_info.setStyleSheet("color: #58a6ff;")
        self.lbl_img_info.setWordWrap(True)
        header.addWidget(self.lbl_img_info, stretch=1)

        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setMinimumWidth(52)
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        self.lbl_zoom.setStyleSheet("color: #8f9ba8; font-weight: bold;")
        header.addWidget(self.lbl_zoom)

        self.image_view = ZoomImageView(IMG_PLACEHOLDER)
        self.image_view.setMinimumSize(300, 300)
        self.image_view.zoom_changed.connect(lambda pct: self.lbl_zoom.setText(f"{pct:.0f}%"))

        tools = (
            ("−", "Thu nhỏ", self.image_view.zoom_out),
            ("+", "Phóng to", self.image_view.zoom_in),
            ("Vừa khung", "Vừa khung (hoặc nháy đúp vào ảnh)", self.image_view.fit_to_view),
            ("1:1", "Kích thước thật", self.image_view.actual_size),
        )
        for text, tip, slot in tools:
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.setFixedHeight(28)
            btn.setStyleSheet("padding: 2px 10px; font-size: 13px;")
            btn.setFocusPolicy(Qt.NoFocus)       # bấm nút không làm mất phím mũi tên của bảng
            btn.clicked.connect(slot)
            header.addWidget(btn)

        img_layout.addLayout(header)
        img_layout.addWidget(self.image_view, stretch=1)
        right_panel.addWidget(img_card)
        return right_panel

    # ==================================================================
    # CHẾ ĐỘ AUTO / MANUAL
    # ==================================================================
    def update_mode_ui(self, is_auto):
        """Ẩn/hiện widget theo chế độ.
        AUTO  : hiện model, ROI, nút Start, thống kê, cột Kết Quả; chỉ có nút NG.
        MANUAL: ẩn các mục trên; có cả OK và NG.
        """
        self.btn_load_model.setVisible(is_auto)
        self.btn_config_roi.setVisible(is_auto)
        self.btn_mic_void.setVisible(is_auto)
        self.btn_start.setVisible(is_auto)
        self.stat_card.setVisible(is_auto)
        self.btn_confirm_ok.setVisible(not is_auto)

        self.table.setColumnHidden(4, not is_auto)
        # 12 hàng tự giãn đều theo chiều cao còn lại của bảng (cả 2 chế độ)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def on_mode_changed(self, index):
        is_auto = (index == 0)
        self.log(f"🎛️ Chuyển sang chế độ {'TỰ ĐỘNG (AI)' if is_auto else 'THỦ CÔNG'}")
        self.stop_worker()                 # dừng worker cũ để tạo lại đúng chế độ
        self.update_mode_ui(is_auto)
        self.disable_confirm_buttons()
        self.reset_image_view()

        if is_auto:
            self.lbl_status.setText("🤖 Đã chuyển sang CHẾ ĐỘ TỰ ĐỘNG. Bấm '▶ BẮT ĐẦU'.")
        elif self.watch_folder:
            self.start_worker()            # Manual: tự chạy luôn, không có nút Start
        else:
            self.lbl_status.setText("🖐 CHẾ ĐỘ THỦ CÔNG: Vui lòng chọn 'Thư Mục X-Ray' để bắt đầu nhận ảnh.")

    # ==================================================================
    # STYLE NÚT XÁC NHẬN
    # ==================================================================
    def set_ng_button_style(self, active=False):
        self.btn_confirm_ng.setStyleSheet(styles.NG_BTN_ACTIVE if active else styles.NG_BTN_IDLE)

    def set_ok_button_style(self, active=False):
        self.btn_confirm_ok.setStyleSheet(styles.OK_BTN_ACTIVE if active else styles.OK_BTN_IDLE)

    def disable_confirm_buttons(self):
        self.btn_confirm_ok.setEnabled(False)
        self.btn_confirm_ng.setEnabled(False)
        self.set_ok_button_style(active=False)
        self.set_ng_button_style(active=False)

    def reset_image_view(self):
        self.image_view.clear_image(IMG_PLACEHOLDER)
        self.lbl_img_info.setText(IMG_INFO_EMPTY)

    # ==================================================================
    # CHỌN MODEL / THƯ MỤC / ROI
    # ==================================================================
    def select_model(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file Model AI", "", "Model AI (*.onnx *.pt)"
        )
        if file_path:
            self.model_path = file_path
            self.lbl_status.setText(f"✅ Đã chọn Model: {os.path.basename(file_path)}")
            self.log(f"✅ Chọn Model: {file_path}", "ok")

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục máy X-Ray gửi ảnh vào")
        if folder:
            self.watch_folder = folder
            self.lbl_status.setText(f"Thư mục X-Ray: {folder}")
            self.log(f"📂 Chọn thư mục X-Ray: {folder}")  
            if self.combo_mode.currentIndex() == 1:    # Manual: chọn xong là tự giám sát
                self.stop_worker()
                self.start_worker()

    def open_mic_void_config(self):
        if self.worker_thread and self.worker_thread.isRunning():
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Đang chạy", "Dừng AUTO trước khi thay đổi ngưỡng MIC Void.")
            return
        MicVoidDialog(self).exec_()

    def open_roi_config(self):
        if self.worker_thread and self.worker_thread.isRunning():
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Đang chạy", "Dừng giám sát trước khi thay đổi ROI / MARK / MIC Void.")
            return
        dialog = ROIConfigDialog(self)
        dialog.exec_()

    # ==================================================================
    # WORKER START / STOP
    # ==================================================================
    def toggle_monitoring(self):
        """Nút Start/Stop (chỉ hiện ở chế độ AUTO)."""
        if self.worker_thread and self.worker_thread.isRunning():
            self.stop_worker()
            self.lbl_status.setText("Trạng thái: Đã tạm dừng.")
            self.log("⏹ Tạm dừng giám sát", "warn")  
        else:
            self.start_worker()

    def start_worker(self):
        is_auto = (self.combo_mode.currentIndex() == 0)

        if not self.watch_folder:
            self.lbl_status.setText("❌ LỖI: Vui lòng chọn Thư mục X-Ray!")
            return False

        if is_auto and not self.model_path:
            self.lbl_status.setText("❌ LỖI: Chế độ Tự động yêu cầu phải chọn Model AI!")
            return False

        self.worker_thread = XRayWorkerThread(
            model_path=self.model_path,
            watch_folder=self.watch_folder,
            storage_root=config.STORAGE_ROOT,
            mode="AUTO" if is_auto else "MANUAL",
        )

        w = self.worker_thread
        w.image_processed.connect(self.on_image_processed)
        w.status_updated.connect(self.lbl_status.setText)
        w.batch_started.connect(self.on_batch_started)
        w.batch_completed.connect(self.on_batch_completed)
        w.ng_confirmation_required.connect(self.on_ng_confirmation_required)
        w.manual_batch_ready.connect(self.on_manual_batch_ready)
        w.log_message.connect(self.log) 
        w.start()
        self.log(f"▶ Bắt đầu giám sát - chế độ {'TỰ ĐỘNG' if is_auto else 'THỦ CÔNG'}, "
                 f"thư mục: {self.watch_folder}", "ok")     

        self.btn_start.setText(STOP_TEXT)
        self.btn_start.setStyleSheet(styles.STOP_BTN_STYLE)
        return True

    def stop_worker(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.stop()
            self.log("⏹ Đã dừng worker giám sát", "warn")
        self.worker_thread = None
        self.btn_start.setText(START_TEXT)
        self.btn_start.setStyleSheet(styles.START_BTN_STYLE)

    # ==================================================================
    # SỰ KIỆN TỪ WORKER
    # ==================================================================
    def on_batch_started(self, batch_id):
        self.lbl_status.setText(f"📦 Đang xử lý Phên hàng: {batch_id}")
        self.log(f"📦 Bắt đầu phên mới: {batch_id} - bắt đầu nhận và quét ảnh") 
        self.disable_confirm_buttons()

        self.batch_images.clear()
        self.pcb_results = new_pcb_results()

        for i in range(config.PCB_COUNT):
            for j in range(1, 5):
                item = QTableWidgetItem("CHỜ")
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(QColor("#16181f"))
                item.setForeground(QColor("#ffffff"))
                self.table.setItem(i, j, item)

    def on_ng_confirmation_required(self, batch_id):
        """Chế độ AUTO khi phát hiện NG: mở nút NG."""
        self.btn_confirm_ng.setEnabled(True)
        self.set_ng_button_style(active=True)
        self.lbl_status.setText(
            f"🔴 PHÊN {batch_id} BỊ NG! Lướt soi ảnh, rồi bấm 'XÁC NHẬN NG' để sang phên mới "
            f"(công nhân tự lấy phên NG ra)"
        )

    def on_manual_batch_ready(self, batch_id):
        """Chế độ MANUAL khi đủ ảnh: mở cả nút OK và NG."""
        self.btn_confirm_ok.setEnabled(True)
        self.btn_confirm_ng.setEnabled(True)
        self.set_ok_button_style(active=True)
        self.set_ng_button_style(active=True)
        self.lbl_status.setText(
            f"🖐 PHÊN {batch_id} ĐÃ ĐỦ {config.BATCH_SIZE} ẢNH! "
            f"Lướt kiểm tra ảnh & Bấm 'XÁC NHẬN OK' hoặc 'XÁC NHẬN NG'"
        )

    def on_confirm_ok_clicked(self,batch_id):
        """Công nhân bấm XÁC NHẬN OK (chế độ Manual)."""
        self.disable_confirm_buttons()
        self.lbl_status.setText("✅ XÁC NHẬN OK! Đang gửi lệnh gắp OK cho Dobot...")
        self.log("👷BẤM XÁC NHẬN OK", "ok")
        self.reset_image_view()
        #self.send_to_dobot(batch_id, config.CMD_PICK_OK)

        if self.worker_thread and self.worker_thread.mode == "MANUAL":
            self.worker_thread.set_manual_decision("OK")

    def on_confirm_ng_clicked(self):
        """Công nhân bấm XÁC NHẬN NG (chế độ Auto hoặc Manual)."""
        self.disable_confirm_buttons()
        self.lbl_status.setText("⚠️ XÁC NHẬN NG! Sang phên mới - hãy tự lấy phên NG ra.")
        self.log("👷 BẤM XÁC NHẬN NG - sang phên mới, tự lấy phên NG ra", "ng") 
        self.reset_image_view()

        if self.worker_thread:
            if self.worker_thread.mode == "AUTO":
                self.worker_thread.confirm_ng()
            else:
                self.worker_thread.set_manual_decision("NG")

    def on_batch_completed(self, batch_id, has_ng):
        """NG: công nhân tự lấy, không gửi gì cho Dobot.
        OK: vào hàng đợi, chỉ gửi lệnh gắp khi Dobot báo đã sẵn sàng."""
        if has_ng:
            self.total_ng += 1
            self.lbl_ng_count.setText(str(self.total_ng))
            self.log(f"❌ KẾT QUẢ PHÊN {batch_id}: NG (tổng NG: {self.total_ng}) "
                     f"- công nhân tự lấy, không gửi Dobot", "ng")  
            self.lbl_status.setText(
                f"🔴 PHÊN NG [{batch_id}]: Đã sang phên mới. Công nhân tự lấy phên NG ra "
                f"(không gửi lệnh cho Dobot).")
            return

        self.total_ok += 1
        self.lbl_ok_count.setText(str(self.total_ok))
        self.log(f"✅ KẾT QUẢ PHÊN {batch_id}: OK (tổng OK: {self.total_ok})", "ok") 
        self.pending_ok.append(batch_id)
        self.try_send_pending()
        if batch_id in self.pending_ok:        # chưa gửi được -> đang chờ Dobot
            self.lbl_status.setText(
                f"⏳ PHÊN OK [{batch_id}]: Chờ Dobot về vị trí sẵn sàng rồi mới gửi lệnh gắp...")
            self.log(f"⏳ Phên {batch_id} chờ Dobot sẵn sàng (hàng đợi: {len(self.pending_ok)})", "warn") 

    def try_send_pending(self):
        """Gửi lệnh gắp phên OK cũ nhất nếu Dobot đang SẴN SÀNG."""
        if not self.pending_ok or self.dobot_state != "READY":
            return
        batch_id = self.pending_ok[0]
        if self.dobot.send_signal(config.CMD_PICK_OK):  
            self.pending_ok.pop(0)
            self.dobot_state = "WAIT_ACK"
            self.log(f"🤝 Gửi lệnh gắp phên {batch_id}, chờ Dobot xác nhận (ACK)") 
            self.ack_deadline = time.monotonic() + config.DOBOT_ACK_TIMEOUT_S
            self.lbl_status.setText(
                f"🟢 PHÊN OK [{batch_id}]: Dobot đã sẵn sàng - đã gửi lệnh {config.CMD_PICK_OK}.")
        else:
            self.dobot_state = "BUSY"          # gửi lỗi: giữ phên trong hàng đợi, chờ Dobot kết nối lại

    def release_worker(self):
        if self.worker_thread:
            self.worker_thread.release_dobot_wait()

    def on_dobot_message(self, msg):
        if msg == config.DOBOT_MSG_READY:
            if self.dobot_state == "WAIT_ACK":
                self.log("⚠️ Bỏ qua DOBOT_READY cũ (đang chờ ACK lệnh gắp)", "warn") 
                return                         # READY cũ còn sót trong luồng -> bỏ qua, KHÔNG phản hồi
            if not self.dobot.send_signal(config.DOBOT_REPLY_READY):   # báo Dobot: PC đã nhận READY
                return                         # gửi lỗi = mất kết nối
            if self.dobot_state == "BUSY":
                self.dobot_state = "READY"
                self.log("🤖 Dobot SẴN SÀNG gắp", "ok")   
                self.try_send_pending()        # có phên OK đang chờ thì lệnh gắp được gửi NGAY SAU phản hồi
        elif msg == config.DOBOT_MSG_ACK:
            if self.dobot_state == "WAIT_ACK":
                self.dobot_state = "BUSY"      # Dobot đang gắp, chờ READY lần sau
                self.release_worker()
                self.log("🤖 Dobot đã nhận lệnh gắp (ACK) - đang gắp", "ok") 
        else:
            self.log(f"⚠️ Dobot gửi chuỗi không nhận ra: {msg!r}", "warn") 

    def poll_dobot(self):
        """Chạy mỗi DOBOT_POLL_MS: nhận kết nối, đọc tin từ Dobot, kiểm tra ACK quá hạn, cập nhật nhãn."""
        self.dobot.check_and_accept()
        for msg in self.dobot.poll_messages():
            self.on_dobot_message(msg)

        if not self.dobot.is_connected:
            self.dobot_state = "BUSY"          # mất kết nối: không biết Dobot đang ở đâu
        elif self.dobot_state == "WAIT_ACK" and time.monotonic() > self.ack_deadline:
            self.dobot_state = "BUSY"
            self.lbl_status.setText("⚠️ Dobot KHÔNG phản hồi ACK sau khi gửi lệnh gắp! Kiểm tra Dobot.")
            self.log(f"⚠️ Dobot KHÔNG phản hồi ACK sau {config.DOBOT_ACK_TIMEOUT_S}s - kiểm tra Dobot", "ng")
            self.release_worker() 
        self.refresh_dobot_label()

    def refresh_dobot_label(self):
        if not self.dobot.is_connected:
            text = f"Dobot MG400: Đang mở cổng {self.dobot.port} (Đang chờ Dobot kết nối...)"
            style = styles.DOBOT_WAIT_STYLE
        else:
            ip = self.dobot.client_address[0] if self.dobot.client_address else "Unknown"
            state_text = {
                "READY": "✅ SẴN SÀNG GẮP",
                "WAIT_ACK": "📨 Chờ Dobot xác nhận lệnh",
                "BUSY": "⏳ Đang bận / chưa về vị trí sẵn sàng",
            }[self.dobot_state]
            text = f"Dobot MG400 ({ip}): {state_text}"
            if self.pending_ok:
                text += f" | Phên OK chờ gắp: {len(self.pending_ok)}"
            style = styles.DOBOT_OK_STYLE if self.dobot_state == "READY" else styles.DOBOT_WAIT_STYLE
        self.lbl_dobot_status.setText(text)
        self.lbl_dobot_status.setStyleSheet(style)

    def on_image_processed(self, pcb_idx, pos_idx, pos_status, defect_info, frame, total_count):
        self.batch_images[(pcb_idx, pos_idx)] = {
            "frame": frame,
            "status": pos_status,
            "defect_info": defect_info,
            "total_count": total_count,
        }
        self.pcb_results[pcb_idx][f"Pos{pos_idx}"] = pos_status
        self.update_table_cell(pcb_idx - 1, pos_idx, pos_status)
        level = {"OK": "ok", "NG": "ng"}.get(pos_status, "info")              
        self.log(f"🖼️ Ảnh {total_count}/{config.BATCH_SIZE} | PCB #{pcb_idx} - Vị trí {pos_idx}: "
                 f"{pos_status} ({defect_info})", level)
        self.pcb_results[pcb_idx][f"Pos{pos_idx}"] = pos_status
        self.display_image_to_gui(
            frame,
            f"Ảnh {total_count}/{config.BATCH_SIZE} | PCB #{pcb_idx} - Pos {pos_idx} "
            f"| Trạng thái: {pos_status} ({defect_info})",
        )
        if self.combo_mode.currentIndex() == 0 and pos_idx == config.POSITIONS_PER_PCB:   # AUTO
            p_res = self.pcb_results[pcb_idx]
            all_ok = all(p_res[f"Pos{p}"] == "OK" for p in range(1, config.POSITIONS_PER_PCB + 1))
            final_status = "OK" if all_ok else "NG"

            p_res["Status"] = final_status
            self.update_table_cell(pcb_idx - 1, 4, final_status)

    # ==================================================================
    # HIỂN THỊ ẢNH / BẢNG
    # ==================================================================
    def display_image_to_gui(self, frame, text_info):
        self.image_view.set_frame(frame)
        self.lbl_img_info.setText(text_info)

    def on_current_cell_changed(self, current_row, current_col, previous_row, previous_col):
        if current_row < 0 or current_col < 0:
            return

        pcb_idx = current_row + 1

        if 1 <= current_col <= config.POSITIONS_PER_PCB:
            pos_idx = current_col
            key = (pcb_idx, pos_idx)
            if key in self.batch_images:
                d = self.batch_images[key]
                info_str = (
                    f"🔍 [SOI THỦ CÔNG] Ảnh {d['total_count']}/{config.BATCH_SIZE} | "
                    f"PCB #{pcb_idx} - Pos {pos_idx} | [{d['status']}] - {d['defect_info']}"
                )
                self.display_image_to_gui(d["frame"], info_str)
            else:
                self.lbl_img_info.setText(f"⚠️ Vị trí PCB #{pcb_idx} - Pos {pos_idx} chưa có dữ liệu ảnh!")

    def update_table_cell(self, row, col, text):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        if text == "OK":
            item.setBackground(QColor("#2ea44f"))
            item.setForeground(QColor("white"))
        elif text == "NG":
            item.setBackground(QColor("#f85149"))
            item.setForeground(QColor("white"))
        elif text == "ĐÃ NHẬN":
            item.setBackground(QColor("#1f3a5f"))
            item.setForeground(QColor("#4da6ff"))
        self.table.setItem(row, col, item)

    # ==================================================================
    # DOBOT
    # ==================================================================

    # ==================================================================
    def closeEvent(self, event):
        self.dobot_timer.stop()
        self.stop_worker()
        self.dobot.close()
        event.accept()
