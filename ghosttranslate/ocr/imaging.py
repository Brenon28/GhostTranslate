from typing import Tuple

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage


# ==============================================================================
# ЧИСТЫЙ NUMPY + QIMAGE БЕЗ OPENCV-PYTHON (cv2)
# ==============================================================================
def compute_small_gray_numpy(img_bgra: np.ndarray) -> np.ndarray:
    """
    Пункт 4.2 ТЗ v3.0: Сверхбыстрое уменьшение кадра для Watchdog 150ms на чистом NumPy
    без импорта тяжелого opencv-python (cv2):
    small_gray = np.mean(frame[::8, ::8, :3], axis=2)
    """
    return np.mean(img_bgra[::8, ::8, :3], axis=2).astype(np.float32)


def downscale_bgr_via_qimage(img_bgra: np.ndarray, scale: float) -> np.ndarray:
    """
    Масштабирование кадра для RapidOCR через встроенный QImage (без cv2).
    """
    h_orig, w_orig = img_bgra.shape[:2]
    new_w = max(64, int(round(w_orig * scale)))
    new_h = max(64, int(round(h_orig * scale)))
    try:
        contiguous = np.ascontiguousarray(img_bgra)
        qimg = QImage(
            contiguous.data,
            w_orig,
            h_orig,
            w_orig * 4,
            QImage.Format.Format_ARGB32,
        )
        scaled_qimg = qimg.scaled(
            new_w,
            new_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).convertToFormat(QImage.Format.Format_ARGB32)
        ptr = scaled_qimg.bits()
        ptr.setsize(new_h * new_w * 4)
        # Срез без копии шёл бы с шагом 4 байта, и RapidOCR на нём заметно медленнее.
        return np.frombuffer(ptr, dtype=np.uint8).reshape((new_h, new_w, 4))[:, :, :3].copy()
    except Exception:
        row_idx = np.linspace(0, h_orig - 1, new_h).astype(int)
        col_idx = np.linspace(0, w_orig - 1, new_w).astype(int)
        return np.ascontiguousarray(img_bgra[np.ix_(row_idx, col_idx)][:, :, :3])


def sample_word_background_and_fg(
    img_bgra: np.ndarray, x1: int, y1: int, x2: int, y2: int
) -> Tuple[QColor, QColor, QColor]:
    h_img, w_img = img_bgra.shape[:2]
    if h_img == 0 or w_img == 0:
        fallback_bg = QColor(20, 22, 28, 240)
        return fallback_bg, fallback_bg, QColor("#FFFFFF")

    x1_c = max(0, min(w_img - 1, x1))
    x2_c = max(x1_c + 1, min(w_img, x2))
    y1_c = max(0, min(h_img - 1, y1))
    y2_c = max(y1_c + 1, min(h_img, y2))

    crop = img_bgra[y1_c:y2_c, x1_c:x2_c, :3]  # BGR
    if crop.size == 0:
        fallback_bg = QColor(20, 22, 28, 240)
        return fallback_bg, fallback_bg, QColor("#FFFFFF")

    ch, cw = crop.shape[:2]
    bw = min(2, ch, cw)
    if bw > 0:
        border_pixels = [
            crop[:bw, :, :].reshape(-1, 3),
            crop[-bw:, :, :].reshape(-1, 3),
            crop[:, :bw, :].reshape(-1, 3),
            crop[:, -bw:, :].reshape(-1, 3),
        ]
        samples = np.concatenate(border_pixels, axis=0)
    else:
        samples = crop.reshape(-1, 3)

    if samples.size == 0:
        fallback_bg = QColor(20, 22, 28, 240)
        return fallback_bg, fallback_bg, QColor("#FFFFFF")

    med_bgr = np.median(samples, axis=0)
    b, g, r = int(med_bgr[0]), int(med_bgr[1]), int(med_bgr[2])

    mid_x = max(1, cw // 2)
    right_crop = crop[:, mid_x:, :]
    if right_crop.size > 0:
        med_right = np.median(right_crop.reshape(-1, 3), axis=0)
        br, gr, rr = int(med_right[0]), int(med_right[1]), int(med_right[2])
    else:
        br, gr, rr = b, g, r

    bg_left = QColor(r, g, b, 245)
    bg_right = QColor(rr, gr, br, 245)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    fg_color = QColor("#111111") if luminance > 140 else QColor("#FFFFFF")
    return bg_left, bg_right, fg_color
