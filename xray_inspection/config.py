"""Cấu hình chung của project: hằng số + đọc/ghi file config_roi.json."""
import os
import json

import sys
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config_roi.json")

# ---------------- Lưu trữ ảnh ----------------
STORAGE_ROOT = r"C:/XRAY_STORAGE"

# ---------------- Dobot (TCP Server) ----------------
DOBOT_HOST = "0.0.0.0"
DOBOT_PORT = 12345
DOBOT_ALLOWED_IP_PREFIX = "192.168.2."
CMD_PICK_OK = "CMD_PICK_BATCH_OK"
CMD_PICK_NG = "CMD_PICK_BATCH_NG"
# --- Bắt tay 2 chiều với Dobot (mỗi tin kết thúc bằng "\n") ---
DOBOT_MSG_READY = "DOBOT_READY"       # Dobot -> PC: đã về vị trí sẵn sàng gắp, đang rảnh
DOBOT_MSG_ACK = "ACK_PICK_OK"         # Dobot -> PC: đã nhận lệnh gắp (phản hồi ngay)
DOBOT_ACK_TIMEOUT_S = 5               # quá thời gian này mà chưa có ACK thì cảnh báo
DOBOT_POLL_MS = 200                   # chu kỳ đọc tin từ Dobot
DOBOT_REPLY_READY = "PC_ACK_READY"    # PC -> Dobot: đã nhận DOBOT_READY (gửi trước lệnh gắp nếu có)

# ---------------- Phên hàng ----------------
PCB_COUNT = 12                                   # số PCB / phên
POSITIONS_PER_PCB = 3                            # số vị trí chụp / PCB
BATCH_SIZE = PCB_COUNT * POSITIONS_PER_PCB       # 36 ảnh / phên

# ---------------- Worker ----------------
VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif")
SCAN_INTERVAL_MS = 1000       # thời gian giữa 2 lần quét thư mục X-Ray
FILE_READY_WAIT_MS = 150      # thời gian chờ kiểm tra file đã ghi xong chưa
YOLO_CONF = 0.25
YOLO_IMGSZ = 1024

# ---------------- Cấu hình ROI / bắt lỗi mất IC ----------------
DEFAULT_CONFIG = {
    "mic_void_threshold_percent": 10.0,
    "mic_void_outside_threshold_percent": 20.0,  # Ngưỡng void riêng cho vết rỗ khí nằm ngoài ROI MIC
    "mic_void_confidence": 0.25,
    "mic_void_save_crop": True,
    "mic_void_save_csv": True,
    "mic_void_polarity": "bright",
    "mic_void_min_pixels": 5,      # vùng rỗ nhỏ hơn số pixel này bị bỏ qua (lọc nhiễu)
    "mic_void_use_for_decision": True,  # True: MIC NG chỉ khi Void% > ngưỡng; False: có phát hiện là NG
    "mic_void_roi": None,  # [x,y,w,h] (tương thích ngược 1 ROI)
    "mic_void_rois": [],   # Danh sách tối đa 10 ROI MIC [[x,y,w,h], ...]
    "mic_void_roi_min_overlap": 0.5,  # khung YOLO phải nằm >= 50% trong ROI MIC mới được tính
    "mic_void_golden_path": "",  # separate from the IC Golden
    "mic_void_mark_roi": None,
    "mic_void_mark_align_enabled": False,  # enabled automatically when drawing MIC MARK
    "mic_void_mark_min_score": 0.75,
    "mic_void_mark_search_margin": 0,
    "mic_void_validated": False,  # reserved: no automatic release based on experimental measurements
    "golden_path": "",
    "pos1_roi": [200, 200, 150, 150],
    "dark_threshold": 115,
    "min_solder_ratio": 0.05,
    "min_blobs": 0,          # số điểm hàn tối thiểu trong ROI (0 = tắt)
    # --- Căn chỉnh theo MARK (core/mark_alignment.py) ---
    "mark_align_enabled": False,   # True: ROI được dịch theo vị trí mark tìm thấy
    "mark_roi": None,              # [x, y, w, h] của mark trên ảnh Golden
    "mark_min_score": 0.75,        # điểm khớp tối thiểu (0 -> 1)
    "mark_search_margin": 0,       # phạm vi tìm mark quanh vị trí gốc (px), 0 = toàn ảnh
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"⚠️ Lỗi đọc file config: {e}")
    return cfg


def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"❌ Lỗi ghi file config: {e}")
        return False
