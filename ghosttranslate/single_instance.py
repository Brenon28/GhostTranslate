"""Один экземпляр на сеанс Windows: второй запуск показывает первый и завершается."""

import ctypes
import ctypes.wintypes
import os
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

# То же имя стоит в AppMutex установщика: установка и удаление ждут закрытия программы.
MUTEX_NAME = "GhostTranslateSingleInstance"
ERROR_ALREADY_EXISTS = 183
ACTIVATE_MESSAGE = b"show"
CONNECT_TIMEOUT_MS = 1000

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
kernel32.CloseHandle.restype = ctypes.wintypes.BOOL


def activation_server_name() -> str:
    """Именованный канал общий для всей машины, поэтому в имени пользователь."""
    return f"GhostTranslate-activate-{os.environ.get('USERNAME', 'user')}"


def acquire_single_instance(name: str = MUTEX_NAME) -> Optional[int]:
    """Дескриптор мьютекса, если это первый экземпляр, иначе None.

    Дескриптор держится до конца процесса: Windows освобождает мьютекс сама,
    в том числе после os._exit и падения. Мьютекс экземпляра с правами администратора
    обычному процессу открыть нельзя, и отказ доступа тоже значит «уже запущен».
    """
    handle = kernel32.CreateMutexW(None, False, name)
    error = ctypes.get_last_error()
    if not handle:
        return None
    if error == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def release_single_instance(handle: Optional[int]) -> None:
    if handle:
        kernel32.CloseHandle(handle)


def notify_running_instance(server_name: Optional[str] = None) -> bool:
    """Просит работающий экземпляр показаться. False, если он не ответил."""
    socket = QLocalSocket()
    socket.connectToServer(server_name or activation_server_name())
    if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
        return False
    written = socket.write(ACTIVATE_MESSAGE) == len(ACTIVATE_MESSAGE)
    # На Windows запись часто уходит сразу, и тогда waitForBytesWritten возвращает False: ждать нечего.
    while written and socket.bytesToWrite() > 0:
        if not socket.waitForBytesWritten(CONNECT_TIMEOUT_MS):
            break
    sent = written and socket.bytesToWrite() == 0
    socket.disconnectFromServer()
    return sent


class ActivationServer(QObject):
    """Принимает просьбы второго запуска показать уже работающую программу."""

    activation_requested = pyqtSignal()

    def __init__(self, server_name: Optional[str] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        # Тот же пользователь достучится и без прав администратора, чужие пользователи нет.
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_new_connection)
        self.listening = self._server.listen(server_name or activation_server_name())

    def error_text(self) -> str:
        return self._server.errorString()

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._on_ready_read(socket)

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        if bytes(socket.readAll()).startswith(ACTIVATE_MESSAGE):
            self.activation_requested.emit()
