"""Пересчёт логических координат Qt в физические пиксели монитора."""

from typing import Dict, Iterable, Optional

import mss
import numpy as np
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QScreen


def open_mss():
    """mss 10 переименовал mss.mss в mss.MSS; requirements допускают и 9.x."""
    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


def screen_at_native_point(screens: Iterable[QScreen], x: int, y: int) -> Optional[QScreen]:
    """Экран по точке в физических пикселях, например центру окна из GetWindowRect."""
    point = QPoint(x, y)
    for screen in screens:
        if screen_native_rect(screen.geometry(), screen.devicePixelRatio()).contains(point):
            return screen
    return None


def crop_to_region(frame: np.ndarray, frame_region: Dict[str, int], region: Dict[str, int]) -> Optional[np.ndarray]:
    """Часть кадра frame (снятого по frame_region) под областью region, обе в пикселях монитора."""
    dx = region["left"] - frame_region["left"]
    dy = region["top"] - frame_region["top"]
    h, w = frame.shape[:2]
    if dx < 0 or dy < 0 or dx + region["width"] > w or dy + region["height"] > h:
        return None
    return frame[dy : dy + region["height"], dx : dx + region["width"]]


def screen_native_rect(geometry: QRect, dpr: float) -> QRect:
    """Прямоугольник экрана в физических пикселях.

    Qt 6 оставляет левый верхний угол QScreen.geometry() в физических пикселях
    и делит на devicePixelRatio только размер, поэтому угол на dpr не умножается.
    """
    dpr = max(1.0, float(dpr))
    return QRect(
        geometry.x(),
        geometry.y(),
        int(round(geometry.width() * dpr)),
        int(round(geometry.height() * dpr)),
    )


def native_capture_region(screen_geometry: QRect, dpr: float, local_rect: QRect) -> Dict[str, int]:
    """Область для mss по прямоугольнику в логических координатах внутри экрана."""
    dpr = max(1.0, float(dpr))
    native = screen_native_rect(screen_geometry, dpr)
    left = native.x() + int(round(local_rect.x() * dpr))
    top = native.y() + int(round(local_rect.y() * dpr))
    right = min(native.x() + native.width(), left + int(round(local_rect.width() * dpr)))
    bottom = min(native.y() + native.height(), top + int(round(local_rect.height() * dpr)))
    left = max(native.x(), left)
    top = max(native.y(), top)
    return {
        "left": left,
        "top": top,
        "width": max(20, right - left),
        "height": max(20, bottom - top),
    }
