"""Experimental MIC void measurement. Requires validated solder ROI masks.

This is NOT a calibrated production acceptance test.
"""
from dataclasses import dataclass
from pathlib import Path
import csv
import cv2
import numpy as np
from core.mark_alignment import AlignmentError, MarkAligner, read_image, draw_mark_alignment

@dataclass
class VoidResult:
    status: str
    void_percent: float | None
    reason: str
    void_pixels: int = 0
    solder_pixels: int = 0
    aligned_roi: tuple | None = None
    alignment: dict | None = None
    applied_threshold: float = 10.0


ROI_TYPE_VOID = 'air_bubbles_mic'
ROI_TYPE_TIN_BALL = 'tin_ball_mic_hole'

ROI_PALETTE = [
    (255, 190, 40),   # ROI 1: Vàng hổ phách (Amber)
    (220, 40, 220),   # ROI 2: Tím hồng (Magenta)
    (0, 215, 255),    # ROI 3: Xanh Cyan
    (40, 215, 100),   # ROI 4: Xanh lá (Green)
    (255, 110, 30),   # ROI 5: Cam rực rỡ (Orange)
    (255, 80, 180),   # ROI 6: Hồng tươi (Pink)
    (60, 140, 255),   # ROI 7: Xanh lam (Sky Blue)
    (230, 230, 30),   # ROI 8: Vàng chanh (Lime)
    (150, 80, 255),   # ROI 9: Tím Violet
    (255, 60, 80),    # ROI 10: Đỏ Coral
]

def normalize_roi_item(item):
    """Chuẩn hóa một ROI về dict {'rect': [x, y, w, h], 'type': str} hoặc None."""
    if isinstance(item, dict):
        rect = item.get('rect') or item.get('roi')
        t = item.get('type', ROI_TYPE_VOID)
        if isinstance(rect, (list, tuple)) and len(rect) >= 4:
            try:
                vals = [int(v) for v in rect[:4]]
                if vals[0] >= 0 and vals[1] >= 0 and vals[2] > 0 and vals[3] > 0:
                    return {'rect': vals, 'type': str(t)}
            except (ValueError, TypeError):
                return None
    elif isinstance(item, (list, tuple)) and len(item) >= 4:
        try:
            vals = [int(v) for v in item[:4]]
            t = str(item[4]) if len(item) > 4 else ROI_TYPE_VOID
            if vals[0] >= 0 and vals[1] >= 0 and vals[2] > 0 and vals[3] > 0:
                return {'rect': vals, 'type': t}
        except (ValueError, TypeError):
            return None
    return None

def get_mic_roi_items(cfg):
    """Lấy danh sách các ROI MIC kèm type: list of {'rect': [x, y, w, h], 'type': str}."""
    items = []
    cfg_rois = cfg.get('mic_void_rois')
    if isinstance(cfg_rois, list):
        for r in cfg_rois:
            norm = normalize_roi_item(r)
            if norm:
                items.append(norm)
    if not items:
        single_roi = cfg.get('mic_void_roi')
        norm = normalize_roi_item(single_roi)
        if norm:
            items.append(norm)
    return items[:10]

def get_mic_rois(cfg, target_type=None):
    """Lấy danh sách tối đa 10 ROI MIC [x, y, w, h] từ cấu hình.
    Nếu target_type ('air_bubbles_mic' hoặc 'tin_ball_mic_hole') được chỉ định,
    chỉ trả về các ROI khớp với loại đó. Nếu không có ROI nào khớp -> fallback trả về tất cả.
    """
    items = get_mic_roi_items(cfg)
    if target_type:
        filtered = [item['rect'] for item in items if item['type'] == target_type]
        if filtered:
            return filtered
    return [item['rect'] for item in items]


def mic_aligner(cfg):
    """MIC uses its own Golden, MARK and ROI; never fall back to the IC task."""
    golden = read_image(cfg.get('mic_void_golden_path', ''), cv2.IMREAD_GRAYSCALE)
    rois = get_mic_rois(cfg)
    first_roi = rois[0] if rois else cfg.get('mic_void_roi')
    aligner = MarkAligner(golden, cfg.get('mic_void_mark_roi'), first_roi,
                          cfg.get('mic_void_mark_min_score', .75),
                          cfg.get('mic_void_mark_search_margin', 0))
    return golden, aligner


def validate_mic_task(cfg):
    """Validate only the MIC task, independently of IC configuration."""
    path = cfg.get('mic_void_golden_path', '')
    rois = get_mic_rois(cfg)
    if cfg.get('mic_void_mark_align_enabled', False):
        golden, aligner = mic_aligner(cfg)
        aligner.locate(golden)
    elif rois:
        golden = read_image(path, cv2.IMREAD_GRAYSCALE)
        if golden is None:
            raise ValueError('Chọn ảnh Golden riêng cho MIC trước khi lưu ROI MIC.')
        for idx, r in enumerate(rois, start=1):
            mask, _ = build_solder_mask(golden.shape, r)
            if mask is None:
                raise ValueError(f'ROI MIC #{idx} nằm ngoài ảnh Golden MIC.')
            if r[2] * r[3] < 100:
                raise ValueError(f'ROI MIC #{idx} cần ít nhất 100 pixel diện tích.')


def measure_void(image_bgr, solder_mask, threshold_percent=10.0,
                 min_void_pixels=5, polarity='bright'):
    """Measure voids inside a validated solder-region mask.

    solder_mask must be uint8 or bool, same height/width as image.
    `polarity` depends on actual X-ray image acquisition settings.
    """
    if image_bgr is None or solder_mask is None:
        return VoidResult('REVIEW', None, 'Missing image or solder ROI mask')
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3 or solder_mask.shape != image_bgr.shape[:2]:
        return VoidResult('REVIEW', None, 'Invalid image/mask dimensions')
    mask = (solder_mask > 0).astype(np.uint8)
    solder_pixels = int(mask.sum())
    if solder_pixels < 100:
        return VoidResult('REVIEW', None, 'Solder ROI too small or missing')
    if not (0 <= threshold_percent <= 100) or polarity not in ('bright', 'dark'):
        return VoidResult('REVIEW', None, 'Invalid configuration')
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    values = gray[mask > 0]
    if values.std() < 3:
        return VoidResult('REVIEW', None, 'Insufficient image contrast', solder_pixels=solder_pixels)
    otsu, _ = cv2.threshold(values.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # THRESH_BINARY của Otsu: pixel > otsu là "sáng". Dùng '>=' sẽ tính luôn mức xám
    # của chính vùng hàn là void (Void% ~ 100%, spec không còn tác dụng).
    candidate = (gray > otsu) if polarity == 'bright' else (gray <= otsu)
    candidate = (candidate & (mask > 0)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
    void_mask = np.zeros_like(mask)
    for i in range(1, count):
        if stats[i, cv2.CC_STAT_AREA] >= min_void_pixels:
            void_mask[labels == i] = 1
    void_pixels = int(void_mask.sum())
    percent = 100.0 * void_pixels / solder_pixels
    return VoidResult('NG' if percent > threshold_percent else 'OK',
                      round(percent, 2), 'Experimental segmentation; verify manually',
                      void_pixels, solder_pixels)


MIC_CLASS_NAME = 'air_bubbles_mic'


def build_solder_mask(image_shape, roi=None, box_xyxy=None, padding=4):
    """Vùng hàn để đo void.

    - Có ROI hợp lệ ([x, y, w, h] trên ảnh gốc) -> dùng ROI.
    - Không có ROI -> dùng khung YOLO (nới thêm `padding` px) của vết rỗ khí.
    Trả về (mask, nguồn) hoặc (None, lý do).
    """
    h, w = image_shape[:2]
    if roi and len(roi) == 4:
        x, y, rw, rh = map(int, roi)
        if x >= 0 and y >= 0 and rw > 0 and rh > 0 and x + rw <= w and y + rh <= h:
            mask = np.zeros((h, w), dtype=np.uint8)
            mask[y:y + rh, x:x + rw] = 255
            return mask, 'ROI'
        return None, 'ROI nằm ngoài ảnh'
    if box_xyxy is not None:
        x1, y1, x2, y2 = map(int, box_xyxy)
        x1, y1 = max(0, x1 - padding), max(0, y1 - padding)
        x2, y2 = min(w, x2 + padding), min(h, y2 + padding)
        if x2 > x1 and y2 > y1:
            mask = np.zeros((h, w), dtype=np.uint8)
            mask[y1:y2, x1:x2] = 255
            return mask, 'BOX'
    return None, 'Không có ROI / khung YOLO'


def box_overlap_ratio(box_xyxy, roi):
    """Tỉ lệ diện tích khung YOLO nằm trong ROI [x, y, w, h] (0 -> 1)."""
    x1, y1, x2, y2 = map(float, box_xyxy)
    rx, ry, rw, rh = map(float, roi)
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if area <= 0:
        return 0.0
    iw = max(0.0, min(x2, rx + rw) - max(x1, rx))
    ih = max(0.0, min(y2, ry + rh) - max(y1, ry))
    return iw * ih / area


def is_box_in_rois(box_xyxy, rois, min_overlap=0.3):
    """Kiểm tra xem khung YOLO box_xyxy có nằm trong bất kỳ ROI [x, y, w, h] nào không.

    - Nếu chưa cài đặt ROI nào -> coi như hợp lệ (không lọc).
    - Nếu đã có ROI -> kiểm tra tâm box nằm trong ROI hoặc tỷ lệ overlap >= min_overlap.
    """
    if not rois:
        return True
    x1, y1, x2, y2 = map(float, box_xyxy)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    for rx, ry, rw, rh in rois:
        if rx <= cx <= rx + rw and ry <= cy <= ry + rh:
            return True
        if box_overlap_ratio(box_xyxy, (rx, ry, rw, rh)) >= min_overlap:
            return True
    return False


def get_aligned_mic_rois(image_bgr, cfg, target_type=None):
    """Lấy danh sách các ROI MIC đã được dịch chuyển theo MARK (nếu bật căn chỉnh MARK).

    Trả về tuple (aligned_rois, alignment_dict, error_msg).
    """
    rois = get_mic_rois(cfg, target_type=target_type)
    if not rois:
        return [], None, None
    if not cfg.get('mic_void_mark_align_enabled', False):
        return list(rois), None, None

    try:
        golden, aligner = mic_aligner(cfg)
        if image_bgr is None or image_bgr.shape[:2] != golden.shape:
            return list(rois), None, 'Ảnh thử MIC phải cùng kích thước Golden MIC.'
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if image_bgr.ndim == 3 else image_bgr
        align_res = aligner.locate_offset(gray)
        dx, dy = align_res['offset']
        h_img, w_img = image_bgr.shape[:2]
        shifted_rois = []
        for rx, ry, rw, rh in rois:
            s_roi = (rx + dx, ry + dy, rw, rh)
            if not (0 <= s_roi[0] and 0 <= s_roi[1] and s_roi[0] + s_roi[2] <= w_img and s_roi[1] + s_roi[3] <= h_img):
                return list(rois), None, 'Đã tìm được mark nhưng có ROI MIC suy ra nằm ngoài ảnh.'
            shifted_rois.append(s_roi)
        align_res['rois'] = shifted_rois
        if shifted_rois:
            align_res['roi'] = shifted_rois[0]
        return shifted_rois, align_res, None
    except (AlignmentError, ValueError, TypeError, cv2.error) as exc:
        return list(rois), None, f'MIC MARK: {exc}'


def evaluate_mic_voids(image_bgr, detections, cfg, precomputed=None):
    """Đo void cho từng khung YOLO 'air_bubbles_mic' theo spec hiện tại.

    Hỗ trợ đa ROI MIC (tối đa 10 vùng ROI).
    - Khung nằm trong bất kỳ ROI nào -> đo theo spec vùng ROI (mic_void_threshold_percent).
    - Khung nằm ngoài tất cả các ROI -> đo riêng trong khung theo spec ngoài ROI (mic_void_outside_threshold_percent).
    Trả về list[VoidResult] cùng thứ tự với detections.
    """
    threshold_in = float(cfg.get('mic_void_threshold_percent', 10.0))
    threshold_out = float(cfg.get('mic_void_outside_threshold_percent', threshold_in))
    polarity = cfg.get('mic_void_polarity', 'bright')
    min_pixels = int(cfg.get('mic_void_min_pixels', 5))
    min_overlap = float(cfg.get('mic_void_roi_min_overlap', 0.5))

    if precomputed is not None:
        aligned_rois, alignment, err = precomputed
    elif detections and cfg.get('mic_void_mark_align_enabled', False):
        aligned_rois, alignment, err = get_aligned_mic_rois(image_bgr, cfg)
    else:
        aligned_rois, alignment, err = get_mic_rois(cfg), None, None

    if err:
        return [VoidResult('REVIEW', None, err) for _ in detections]

    has_rois = bool(aligned_rois)
    roi_masks = []
    if has_rois and image_bgr is not None:
        for idx, r in enumerate(aligned_rois):
            m, src = build_solder_mask(image_bgr.shape, r)
            if m is None:
                return [VoidResult('REVIEW', None, f'ROI #{idx+1} {src}') for _ in detections]
            roi_masks.append((m, src, r))

    roi_cached_results = {}  # index -> VoidResult
    results = []

    for xyxy, _conf in detections:
        if image_bgr is None:
            results.append(VoidResult('REVIEW', None, 'Không đọc được ảnh'))
            continue

        matched_roi_idx = None
        if has_rois:
            for r_idx, (_, _, r_geom) in enumerate(roi_masks):
                overlap = box_overlap_ratio(xyxy, r_geom)
                if overlap >= min_overlap:
                    matched_roi_idx = r_idx
                    break

        if matched_roi_idx is not None:
            # Khung nằm trong ROI #{matched_roi_idx + 1}: đo void trên ROI này
            if matched_roi_idx not in roi_cached_results:
                r_mask, r_src, r_geom = roi_masks[matched_roi_idx]
                r_res = measure_void(image_bgr, r_mask, threshold_in, min_pixels, polarity)
                r_res.reason = f'{r_src} #{matched_roi_idx + 1}: {r_res.reason}'
                roi_cached_results[matched_roi_idx] = r_res

            cached = roi_cached_results[matched_roi_idx]
            res = VoidResult(cached.status, cached.void_percent, cached.reason,
                             cached.void_pixels, cached.solder_pixels,
                             aligned_roi=tuple(roi_masks[matched_roi_idx][2]),
                             applied_threshold=threshold_in)
        else:
            # Khung nằm ngoài tất cả các ROI MIC: đo void trực tiếp ngay trong khung YOLO với Spec Ngoài ROI
            box_mask, box_src = build_solder_mask(image_bgr.shape, None, xyxy)
            if box_mask is None:
                res = VoidResult('REVIEW', None, box_src, applied_threshold=threshold_out)
            else:
                res = measure_void(image_bgr, box_mask, threshold_out, min_pixels, polarity)
                tag = 'ngoài ROI' if has_rois else 'không có ROI'
                res.reason = f'{box_src} ({tag}): {res.reason}'
                res.applied_threshold = threshold_out

        if alignment:
            res.alignment = alignment
            if res.aligned_roi:
                res.reason = f"MIC MARK dX={alignment['offset'][0]}, dY={alignment['offset'][1]}, score={alignment['score']:.3f}, ROI={res.aligned_roi}: {res.reason}"
            else:
                res.reason = f"MIC MARK dX={alignment['offset'][0]}, dY={alignment['offset'][1]}, score={alignment['score']:.3f}: {res.reason}"

        results.append(res)

    return results


def judge_mic(void_results, use_void_decision):
    """True = MIC NG.

    - use_void_decision=False: có bất kỳ phát hiện MIC nào -> NG (an toàn, như cũ).
    - use_void_decision=True : chỉ NG khi Void% > ngưỡng; không đo được (REVIEW) -> NG.
    """
    if not void_results:
        return False
    if not use_void_decision:
        return True
    return any(r.status != 'OK' for r in void_results)


def annotate_void(frame_bgr, box_xyxy, result, threshold=None):
    """Vẽ khung + Void% lên ảnh hiển thị (xanh = OK, đỏ = NG, cam = REVIEW)."""
    if result.alignment:
        draw_mark_alignment(frame_bgr, result.alignment)
        aligned_rois = result.alignment.get('rois')
        if aligned_rois:
            for r_i, r_data in enumerate(aligned_rois, start=1):
                rx, ry, rw, rh = r_data['rect'] if isinstance(r_data, dict) else r_data[:4]
                t = r_data.get('type', ROI_TYPE_VOID) if isinstance(r_data, dict) else (r_data[4] if len(r_data) > 4 else ROI_TYPE_VOID)
                rgb = ROI_PALETTE[(r_i - 1) % len(ROI_PALETTE)]
                bgr = (rgb[2], rgb[1], rgb[0])
                tag = 'VOID' if t == ROI_TYPE_VOID else 'TIN BALL'
                cv2.rectangle(frame_bgr, (rx, ry), (rx+rw, ry+rh), bgr, 2)
                cv2.putText(frame_bgr, f"#{r_i} [{tag}]", (rx + 2, max(ry - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, bgr, 1, cv2.LINE_AA)
        elif result.aligned_roi:
            x, y, w, h = result.aligned_roi
            cv2.rectangle(frame_bgr, (x, y), (x+w, y+h), (0, 190, 255), 2)
    colors = {'OK': (0, 200, 0), 'NG': (0, 0, 255)}
    color = colors.get(result.status, (0, 165, 255))
    x1, y1, x2, y2 = map(int, box_xyxy)
    cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), color, 2)
    th_val = getattr(result, 'applied_threshold', threshold)
    if th_val is None:
        th_val = threshold if threshold is not None else 10.0
    if result.void_percent is not None:
        text = f'{result.status} void {result.void_percent:.1f}% / {th_val:.1f}%'
    else:
        text = 'REVIEW (khong do duoc)'
    scale = max(0.5, frame_bgr.shape[1] / 1600)
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    ty = y2 + th + 6 if y1 - th - 6 < 0 else y1 - 6
    cv2.rectangle(frame_bgr, (x1, ty - th - 4), (x1 + tw + 4, ty + base), color, -1)
    cv2.putText(frame_bgr, text, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, scale,
                (255, 255, 255), 2, cv2.LINE_AA)
    scale = max(0.5, frame_bgr.shape[1] / 1600)
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    ty = y2 + th + 6 if y1 - th - 6 < 0 else y1 - 6
    cv2.rectangle(frame_bgr, (x1, ty - th - 4), (x1 + tw + 4, ty + base), color, -1)
    cv2.putText(frame_bgr, text, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, scale,
                (255, 255, 255), 2, cv2.LINE_AA)


def save_crop(image_bgr, box_xyxy, output_path, padding=12):
    h, w = image_bgr.shape[:2]
    x1, y1, x2, y2 = map(int, box_xyxy)
    x1, y1, x2, y2 = max(0, x1-padding), max(0, y1-padding), min(w, x2+padding), min(h, y2+padding)
    if x2 <= x1 or y2 <= y1:
        raise ValueError('Invalid detection box')
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image_bgr[y1:y2, x1:x2]):
        raise IOError(f'Could not save crop: {path}')
    return path


def append_measurement(csv_path, batch_id, filename, confidence, result):
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open('a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(['batch_id','filename','class','confidence','void_percent','status','reason'])
        writer.writerow([batch_id, filename, 'air_bubbles_mic', confidence,
                         result.void_percent, result.status, result.reason])
