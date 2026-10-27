with open('core/mic_void.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Define constants & palette at the top
top_defs = '''ROI_TYPE_VOID = 'air_bubbles_mic'
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
'''

if 'ROI_PALETTE' not in code:
    code = code.replace("def get_mic_rois(cfg):", top_defs + "\ndef get_mic_rois(cfg, target_type=None):", 1)

# Replace get_mic_rois body
old_get_mic_rois = """def get_mic_rois(cfg, target_type=None):
    \"\"\"Lấy danh sách tối đa 10 ROI MIC từ cấu hình.

    Hỗ trợ cả mic_void_rois (list các [x,y,w,h]) và mic_void_roi đơn lẻ (tương thích ngược).
    Trả về list các [x, y, w, h] hợp lệ (tối đa 10).
    \"\"\"
    rois = []
    cfg_rois = cfg.get('mic_void_rois')
    if isinstance(cfg_rois, list):
        for r in cfg_rois:
            if isinstance(r, (list, tuple)) and len(r) == 4:
                try:
                    vals = [int(v) for v in r]
                    if vals[0] >= 0 and vals[1] >= 0 and vals[2] > 0 and vals[3] > 0:
                        rois.append(vals)
                except (ValueError, TypeError):
                    pass
    if not rois:
        single_roi = cfg.get('mic_void_roi')
        if isinstance(single_roi, (list, tuple)) and len(single_roi) == 4:
            try:
                vals = [int(v) for v in single_roi]
                if vals[0] >= 0 and vals[1] >= 0 and vals[2] > 0 and vals[3] > 0:
                    rois.append(vals)
            except (ValueError, TypeError):
                pass
    return rois[:10]"""

new_get_mic_rois = """def get_mic_rois(cfg, target_type=None):
    \"\"\"Lấy danh sách tối đa 10 ROI MIC [x, y, w, h] từ cấu hình.
    Nếu target_type ('air_bubbles_mic' hoặc 'tin_ball_mic_hole') được chỉ định,
    chỉ trả về các ROI khớp với loại đó. Nếu không có ROI nào khớp -> fallback trả về tất cả.
    \"\"\"
    items = get_mic_roi_items(cfg)
    if target_type:
        filtered = [item['rect'] for item in items if item['type'] == target_type]
        if filtered:
            return filtered
    return [item['rect'] for item in items]"""

code = code.replace(old_get_mic_rois, new_get_mic_rois)

# Update get_aligned_mic_rois to support target_type and return items if needed
old_aligned = """def get_aligned_mic_rois(image_bgr, cfg):
    \"\"\"Lấy danh sách các ROI MIC đã được dịch chuyển theo MARK (nếu bật căn chỉnh MARK).

    Trả về tuple (aligned_rois, alignment_dict, error_msg).
    \"\"\"
    rois = get_mic_rois(cfg)
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
        return list(rois), None, f'MIC MARK: {exc}'"""

new_aligned = """def get_aligned_mic_rois(image_bgr, cfg, target_type=None):
    \"\"\"Lấy danh sách các ROI MIC đã được dịch chuyển theo MARK (nếu bật căn chỉnh MARK).

    Trả về tuple (aligned_rois, alignment_dict, error_msg).
    \"\"\"
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
        return list(rois), None, f'MIC MARK: {exc}'"""

code = code.replace(old_aligned, new_aligned)

# Update annotate_void to draw each ROI with its color from ROI_PALETTE
old_annotate = """    if result.alignment:
        draw_mark_alignment(frame_bgr, result.alignment)
        aligned_rois = result.alignment.get('rois')
        if aligned_rois:
            for r_i, (rx, ry, rw, rh) in enumerate(aligned_rois, start=1):
                cv2.rectangle(frame_bgr, (rx, ry), (rx+rw, ry+rh), (0, 190, 255), 2)
                cv2.putText(frame_bgr, f"ROI #{r_i}", (rx + 2, ry - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 190, 255), 1, cv2.LINE_AA)
        elif result.aligned_roi:
            x, y, w, h = result.aligned_roi
            cv2.rectangle(frame_bgr, (x, y), (x+w, y+h), (0, 190, 255), 2)"""

new_annotate = """    if result.alignment:
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
            cv2.rectangle(frame_bgr, (x, y), (x+w, y+h), (0, 190, 255), 2)"""

code = code.replace(old_annotate, new_annotate)

with open('core/mic_void.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Updated core/mic_void.py successfully")

