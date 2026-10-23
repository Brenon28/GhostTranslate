from typing import List, Optional, Tuple

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..config import (
    DEFAULT_HOTKEY_SNIP,
    DEFAULT_HOTKEY_TOGGLE,
    DEFAULT_OCR_BACKEND,
    DEFAULT_RENDER_STYLE,
    PLAQUE_STYLES,
    STYLE_ID_TO_LABEL,
    STYLE_LABEL_TO_ID,
    TIMER_OPTIONS,
)
from ..win32 import apply_color_key, paint_color_key_background

# Запас по краям экрана, чтобы панель не упиралась в рамку монитора.
SCREEN_MARGIN_PX = 16


# ==============================================================================
# ПЛАВАЮЩАЯ ПАНЕЛЬ FLOATING TOOLBAR v3.0 (С КНОПКОЙ "Aa Шрифт" И ХОТКЕЯМИ F8/F9)
# ==============================================================================
class FloatingToolbar(QWidget):
    fullscreen_clicked = pyqtSignal()
    region_snip_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    ocr_backend_toggled = pyqtSignal(str)
    render_style_changed = pyqtSignal(str)
    font_popup_toggled = pyqtSignal()
    timer_changed = pyqtSignal(str)
    hide_toggle_clicked = pyqtSignal()
    logs_clicked = pyqtSignal()
    exit_clicked = pyqtSignal()
    # Середина верхнего края после перетаскивания (кортеж x, y) или None после сброса двойным щелчком.
    anchor_changed = pyqtSignal(object)

    def __init__(self, anchor: Optional[Tuple[int, int]] = None):
        super().__init__()
        self.setWindowTitle("GhostTranslate Toolbar v3.0")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self._drag_offset: Optional[QPoint] = None
        self._dragged = False
        self._anchor: Optional[QPoint] = QPoint(*anchor) if anchor else None
        self.is_two_rows = False
        self.is_collapsed = False
        self.current_ocr = DEFAULT_OCR_BACKEND
        self.current_style = DEFAULT_RENDER_STYLE

        self.collapse_timer = QTimer(self)
        self.collapse_timer.setSingleShot(True)
        self.collapse_timer.timeout.connect(self._collapse_to_edge)

        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 4)
        layout.setSpacing(0)

        self.setStyleSheet(
            """
            QWidget#ExpandedBar {
                background-color: rgba(15, 17, 23, 244);
                border: 1px solid rgba(0, 229, 255, 0.55);
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QWidget#CollapsedTab {
                background-color: rgba(15, 17, 23, 185);
                border: 1px solid rgba(0, 229, 255, 0.45);
                border-top: none;
                border-bottom-left-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QPushButton, QComboBox {
                background-color: rgba(255, 255, 255, 0.07);
                color: #D8DEE9;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 5px;
                font-family: "Segoe UI";
                font-size: 12px;
                font-weight: 500;
                padding: 3px 8px;
                min-height: 22px;
            }
            QPushButton:hover, QComboBox:hover {
                border-color: #00E5FF;
                color: #00E5FF;
            }
            QPushButton#PrimaryBtn {
                background-color: #00E5FF;
                color: #0B0E14;
                border-color: #00E5FF;
                font-weight: 600;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #33ECFF;
            }
            QPushButton#SwitchBtn {
                background-color: rgba(0, 229, 255, 0.12);
                color: #00E5FF;
                border: 1px solid rgba(0, 229, 255, 0.40);
                font-weight: 600;
            }
            QPushButton#FontBtn {
                background-color: rgba(138, 92, 245, 0.18);
                color: #C4B5FD;
                border: 1px solid rgba(138, 92, 245, 0.55);
                font-weight: 600;
            }
            QPushButton#FontBtn:hover {
                border-color: #00E5FF;
                color: #FFFFFF;
            }
            QPushButton#StopBtnActive {
                background-color: rgba(255, 82, 82, 0.22);
                color: #FF5252;
                border: 1px solid #FF5252;
                font-weight: 600;
            }
            QPushButton#StopBtnActive:hover {
                background-color: #FF5252;
                color: #FFFFFF;
            }
            QPushButton#CloseBtn {
                background-color: rgba(239, 68, 68, 0.18);
                color: #F87171;
                border: 1px solid rgba(239, 68, 68, 0.45);
                font-weight: 700;
                padding: 3px 7px;
            }
            QPushButton#CloseBtn:hover {
                background-color: #EF4444;
                color: #FFFFFF;
            }
            """
        )

        self.collapsed_widget = QWidget(self)
        self.collapsed_widget.setObjectName("CollapsedTab")
        col_layout = QHBoxLayout(self.collapsed_widget)
        col_layout.setContentsMargins(14, 2, 14, 3)
        self.collapsed_label = QLabel(self.collapsed_widget)
        self.collapsed_label.setStyleSheet("color: #00E5FF; font-size: 10px; font-weight: 600;")
        col_layout.addWidget(self.collapsed_label)
        self.collapsed_widget.hide()

        self.expanded_widget = QWidget(self)
        self.expanded_widget.setObjectName("ExpandedBar")
        rows = QVBoxLayout(self.expanded_widget)
        rows.setContentsMargins(10, 5, 10, 5)
        rows.setSpacing(5)
        self.row_main = QHBoxLayout()
        self.row_main.setSpacing(5)
        self.row_extra = QHBoxLayout()
        self.row_extra.setSpacing(5)
        # В два ряда строки разной длины: кнопки прижаты влево, а не растянуты.
        self.row_main.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.row_extra.setAlignment(Qt.AlignmentFlag.AlignLeft)
        rows.addLayout(self.row_main)
        rows.addLayout(self.row_extra)

        title_lbl = QLabel("GhostTranslate v3.0", self.expanded_widget)
        title_lbl.setStyleSheet("color: #00E5FF; font-weight: 700; font-size: 12px; padding-right: 2px;")

        self.btn_fullscreen = QPushButton("Весь экран", self.expanded_widget)
        self.btn_fullscreen.setObjectName("PrimaryBtn")
        self.btn_fullscreen.setToolTip("Перевести монитор, на котором открыто активное окно (игра, браузер)")
        self.btn_fullscreen.clicked.connect(self.fullscreen_clicked.emit)

        self.btn_region = QPushButton(self.expanded_widget)
        self.btn_region.clicked.connect(self.region_snip_clicked.emit)

        self.btn_stop = QPushButton("Стоп", self.expanded_widget)
        self.btn_stop.setToolTip("Остановить таймер, прервать перевод и очистить плашки")
        self.btn_stop.clicked.connect(self.stop_clicked.emit)

        self.btn_ocr_toggle = QPushButton(f"OCR: {self.current_ocr}", self.expanded_widget)
        self.btn_ocr_toggle.setObjectName("SwitchBtn")
        self.btn_ocr_toggle.setToolTip("Переключить движок распознавания: WinOCR (пословный) <-> RapidOCR")
        self.btn_ocr_toggle.clicked.connect(self._on_toggle_ocr)

        self.style_combo = QComboBox(self.expanded_widget)
        self.style_combo.setToolTip("Выбор одного из 6 визуальных режимов отрисовки плашек")
        for _, label in PLAQUE_STYLES:
            self.style_combo.addItem(label)
        # Закрытый список узкий, раскрытый показывает названия стилей целиком.
        self.style_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.style_combo.setMinimumContentsLength(18)
        self.style_combo.view().setMinimumWidth(self.style_combo.view().sizeHintForColumn(0) + 24)
        default_label = STYLE_ID_TO_LABEL.get(self.current_style, PLAQUE_STYLES[0][1])
        self.style_combo.setCurrentText(default_label)
        self.style_combo.currentTextChanged.connect(self._on_style_combo_changed)

        # Пункт 2.1 ТЗ v3.0: Кнопка «Aa Шрифт» для открытия FontSettingsPopup
        self.btn_font = QPushButton("Aa Шрифт", self.expanded_widget)
        self.btn_font.setObjectName("FontBtn")
        self.btn_font.setToolTip("Шрифт плашек, рамка области, звук и глобальные клавиши")
        self.btn_font.clicked.connect(self.font_popup_toggled.emit)

        self.timer_combo = QComboBox(self.expanded_widget)
        self.timer_combo.addItems(TIMER_OPTIONS)
        self.timer_combo.currentTextChanged.connect(self.timer_changed.emit)

        self.btn_clear = QPushButton(self.expanded_widget)
        self.btn_clear.clicked.connect(self.hide_toggle_clicked.emit)

        self.btn_logs = QPushButton("Логи", self.expanded_widget)
        self.btn_logs.setToolTip("Открыть живое окно логов и замеров скорости")
        self.btn_logs.clicked.connect(self.logs_clicked.emit)

        self.btn_close = QPushButton("[X]", self.expanded_widget)
        self.btn_close.setObjectName("CloseBtn")
        self.btn_close.setToolTip("Полное закрытие программы и выгрузка процесса")
        self.btn_close.clicked.connect(self.exit_clicked.emit)

        # На узком экране вторая группа уходит во второй ряд.
        self._main_widgets: List[QWidget] = [
            title_lbl,
            self.btn_fullscreen,
            self.btn_region,
            self.btn_stop,
            self.btn_ocr_toggle,
        ]
        self._extra_widgets: List[QWidget] = [
            self.style_combo,
            self.btn_font,
            self.timer_combo,
            self.btn_clear,
            self.btn_logs,
            self.btn_close,
        ]
        for widget in self._main_widgets + self._extra_widgets:
            self.row_main.addWidget(widget)

        layout.addWidget(self.collapsed_widget)
        layout.addWidget(self.expanded_widget)
        self.set_hotkey_labels(DEFAULT_HOTKEY_TOGGLE, DEFAULT_HOTKEY_SNIP)

    def set_hotkey_labels(self, toggle_text: str, snip_text: str) -> None:
        self.btn_region.setText(f"Область [{snip_text}]")
        self.btn_region.setToolTip(f"Нажмите {snip_text} или кнопку, затем выделите зону обычной ЛКМ")
        self.btn_clear.setText(f"Скрыть [{toggle_text}]")
        self.btn_clear.setToolTip(f"Скрыть / Показать панель и плашки (глобальная клавиша {toggle_text})")
        self.collapsed_label.setText(f"GhostTranslate v3.0 · {toggle_text}: Скрыть · {snip_text}: Область")
        self.reposition()

    def _on_toggle_ocr(self):
        self.current_ocr = "RapidOCR" if self.current_ocr == "WinOCR" else "WinOCR"
        self.btn_ocr_toggle.setText(f"OCR: {self.current_ocr}")
        self.reposition()
        self.ocr_backend_toggled.emit(self.current_ocr)

    def _on_style_combo_changed(self, label_text: str):
        style_id = STYLE_LABEL_TO_ID.get(label_text, "wrap_gradient")
        self.current_style = style_id
        self.render_style_changed.emit(style_id)

    def set_stop_active(self, active: bool):
        self.btn_stop.setObjectName("StopBtnActive" if active else "")
        self.btn_stop.style().unpolish(self.btn_stop)
        self.btn_stop.style().polish(self.btn_stop)

    def showEvent(self, event):
        super().showEvent(event)
        apply_color_key(self)

    def paintEvent(self, event):
        paint_color_key_background(self)

    def _single_row_width(self) -> int:
        margins = self.expanded_widget.layout().contentsMargins()
        spacing = self.row_main.spacing()
        widths = [w.sizeHint().width() for w in self._main_widgets + self._extra_widgets]
        return sum(widths) + spacing * (len(widths) - 1) + margins.left() + margins.right() + 12

    def fit_to_width(self, available_width: int) -> None:
        """Один ряд кнопок, если он помещается в ширину экрана, иначе два."""
        two_rows = self._single_row_width() > available_width - SCREEN_MARGIN_PX
        if two_rows == self.is_two_rows:
            return
        self.is_two_rows = two_rows
        target = self.row_extra if two_rows else self.row_main
        for widget in self._extra_widgets:
            target.addWidget(widget)
        # Без явного пересчёта adjustSize() до следующего витка событий берёт старый размер.
        self.expanded_widget.layout().activate()
        self.layout().invalidate()
        self.layout().activate()

    def _anchor_screen(self):
        if self._anchor is not None:
            screen = QApplication.screenAt(self._anchor)
            if screen is not None:
                return screen
            self._anchor = None
        return QApplication.primaryScreen()

    def reset_position(self) -> None:
        self._anchor = None
        self.reposition()

    def reposition(self) -> None:
        """Середина верхнего края остаётся на месте при сворачивании и смене ширины."""
        screen = self._anchor_screen()
        if screen is None:
            return
        geo = screen.geometry()
        self.fit_to_width(geo.width())
        self.adjustSize()
        if self._anchor is None:
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y()
        else:
            x = self._anchor.x() - self.width() // 2
            y = self._anchor.y()
        x = max(geo.x(), min(x, geo.x() + geo.width() - self.width()))
        y = max(geo.y(), min(y, geo.y() + geo.height() - self.height()))
        self.move(x, y)

    def _collapse_to_edge(self):
        if self.style_combo.view().isVisible() or self.timer_combo.view().isVisible():
            return
        if self._drag_offset is not None:
            return
        self.is_collapsed = True
        self.expanded_widget.hide()
        self.collapsed_widget.show()
        self.reposition()

    def _expand_from_edge(self):
        self.collapse_timer.stop()
        if self.is_collapsed:
            self.is_collapsed = False
            self.collapsed_widget.hide()
            self.expanded_widget.show()
            self.reposition()

    def enterEvent(self, event):
        self._expand_from_edge()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.collapse_timer.start(650)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragged = False

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self._dragged = True

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        if not self._dragged:
            return
        self._dragged = False
        self._anchor = QPoint(self.x() + self.width() // 2, self.y())
        # Панель могли перетащить на монитор другой ширины: ряды и края пересчитываются там.
        self.reposition()
        self._anchor = QPoint(self.x() + self.width() // 2, self.y())
        self.anchor_changed.emit((self._anchor.x(), self._anchor.y()))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_position()
            self.anchor_changed.emit(None)
