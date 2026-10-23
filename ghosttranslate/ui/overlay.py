from typing import TYPE_CHECKING, List, Optional

import win32con
import win32gui
from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QScreen,
    QSurfaceFormat,
)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..config import APP_VERSION
from ..models import OverlayBlock
from ..settings import FontCustomConfig
from ..win32 import exclude_from_capture
from .plaque_layout import layout_blocks, wrap_lines

if TYPE_CHECKING:
    from ..controller import GhostTranslateController


# ==============================================================================
# ОТРИСОВКА ПЛАШЕК ПЕРЕВОДА (6 СТИЛЕЙ, EXACT MENU ALIGN)
# ==============================================================================
def paint_overlay_blocks(
    painter: QPainter,
    blocks: List[OverlayBlock],
    font_cfg: FontCustomConfig,
    style_mode: str,
    bounds: Optional[QRect] = None,
) -> None:
    if bounds is None:
        device = painter.device()
        bounds = QRect(0, 0, device.width(), device.height())

    for lay in layout_blocks(blocks, font_cfg, style_mode, bounds):
        block = lay.block
        if block.is_pending:
            painter.setPen(QPen(QColor(168, 85, 247, 190), 1.0))
            painter.setBrush(QColor(138, 92, 245, 95))
            painter.drawRoundedRect(QRectF(lay.rect), 4.0, 4.0)
            continue

        draw_rect = lay.rect
        font = lay.font

        if style_mode == "outline_only":
            painter.setFont(font)
            fm_outline = QFontMetrics(font)
            text_path = QPainterPath()
            text_rect = lay.text_rect
            if lay.flags & int(Qt.TextFlag.TextWordWrap):
                lines = wrap_lines(font, lay.text, text_rect.width())
                baseline_y = text_rect.y() + fm_outline.ascent()
            else:
                lines = [lay.text]
                baseline_y = text_rect.y() + (text_rect.height() + fm_outline.ascent() - fm_outline.descent()) // 2
            for line in lines:
                text_x = text_rect.x()
                if lay.flags & int(Qt.AlignmentFlag.AlignHCenter):
                    text_x += max(0, (text_rect.width() - fm_outline.horizontalAdvance(line)) // 2)
                text_path.addText(float(text_x), float(baseline_y), font, line)
                baseline_y += fm_outline.lineSpacing()

            outline_pen = QPen(
                QColor(0, 0, 0, 245),
                2.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            painter.strokePath(text_path, outline_pen)
            painter.fillPath(text_path, QColor("#FFFFFF"))
            continue

        radius = 4.0
        text_color = block.fg_color

        if style_mode == "wrap_gradient":
            painter.setPen(Qt.PenStyle.NoPen)
            grad = QLinearGradient(
                QPointF(draw_rect.left(), draw_rect.top()),
                QPointF(draw_rect.right(), draw_rect.top()),
            )
            grad.setColorAt(0.0, block.bg_color)
            grad.setColorAt(1.0, block.bg_color_right)
            painter.setBrush(grad)
        elif style_mode == "single":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(block.bg_color)
        elif style_mode == "dark_glass":
            painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
            painter.setBrush(QColor(12, 15, 22, 215))
            radius = 6.0
            text_color = QColor("#ECEFF4")
        elif style_mode == "cyber_neon":
            painter.setPen(QPen(QColor("#00E5FF"), 1.5))
            painter.setBrush(QColor(10, 14, 20, 230))
            radius = 4.0
            text_color = QColor("#00E5FF")
        elif style_mode == "high_contrast":
            painter.setPen(QPen(QColor(255, 214, 0, 110), 1.0))
            painter.setBrush(QColor("#111318"))
            radius = 8.0
            text_color = QColor("#FFD600")

        painter.drawRoundedRect(QRectF(draw_rect), radius, radius)

        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(lay.text_rect, lay.flags, lay.text)


class ScreenOverlay(QWidget):
    """Прозрачное окно поверх одного монитора: рамка области и плашки перевода.

    На каждый экран своё окно: окно, растянутое на несколько мониторов, Qt рисует
    с масштабом только одного из них, и на соседнем экране плашки съезжают.
    Рисует дочерний OpenGL-виджет: растровое прозрачное окно Qt Windows
    не даёт исключить из снимка экрана, а OpenGL-окно даёт и сохраняет полупрозрачность.
    """

    def __init__(self, controller: "GhostTranslateController", screen: QScreen):
        super().__init__()
        self.controller = controller
        self.target_screen = screen
        self.setWindowTitle(f"GhostTranslate Overlay v{APP_VERSION} ({screen.name()})")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = OverlayCanvas(self)
        layout.addWidget(self.canvas)
        self.fit_to_screen()

    def fit_to_screen(self):
        self.setScreen(self.target_screen)
        self.setGeometry(self.target_screen.geometry())

    def refresh(self):
        self.canvas.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_to_screen()
        self._enable_click_through()

    def _enable_click_through(self):
        hwnd = int(self.winId())
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(
            hwnd,
            win32con.GWL_EXSTYLE,
            ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT,
        )
        exclude_from_capture(self)


class OverlayCanvas(QOpenGLWidget):
    def __init__(self, overlay: ScreenOverlay):
        super().__init__(overlay)
        self.overlay = overlay
        fmt = QSurfaceFormat(self.format())
        fmt.setAlphaBufferSize(8)
        self.setFormat(fmt)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintGL(self):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        ctrl = self.overlay.controller
        if ctrl.target_screen is not self.overlay.target_screen:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Пункт 3.1 ТЗ v3.0: над рамкой нет текстовой плашки, только тонкая бирюзовая рамка
        # зоны захвата (отключается в FontSettingsPopup).
        if ctrl.show_region_border and ctrl.region_rect is not None and ctrl.font_cfg.show_capture_border:
            pen = QPen(QColor(0, 229, 255, 130))
            pen.setWidthF(1.3)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(ctrl.region_rect.adjusted(1, 1, -1, -1))

        paint_overlay_blocks(painter, ctrl.overlay_blocks, ctrl.font_cfg, ctrl.plaque_render_mode, self.rect())
