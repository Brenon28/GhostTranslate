from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..config import FONT_FAMILIES
from ..hotkeys import parse_hotkey
from ..settings import FontCustomConfig
from ..sounds import play_startup_sound
from ..win32 import apply_color_key, paint_color_key_background


class HotkeyEdit(QKeySequenceEdit):
    """Поле записи одного сочетания. Сообщает, когда ждёт нажатия."""

    capture_active = pyqtSignal(bool)

    def __init__(self, text: str, parent=None):
        super().__init__(QKeySequence(text), parent)
        self.setMaximumSequenceLength(1)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.capture_active.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.capture_active.emit(False)


# ==============================================================================
# ПУНКТ 2 ТЗ v3.0: ПЛАВАЮЩИЙ ПОПАП НАСТРОЙКИ ШРИФТА (FontSettingsPopup "Aa Шрифт")
# ==============================================================================
class FontSettingsPopup(QWidget):
    settings_changed = pyqtSignal()
    hotkeys_changed = pyqtSignal()
    # True, пока поле клавиши ждёт нажатия: глобальные клавиши на это время снимаются.
    hotkey_capture_active = pyqtSignal(bool)

    def __init__(self, font_cfg: FontCustomConfig, parent=None):
        super().__init__(parent)
        self.font_cfg = font_cfg
        self.setWindowTitle("GhostTranslate v3.0 — Настройка шрифта Aa")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget(self)
        card.setObjectName("FontPopupCard")
        card.setStyleSheet(
            """
            QWidget#FontPopupCard {
                background-color: rgba(13, 17, 26, 248);
                border: 1px solid rgba(0, 229, 255, 0.65);
                border-radius: 10px;
            }
            QLabel {
                color: #D8DEE9;
                font-family: "Segoe UI";
                font-size: 12px;
            }
            QComboBox, QPushButton {
                background-color: #171E2E;
                color: #D8DEE9;
                border: 1px solid #263147;
                border-radius: 5px;
                padding: 4px 8px;
                font-family: "Segoe UI";
                font-size: 12px;
            }
            QComboBox:hover, QPushButton:hover {
                border-color: #00E5FF;
                color: #00E5FF;
            }
            QCheckBox {
                color: #D8DEE9;
                font-family: "Segoe UI";
                font-size: 12px;
                spacing: 6px;
            }
            QLineEdit {
                background-color: #171E2E;
                color: #D8DEE9;
                border: 1px solid #263147;
                border-radius: 5px;
                padding: 3px 6px;
                font-family: "Segoe UI";
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #00E5FF;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Заголовок попапа
        hdr = QHBoxLayout()
        title = QLabel("Aa Шрифт, звук и клавиши (v3.0)", card)
        title.setStyleSheet("color: #00E5FF; font-weight: 700; font-size: 12px;")
        btn_close = QPushButton("✕", card)
        btn_close.setFixedWidth(26)
        btn_close.clicked.connect(self.hide)
        hdr.addWidget(title)
        hdr.addStretch(1)
        hdr.addWidget(btn_close)
        layout.addLayout(hdr)

        # 1. Выбор гарнитуры
        row_fam = QHBoxLayout()
        row_fam.addWidget(QLabel("Гарнитура:", card))
        self.combo_family = QComboBox(card)
        self.combo_family.addItems(FONT_FAMILIES)
        self.combo_family.setCurrentText(self.font_cfg.font_family)
        self.combo_family.currentTextChanged.connect(self._on_family_changed)
        row_fam.addWidget(self.combo_family, 1)
        layout.addLayout(row_fam)

        # 2. Масштаб размера (60% .. 180%) с кнопками - / +
        row_scale = QHBoxLayout()
        self.lbl_scale = QLabel(f"Масштаб: {self.font_cfg.scale_percent}%", card)
        btn_minus = QPushButton("−10%", card)
        btn_plus = QPushButton("+10%", card)
        btn_minus.clicked.connect(lambda: self._step_scale(-10))
        btn_plus.clicked.connect(lambda: self._step_scale(10))
        row_scale.addWidget(self.lbl_scale)
        row_scale.addStretch(1)
        row_scale.addWidget(btn_minus)
        row_scale.addWidget(btn_plus)
        layout.addLayout(row_scale)

        self.slider_scale = QSlider(Qt.Orientation.Horizontal, card)
        self.slider_scale.setRange(60, 180)
        self.slider_scale.setSingleStep(10)
        self.slider_scale.setPageStep(10)
        self.slider_scale.setValue(self.font_cfg.scale_percent)
        self.slider_scale.valueChanged.connect(self._on_scale_slider)
        layout.addWidget(self.slider_scale)

        # 3. Фиксированный размер (8 pt .. 28 pt)
        row_fixed = QHBoxLayout()
        self.chk_fixed = QCheckBox("Фиксированный размер (pt):", card)
        self.chk_fixed.setChecked(self.font_cfg.use_fixed_pt)
        self.chk_fixed.toggled.connect(self._on_fixed_toggled)
        self.combo_pt = QComboBox(card)
        for pt_val in range(8, 29, 2):
            self.combo_pt.addItem(f"{pt_val} pt", pt_val)
        idx_pt = max(0, (self.font_cfg.fixed_pt - 8) // 2)
        self.combo_pt.setCurrentIndex(idx_pt)
        self.combo_pt.currentIndexChanged.connect(self._on_fixed_pt_changed)
        row_fixed.addWidget(self.chk_fixed)
        row_fixed.addWidget(self.combo_pt)
        layout.addLayout(row_fixed)

        # 4. Выравнивание текста внутри плашек
        row_align = QHBoxLayout()
        row_align.addWidget(QLabel("Выравнивание:", card))
        self.combo_align = QComboBox(card)
        self.combo_align.addItem("Авто (Кнопки — Центр, Абзацы — Слева)", "auto")
        self.combo_align.addItem("Всегда по центру (AlignCenter)", "center")
        self.combo_align.addItem("Всегда по левому краю (AlignLeft)", "left")
        align_map = {"auto": 0, "center": 1, "left": 2}
        self.combo_align.setCurrentIndex(align_map.get(self.font_cfg.text_align, 0))
        self.combo_align.currentIndexChanged.connect(self._on_align_changed)
        row_align.addWidget(self.combo_align, 1)
        layout.addLayout(row_align)

        # 5. Чекбоксы Жирный шрифт (Bold) и Показ бирюзовой рамки захвата
        self.chk_bold = QCheckBox("Жирный шрифт (Bold)", card)
        self.chk_bold.setChecked(self.font_cfg.is_bold)
        self.chk_bold.toggled.connect(self._on_bold_toggled)
        layout.addWidget(self.chk_bold)

        self.chk_border = QCheckBox("Показывать бирюзовую рамку выделенной зоны", card)
        self.chk_border.setChecked(self.font_cfg.show_capture_border)
        self.chk_border.toggled.connect(self._on_border_toggled)
        layout.addWidget(self.chk_border)

        # 6. Звук и глобальные клавиши
        line = QFrame(card)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #263147;")
        layout.addWidget(line)

        row_sound = QHBoxLayout()
        self.chk_sound = QCheckBox("Звук при запуске и выходе", card)
        self.chk_sound.setChecked(self.font_cfg.sound_enabled)
        self.chk_sound.toggled.connect(self._on_sound_toggled)
        btn_preview = QPushButton("Прослушать", card)
        btn_preview.clicked.connect(play_startup_sound)
        row_sound.addWidget(self.chk_sound)
        row_sound.addStretch(1)
        row_sound.addWidget(btn_preview)
        layout.addLayout(row_sound)

        self.edit_toggle = HotkeyEdit(self.font_cfg.hotkey_toggle, card)
        self.edit_snip = HotkeyEdit(self.font_cfg.hotkey_snip, card)
        for caption, edit in (("Скрыть / показать:", self.edit_toggle), ("Выделить область:", self.edit_snip)):
            row = QHBoxLayout()
            row.addWidget(QLabel(caption, card))
            row.addWidget(edit, 1)
            layout.addLayout(row)
            edit.capture_active.connect(self.hotkey_capture_active.emit)
            edit.editingFinished.connect(self._on_hotkey_edited)

        self.lbl_hotkey_hint = QLabel(card)
        self.lbl_hotkey_hint.setWordWrap(True)
        self._show_hotkey_hint("Щёлкните поле и нажмите сочетание. Если игра сама использует F8 или F9, "
                               "выберите, например, Ctrl+Alt+T.")
        layout.addWidget(self.lbl_hotkey_hint)

        outer.addWidget(card)
        self.setFixedWidth(400)
        self.adjustSize()

    def showEvent(self, event):
        super().showEvent(event)
        apply_color_key(self)

    def paintEvent(self, event):
        paint_color_key_background(self)

    def _emit_and_save(self):
        self.font_cfg.save()
        self.settings_changed.emit()

    def _on_family_changed(self, fam: str):
        self.font_cfg.font_family = fam
        self._emit_and_save()

    def _step_scale(self, delta: int):
        next_val = max(60, min(180, self.font_cfg.scale_percent + delta))
        self.slider_scale.setValue(next_val)

    def _on_scale_slider(self, val: int):
        snapped = int(round(val / 10.0) * 10)
        self.font_cfg.scale_percent = max(60, min(180, snapped))
        self.lbl_scale.setText(f"Масштаб: {self.font_cfg.scale_percent}%")
        self._emit_and_save()

    def _on_fixed_toggled(self, checked: bool):
        self.font_cfg.use_fixed_pt = checked
        self._emit_and_save()

    def _on_fixed_pt_changed(self, _idx: int):
        val = self.combo_pt.currentData()
        if val is not None:
            self.font_cfg.fixed_pt = int(val)
            self._emit_and_save()

    def _on_align_changed(self, _idx: int):
        val = self.combo_align.currentData()
        if val:
            self.font_cfg.text_align = str(val)
            self._emit_and_save()

    def _on_bold_toggled(self, checked: bool):
        self.font_cfg.is_bold = checked
        self._emit_and_save()

    def _on_border_toggled(self, checked: bool):
        self.font_cfg.show_capture_border = checked
        self._emit_and_save()

    def _on_sound_toggled(self, checked: bool):
        self.font_cfg.sound_enabled = checked
        self.font_cfg.save()

    def _show_hotkey_hint(self, text: str, is_error: bool = False) -> None:
        color = "#FF7A7A" if is_error else "#8C96A8"
        self.lbl_hotkey_hint.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.lbl_hotkey_hint.setText(text)

    def _on_hotkey_edited(self):
        toggle = parse_hotkey(self.edit_toggle.keySequence().toString(QKeySequence.SequenceFormat.PortableText))
        snip = parse_hotkey(self.edit_snip.keySequence().toString(QKeySequence.SequenceFormat.PortableText))
        error = ""
        if toggle is None or snip is None:
            error = "Нужна F1–F12 или сочетание с Ctrl, Alt или Win. Одна буква без них занята набором текста."
        elif toggle.text == snip.text:
            error = "Обе команды получили одно и то же сочетание."
        if error:
            self._show_hotkey_hint(error, is_error=True)
            self.reset_hotkey_fields()
            return
        if (toggle.text, snip.text) == (self.font_cfg.hotkey_toggle, self.font_cfg.hotkey_snip):
            return
        self.font_cfg.hotkey_toggle = toggle.text
        self.font_cfg.hotkey_snip = snip.text
        self.font_cfg.save()
        self._show_hotkey_hint(f"Сохранено: {toggle.text} — скрыть, {snip.text} — область.")
        self.hotkeys_changed.emit()

    def reset_hotkey_fields(self) -> None:
        """Возвращает в поля сочетания, которые реально действуют сейчас."""
        for edit, text in ((self.edit_toggle, self.font_cfg.hotkey_toggle), (self.edit_snip, self.font_cfg.hotkey_snip)):
            edit.blockSignals(True)
            edit.setKeySequence(QKeySequence(text))
            edit.blockSignals(False)

    def show_hotkey_error(self, text: str) -> None:
        self._show_hotkey_hint(text, is_error=True)
