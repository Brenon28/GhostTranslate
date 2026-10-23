from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from ..diagnostics import BENCHMARK_STATS, LOG_RING_BUFFER, format_benchmark_summary, log_event
from ..win32 import exclude_from_capture


# ==============================================================================
# МОДАЛЬНОЕ ОКНО ЖИВЫХ ЛОГОВ И БЕНЧМАРКА (LogViewerDialog v3.0)
# ==============================================================================
class LogViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GhostTranslate v3.0 — Журнал работы и бенчмарк")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(760, 440)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #0D111A;
                color: #D8DEE9;
            }
            QLabel {
                color: #00E5FF;
                font-family: "Consolas", monospace;
                font-size: 12px;
                font-weight: 600;
            }
            QPlainTextEdit {
                background-color: #080B10;
                color: #D8DEE9;
                border: 1px solid #1E2638;
                border-radius: 6px;
                font-family: "Consolas", monospace;
                font-size: 11px;
                padding: 8px;
            }
            QPushButton {
                background-color: #171E2E;
                color: #D8DEE9;
                border: 1px solid #263147;
                border-radius: 5px;
                padding: 5px 12px;
                font-family: "Segoe UI";
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                border-color: #00E5FF;
                color: #00E5FF;
            }
            """
        )

        layout = QVBoxLayout(self)
        self.stats_label = QLabel("", self)
        layout.addWidget(self.stats_label)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        btn_row = QHBoxLayout()
        self.btn_copy = QPushButton("Скопировать отчет в буфер", self)
        self.btn_bundle = QPushButton("Сохранить бандл (ghost_report_bundle.txt)", self)
        self.btn_clear = QPushButton("Очистить журнал", self)
        btn_row.addWidget(self.btn_copy)
        btn_row.addWidget(self.btn_bundle)
        btn_row.addWidget(self.btn_clear)
        layout.addLayout(btn_row)

        self.btn_clear.clicked.connect(self._on_clear)

    def showEvent(self, event):
        super().showEvent(event)
        exclude_from_capture(self)
        self.refresh_view()

    def refresh_view(self):
        self.stats_label.setText(f"Сводка скорости v3.0: {format_benchmark_summary()}")
        self.text_edit.setPlainText("\n".join(LOG_RING_BUFFER))
        sb = self.text_edit.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _on_clear(self):
        LOG_RING_BUFFER.clear()
        for k in BENCHMARK_STATS:
            BENCHMARK_STATS[k].clear()
        log_event("Журнал и метрики бенчмарка очищены пользователем")
        self.refresh_view()
