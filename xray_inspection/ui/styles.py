"""Toàn bộ giao diện màu sắc (QSS) và style của các nút. Muốn đổi màu chỉ sửa file này."""

INDUSTRIAL_DARK_QSS = """
QMainWindow {
    background-color: #121418;
}
QWidget {
    color: #e0e6ed;
    font-family: 'Segoe UI', Arial, sans-serif;
}
QFrame#cardFrame {
    background-color: #1e222b;
    border: 1px solid #2d3342;
    border-radius: 8px;
}
QTableWidget {
    background-color: #16181f;
    gridline-color: #2d3342;
    border: 1px solid #2d3342;
    border-radius: 6px;
    color: #ffffff;
    selection-background-color: #2b3345;
}
QHeaderView::section {
    background-color: #252b37;
    color: #9da8b6;
    padding: 8px;
    font-weight: bold;
    border: none;
    border-bottom: 2px solid #2d3342;
}
QPushButton {
    background-color: #2b313e;
    color: #e0e6ed;
    border: 1px solid #3d4556;
    border-radius: 6px;
    padding: 8px 12px;
    font-weight: 600;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #363e4f;
    border-color: #4f5b72;
}
QPushButton:pressed {
    background-color: #222731;
}
QComboBox {
    background-color: #121418;
    color: #4da6ff;
    font-weight: bold;
    padding: 6px;
    border: 1px solid #3d4556;
    border-radius: 6px;
}
QComboBox QAbstractItemView {
    background-color: #1e222b;
    color: #ffffff;
    selection-background-color: #2b3345;
}
"""

# ---------------- Nút Bắt đầu / Dừng giám sát ----------------
START_BTN_STYLE = "background-color: #2ea44f; color: white; font-weight: bold; font-size: 13px;"
STOP_BTN_STYLE = "background-color: #d73a49; color: white; font-weight: bold; font-size: 13px;"

# ---------------- Nút Cấu hình ROI ----------------
ROI_BTN_STYLE = "background-color: #1a4971; color: white;"

# ---------------- Nút XÁC NHẬN NG ----------------
NG_BTN_ACTIVE = """
QPushButton {
    background-color: #d32f2f;
    color: #ffffff;
    font-size: 14px;
    font-weight: bold;
    border: 2px solid #ff5252;
    border-radius: 6px;
}
QPushButton:hover {
    background-color: #f44336;
    border-color: #ff7961;
}
"""
NG_BTN_IDLE = """
QPushButton {
    background-color: #4a2326;
    color: #8a6468;
    font-size: 14px;
    font-weight: bold;
    border: 1px solid #5c2d31;
    border-radius: 6px;
}
"""

# ---------------- Nút XÁC NHẬN OK ----------------
OK_BTN_ACTIVE = """
QPushButton {
    background-color: #2ea44f;
    color: #ffffff;
    font-size: 14px;
    font-weight: bold;
    border: 2px solid #3fb950;
    border-radius: 6px;
}
QPushButton:hover {
    background-color: #3fb950;
}
"""
OK_BTN_IDLE = """
QPushButton {
    background-color: #1f3a2b;
    color: #5f7a6b;
    font-size: 14px;
    font-weight: bold;
    border: 1px solid #2d4a3a;
    border-radius: 6px;
}
"""

# ---------------- Nhãn trạng thái ----------------
STATUS_LABEL_STYLE = "color: #4da6ff; font-weight: bold; font-size: 11px;"
DOBOT_WAIT_STYLE = "color: #ffaa00; font-weight: bold; font-size: 11px;"
DOBOT_OK_STYLE = "color: #2ea44f; font-weight: bold; font-size: 11px;"
