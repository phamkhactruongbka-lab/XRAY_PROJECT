"""Locate a golden-image mark and translate an inspection ROI with it."""
import cv2
import numpy as np


class AlignmentError(ValueError):
    pass

def read_image(path, flags=cv2.IMREAD_COLOR):
    """OpenCV image loading that also supports Unicode Windows paths."""
    try:
        return cv2.imdecode(np.fromfile(path, dtype=np.uint8), flags)
    except (OSError, ValueError, cv2.error):
        return None


def valid_rect(rect, shape):
    if not isinstance(rect, (tuple, list)) or len(rect) != 4:
        return False
    if not all(isinstance(v, (int, np.integer)) for v in rect):
        return False
    x, y, w, h = rect
    return x >= 0 and y >= 0 and w > 5 and h > 5 and x + w <= shape[1] and y + h <= shape[0]


class MarkAligner:
    def __init__(self, golden_gray, mark_roi, inspection_roi, min_score=0.75, search_margin=0):
        if golden_gray is None:
            raise AlignmentError("Không đọc được ảnh Golden.")
        if not valid_rect(mark_roi, golden_gray.shape):
            raise AlignmentError("Hãy vẽ mark hợp lệ trên ảnh Golden.")
        if not valid_rect(inspection_roi, golden_gray.shape):
            raise AlignmentError("ROI kiểm tra nằm ngoài ảnh Golden hoặc quá nhỏ.")
        self.mark_roi = tuple(mark_roi)
        self.inspection_roi = tuple(inspection_roi)
        self.min_score = float(min_score)
        self.search_margin = int(search_margin)
        if not 0 < self.min_score <= 1 or self.search_margin < 0:
            raise AlignmentError("Ngưỡng mark hoặc phạm vi tìm kiếm không hợp lệ.")
        x, y, w, h = self.mark_roi
        self.template = golden_gray[y:y+h, x:x+w].copy()
        if np.std(self.template) < 5:
            raise AlignmentError("Mark ít chi tiết. Chọn vùng có cạnh/hình dạng đặc trưng.")

    def locate(self, gray):
        if gray is None or gray.ndim != 2:
            raise AlignmentError("Không đọc được ảnh cần căn chỉnh.")
        mx, my, mw, mh = self.mark_roi
        height, width = gray.shape
        if self.search_margin:
            m = self.search_margin
            sx, sy = max(0, mx-m), max(0, my-m)
            ex, ey = min(width, mx+mw+m), min(height, my+mh+m)
        else:
            sx, sy, ex, ey = 0, 0, width, height
        region = gray[sy:ey, sx:ex]
        if region.shape[0] < mh or region.shape[1] < mw:
            raise AlignmentError("Vùng tìm kiếm nhỏ hơn mark.")
        scores = cv2.matchTemplate(region, self.template, cv2.TM_CCOEFF_NORMED)
        scores = np.nan_to_num(scores, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, score, _, point = cv2.minMaxLoc(scores)
        if score < self.min_score:
            raise AlignmentError(f"Không tìm thấy mark tin cậy: {score:.3f} < {self.min_score:.3f}.")
        # Reject a second, spatially distinct match instead of guessing between repeated pads.
        px, py = point
        other = scores.copy()
        rx, ry = max(3, mw//2), max(3, mh//2)
        other[max(0, py-ry):py+ry+1, max(0, px-rx):px+rx+1] = -1
        second = float(other.max())
        if second >= self.min_score and score - second < 0.05:
            raise AlignmentError("Mark bị trùng/khó phân biệt. Chọn vùng đặc trưng hơn hoặc thu hẹp vùng tìm.")
        found_x, found_y = sx + px, sy + py
        dx, dy = found_x - mx, found_y - my
        bx, by, bw, bh = self.inspection_roi
        roi = (bx+dx, by+dy, bw, bh)
        if not valid_rect(roi, gray.shape):
            raise AlignmentError("Đã tìm được mark nhưng ROI suy ra nằm ngoài ảnh.")
        return {"roi": roi, "mark": (found_x, found_y, mw, mh),
                "master_center": (mx + mw / 2.0, my + mh / 2.0),
                "mark_center": (found_x + mw / 2.0, found_y + mh / 2.0),
                "offset": (dx, dy), "score": float(score)}

    def locate_offset(self, gray):
        """Chỉ tìm mark và trả về độ lệch (dx, dy) cùng thông tin alignment, không phụ thuộc inspection_roi."""
        if gray is None or gray.ndim != 2:
            raise AlignmentError("Không đọc được ảnh cần căn chỉnh.")
        mx, my, mw, mh = self.mark_roi
        height, width = gray.shape
        if self.search_margin:
            m = self.search_margin
            sx, sy = max(0, mx-m), max(0, my-m)
            ex, ey = min(width, mx+mw+m), min(height, my+mh+m)
        else:
            sx, sy, ex, ey = 0, 0, width, height
        region = gray[sy:ey, sx:ex]
        if region.shape[0] < mh or region.shape[1] < mw:
            raise AlignmentError("Vùng tìm kiếm nhỏ hơn mark.")
        scores = cv2.matchTemplate(region, self.template, cv2.TM_CCOEFF_NORMED)
        scores = np.nan_to_num(scores, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, score, _, point = cv2.minMaxLoc(scores)
        if score < self.min_score:
            raise AlignmentError(f"Không tìm thấy mark tin cậy: {score:.3f} < {self.min_score:.3f}.")
        px, py = point
        other = scores.copy()
        rx, ry = max(3, mw//2), max(3, mh//2)
        other[max(0, py-ry):py+ry+1, max(0, px-rx):px+rx+1] = -1
        second = float(other.max())
        if second >= self.min_score and score - second < 0.05:
            raise AlignmentError("Mark bị trùng/khó phân biệt. Chọn vùng đặc trưng hơn hoặc thu hẹp vùng tìm.")
        found_x, found_y = sx + px, sy + py
        dx, dy = found_x - mx, found_y - my
        return {"mark": (found_x, found_y, mw, mh),
                "master_center": (mx + mw / 2.0, my + mh / 2.0),
                "mark_center": (found_x + mw / 2.0, found_y + mh / 2.0),
                "offset": (dx, dy), "score": float(score)}


def draw_mark_alignment(frame, alignment):
    """Overlay geometric mark centers in original image coordinates (BGR)."""
    current_color, master_color = (170, 220, 0), (255, 170, 80)
    if 'mark' in alignment:
        x, y, w, h = alignment['mark']
        cv2.rectangle(frame, (x, y), (x+w, y+h), current_color, 2)
    cx, cy = alignment['mark_center']
    mx, my = alignment['master_center']
    dx, dy = alignment['offset']
    current = (int(round(cx)), int(round(cy)))
    master = (int(round(mx)), int(round(my)))
    if current != master:
        cv2.arrowedLine(frame, master, current, master_color, 2, cv2.LINE_AA, tipLength=0.2)
    cv2.drawMarker(frame, master, master_color, cv2.MARKER_DIAMOND, 16, 2, cv2.LINE_AA)
    cv2.drawMarker(frame, current, current_color, cv2.MARKER_CROSS, 14, 2, cv2.LINE_AA)
    lines = [
        (f"MASTER center: ({mx:.1f}, {my:.1f}) px", master_color),
        (f"MARK center: ({cx:.1f}, {cy:.1f}) px | score {alignment['score']:.3f}", current_color),
        (f"dX: {dx:+d} px   dY: {dy:+d} px  (+X right, +Y down)", (255, 255, 255)),
    ]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(0.2, min(0.65, frame.shape[1] / 1000.0))
    longest = max(cv2.getTextSize(text, font, scale, 1)[0][0] for text, _ in lines)
    if longest > frame.shape[1] - 20:
        scale *= max(1, frame.shape[1] - 20) / longest
    line_height = max(14, int(32 * scale))
    panel_width = max(cv2.getTextSize(text, font, scale, 1)[0][0] for text, _ in lines) + 16
    cv2.rectangle(frame, (3, 3), (min(frame.shape[1]-1, panel_width), 3*line_height+12), (20, 24, 28), -1)
    for i, (text, color) in enumerate(lines):
        cv2.putText(frame, text, (8, (i+1)*line_height+3), font, scale, color, 1, cv2.LINE_AA)
