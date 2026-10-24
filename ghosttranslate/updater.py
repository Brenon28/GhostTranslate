"""Обновление из релизов GitHub: новая версия, загрузка установщика, тихая установка поверх."""

import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from PyQt6.QtCore import QThread, pyqtSignal

from .config import APP_VERSION, UPDATE_REPO

LATEST_RELEASE_URL = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
INSTALLER_ASSET_REGEX = re.compile(r"^GhostTranslate_v[\d.]+_Setup\.exe$", re.IGNORECASE)
TRUSTED_DOWNLOAD_PREFIX = f"https://github.com/{UPDATE_REPO}/releases/download/"
HTTP_TIMEOUT_S = 20
CHUNK_BYTES = 256 * 1024
# /SILENT показывает только окно прогресса. UPDATE=1 — установщик ждёт, пока программа
# закроется, а после установки запускает её снова (секция [Code] в installer.iss).
INSTALLER_ARGUMENTS = "/SILENT /SUPPRESSMSGBOXES /NORESTART /UPDATE=1"


class UpdateError(Exception):
    pass


class UpdateCancelled(UpdateError):
    pass


@dataclass
class ReleaseInfo:
    version: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    asset_size: int
    sha256: Optional[str]


def parse_version(text) -> Tuple[int, ...]:
    """«v3.10» -> (3, 10). Хвостовые нули не значат ничего: 3.4.0 и 3.4 — одна версия."""
    numbers = [int(part) for part in re.findall(r"\d+", str(text or ""))[:4]]
    while numbers and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def is_newer(candidate, current: str = APP_VERSION) -> bool:
    new = parse_version(candidate)
    return bool(new) and new > parse_version(current)


def can_self_update() -> bool:
    """Из исходников обновляются через git; поставить установщик можно только поверх сборки."""
    return bool(getattr(sys, "frozen", False))


def release_from_json(data) -> Optional[ReleaseInfo]:
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not INSTALLER_ASSET_REGEX.match(name) or not url.startswith(TRUSTED_DOWNLOAD_PREFIX):
            continue
        digest = str(asset.get("digest") or "")
        sha256 = digest[len("sha256:"):].lower() if digest.lower().startswith("sha256:") else None
        return ReleaseInfo(
            version=tag.lstrip("vV"),
            notes=str(data.get("body") or ""),
            page_url=str(data.get("html_url") or ""),
            asset_name=name,
            asset_url=url,
            asset_size=int(asset.get("size") or 0),
            sha256=sha256,
        )
    return None


def _request(url: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"GhostTranslate/{APP_VERSION}"})


def fetch_latest_release() -> Optional[ReleaseInfo]:
    request = _request(LATEST_RELEASE_URL, "application/vnd.github+json")
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        data = json.loads(response.read().decode("utf-8"))
    return release_from_json(data)


def download_installer(
    release: ReleaseInfo,
    on_progress: Callable[[int, int], None],
    cancelled: Callable[[], bool],
    folder: Optional[str] = None,
) -> str:
    """Качает установщик во временную папку и сверяет размер и SHA256 из релиза."""
    folder = folder or os.path.join(tempfile.gettempdir(), "GhostTranslate_update")
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, release.asset_name)
    partial = target + ".part"
    digest = hashlib.sha256()
    received = 0
    try:
        with urllib.request.urlopen(_request(release.asset_url, "application/octet-stream"),
                                    timeout=HTTP_TIMEOUT_S) as response, open(partial, "wb") as out:
            total = release.asset_size or int(response.headers.get("Content-Length") or 0)
            while True:
                if cancelled():
                    raise UpdateCancelled("загрузка отменена")
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                on_progress(received, total)
        if release.asset_size and received != release.asset_size:
            raise UpdateError(f"скачано {received} байт из {release.asset_size}")
        if release.sha256 and digest.hexdigest() != release.sha256:
            raise UpdateError("контрольная сумма установщика не совпала с релизом")
        os.replace(partial, target)
    except BaseException:
        try:
            os.remove(partial)
        except OSError:
            pass
        raise
    return target


def launch_installer(path: str) -> None:
    """ShellExecute, а не CreateProcess: установщику нужны права администратора,
    и из программы без них Windows сама покажет запрос UAC."""
    os.startfile(path, "open", INSTALLER_ARGUMENTS)


class UpdateCheckThread(QThread):
    # (ReleaseInfo или None, текст ошибки)
    checked = pyqtSignal(object, str)

    def run(self):
        try:
            release = fetch_latest_release()
        except Exception as exc:
            self.checked.emit(None, str(exc))
            return
        self.checked.emit(release, "")


class UpdateDownloadThread(QThread):
    progress = pyqtSignal(int, int)
    # (путь к установщику, текст ошибки); оба пустые — загрузку отменили.
    done = pyqtSignal(str, str)

    def __init__(self, release: ReleaseInfo):
        super().__init__()
        self.release = release

    def run(self):
        try:
            path = download_installer(self.release, self.progress.emit, self.isInterruptionRequested)
        except UpdateCancelled:
            self.done.emit("", "")
            return
        except Exception as exc:
            self.done.emit("", str(exc) or type(exc).__name__)
            return
        self.done.emit(path, "")
