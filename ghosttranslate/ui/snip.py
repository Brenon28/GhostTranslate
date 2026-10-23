from typing import Optional

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QScreen
from PyQt6.QtWidgets import QWidget

from ..config import APP_VERSION


# ==============================================================================
# ОКНО ВЫДЕЛЕНИЯ ОБЛАСТИ ПО КЛАВИШЕ F9 (Обычной ЛКМ без зажатия модификаторов)
# ==============================================================================
SNIP_MIN_SIZE = 40
SNIP_HIDE_SETTLE_MS = 80


class SnipOverlay(QWidget):
    """Затемнение одного монитора на время выделения области.

    Окно само принимает мышь, поэтому протяжка не уходит в игру или браузер под ним.
    Прозрачные пиксели слоистого окна Windows пропускает насквозь, так что даже
    внутри рамки альфа-канал не опускается до нуля. Из снимка окно не исключается
    (растровое прозрачное окно этого не умеет), поэтому снимок делается после его скрытия.
    """

    region_selected = pyqtSignal(object, QRect)
    cancelled = pyqtSignal()

    def __init__(self, screen: QScreen):
        super().__init__()
        self.target_screen = screen
        self.setWindowTitle(f"GhostTranslate Snip v{APP_VERSION}")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._origin: Optional[QPoint] = None
        self._current: Optional[QPoint] = None
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

    def _selection(self) -> Optional[QRect]:
        if self._origin is None or self._current is None:
            return None
        return QRect(self._origin, self._current).normalized().intersected(self.rect())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(8, 10, 16, 90))
        sel = self._selection()
        if sel is None or sel.isEmpty():
            return
        painter.fillRect(sel, QColor(0, 0, 0, 1))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        pen = QPen(QColor(0, 229, 255, 235))
        pen.setWidthF(1.8)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(sel.adjusted(0, 0, -1, -1))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        self._current = event.position().toPoint()
        sel = self._selection()
        self._origin = None
        self._current = None
        self.update()
        if sel is not None and sel.width() > SNIP_MIN_SIZE and sel.height() > SNIP_MIN_SIZE:
            self.region_selected.emit(self.target_screen, sel)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)
