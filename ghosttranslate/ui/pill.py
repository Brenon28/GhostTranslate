from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from ..config import APP_VERSION
from ..win32 import apply_color_key, paint_color_key_background


# ==============================================================================
# ПУНКТ 3.2 ТЗ v3.0: МИНИ-ТАБЛЕТКА МАЯЧОК MiniRestorePill ("👻 GT [F8]")
# ==============================================================================
class MiniRestorePill(QWidget):
    restore_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GhostTranslate Mini Pill v{APP_VERSION}")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.btn = QPushButton(self)
        self.btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(15, 17, 23, 215);
                color: #00E5FF;
                border: 1px solid rgba(0, 229, 255, 0.60);
                border-radius: 11px;
                font-family: "Segoe UI";
                font-size: 11px;
                font-weight: 700;
                padding: 3px 10px;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 0.22);
                border-color: #00E5FF;
                color: #FFFFFF;
            }
            """
        )
        self.btn.clicked.connect(self.restore_clicked.emit)
        layout.addWidget(self.btn)
        self.set_hotkey_label("F8")

    def set_hotkey_label(self, toggle_text: str) -> None:
        self.btn.setText(f"👻 GT [{toggle_text}]")
        self.btn.setToolTip(f"Нажмите {toggle_text} или кликните сюда, чтобы вернуть панель и перевод")
        self.adjustSize()

    def showEvent(self, event):
        super().showEvent(event)
        apply_color_key(self)
        screen_geom = QApplication.primaryScreen().geometry()
        self.move(screen_geom.width() - self.width() - 18, 12)

    def paintEvent(self, event):
        paint_color_key_background(self)
