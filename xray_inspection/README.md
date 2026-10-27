# Hệ thống soi X-Ray PCB

## Chạy
```
pip install -r requirements.txt
python main.py
```
Chạy bằng terminal (không dùng nút debug của VS Code) để thấy lỗi nếu có.

## Cấu trúc
```
xray_inspection/
├── main.py              # điểm khởi chạy
├── config.py            # hằng số (cổng Dobot, thư mục lưu, thời gian quét...) + đọc/ghi config_roi.json
├── core/                # xử lý, không có giao diện
│   ├── worker.py        # luồng giám sát thư mục, chạy AI, gom phên 36 ảnh
│   ├── ic_checker.py    # bắt lỗi mất IC: căn chỉnh (theo MARK hoặc ECC) rồi đếm điểm hàn trong ROI
│   ├── mark_alignment.py# tìm MARK trên ảnh, dịch ROI theo độ lệch; vẽ overlay vị trí mark
│   └── dobot_server.py  # TCP server gửi lệnh gắp OK/NG cho Dobot
├── ui/                  # giao diện PyQt5
│   ├── main_window.py   # cửa sổ chính
│   ├── roi_dialog.py    # cửa sổ cấu hình ROI + MARK + nút "Thử ảnh"
│   ├── roi_test_dialog.py # cửa sổ hiện kết quả thử ảnh
│   ├── roi_label.py     # ô vẽ ROI (đỏ) và MARK (xanh) bằng chuột
│   └── styles.py        # màu sắc, QSS, style các nút
├── tests/
│   ├── test_mark_alignment.py   # unit test thuật toán MARK, checker, worker, cửa sổ cấu hình
│   └── test_image_trial.py      # unit test nút "Thử ảnh"
├── requirements.txt
└── README.md
```

## Muốn sửa gì thì mở file nào
| Việc cần sửa | File |
|---|---|
| Thời gian quét thư mục, cổng/IP Dobot, thư mục lưu ảnh, số ảnh/phên, tên lệnh Dobot | `config.py` |
| Màu sắc nút, màu nền | `ui/styles.py` |
| Bố cục, chế độ AUTO/MANUAL, hành vi nút bấm | `ui/main_window.py` |
| Thuật toán bắt lỗi mất IC | `core/ic_checker.py` |
| Thuật toán tìm MARK, hình vẽ overlay mark | `core/mark_alignment.py` |
| Luồng xử lý ảnh, quy trình hết phên | `core/worker.py` |
| Số điểm hàn tối thiểu (`min_blobs`), điểm khớp mark tối thiểu (`mark_min_score`) | `config_roi.json` |

## File cần đặt trong thư mục này
- `best.onnx` hoặc `best.pt` (model AI, tự động nạp nếu có)
- `config_roi.json` (nếu đã có từ bản cũ thì copy vào đây; chưa có thì app tự tạo khi bấm Lưu cấu hình)

## Căn chỉnh theo MARK (bù lệch phên hàng)
1. Bấm **Cấu Hình ROI**, chọn ảnh Golden.
2. Ở ô "Đang vẽ" chọn **ROI kiểm tra IC** rồi kéo chuột vẽ khung đỏ quanh IC.
3. Đổi sang **MARK căn chỉnh** rồi vẽ khung xanh quanh một chi tiết **đặc trưng, duy nhất** trên PCB
   (không chọn vùng phẳng hoặc chi tiết lặp lại nhiều lần). Vẽ xong, ô "Bật căn chỉnh theo MARK" tự được tick.
4. "Phạm vi tìm mark": 0 = tìm trên toàn ảnh; đặt số px nếu muốn giới hạn quanh vị trí gốc.
5. Lưu cấu hình. Khi lưu, chương trình tự kiểm tra mark trên ảnh Golden và báo lỗi nếu mark bị trùng / ít chi tiết.

Khi chạy (chế độ AI, Vị trí 1): tìm mark -> dịch ROI theo độ lệch -> đếm điểm hàn trong ROI đã dịch.
Không tìm thấy mark tin cậy thì ảnh đó bị tính **NG** với thông báo "Lỗi căn chỉnh/ROI".
Không bật MARK thì dùng căn chỉnh ECC tự động như trước.

## Thử ảnh (không cần chạy cả hệ thống)
Trong **Cấu Hình ROI** bấm **🧪 THỬ ẢNH**, chọn một ảnh bất kỳ. Chương trình chạy kiểm tra mất IC bằng
**đúng các thông số đang chỉnh trên cửa sổ (chưa cần lưu)** và hiện kết quả:
- 🟢 OK / 🔴 NG: MẤT IC / ⚠️ LỖI CĂN CHỈNH (ngoài sản xuất sẽ bị tính NG)
- Ảnh có vẽ mark, ROI đã dịch, độ lệch dX/dY, điểm khớp mark, tỷ lệ pixel tối trong ROI
Chỉnh ROI/MARK/ngưỡng rồi bấm thử lại nhiều ảnh cho tới khi kết quả đúng, sau đó mới Lưu.
Nút này chỉ thử phần OpenCV (mất IC + căn chỉnh), không chạy model YOLO.

## Chạy test
```
python -m unittest discover -s tests -t . -v
```

## MIC Void trong ROI Setting — 26/10/2026

Cửa sổ **Cấu Hình ROI** có hai tab:

1. **ROI / MARK**: chọn Golden, chọn **ROI MIC Void** trong ô Đang vẽ rồi kéo vùng màu vàng. Vùng IC đỏ và MARK xanh được giữ riêng.
2. **MIC Void / Spec & thử ảnh**: chỉnh ngưỡng Void %, confidence MIC, số pixel nhỏ nhất, polarity, tọa độ ROI, cách phán định và lưu crop/CSV như cửa sổ MIC Void độc lập. Chọn ảnh thử để chạy YOLO; thay spec cập nhật phép đo trên các detection đã có.
3. **Lưu cấu hình** ghi chung ROI, MARK và MIC vào config_roi.json. **Hủy** bỏ thay đổi chưa lưu ở cả hai tab. ROI MIC nhập tay đồng bộ khung vàng; để trống giữ cơ chế dùng box YOLO hiện có. ROI được khai báo phải nằm trong Golden và ≥100 pixel diện tích.

Cần dừng giám sát trước khi mở ROI Setting để thay cấu hình. Nút MIC Void độc lập vẫn hoạt động. Model chọn ở màn hình chính được truyền vào tab thử MIC. Đây là tích hợp giao diện và cấu hình; thuật toán phân đoạn/phán định, worker và giao thức Dobot không được thay đổi. ROI MIC vẫn là một vùng tọa độ gốc dùng chung, chưa tự dịch theo MARK; phần trăm Void chưa được kiểm chứng như phép đo sản xuất.

Kiểm chứng: 21 test đạt (5 tích hợp mới, 8 MIC hiện có, 8 thử ảnh IC), Qt offscreen; đã render hai tab ở 1100×700. Log tại `tests/artifacts/roi-mic-tests.txt`, ảnh tại `tests/artifacts/roi-drawing.png` và `roi-mic-settings.png`. Chưa thử suy luận best.pt trên ảnh sản xuất, thao tác phần cứng hoặc Dobot trong lượt này. Test dùng cấu hình giả lập và ảnh tổng hợp, không sửa config_roi.json thực.
