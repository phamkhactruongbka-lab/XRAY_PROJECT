"""Bắt lỗi mất IC trong ROI.

Có 2 cách bù lệch cơ khí (chọn bằng mark_align_enabled):
  - MARK  : tìm mark đặc trưng đã vẽ trên ảnh Golden (core/mark_alignment.py),
            dịch ROI theo độ lệch của mark. Nếu không tìm được mark -> báo lỗi căn chỉnh.
  - ECC   : tự căn chỉnh cả tấm ảnh với ảnh Golden (dịch + xoay), không cần vẽ mark.
"""
import os
import cv2
import numpy as np
from core.mark_alignment import AlignmentError, MarkAligner, draw_mark_alignment, read_image

class RobustSolderICChecker:
    def __init__(self, golden_template_path, base_roi, dark_threshold=115,
                 min_solder_ratio=0.05, mark_align_enabled=False, mark_roi=None,
                 mark_min_score=0.75, mark_search_margin=0,
                 min_blobs=0, max_shift=120, debug=False):
        self.base_roi = base_roi
        self.dark_threshold = dark_threshold
        self.min_solder_ratio = min_solder_ratio
        self.min_blobs = min_blobs        # số điểm hàn tối thiểu (0 = tắt)
        self.max_shift = max_shift        # dịch tối đa cho phép của ECC (px)
        self.debug = debug

        self.mark_align_enabled = bool(mark_align_enabled)
        self.mark_roi = tuple(mark_roi) if mark_roi else None
        self.aligner = None

        # Kết quả của lần kiểm tra gần nhất (worker đọc để hiển thị / quyết định NG)
        self.config_error = None     # lỗi cấu hình mark (nếu có)
        self.last_error = None       # lỗi căn chỉnh của ảnh vừa kiểm tra
        self.last_roi = None         # ROI đã dịch (x, y, w, h) theo toạ độ ảnh test
        self.last_alignment = None   # dict kết quả MarkAligner.locate()
        self.last_ratio = None       # tỷ lệ pixel tối trong ROI (lần kiểm tra gần nhất)
        self.last_blobs = None       # số điểm hàn trong ROI (chỉ tính khi min_blobs > 0)

        self.align_scale = 0.25
        self.golden_gray = None
        self.golden_small = None

        if golden_template_path and os.path.exists(golden_template_path):
            self.golden_gray = read_image(golden_template_path, cv2.IMREAD_GRAYSCALE)
            if self.golden_gray is not None:
                self.golden_small = self._prep(self.golden_gray)

        if self.mark_align_enabled:
            try:
                self.aligner = MarkAligner(self.golden_gray, self.mark_roi, self.base_roi,
                                           mark_min_score, mark_search_margin)
            except AlignmentError as e:
                self.config_error = str(e)

    # ------------------------------------------------------------------
    # Đánh giá 1 vùng ROI đã cắt: tỷ lệ pixel tối + số điểm hàn
    # ------------------------------------------------------------------
    def _evaluate(self, crop):
        dark_mask = (crop < self.dark_threshold).astype(np.uint8)
        total = crop.size
        solder_ratio = float(dark_mask.sum()) / total if total > 0 else 0.0

        blobs = 0
        if self.min_blobs > 0:
            dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN,
                                         np.ones((3, 3), np.uint8))
            _, _, stats, _ = cv2.connectedComponentsWithStats(dark_mask)
            blobs = int(np.sum(stats[1:, cv2.CC_STAT_AREA] >= 15))

        is_missing = solder_ratio < self.min_solder_ratio
        if self.min_blobs > 0 and blobs < self.min_blobs:
            is_missing = True
        self.last_ratio, self.last_blobs = solder_ratio, blobs
        return is_missing, solder_ratio, blobs

    # ------------------------------------------------------------------
    # API chính
    # ------------------------------------------------------------------
    def check_missing_ic(self, test_img_bgr):
        """Trả về (is_missing, [(x1, y1, x2, y2), ...]).
        Lỗi căn chỉnh không phải "mất IC": xem self.last_error."""
        self.last_error = None
        self.last_roi = None
        self.last_alignment = None
        self.last_ratio = None
        self.last_blobs = None

        if self.mark_align_enabled:
            return self._check_with_mark(test_img_bgr)
        return self._check_with_ecc(test_img_bgr)

    # ------------------------------------------------------------------
    # Cách 1: căn chỉnh theo MARK
    # ------------------------------------------------------------------
    def _check_with_mark(self, test_img_bgr):
        if self.aligner is None:
            self.last_error = self.config_error or "Chưa cấu hình căn chỉnh MARK."
            return False, []
        if test_img_bgr is None:
            self.last_error = "Không đọc được ảnh cần căn chỉnh."
            return False, []

        test_gray = (cv2.cvtColor(test_img_bgr, cv2.COLOR_BGR2GRAY)
                     if test_img_bgr.ndim == 3 else test_img_bgr)
        try:
            alignment = self.aligner.locate(test_gray)
        except AlignmentError as e:
            self.last_error = str(e)
            return False, []

        self.last_alignment = alignment
        self.last_roi = alignment["roi"]
        x, y, w, h = alignment["roi"]
        crop = test_gray[y:y + h, x:x + w]

        is_missing, ratio, blobs = self._evaluate(crop)
        if self.debug:
            print(f"[IC-MARK] offset={alignment['offset']} score={alignment['score']:.3f} "
                  f"ratio={ratio:.3f} blobs={blobs}")

        if is_missing:
            return True, [(x, y, x + w, y + h)]
        return False, []

    # ------------------------------------------------------------------
    # Cách 2: căn chỉnh ECC cả tấm ảnh
    # ------------------------------------------------------------------
    def _prep(self, gray):
        small = cv2.resize(gray, None, fx=self.align_scale, fy=self.align_scale,
                           interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(small, (5, 5), 0)

    def _estimate_warp(self, test_gray):
        """Ma trận 2x3 ánh xạ toạ độ ảnh golden -> toạ độ ảnh test (dịch + xoay)."""
        identity = np.eye(2, 3, dtype=np.float32)
        test_small = self._prep(test_gray)
        warp = np.eye(2, 3, dtype=np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5)
        try:
            _, warp = cv2.findTransformECC(
                self.golden_small, test_small, warp,
                cv2.MOTION_EUCLIDEAN, criteria, None, 5)
            warp[:, 2] /= self.align_scale
        except cv2.error:
            return identity, False

        if np.hypot(warp[0, 2], warp[1, 2]) > self.max_shift:
            return identity, False
        return warp, True

    def _check_with_ecc(self, test_img_bgr):
        if self.golden_gray is None or test_img_bgr is None:
            return False, []

        test_gray = cv2.cvtColor(test_img_bgr, cv2.COLOR_BGR2GRAY)
        gh, gw = self.golden_gray.shape
        if test_gray.shape != (gh, gw):
            test_gray = cv2.resize(test_gray, (gw, gh))

        warp, aligned_ok = self._estimate_warp(test_gray)

        # Kéo ảnh test về đúng khung của ảnh golden
        aligned = cv2.warpAffine(
            test_gray, warp, (gw, gh),
            flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)

        bx, by, bw, bh = self.base_roi
        crop = aligned[by:by + bh, bx:bx + bw]

        is_missing, ratio, blobs = self._evaluate(crop)
        if self.debug:
            print(f"[IC-ECC] align_ok={aligned_ok} dx={warp[0,2]:.1f} dy={warp[1,2]:.1f} "
                  f"ratio={ratio:.3f} blobs={blobs}")

        if is_missing:
            # Đổi ROI sang toạ độ ảnh test để vẽ khung đỏ đúng chỗ
            corners = np.array([[[bx, by], [bx + bw, by],
                                 [bx + bw, by + bh], [bx, by + bh]]], dtype=np.float32)
            moved = cv2.transform(corners, warp)[0]
            x, y, w, h = cv2.boundingRect(moved.astype(np.int32))
            return True, [(x, y, x + w, y + h)]

        return False, []


def annotate_ic_check(frame, checker, is_missing, boxes):
    """Vẽ kết quả kiểm tra IC lên ảnh BGR (dùng chung cho worker và nút "Thử ảnh").

    - Căn chỉnh MARK thành công: khung vàng ROI đã dịch + vị trí mark + độ lệch.
    - Căn chỉnh lỗi: dòng cảnh báo đỏ.
    - Mất IC: khung đỏ + chữ "NG: MISSING IC".
    """
    if checker.last_alignment:
        x, y, w, h = checker.last_roi
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 255), 2)
        draw_mark_alignment(frame, checker.last_alignment)
    elif checker.last_error:
        cv2.putText(frame, "NG: ALIGNMENT ERROR", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

    if is_missing:
        for (x1, y1, x2, y2) in boxes:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
            cv2.putText(frame, "NG: MISSING IC", (x1, max(y1 - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
