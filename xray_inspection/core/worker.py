"""Worker thread: giám sát thư mục X-Ray, xử lý ảnh (AI hoặc thủ công), gom thành phên."""
import os
import shutil
from datetime import datetime

import cv2
from ultralytics import YOLO
from PyQt5.QtCore import QThread, pyqtSignal

import config
from core.mic_void import (save_crop, append_measurement, VoidResult, MIC_CLASS_NAME,
                           evaluate_mic_voids, judge_mic, annotate_void,
                           get_aligned_mic_rois, is_box_in_rois)
import numpy as np
from core.ic_checker import RobustSolderICChecker, annotate_ic_check
from core.mark_alignment import read_image

class XRayWorkerThread(QThread):
    image_processed = pyqtSignal(int, int, str, str, object, int)
    status_updated = pyqtSignal(str)
    log_message = pyqtSignal(str, str)          
    batch_started = pyqtSignal(str)
    batch_completed = pyqtSignal(str, bool)
    ng_confirmation_required = pyqtSignal(str)
    manual_batch_ready = pyqtSignal(str)

    def __init__(self, model_path, watch_folder, storage_root=config.STORAGE_ROOT, mode="AUTO"):
        super().__init__()
        self.model_path = model_path
        self.watch_folder = watch_folder
        self.storage_root = storage_root
        self.mode = mode  # "AUTO" hoặc "MANUAL"
        self.is_running = True

        self.current_img_count = 0
        self.current_batch_id = ""
        self.current_batch_dir = None
        self.batch_has_ng = False
        self.waiting_for_ng_confirm = False
        self.waiting_for_manual_decision = False
        self.waiting_for_dobot = False   # phên OK: chờ Dobot nhận lệnh gắp rồi mới quét phên mới
        self.batch_sources = []          # đường dẫn ảnh gốc của phên hiện tại (chỉ xóa sau khi đủ ảnh)
        self.processed_names = set()     # tên ảnh đã nhận trong phên hiện tại (không quét lại)
        self.failed_deletes = {}         # tên -> đường dẫn: ảnh gốc xóa thất bại, sẽ thử xóa lại
        self.manual_decision = None  # "OK" hoặc "NG"

        cfg = config.load_config()
        mark_roi = cfg.get("mark_roi")
        self.ic_checker_pos1 = RobustSolderICChecker(
            golden_template_path=cfg.get("golden_path", ""),
            base_roi=tuple(cfg.get("pos1_roi", [200, 200, 150, 150])),
            dark_threshold=cfg.get("dark_threshold", 115),
            min_solder_ratio=cfg.get("min_solder_ratio", 0.05),
            mark_align_enabled=cfg.get("mark_align_enabled", False),
            mark_roi=tuple(mark_roi) if mark_roi else None,
            mark_min_score=cfg.get("mark_min_score", 0.75),
            mark_search_margin=cfg.get("mark_search_margin", 0),
            min_blobs=cfg.get("min_blobs", 0),
        )

    # ------------------------------------------------------------------
    # Tín hiệu từ giao diện
    # ------------------------------------------------------------------
    def confirm_ng(self):
        self.waiting_for_ng_confirm = False

    def set_manual_decision(self, decision):
        self.manual_decision = decision
        self.waiting_for_manual_decision = False

    def _log(self, text, level="info"):
        self.log_message.emit(text, level)

    def _delete_batch_sources(self):
        """Đủ ảnh của phên -> mới xóa các ảnh gốc của phên này khỏi thư mục X-Ray."""
        paths, self.batch_sources = self.batch_sources, []
        self.processed_names.clear()
        failed = 0
        for path in paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                failed += 1
                self.failed_deletes[os.path.basename(path)] = path     # giữ lại để không bị quét nhầm thành ảnh mới
                self._log(f"⚠️ Chưa xóa được {os.path.basename(path)}: {e} (sẽ thử lại)", "warn")
        self._log(f"🧹 Đã xóa {len(paths) - failed}/{len(paths)} ảnh gốc khỏi thư mục X-Ray",
                  "ok" if not failed else "warn")

    def _retry_failed_deletes(self):
        for name, path in list(self.failed_deletes.items()):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                continue
            del self.failed_deletes[name]
            self._log(f" Đã xóa được ảnh gốc {name} (lần thử lại)")

    def release_dobot_wait(self):
        """Giao diện gọi khi Dobot đã xác nhận (ACK) nhận lệnh gắp -> cho phép quét phên mới."""
        self.waiting_for_dobot = False

    def stop(self):
        self.is_running = False
        self.waiting_for_ng_confirm = False
        self.waiting_for_manual_decision = False
        self.waiting_for_dobot = False          
        self.wait()

    # ------------------------------------------------------------------
    # Quản lý phên
    # ------------------------------------------------------------------
    def create_new_batch(self):
        self.current_batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.current_batch_dir = os.path.join(self.storage_root, self.current_batch_id)
        self.batch_has_ng = False

        os.makedirs(os.path.join(self.current_batch_dir, "RAW"), exist_ok=True)
        os.makedirs(os.path.join(self.current_batch_dir, "DETECTED"), exist_ok=True)

        self.batch_started.emit(self.current_batch_id)

    # ------------------------------------------------------------------
    # Xử lý 1 ảnh
    # ------------------------------------------------------------------
    def _process_auto(self, model, dst_raw_path, file_name, pos_idx):
        self._log(f"Bắt đầu quét AI: {file_name}")
        """AUTO: YOLO + kiểm tra mất IC (Pos 1) + đo MIC void theo spec. Trả về (status, info, frame_rgb)."""
        # Đọc spec MIC mỗi ảnh -> thay đổi trong cửa sổ MIC Void có hiệu lực ngay ở ảnh tiếp theo
        mic_cfg = config.load_config()
        mic_threshold = float(mic_cfg.get('mic_void_threshold_percent', 10.0))
        mic_conf = float(mic_cfg.get('mic_void_confidence', .25))
        use_void_decision = bool(mic_cfg.get('mic_void_use_for_decision', True))

        img_bgr = read_image(dst_raw_path)

        # Căn chỉnh Mark MIC và lấy danh sách ROI MIC đã dịch
        mic_alignment_info = get_aligned_mic_rois(img_bgr, mic_cfg)
        aligned_mic_rois, mic_alignment, mic_align_err = mic_alignment_info

        # Phân loại ROI theo loại lỗi (tin_ball_mic_hole vs air_bubbles_mic)
        from core.mic_void import get_mic_roi_items, ROI_TYPE_TIN_BALL
        roi_items = get_mic_roi_items(mic_cfg)
        aligned_tin_ball_rois = [r for it, r in zip(roi_items, aligned_mic_rois) if it.get('type') == ROI_TYPE_TIN_BALL]
        target_tin_ball_rois = aligned_tin_ball_rois if aligned_tin_ball_rois else aligned_mic_rois

        # Chạy YOLO với conf thấp nhất cần dùng, sau đó lọc riêng từng lớp
        results = model.predict(source=dst_raw_path, conf=min(config.YOLO_CONF, mic_conf),
                                imgsz=config.YOLO_IMGSZ, verbose=False)
        result = results[0]

        other_idx, mic_idx = [], []
        ignored_tin_balls = 0
        for i, box in enumerate(result.boxes):
            cls_name = str(result.names[int(box.cls[0])])
            conf = float(box.conf[0])
            if cls_name == MIC_CLASS_NAME:
                if conf >= mic_conf:
                    mic_idx.append(i)
            elif cls_name == "tin_ball_mic_hole":
                if conf >= config.YOLO_CONF:
                    box_xyxy = box.xyxy[0].tolist()
                    if is_box_in_rois(box_xyxy, target_tin_ball_rois):
                        other_idx.append(i)
                        self._log(f"PHÁT HIỆN BI THIẾC LỖ MIC TRONG ROI (conf {conf:.2f}) -> NG", "error")
                    else:
                        ignored_tin_balls += 1
                        self._log(f"Bỏ qua tin_ball_mic_hole ngoài vùng ROI MIC (conf {conf:.2f} tại {box_xyxy})", "warn")
            elif conf >= config.YOLO_CONF:
                other_idx.append(i)

        # Ảnh hiển thị: lỗi khác vẽ bằng YOLO, MIC vẽ riêng kèm Void% + OK/NG theo spec
        if other_idx:
            annotated_frame = result[other_idx].plot()
        else:
            base = getattr(result, 'orig_img', None)
            annotated_frame = base.copy() if base is not None else (img_bgr.copy() if img_bgr is not None else read_image(dst_raw_path))

        has_missing_ic = False
        missing_boxes = []
        align_error = None
        if pos_idx == 1:
            if img_bgr is None:
                img_bgr = read_image(dst_raw_path)
            has_missing_ic, missing_boxes = self.ic_checker_pos1.check_missing_ic(img_bgr)
            align_error = self.ic_checker_pos1.last_error
            annotate_ic_check(annotated_frame, self.ic_checker_pos1, has_missing_ic, missing_boxes)

        # MIC void: đo % rỗ khí trong vùng hàn và so với ngưỡng spec
        void_notes = []
        void_results = []
        if mic_idx:
            img_for_void = img_bgr if img_bgr is not None else read_image(dst_raw_path)
            detections = [(result.boxes[i].xyxy[0].tolist(), float(result.boxes[i].conf[0])) for i in mic_idx]
            try:
                void_results = evaluate_mic_voids(img_for_void, detections, mic_cfg, precomputed=mic_alignment_info)
            except Exception as e:
                self._log(f'MIC Void REVIEW: {file_name}: {e}', 'warn')
                void_results = [VoidResult('REVIEW', None, f'Lỗi đo: {e}') for _ in detections]
            for k, ((xyxy, conf), measurement) in enumerate(zip(detections, void_results)):
                annotate_void(annotated_frame, xyxy, measurement, mic_threshold)
                try:
                    if img_for_void is not None and mic_cfg.get('mic_void_save_crop', True):
                        crop_file = os.path.join(self.current_batch_dir, 'MIC_VOID_CROPS',
                                                 f'{os.path.splitext(file_name)[0]}_box{mic_idx[k]}.png')
                        crop_box = xyxy
                        if measurement.aligned_roi and ('ROI:' in measurement.reason or 'ROI #' in measurement.reason):
                            x, y, w, h = measurement.aligned_roi
                            crop_box = [x, y, x+w, y+h]
                        save_crop(img_for_void, crop_box, crop_file)
                    if mic_cfg.get('mic_void_save_csv', True):
                        append_measurement(os.path.join(self.current_batch_dir, 'mic_void_results.csv'),
                                           self.current_batch_id, file_name, conf, measurement)
                except Exception as e:
                    self._log(f'MIC Void: lỗi lưu crop/CSV {file_name}: {e}', 'warn')
                label = f'{measurement.void_percent:.1f}%' if measurement.void_percent is not None else 'không đo được'
                th_used = getattr(measurement, 'applied_threshold', mic_threshold)
                void_notes.append(f'MIC Void {label} / ngưỡng {th_used:.1f}% → {measurement.status}')
                if measurement.alignment or measurement.status == 'REVIEW':
                    void_notes.append(measurement.reason)

        mic_ng = judge_mic(void_results, use_void_decision)
        other_has_defect = len(other_idx) > 0
        yolo_has_defect = other_has_defect or mic_ng
        # Không căn chỉnh được mark/ROI thì không thể kiểm tra IC -> coi là NG để người xem lại
        final_has_defect = yolo_has_defect or has_missing_ic or bool(align_error)
        pos_status = "NG" if final_has_defect else "OK"

        if final_has_defect:
            self.batch_has_ng = True

        detected_save_path = os.path.join(self.current_batch_dir, "DETECTED", f"detected_{file_name}")
        cv2.imwrite(detected_save_path, annotated_frame)

        frame_rgb = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)

        info_list = []
        if other_has_defect:
            defect_names = [str(result.names[int(result.boxes[i].cls[0])]) for i in other_idx]
            from collections import Counter
            counts = Counter(defect_names)
            details = ", ".join(f"{name}: {cnt}" for name, cnt in counts.items())
            info_list.append(f"YOLO: {len(other_idx)} lỗi ({details})")
        info_list.extend(void_notes)
        if has_missing_ic:
            info_list.append("OpenCV: Mất IC (Pos 1)")
        if align_error:
            info_list.append(f"Lỗi căn chỉnh/ROI: {align_error}")
        if final_has_defect:
            defect_info = " | ".join(info_list)
        elif void_notes:
            defect_info = "SẠCH (MIC trong spec) | " + " | ".join(void_notes)
        else:
            defect_info = "SẠCH (No Defect)"

        return pos_status, defect_info, frame_rgb

    def _process_manual(self, dst_raw_path, file_name):
        """MANUAL: không chạy AI, chỉ lưu và hiển thị ảnh."""
        img_bgr = cv2.imread(dst_raw_path)
        frame_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        detected_save_path = os.path.join(self.current_batch_dir, "DETECTED", f"raw_{file_name}")
        cv2.imwrite(detected_save_path, img_bgr)

        return "ĐÃ NHẬN", "Chờ công nhân soi thủ công", frame_rgb

    # ------------------------------------------------------------------
    # Kết thúc phên (đủ BATCH_SIZE ảnh). Trả về False nếu bị dừng giữa chừng.
    # ------------------------------------------------------------------
    def _finish_batch(self):
        """Đủ BATCH_SIZE ảnh. Thời điểm xóa ảnh gốc khỏi thư mục X-Ray:
        - AUTO, phên OK : xóa ngay (đã quét hết 36 ảnh).
        - AUTO, phên NG : chờ công nhân bấm XÁC NHẬN NG rồi mới xóa (giữ ảnh gốc làm bằng chứng).
        - MANUAL        : kết quả do công nhân quyết định, nên xóa sau khi công nhân bấm OK hoặc NG.
        Bị dừng giữa chừng thì KHÔNG xóa gì."""
        if self.mode == "AUTO":
            is_ng = self.batch_has_ng
            if not is_ng:
                self._log(f"📋 Phên {self.current_batch_id} đủ {config.BATCH_SIZE} ảnh, không phát hiện lỗi", "ok")
                self._delete_batch_sources()                  # OK: quét hết 36 ảnh là xóa
            else:
                self.status_updated.emit(f"🔴 PHÊN {self.current_batch_id} BỊ NG! CHỜ NGƯỜI BẤM 'XÁC NHẬN NG'...")
                self.ng_confirmation_required.emit(self.current_batch_id)
                self.waiting_for_ng_confirm = True

                while self.waiting_for_ng_confirm and self.is_running:
                    self.msleep(200)

                if not self.is_running:                       # bị dừng: giữ nguyên ảnh gốc, không gửi lệnh
                    return False
                self._delete_batch_sources()                  # NG: công nhân đã xác nhận mới xóa
        else:
            self.status_updated.emit(
                f"🖐 PHÊN {self.current_batch_id} ĐÃ ĐỦ {config.BATCH_SIZE} ẢNH. CHỜ CÔNG NHÂN BẤM XÁC NHẬN OK / NG...")
            self.manual_decision = None
            self.waiting_for_manual_decision = True
            self.manual_batch_ready.emit(self.current_batch_id)

            while self.waiting_for_manual_decision and self.is_running:
                self.msleep(200)

            if not self.is_running:
                return False
            is_ng = (self.manual_decision == "NG")
            self._delete_batch_sources()                      # công nhân đã quyết định (OK hoặc NG) mới xóa

        # Phên OK: bật cờ TRƯỚC khi báo cho giao diện, rồi đợi Dobot ACK mới quét phên mới.
        # Phên NG: công nhân tự lấy ra, sang phên mới ngay.
        if not is_ng:
            self.waiting_for_dobot = True
        self.batch_completed.emit(self.current_batch_id, is_ng)

        if not is_ng:
            self._log("⏳ Chờ Dobot nhận lệnh gắp rồi mới quét phên mới...", "warn")
            while self.waiting_for_dobot and self.is_running:
                self.msleep(100)
            if not self.is_running:
                return False
            self._log("▶ Dobot đã nhận lệnh gắp - tiếp tục quét phên mới")

        self.current_img_count = 0
        self.create_new_batch()
        return True
    # ------------------------------------------------------------------
    # Vòng lặp chính
    # ------------------------------------------------------------------
    def run(self):
        model = None
        if self.mode == "AUTO":
            try:
                self.status_updated.emit("⏳ Đang nạp Model AI ngầm...")
                model = YOLO(self.model_path, task="detect")
                self.status_updated.emit("🟢 [TỰ ĐỘNG] ĐANG GIÁM SÁT THƯ MỤC X-RAY...")
            except Exception as e:
                self.status_updated.emit(f"❌ Lỗi nạp model AI: {str(e)}")
                return
        else:
            self.status_updated.emit("🖐 [THỦ CÔNG] ĐANG GIÁM SÁT THƯ MỤC (NHẬN ẢNH THỦ CÔNG)...")

        self.create_new_batch()

        while self.is_running:
            if not os.path.exists(self.watch_folder):
                self.msleep(1500)
                continue

            try:
                self._retry_failed_deletes() 
                files = [f for f in os.listdir(self.watch_folder)
                        if f.lower().endswith(config.VALID_EXTENSIONS)
                        and f not in self.processed_names
                        and f not in self.failed_deletes] 
                files.sort(key=lambda x: os.path.getmtime(os.path.join(self.watch_folder, x)))
                
                for file_name in files:
                    if not self.is_running:
                        break

                    src_path = os.path.join(self.watch_folder, file_name)

                    # File rác của máy X-Ray (*_o.jpg): xóa
                    if file_name.lower().endswith("_o.jpg"):
                        try:
                            if self.is_file_ready(src_path):
                                os.remove(src_path)
                                self._log(f"Xóa file rác của máy X-Ray: {file_name}")   
                        except Exception as e:
                            print(f"Không thể xóa file rác {file_name}: {e}")
                        continue

                    if not self.is_file_ready(src_path):
                        continue

                    self.current_img_count += 1

                    dst_raw_path = os.path.join(self.current_batch_dir, "RAW", file_name)
                    shutil.copy2(src_path, dst_raw_path)        # SAO CHÉP: ảnh gốc vẫn nằm trong thư mục X-Ray
                    self.batch_sources.append(src_path)
                    self.processed_names.add(file_name)

                    pcb_idx = ((self.current_img_count - 1) // config.POSITIONS_PER_PCB) + 1
                    pos_idx = ((self.current_img_count - 1) % config.POSITIONS_PER_PCB) + 1
                    self._log(f"📥 Nhận ảnh {file_name} → ảnh {self.current_img_count}/{config.BATCH_SIZE} "
                              f"(PCB #{pcb_idx} - Vị trí {pos_idx})")      

                    if self.mode == "AUTO" and model is not None:
                        pos_status, defect_info, frame_rgb = self._process_auto(
                            model, dst_raw_path, file_name, pos_idx)
                    else:
                        pos_status, defect_info, frame_rgb = self._process_manual(
                            dst_raw_path, file_name)

                    self.image_processed.emit(
                        pcb_idx, pos_idx, pos_status, defect_info, frame_rgb, self.current_img_count)

                    self.msleep(100)

                    if self.current_img_count % config.BATCH_SIZE == 0:
                        if not self._finish_batch():
                            break

            except Exception as e:
                print(f"Lỗi tiến trình Worker: {e}")
                self._log(f"❌ Lỗi tiến trình Worker: {e}", "ng")  

            self.msleep(config.SCAN_INTERVAL_MS)

    def is_file_ready(self, filepath):
        if not os.path.exists(filepath):
            return False
        try:
            initial_size = os.path.getsize(filepath)
            if initial_size == 0:
                return False
            self.msleep(config.FILE_READY_WAIT_MS)
            current_size = os.path.getsize(filepath)
            if initial_size != current_size:
                return False
            with open(filepath, "r+b"):
                pass
            img = cv2.imread(filepath)
            if img is None or img.size == 0:
                return False
            return True
        except Exception:
            return False
