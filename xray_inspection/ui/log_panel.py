"""Khung nhật ký hoạt động: hiện trên giao diện (có màu) và ghi file logs/xray_YYYYMMDD.log."""
import html
import os
from datetime import datetime

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

import config

LOG_DIR = os.path.join(config.BASE_DIR, "logs")
MAX_LINES = 5000          # chỉ giữ tối đa số dòng này trên màn hình (file log vẫn ghi đủ)

LEVEL_COLORS = {
    "info": "#c9d1d9",    # thông tin chung
    "ok":   "#3fb950",    # OK / thành công
    "ng":   "#f85149",    # NG / lỗi
    "warn": "#ffaa00",    # cảnh báo
    "tx":   "#58a6ff",    # PC -> Dobot
    "rx":   "#39d0d0",    # Dobot -> PC
}

class LogPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cardFrame")
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("📋 NHẬT KÝ HOẠT ĐỘNG")
        title.setFont(QFont("Arial", 10, QFont.Bold))
        title.setStyleSheet("color: #8f9ba8;")
        self.btn_clear = QPushButton("Xóa")
        self.btn_clear.setFixedWidth(10)
        self.btn_clear.setFixedHeight(10)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.btn_clear)
        layout.addLayout(header)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 9))
        self.view.document().setMaximumBlockCount(MAX_LINES)
        self.view.setStyleSheet("background-color: #0b0c0e; border: 1px solid #2d3342;")
        layout.addWidget(self.view, stretch=1)

        self.btn_clear.clicked.connect(self.view.clear)

    def log(self, text, level="info"):
        now = datetime.now()
        stamp = now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
        color = LEVEL_COLORS.get(level, LEVEL_COLORS["info"])
        self.view.append(
            f'<span style="color:#6e7681">{stamp}</span> '
            f'<span style="color:{color}">{html.escape(str(text))}</span>'
        )
        self._write_file(now, stamp, text)

    def _write_file(self, now, stamp, text):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            path = os.path.join(LOG_DIR, f"xray_{now:%Y%m%d}.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{now:%Y-%m-%d} {stamp} {text}\n")
        except OSError:
            pass