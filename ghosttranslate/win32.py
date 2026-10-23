"""Win32-обвязка: прототипы user32, права администратора, исключение окон из снимка экрана."""

import ctypes
import ctypes.wintypes

import win32con
import win32gui
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from .config import WDA_EXCLUDEFROMCAPTURE
from .diagnostics import log_event


# DPI-режим процесса не задаётся вручную: Qt 6 сам включает Per-Monitor V2,
# а ранний SetProcessDpiAwareness(2) закрепляет устаревший Per-Monitor V1.
user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

# Явные прототипы Win32: без argtypes ctypes усекает HWND до 32 бит.
try:
    user32.RegisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL
    user32.SetWindowDisplayAffinity.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = ctypes.wintypes.BOOL
except Exception:
    pass


def is_user_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


_capture_exclusion_warned = False

# Цвет, который Windows делает прозрачным в небольших окнах интерфейса.
COLOR_KEY = QColor(1, 0, 1)
COLOR_KEY_REF = 0x00010001


def exclude_from_capture(widget: QWidget) -> bool:
    """Прячет окно от снимков экрана, чтобы OCR не читал собственные плашки и панель.

    Windows отказывает (ошибка 8) окнам с WA_TranslucentBackground на растровом движке Qt:
    они рисуются через UpdateLayeredWindow. Поэтому прозрачность здесь делается
    через OpenGL (оверлеи) или цветовой ключ (панели). WDA_EXCLUDEFROMCAPTURE есть
    только с Windows 10 2004; ctypes не бросает исключение, отказ виден лишь по FALSE.
    """
    global _capture_exclusion_warned
    try:
        ok = bool(user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        ok = False
    if not ok and not _capture_exclusion_warned:
        _capture_exclusion_warned = True
        log_event(
            f"WDA_EXCLUDEFROMCAPTURE не применился к окну «{widget.windowTitle()}»: "
            "оно попадёт в снимок экрана (нужна Windows 10 2004 или новее)",
            "WARN",
        )
    return ok


def apply_color_key(widget: QWidget) -> None:
    """Пиксели цвета COLOR_KEY становятся прозрачными, окно исключается из снимка экрана."""
    hwnd = int(widget.winId())
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style | win32con.WS_EX_LAYERED)
    win32gui.SetLayeredWindowAttributes(hwnd, COLOR_KEY_REF, 255, win32con.LWA_COLORKEY)
    exclude_from_capture(widget)


def paint_color_key_background(widget: QWidget) -> None:
    painter = QPainter(widget)
    painter.fillRect(widget.rect(), COLOR_KEY)
