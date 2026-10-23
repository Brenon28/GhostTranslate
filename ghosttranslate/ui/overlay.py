from typing import TYPE_CHECKING, List

import win32con
import win32gui
from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
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

from ..config import FONT_HEIGHT_RATIO
from ..models import OverlayBlock
from ..ocr.layout import place_plaque_around
from ..settings import FontCustomConfig
from ..win32 import exclude_from_capture

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
) -> None:
    weight = QFont.Weight.Bold if font_cfg.is_bold else QFont.Weight.Medium

    for block in blocks:
        r = block.rect
        if block.is_pending:
            painter.setPen(QPen(QColor(168, 85, 247, 190), 1.0))
            painter.setBrush(QColor(138, 92, 245, 95))
            painter.drawRoundedRect(QRectF(r), 4.0, 4.0)
            continue

        single_line_h = max(12, int(r.height() / max(1, block.lines_merged)))
        auto_font_px = max(10, int(single_line_h * FONT_HEIGHT_RATIO))
        if font_cfg.use_fixed_pt:
            font_px = max(9, min(46, int(round(font_cfg.fixed_pt * 1.333))))
        else:
            scale_mult = max(0.6, min(1.8, font_cfg.scale_percent / 100.0))
            font_px = max(8, min(48, int(round(auto_font_px * scale_mult))))

        font = QFont(font_cfg.font_family, -1, weight)
        font.setPixelSize(font_px)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(block.trans_text)

        draw_rect = QRect(r)
        use_word_wrap = False

        allow_wrap_in_mode = style_mode in ("wrap_gradient", "dark_glass", "cyber_neon", "high_contrast")
        if allow_wrap_in_mode and (
            block.lines_merged >= 2 or (text_w > r.width() * 1.35 and len(block.trans_text.split()) >= 3)
        ):
            use_word_wrap = True
            draw_rect.setWidth(max(r.width() + 10, int(r.width() * 1.12)))
            if not font_cfg.use_fixed_pt:
                est_lines = max(2, int(round(text_w / max(40, draw_rect.width() - 12))) + 1)
                max_font_by_h = max(10, int((draw_rect.height() - 6) / max(1.8, est_lines * 1.18)))
                font_px = min(font_px, max(10, int(max_font_by_h * (font_cfg.scale_percent / 100.0))))
                font.setPixelSize(font_px)
            req_h = int(2 * font_px * 1.24) + 8
            if req_h > draw_rect.height():
                draw_rect.setHeight(min(int(r.height() * 1.35) + 12, req_h))
        elif text_w > r.width() - 6 and not font_cfg.use_fixed_pt:
            expanded_w = int(r.width() * 1.12)
            if text_w <= expanded_w - 6:
                draw_rect.setWidth(text_w + 8)
            else:
                draw_rect.setWidth(expanded_w)
                ratio = max(0.55, (expanded_w - 6) / max(1, text_w))
                font_px = max(8, int(font_px * ratio))
                font.setPixelSize(font_px)

        draw_rect = place_plaque_around(r, draw_rect.width(), draw_rect.height())

        if style_mode == "outline_only":
            painter.setFont(font)
            fm_outline = QFontMetrics(font)
            text_path = QPainterPath()
            baseline_y = draw_rect.y() + (draw_rect.height() + fm_outline.ascent() - fm_outline.descent()) // 2
            text_path.addText(float(draw_rect.x() + 2), float(baseline_y), font, block.trans_text)

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

        # Пункт 1.2 и 2.1 ТЗ v3.0: Кнопки меню центрируются (AlignCenter), абзацы — по левому краю
        if font_cfg.text_align == "center":
            horiz_flag = Qt.AlignmentFlag.AlignCenter
        elif font_cfg.text_align == "left":
            horiz_flag = Qt.AlignmentFlag.AlignLeft
        else:
            is_short_ui_button = (block.lines_merged == 1 and len(block.orig_text.split()) <= 2)
            horiz_flag = Qt.AlignmentFlag.AlignCenter if is_short_ui_button else Qt.AlignmentFlag.AlignLeft

        flags = Qt.AlignmentFlag.AlignVCenter | horiz_flag
        if use_word_wrap:
            flags |= Qt.TextFlag.TextWordWrap
        painter.drawText(draw_rect.adjusted(4, 2, -4, -2), flags, block.trans_text)


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
        self.setWindowTitle(f"GhostTranslate Overlay v3.0 ({screen.name()})")
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

        paint_overlay_blocks(painter, ctrl.overlay_blocks, ctrl.font_cfg, ctrl.plaque_render_mode)
