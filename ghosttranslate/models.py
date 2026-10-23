from dataclasses import dataclass

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor


# ==============================================================================
# СТРУКТУРЫ ДАННЫХ РАСПОЗНАННЫХ СЛОВ И КЛАСТЕРИЗОВАННЫХ БЛОКОВ
# ==============================================================================
@dataclass
class RawWordBox:
    x1: int
    y1: int
    x2: int
    y2: int
    text: str
    score: float
    lines_merged: int = 1
    split_from_bullet: bool = False

    @property
    def width(self) -> int:
        return max(1, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return float(max(1, self.y2 - self.y1))

    @property
    def area(self) -> int:
        return self.width * int(self.height)


@dataclass
class OverlayBlock:
    rect: QRect
    orig_text: str
    trans_text: str
    bg_color: QColor
    bg_color_right: QColor
    fg_color: QColor
    lines_merged: int = 1
    is_pending: bool = True
    # Показан исходный текст вместо перевода: повторить, когда модель будет готова.
    is_fallback: bool = False
