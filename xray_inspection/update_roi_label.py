with open('ui/roi_label.py', 'r', encoding='utf-8') as f:
    code = f.read()

palette_def = '''# Bảng 10 màu rực rỡ riêng biệt cho tối đa 10 vùng ROI
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

'''

if 'ROI_PALETTE' not in code:
    code = code.replace('class ROISelectionLabel(QLabel):', palette_def + 'class ROISelectionLabel(QLabel):', 1)

# Add active_roi_idx
old_init = "self.current_mic_rois = []   # Danh sách tối đa 10 ROI MIC: list các [x,y,w,h]"
new_init = "self.current_mic_rois = []   # Danh sách tối đa 10 ROI MIC: list các [x,y,w,h] hoặc dict\n        self.active_roi_idx = 0"
if old_init in code:
    code = code.replace(old_init, new_init, 1)

# Update paintEvent for multi-color and tags
old_paint = """        if self.current_mic_rois:
            for idx, r in enumerate(self.current_mic_rois, start=1):
                rect = self.map_orig_roi_to_display(r)
                if rect:
                    draw_box(rect, self.MIC_COLOR, f"MIC #{idx}")
        elif self.current_mic:
            rect = self.map_orig_roi_to_display(self.current_mic)
            if rect:
                draw_box(rect, self.MIC_COLOR, "MIC VOID")

        if self.is_drawing:
            color = {"mark": self.MARK_COLOR, "mic": self.MIC_COLOR}.get(self.draw_target, self.ROI_COLOR)
            painter.setPen(QPen(QColor(*color), 2, Qt.DashLine))
            painter.drawRect(QRect(self.start_point, self.end_point).normalized())"""

new_paint = """        if self.current_mic_rois:
            for idx, item_data in enumerate(self.current_mic_rois, start=1):
                r = item_data['rect'] if isinstance(item_data, dict) else item_data[:4]
                t = item_data.get('type', 'air_bubbles_mic') if isinstance(item_data, dict) else (item_data[4] if len(item_data) > 4 else 'air_bubbles_mic')
                rect = self.map_orig_roi_to_display(r)
                if rect:
                    color = ROI_PALETTE[(idx - 1) % len(ROI_PALETTE)]
                    tag = "VOID" if t == 'air_bubbles_mic' else "TIN BALL"
                    draw_box(rect, color, f"#{idx} [{tag}]")
        elif self.current_mic:
            rect = self.map_orig_roi_to_display(self.current_mic)
            if rect:
                draw_box(rect, self.MIC_COLOR, "MIC VOID")

        if self.is_drawing:
            if self.draw_target == "mark":
                color = self.MARK_COLOR
            elif self.draw_target == "mic":
                idx = getattr(self, 'active_roi_idx', 0)
                color = ROI_PALETTE[idx % len(ROI_PALETTE)]
            else:
                color = self.ROI_COLOR
            painter.setPen(QPen(QColor(*color), 2, Qt.DashLine))
            painter.drawRect(QRect(self.start_point, self.end_point).normalized())"""

if old_paint in code:
    code = code.replace(old_paint, new_paint, 1)

with open('ui/roi_label.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Updated roi_label.py successfully")

