import os
import sys

# Pre-load torch DLLs when frozen to prevent WinError 1114 access violation
if getattr(sys, 'frozen', False):
    internal_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    torch_lib = os.path.join(internal_dir, 'torch', 'lib')
    if os.path.isdir(torch_lib):
        try:
            os.add_dll_directory(torch_lib)
        except Exception:
            pass
        os.environ['PATH'] = torch_lib + ';' + internal_dir + ';' + os.environ.get('PATH', '')

"""Điểm khởi chạy chương trình:  python main.py"""
import sys
import traceback
# In lỗi ra terminal thay vì để PyQt5 tự thoát im lặng
if sys.stderr is not None:
    import faulthandler
    faulthandler.enable()

def _excepthook(exc_type, exc, tb):
    traceback.print_exception(exc_type, exc, tb)
sys.excepthook = _excepthook

# QUAN TRỌNG: import ultralytics (torch) TRƯỚC PyQt5 để tránh xung đột DLL trên Windows
from ultralytics import YOLO  # noqa: F401,E402
from PyQt5.QtWidgets import QApplication  # noqa: E402
from ui.main_window import XRayInspectionApp  # noqa: E402

def main():
    app = QApplication(sys.argv)
    window = XRayInspectionApp()
    window.show()
    sys.exit(app.exec_())
    
if __name__ == "__main__":
    main()
