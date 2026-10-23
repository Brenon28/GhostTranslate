import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from .config import APP_VERSION
from .controller import GhostTranslateController
from .diagnostics import install_exception_logger, log_event
from .single_instance import ActivationServer, acquire_single_instance, notify_running_instance


def main() -> None:
    install_exception_logger()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    instance_lock = acquire_single_instance()
    if instance_lock is None:
        # Второй экземпляр не грузит модель и не пишет в журнал: файл журнала держит первый.
        if not notify_running_instance():
            QMessageBox.information(
                None,
                f"GhostTranslate v{APP_VERSION}",
                "GhostTranslate уже запущен. Значок программы в области уведомлений рядом с часами.",
            )
        sys.exit(0)

    controller = GhostTranslateController()
    activation = ActivationServer()
    activation.activation_requested.connect(controller.bring_to_front)
    if not activation.listening:
        log_event(f"Канал для повторного запуска не открылся: {activation.error_text()}", "WARN")
    sys.exit(app.exec())
