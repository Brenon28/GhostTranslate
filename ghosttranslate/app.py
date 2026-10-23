import sys

from PyQt6.QtWidgets import QApplication

from .controller import GhostTranslateController
from .diagnostics import install_exception_logger


def main() -> None:
    install_exception_logger()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = GhostTranslateController()
    sys.exit(app.exec())
