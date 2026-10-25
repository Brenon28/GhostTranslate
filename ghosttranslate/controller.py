import ctypes
import ctypes.wintypes
import os
import platform
import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import numpy as np
import win32gui
import win32process
from PyQt6.QtCore import QRect, Qt, QThread, QTimer
from PyQt6.QtGui import QAction, QColor, QCursor, QIcon, QPixmap, QScreen
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QProgressDialog, QSystemTrayIcon, QWidget

from .config import (
    APP_VERSION,
    BUNDLE_FILE_PATH,
    CAPTURE_VEIL_SETTLE_MS,
    DATA_DIR,
    DEFAULT_OCR_BACKEND,
    DEFAULT_RENDER_STYLE,
    HOTKEY_ID_SNIP,
    HOTKEY_ID_TOGGLE,
    LRU_MAX_SIZE,
    MAX_BLOCKS_PER_FRAME,
    PIXEL_DIFF_THRESHOLD,
    RAPIDOCR_MAX_SIDE,
    RAPIDOCR_REC_MODEL_PATH,
    RAPIDOCR_THREADS,
    SEQ_MATCH_THRESHOLD,
    TRANSLATE_CHUNK_BLOCKS,
    TRANSLATION_ENGINE,
    UPDATE_CHECK_DELAY_MS,
    VK_ESCAPE,
    WATCHDOG_CHAT_VERT_PAD_PX,
    WATCHDOG_PADDING_PX,
    WM_HOTKEY,
)
from .diagnostics import LOG_RING_BUFFER, format_benchmark_summary, log_event
from .game_dict import GAME_UI_DICT
from .hotkeys import MOD_NOREPEAT, Hotkey, is_hotkey_down, parse_hotkey
from .models import OverlayBlock
from .ocr.imaging import compute_small_gray_numpy, max_grid_diff_numpy
from .screens import (
    crop_to_region,
    mask_native_rects,
    native_capture_region,
    open_mss,
    screen_at_native_point,
    screen_native_rect,
)
from .settings import FontCustomConfig
from .sounds import play_shutdown_sound_sync, play_startup_sound
from .translator import TranslationLRUCache
from .ui.font_popup import FontSettingsPopup
from .ui.log_dialog import LogViewerDialog
from .ui.overlay import ScreenOverlay
from .ui.pill import MiniRestorePill
from .ui.snip import SNIP_HIDE_SETTLE_MS, SnipOverlay
from .ui.toolbar import FloatingToolbar
from .updater import (
    ReleaseInfo,
    UpdateCheckThread,
    UpdateDownloadThread,
    can_self_update,
    is_newer,
    launch_installer,
)
from .win32 import apply_capture_affinity, is_user_admin, native_window_rect, set_hide_from_capture, user32
from .workers import (
    HAS_RAPIDOCR,
    HAS_RU_WINOCR,
    HAS_WINOCR,
    FrameWatchdogThread,
    LazyRapidOCR,
    ModelLoaderThread,
    NativeCT2TranslationWorker,
    OcrWorkerThread,
)

# Окна оболочки Windows: по ним нельзя понять, какой монитор переводить.
SHELL_WINDOW_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow"}


def _key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


# ==============================================================================
# КОНТРОЛЛЕР v3.0: ОВЕРЛЕИ ПО МОНИТОРАМ, F8/F9, СНИМОК ЭКРАНА, OCR И ПЕРЕВОД
# ==============================================================================
class GhostTranslateController(QWidget):
    """Невидимое окно-диспетчер. Его HWND нужен только для RegisterHotKey (WM_HOTKEY)."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GhostTranslate Controller v{APP_VERSION}")
        self.setWindowFlags(Qt.WindowType.Tool)

        # Плашки и область захвата хранятся в логических координатах внутри target_screen.
        self.overlay_blocks: List[OverlayBlock] = []
        self.target_screen: Optional[QScreen] = None
        self.region_rect: Optional[QRect] = None
        self.show_region_border = False
        self._last_capture_dpr = 1.0
        self.ocr_backend: str = DEFAULT_OCR_BACKEND
        self.plaque_render_mode: str = DEFAULT_RENDER_STYLE
        self.font_cfg: FontCustomConfig = FontCustomConfig.load()
        set_hide_from_capture(not self.font_cfg.game_mode)
        # Игровой режим: плашки погашены, снимок ждёт, пока DWM покажет пустой оверлей.
        self.capture_veiled = False
        self._grab_scheduled = False
        self._grab_check_static = True
        self._grab_generation = 0
        self.job_id: int = 0
        self.monitor_interval_ms: int = 0

        self.pipeline_busy: bool = False
        self.pending_rescan: bool = False
        self.is_hidden: bool = False
        self._check_seq_on_complete = False
        self._retranslate_when_idle = False

        self.sct = open_mss()
        self._last_grab_warn_ts: float = 0.0
        # Кадр последнего запуска конвейера: из него вырезается эталон для watchdog.
        self._frame_bgra: Optional[np.ndarray] = None
        self._frame_region: Optional[Dict[str, int]] = None
        # Последнее активное окно чужой программы: «Весь экран» переводит его монитор.
        self._last_external_hwnd: int = 0
        self.ocr_engine = LazyRapidOCR() if HAS_RAPIDOCR else None
        if self.ocr_engine is not None and (self.ocr_backend == "RapidOCR" or not HAS_WINOCR):
            self.ocr_engine.preload()
        self.lru_cache = TranslationLRUCache(LRU_MAX_SIZE)

        self._live_threads: List[QThread] = []
        self.ocr_thread: Optional[OcrWorkerThread] = None
        self.trans_thread: Optional[NativeCT2TranslationWorker] = None

        self.model_loader = ModelLoaderThread()
        self.model_loader.loaded.connect(self._on_model_loaded)
        self._track_thread(self.model_loader)
        self.model_loader.start()

        self.prev_small_gray: Optional[np.ndarray] = None
        self.prev_ocr_signature: str = ""

        self.monitor_timer = QTimer(self)
        self.monitor_timer.setSingleShot(True)
        self.monitor_timer.timeout.connect(self.on_auto_monitor_tick)

        self.watchdog = FrameWatchdogThread()
        self.watchdog.screen_changed.connect(self._on_watchdog_screen_changed)
        self.watchdog.start()

        self.overlays: List[ScreenOverlay] = []
        self.snip_overlays: List[SnipOverlay] = []
        self._retired_widgets: List[QWidget] = []

        # Пункт 3.2 ТЗ v3.0: Мини-таблетка маячок при скрытии по F8
        self.mini_pill = MiniRestorePill()
        self.mini_pill.restore_clicked.connect(self.toggle_visibility)

        # Пункт 2 ТЗ v3.0: Плавающий попап настройки шрифта Aa
        self.font_popup = FontSettingsPopup(self.font_cfg)
        self.font_popup.settings_changed.connect(self._on_font_settings_updated)
        self.font_popup.hotkeys_changed.connect(self._on_hotkeys_changed)
        self.font_popup.hotkey_capture_active.connect(self._set_hotkeys_suspended)
        self.font_popup.game_mode_changed.connect(self._on_game_mode_changed)
        self.font_popup.timer_scan_mode_changed.connect(self._on_timer_scan_mode_changed)

        self.log_dialog = LogViewerDialog()
        self.log_dialog.btn_copy.clicked.connect(self.export_and_copy_logs)
        self.log_dialog.btn_bundle.clicked.connect(self.save_diagnostic_bundle)

        self.toolbar = FloatingToolbar(self.font_cfg.toolbar_anchor, self.font_cfg.timer_scan_mode)
        self.toolbar.anchor_changed.connect(self._on_toolbar_anchor_changed)
        self.toolbar.fullscreen_clicked.connect(self.capture_full_screen)
        self.toolbar.region_snip_clicked.connect(self.start_snipping_mode)
        self.toolbar.stop_clicked.connect(self.stop_translation_and_clear)
        self.toolbar.ocr_backend_toggled.connect(self.set_ocr_backend)
        self.toolbar.render_style_changed.connect(self.set_render_style)
        self.toolbar.font_popup_toggled.connect(self.toggle_font_popup)
        self.toolbar.timer_changed.connect(self.set_timer_interval)
        self.toolbar.timer_scan_mode_toggled.connect(self._on_toolbar_timer_scan_mode_toggled)
        self.toolbar.hide_toggle_clicked.connect(self.toggle_visibility)
        self.toolbar.logs_clicked.connect(self.show_logs_modal)
        self.toolbar.exit_clicked.connect(self.emergency_shutdown)

        app = QApplication.instance()
        app.screenAdded.connect(self._on_screen_added)
        app.screenRemoved.connect(self._on_screen_removed)
        app.primaryScreenChanged.connect(self._on_primary_screen_changed)
        for screen in QApplication.screens():
            self._add_overlay(screen)

        self._update_release: Optional[ReleaseInfo] = None
        self._update_check_thread: Optional[UpdateCheckThread] = None
        self._update_check_manual = False
        self._update_download: Optional[UpdateDownloadThread] = None
        self._update_progress: Optional[QProgressDialog] = None
        self._tray_message_kind = ""
        self._init_tray_icon()
        self.hotkey_toggle: Hotkey = parse_hotkey(self.font_cfg.hotkey_toggle)
        self.hotkey_snip: Hotkey = parse_hotkey(self.font_cfg.hotkey_snip)
        self._hotkeys_suspended = False
        self._apply_hotkey_labels()
        self.toolbar.show()
        self._register_global_hotkeys()
        self._init_win32_input_poller()

        admin_status = "ДА (Оверлей поверх игр активен)" if is_user_admin() else "НЕТ (Рекомендуется запуск от Админа)"
        log_event(
            f"GhostTranslate v{APP_VERSION} запущен (Движок={TRANSLATION_ENGINE}, OCR={self.ocr_backend}, "
            f"русский OCR для отсева кириллицы={'да' if HAS_RU_WINOCR else 'нет'}, "
            f"Хоткеи={self.hotkey_toggle.text}/{self.hotkey_snip.text}, Админ={admin_status}, "
            f"Настройки и журнал: {DATA_DIR}, Экраны: {self._describe_screens()})"
        )
        if self.font_cfg.sound_enabled:
            play_startup_sound()
        if self.font_cfg.check_updates:
            QTimer.singleShot(UPDATE_CHECK_DELAY_MS, self.check_for_updates)

    def _init_tray_icon(self):
        pix = QPixmap(16, 16)
        pix.fill(QColor("#00E5FF"))
        self.tray = QSystemTrayIcon(QIcon(pix), self)
        menu = QMenu()
        act_full = QAction("Перевести весь экран", self)
        act_full.triggered.connect(self.capture_full_screen)
        self.tray_act_snip = QAction(self)
        self.tray_act_snip.triggered.connect(self.start_snipping_mode)
        self.tray_act_toggle = QAction(self)
        self.tray_act_toggle.triggered.connect(self.toggle_visibility)
        act_font = QAction("Настройки (Aa Шрифт)", self)
        act_font.triggered.connect(self.toggle_font_popup)
        act_stop = QAction("Стоп и очистить", self)
        act_stop.triggered.connect(self.stop_translation_and_clear)
        act_logs = QAction("Открыть журнал и бенчмарк", self)
        act_logs.triggered.connect(self.show_logs_modal)
        self.tray_act_update = QAction("Проверить обновления", self)
        self.tray_act_update.triggered.connect(self._on_update_action)
        act_auto_update = QAction("Проверять обновления при запуске", self)
        act_auto_update.setCheckable(True)
        act_auto_update.setChecked(self.font_cfg.check_updates)
        act_auto_update.toggled.connect(self._set_check_updates)
        act_exit = QAction("Полный выход [X]", self)
        act_exit.triggered.connect(self.emergency_shutdown)
        menu.addAction(act_full)
        menu.addAction(self.tray_act_snip)
        menu.addAction(self.tray_act_toggle)
        menu.addAction(act_font)
        menu.addAction(act_stop)
        menu.addAction(act_logs)
        menu.addSeparator()
        menu.addAction(self.tray_act_update)
        menu.addAction(act_auto_update)
        menu.addSeparator()
        menu.addAction(act_exit)
        self.tray.setContextMenu(menu)
        self.tray.messageClicked.connect(self._on_tray_message_clicked)
        self.tray.show()

    def _show_tray_message(
        self,
        title: str,
        text: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        kind: str = "",
        timeout_ms: int = 3000,
    ) -> None:
        # Сигнал messageClicked у всех уведомлений общий; kind говорит, на какое из них нажали.
        self._tray_message_kind = kind
        self.tray.showMessage(title, text, icon, timeout_ms)

    def _on_tray_message_clicked(self) -> None:
        if self._tray_message_kind == "update":
            self.offer_update()

    # ------------------------------------------------------------------ обновления
    def _set_check_updates(self, enabled: bool) -> None:
        self.font_cfg.check_updates = enabled
        self.font_cfg.save()

    def _on_update_action(self) -> None:
        if self._update_release is not None:
            self.offer_update()
        else:
            self.check_for_updates(manual=True)

    def check_for_updates(self, manual: bool = False) -> None:
        if self._update_check_thread is not None or self._update_download is not None:
            return
        self._update_check_manual = manual
        thread = UpdateCheckThread()
        thread.checked.connect(self._on_update_checked)
        self._update_check_thread = thread
        self._track_thread(thread)
        thread.start()

    def _on_update_checked(self, release: Optional[ReleaseInfo], error: str) -> None:
        self._update_check_thread = None
        manual = self._update_check_manual
        if error:
            log_event(f"Проверка обновлений не удалась: {error}", "WARN")
            if manual:
                self._show_tray_message(
                    "Проверка обновлений", f"Не удалось связаться с GitHub: {error}",
                    QSystemTrayIcon.MessageIcon.Warning,
                )
            return
        if release is None or not is_newer(release.version):
            latest = f"v{release.version}" if release else "релиз без установщика"
            log_event(f"Обновлений нет: установлена v{APP_VERSION}, последний релиз {latest}")
            if manual:
                self._show_tray_message("Проверка обновлений", f"У вас последняя версия: v{APP_VERSION}.")
            return
        self._update_release = release
        self.tray_act_update.setText(f"Обновить до v{release.version}")
        log_event(f"Доступно обновление v{release.version}: {release.asset_name}, "
                  f"{release.asset_size / (1024 * 1024):.0f} МБ, sha256={'есть' if release.sha256 else 'нет'}")
        if manual:
            self.offer_update()
        else:
            self._show_tray_message(
                f"Доступна GhostTranslate v{release.version}",
                "Нажмите на это уведомление или выберите «Обновить» в меню значка.",
                kind="update",
                timeout_ms=10000,
            )

    def offer_update(self) -> None:
        release = self._update_release
        if release is None or self._update_download is not None:
            return
        box = QMessageBox()
        box.setWindowTitle(f"GhostTranslate v{APP_VERSION}")
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"Доступна версия {release.version}. Скачать установщик "
                    f"({release.asset_size / (1024 * 1024):.0f} МБ) и обновиться?")
        box.setInformativeText("Программа закроется, установка пройдёт сама и запустит новую версию. "
                               "Настройки сохранятся.")
        notes = release.notes.strip()
        if notes:
            box.setDetailedText(notes)
        update_button = box.addButton("Обновить", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Позже", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not update_button:
            return
        if not can_self_update():
            QMessageBox.information(
                None, f"GhostTranslate v{APP_VERSION}",
                "Программа запущена из исходников: обновите её через git pull. "
                "Установщик ставится только поверх собранной версии.",
            )
            return
        self._start_update_download(release)

    def _start_update_download(self, release: ReleaseInfo) -> None:
        thread = UpdateDownloadThread(release)
        dialog = QProgressDialog(f"Загрузка GhostTranslate v{release.version}...", "Отмена", 0, 100)
        dialog.setWindowTitle(f"GhostTranslate v{APP_VERSION}")
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(thread.requestInterruption)
        thread.progress.connect(self._on_update_progress)
        thread.done.connect(self._on_update_downloaded)
        self._update_download = thread
        self._update_progress = dialog
        self._track_thread(thread)
        log_event(f"Загрузка обновления v{release.version}: {release.asset_url}")
        dialog.show()
        thread.start()

    def _on_update_progress(self, received: int, total: int) -> None:
        if self._update_progress is None or total <= 0:
            return
        self._update_progress.setValue(min(100, received * 100 // total))
        self._update_progress.setLabelText(
            f"Загрузка GhostTranslate v{self._update_release.version}: "
            f"{received / (1024 * 1024):.0f} из {total / (1024 * 1024):.0f} МБ"
        )

    def _on_update_downloaded(self, path: str, error: str) -> None:
        self._update_download = None
        if self._update_progress is not None:
            self._update_progress.close()
            self._update_progress = None
        if not path:
            if error:
                log_event(f"Не удалось скачать обновление: {error}", "ERROR")
                QMessageBox.warning(None, f"GhostTranslate v{APP_VERSION}", f"Не удалось скачать обновление: {error}")
            else:
                log_event("Загрузка обновления отменена")
            return
        log_event(f"Обновление скачано в {path}, запуск установщика")
        try:
            launch_installer(path)
        except OSError as exc:
            log_event(f"Установщик не запустился: {exc}", "ERROR")
            QMessageBox.warning(None, f"GhostTranslate v{APP_VERSION}", f"Установщик не запустился: {exc}")
            return
        # Установщик ждёт, пока освободится мьютекс экземпляра, — выход его и освобождает.
        self.emergency_shutdown()

    def _apply_hotkey_labels(self) -> None:
        toggle, snip = self.hotkey_toggle.text, self.hotkey_snip.text
        self.toolbar.set_hotkey_labels(toggle, snip)
        self.mini_pill.set_hotkey_label(toggle)
        self.tray.setToolTip(f"GhostTranslate AR v{APP_VERSION} ({toggle}: Скрыть/Показать · {snip}: Область)")
        self.tray_act_snip.setText(f"Выделить область ({snip})")
        self.tray_act_toggle.setText(f"Скрыть / Показать ({toggle})")

    def toggle_font_popup(self):
        if self.font_popup.isVisible():
            self.font_popup.hide()
        else:
            tb_geom = self.toolbar.geometry()
            x = tb_geom.x() + (tb_geom.width() - self.font_popup.width()) // 2
            y = tb_geom.bottom() + 6
            screen = self.toolbar.screen()
            if screen is not None:
                geo = screen.geometry()
                x = max(geo.x(), min(x, geo.x() + geo.width() - self.font_popup.width()))
                if y + self.font_popup.height() > geo.y() + geo.height():
                    y = max(geo.y(), tb_geom.top() - 6 - self.font_popup.height())
            self.font_popup.move(x, y)
            self.font_popup.show()
            self.font_popup.raise_()
            self.font_popup.activateWindow()

    def _on_toolbar_anchor_changed(self, anchor) -> None:
        self.font_cfg.toolbar_anchor = tuple(anchor) if anchor else None
        self.font_cfg.save()

    def _on_font_settings_updated(self):
        # Пункт 2.2 ТЗ v3.0: Мгновенное живое превью на текущих плашках без повторного OCR
        self._refresh_overlays()

    def _own_windows(self) -> List[QWidget]:
        return [*self.overlays, self.toolbar, self.font_popup, self.log_dialog, self.mini_pill]

    def _on_game_mode_changed(self, enabled: bool) -> None:
        set_hide_from_capture(not enabled)
        # Скрытые окна получат режим в showEvent; видимым он ставится сразу.
        for window in self._own_windows():
            if window.isVisible():
                apply_capture_affinity(window)
        if enabled:
            self.watchdog.disarm()
        else:
            self._arm_watchdog()
        log_event(
            "Игровой режим включён: окна видны захвату экрана, плашки гаснут на время снимка, watchdog отключён"
            if enabled
            else "Игровой режим выключен: окна снова скрыты от захвата экрана"
        )

    def _on_timer_scan_mode_changed(self, mode: str) -> None:
        self.toolbar.set_timer_scan_mode(mode)
        log_event(f"Режим обновления таймера переключен на: {mode}")

    def _on_toolbar_timer_scan_mode_toggled(self, mode: str) -> None:
        self.font_cfg.timer_scan_mode = mode
        self.font_cfg.save()
        self.font_popup.set_timer_scan_mode(mode)
        log_event(f"Режим обновления таймера переключен с панели на: {mode}")

    # --------------------------------------------------------------------------
    # ПОТОКИ: ССЫЛКА ДЕРЖИТСЯ ДО finished, ИНАЧЕ QThread УДАЛЯЕТСЯ ВО ВРЕМЯ run()
    # --------------------------------------------------------------------------
    def _track_thread(self, thread: QThread) -> None:
        self._live_threads.append(thread)
        thread.finished.connect(lambda t=thread: self._release_thread(t))

    def _release_thread(self, thread: QThread) -> None:
        thread.wait()
        if thread in self._live_threads:
            self._live_threads.remove(thread)

    def _retire_widgets_later(self, widgets: List[QWidget]) -> None:
        """Окна прячутся сразу, а ссылки отпускаются на следующем витке цикла событий.

        Окно без родителя принадлежит Python: потеря последней ссылки внутри его же
        обработчика мыши удалит C++-объект посреди вызова.
        """
        for widget in widgets:
            widget.hide()
        self._retired_widgets.extend(widgets)
        QTimer.singleShot(0, self._drop_retired_widgets)

    def _drop_retired_widgets(self) -> None:
        retired = self._retired_widgets
        self._retired_widgets = []
        for widget in retired:
            widget.deleteLater()

    # --------------------------------------------------------------------------
    # МОНИТОРЫ: ПО ОДНОМУ ОВЕРЛЕЮ НА ЭКРАН, РЕАКЦИЯ НА ПОДКЛЮЧЕНИЕ И СМЕНУ РАЗРЕШЕНИЯ
    # --------------------------------------------------------------------------
    @staticmethod
    def _describe_screens() -> str:
        parts = []
        for s in QApplication.screens():
            geo = s.geometry()
            native = screen_native_rect(geo, s.devicePixelRatio())
            parts.append(
                f"{s.name()} {native.width()}x{native.height()} @ ({native.x()},{native.y()}) "
                f"масштаб {s.devicePixelRatio():.2f}"
            )
        return "; ".join(parts)

    def _add_overlay(self, screen: QScreen) -> None:
        overlay = ScreenOverlay(self, screen)
        screen.geometryChanged.connect(lambda _geo, s=screen: self._on_screen_geometry_changed(s))
        self.overlays.append(overlay)
        if not self.is_hidden:
            overlay.show()

    def _refresh_overlays(self) -> None:
        for overlay in self.overlays:
            overlay.refresh()

    def _on_screen_added(self, screen: QScreen) -> None:
        self._add_overlay(screen)
        self._cancel_snipping()
        log_event(f"Подключён монитор {screen.name()}. Экраны: {self._describe_screens()}")

    def _on_screen_removed(self, screen: QScreen) -> None:
        if self.target_screen is screen:
            self._reset_capture_target(f"отключён монитор {screen.name()}")
        gone = [o for o in self.overlays if o.target_screen is screen]
        self.overlays = [o for o in self.overlays if o.target_screen is not screen]
        self._retire_widgets_later(gone)
        self._cancel_snipping()
        # Панель могла стоять на отключённом мониторе; Qt удаляет экран из списка уже после сигнала.
        QTimer.singleShot(0, self.toolbar.reposition)
        log_event(f"Отключён монитор {screen.name()}")

    def _on_screen_geometry_changed(self, screen: QScreen) -> None:
        for overlay in self.overlays:
            if overlay.target_screen is screen:
                overlay.fit_to_screen()
        if self.target_screen is screen:
            self._reset_capture_target(f"изменились разрешение или масштаб монитора {screen.name()}")
        self.toolbar.reposition()
        log_event(f"Изменилась геометрия монитора {screen.name()}. Экраны: {self._describe_screens()}")

    def _on_primary_screen_changed(self, _screen: QScreen) -> None:
        self.toolbar.reposition()

    def _reset_capture_target(self, reason: str) -> None:
        """Координаты плашек и области больше не совпадают с экраном, поэтому всё сбрасывается."""
        self._cancel_active_job()
        self.target_screen = None
        self.region_rect = None
        self.show_region_border = False
        self.prev_ocr_signature = ""
        self.prev_small_gray = None
        self._frame_bgra = None
        self._frame_region = None
        self._abort_scheduled_grab()
        self.clear_all_plaques()
        log_event(f"Область захвата сброшена: {reason}", "WARN")

    # --------------------------------------------------------------------------
    # СНИМОК ЭКРАНА
    # --------------------------------------------------------------------------
    def _capture_target(self) -> Tuple[Optional[QScreen], QRect]:
        """Экран и прямоугольник в его логических координатах. По умолчанию основной монитор целиком."""
        screen = self.target_screen or QApplication.primaryScreen()
        if screen is None:
            return None, QRect()
        if self.region_rect is not None and self.target_screen is not None:
            return screen, QRect(self.region_rect)
        geo = screen.geometry()
        return screen, QRect(0, 0, geo.width(), geo.height())

    def _active_capture_mss_region(self) -> Optional[Dict[str, int]]:
        screen, local_rect = self._capture_target()
        if screen is None:
            return None
        dpr = max(1.0, float(screen.devicePixelRatio()))
        self._last_capture_dpr = dpr
        return native_capture_region(screen.geometry(), dpr, local_rect)

    def safe_grab_screen(self, region: Optional[Dict[str, int]] = None) -> Optional[np.ndarray]:
        target = region if region is not None else self._active_capture_mss_region()
        if target is None:
            return None
        try:
            shot = self.sct.grab(target)
            arr = np.array(shot)
            if arr is None or arr.size == 0:
                return None
            return arr
        except Exception as exc:
            now = time.monotonic()
            if now - self._last_grab_warn_ts >= 5.0:
                self._last_grab_warn_ts = now
                log_event(
                    f"Экран временно недоступен (Secure Desktop / UAC: {exc}), пропуск кадра",
                    "WARN",
                )
            try:
                self.sct = open_mss()
            except Exception:
                pass
            return None

    # --------------------------------------------------------------------------
    # ПУНКТ 3.2 ТЗ v3.0: F8 — СКРЫТЬ / ПОКАЗАТЬ ОВЕРЛЕЙ И ПАНЕЛЬ ("👻 GT [F8]")
    # --------------------------------------------------------------------------
    def toggle_visibility(self):
        self.is_hidden = not self.is_hidden
        key = self.hotkey_toggle.text
        if self.is_hidden:
            self.monitor_timer.stop()
            self.watchdog.disarm()
            self._abort_scheduled_grab()
            self._cancel_snipping()
            self.font_popup.hide()
            self.toolbar.hide()
            for overlay in self.overlays:
                overlay.hide()
            self.mini_pill.show()
            self.mini_pill.raise_()
            log_event(f"Оверлей и панель скрыты (Клавиша {key}) -> показан маячок 👻 GT [{key}]")
        else:
            self.mini_pill.hide()
            for overlay in self.overlays:
                overlay.show()
            self.toolbar.show()
            self.toolbar.raise_()
            self._refresh_overlays()
            if self.monitor_interval_ms > 0:
                self._schedule_next_monitor_tick()
                self._arm_watchdog()
            log_event(f"Оверлей и панель раскрыты обратно (Клавиша {key})")

    def bring_to_front(self) -> None:
        """Повторный запуск exe: вместо второй копии показывается эта."""
        if self.is_hidden:
            self.toggle_visibility()
        else:
            self.toolbar.show()
            self.toolbar.raise_()
        self._show_tray_message(f"GhostTranslate v{APP_VERSION}", "Программа уже запущена, вторая копия не нужна.")
        log_event("Повторный запуск: вторая копия закрыта, показана панель этой")

    def clear_all_plaques(self):
        self.overlay_blocks.clear()
        self.watchdog.disarm()
        self._refresh_overlays()

    def set_ocr_backend(self, backend: str):
        self.ocr_backend = backend
        self.prev_ocr_signature = ""
        log_event(f"[SWITCH] Движок OCR переключен на: {backend}")
        if backend == "RapidOCR" and self.ocr_engine is not None:
            self.ocr_engine.preload()
        if self.overlay_blocks and not self.pipeline_busy:
            self._trigger_capture_pipeline(check_static=False)

    def set_render_style(self, style_id: str):
        self.plaque_render_mode = style_id
        log_event(f"[RENDER_STYLE] Стиль отрисовки плашек переключен на: {style_id}")
        self._refresh_overlays()

    def set_timer_interval(self, mode_text: str):
        self.monitor_timer.stop()
        if mode_text == "Ручной":
            self.monitor_interval_ms = 0
            self.watchdog.disarm()
            self.toolbar.set_stop_active(False)
            log_event("Режим таймера переключен в 'Ручной' (Watchdog 150ms отключен)")
            return
        sec = float(mode_text.replace("s", ""))
        self.monitor_interval_ms = int(sec * 1000)
        self.toolbar.set_stop_active(True)
        log_event(f"Включен SingleShot авто-мониторинг с интервалом {mode_text}")
        self._arm_watchdog()
        self._schedule_next_monitor_tick()

    def _schedule_next_monitor_tick(self):
        if self.monitor_interval_ms > 0 and not self.is_hidden and not self.pipeline_busy:
            self.monitor_timer.start(self.monitor_interval_ms)

    def _cancel_active_job(self):
        """Новый ручной запрос важнее текущего: результаты старой задачи отбрасываются по job_id."""
        self.job_id += 1
        self.pipeline_busy = False
        if self.trans_thread is not None and self.trans_thread.isRunning():
            self.trans_thread.stop()

    def stop_translation_and_clear(self):
        self._cancel_active_job()
        self.pending_rescan = False
        self._retranslate_when_idle = False
        self.monitor_interval_ms = 0
        self.monitor_timer.stop()
        self.watchdog.disarm()
        self._abort_scheduled_grab()
        self.toolbar.timer_combo.blockSignals(True)
        self.toolbar.timer_combo.setCurrentText("Ручной")
        self.toolbar.timer_combo.blockSignals(False)
        self.toolbar.set_stop_active(False)

        self.prev_ocr_signature = ""
        self.target_screen = None
        self.region_rect = None
        self.show_region_border = False
        self.clear_all_plaques()
        log_event(f"Остановка перевода и полная очистка экрана (job_id={self.job_id})")

    def build_diagnostic_report(self) -> str:
        report_lines = [
            f"=== GhostTranslate v{APP_VERSION} Diagnostic Report ===",
            f"OS: {platform.system()} {platform.release()} ({platform.version()}) | Admin={is_user_admin()}",
            f"Screens: {self._describe_screens()}",
            f"Translation Engine: {TRANSLATION_ENGINE} (GAME_UI_DICT={len(GAME_UI_DICT)} words, "
            f"chunk={TRANSLATE_CHUNK_BLOCKS}, max blocks per frame={MAX_BLOCKS_PER_FRAME})",
            f"Active OCR Backend: {self.ocr_backend} (HAS_WINOCR={HAS_WINOCR}, RU filter={HAS_RU_WINOCR}, "
            f"RapidOCR max_side={RAPIDOCR_MAX_SIDE}, threads={RAPIDOCR_THREADS}, "
            f"en rec model={os.path.isfile(RAPIDOCR_REC_MODEL_PATH)})",
            f"Settings ({DATA_DIR}): {self.font_cfg.to_dict()}",
            f"Global Hotkeys: {self.hotkey_toggle.text} (Hide/Restore) | {self.hotkey_snip.text} (Region Snip) | "
            f"RegisterHotKey={self._hotkeys_registered}",
            f"Benchmark Summary: {format_benchmark_summary()}",
            f"LRU Cache Size: {len(self.lru_cache)}/{LRU_MAX_SIZE} | Active Blocks: {len(self.overlay_blocks)}",
            "--- Recent Events ---",
            *list(LOG_RING_BUFFER),
        ]
        return "\n".join(report_lines)

    def show_logs_modal(self):
        self.log_dialog.refresh_view()
        self.log_dialog.show()
        self.log_dialog.raise_()

    def export_and_copy_logs(self):
        report_text = self.build_diagnostic_report()
        QApplication.clipboard().setText(report_text)
        log_event(f"Отчет v{APP_VERSION} скопирован в буфер обмена")
        if self.log_dialog.isVisible():
            self.log_dialog.refresh_view()

    def save_diagnostic_bundle(self):
        report_text = self.build_diagnostic_report()
        try:
            with open(BUNDLE_FILE_PATH, "w", encoding="utf-8") as f:
                f.write(report_text)
            log_event(f"Диагностический бандл сохранен в {BUNDLE_FILE_PATH}")
            os.startfile(BUNDLE_FILE_PATH)
        except Exception as exc:
            log_event(f"Ошибка сохранения бандла: {exc}", "ERROR")
        if self.log_dialog.isVisible():
            self.log_dialog.refresh_view()

    # --------------------------------------------------------------------------
    # ПУНКТ 3.2 ТЗ v3.0: F9 — ВЫДЕЛЕНИЕ ОБЛАСТИ ОБЫЧНОЙ ЛКМ (ОКНО САМО ЛОВИТ МЫШЬ)
    # --------------------------------------------------------------------------
    def start_snipping_mode(self):
        if self.is_hidden:
            self.toggle_visibility()
        if self.snip_overlays:
            return
        self.font_popup.hide()
        # Затемнение выделения попадает в снимок и сработало бы как смена экрана.
        self.watchdog.disarm()
        for screen in QApplication.screens():
            snip = SnipOverlay(screen)
            snip.region_selected.connect(self._on_snip_selected)
            snip.cancelled.connect(self._on_snip_cancelled)
            self.snip_overlays.append(snip)
            snip.show()
        under_cursor = QApplication.screenAt(QCursor.pos())
        for snip in self.snip_overlays:
            if snip.target_screen is under_cursor:
                snip.raise_()
                snip.activateWindow()
        log_event(
            f"Режим выделения области активирован ({self.hotkey_snip.text}): выделите рамку ЛКМ, Esc или ПКМ — отмена"
        )

    def _cancel_snipping(self) -> bool:
        if not self.snip_overlays:
            return False
        active = self.snip_overlays
        self.snip_overlays = []
        self._retire_widgets_later(active)
        return True

    def _on_snip_cancelled(self):
        if self._cancel_snipping():
            log_event("Выделение области отменено")
            self._schedule_next_monitor_tick()
            # Окна выделения прячутся не мгновенно; эталон кадра под плашками их не содержит.
            QTimer.singleShot(SNIP_HIDE_SETTLE_MS, self._arm_watchdog)

    def _on_snip_selected(self, screen: QScreen, rect: QRect):
        self._cancel_snipping()
        if screen not in QApplication.screens():
            return
        self._cancel_active_job()
        self.target_screen = screen
        self.region_rect = QRect(rect)
        self.show_region_border = True
        self.prev_ocr_signature = ""
        self.clear_all_plaques()
        log_event(
            f"Выделена новая область [{self.hotkey_snip.text}] на мониторе {screen.name()}: "
            f"x={rect.x()}, y={rect.y()}, w={rect.width()}, h={rect.height()}"
        )
        # Затемнение выделения попадает в снимок, пока DWM не перерисовал экран после его скрытия.
        job_at_selection = self.job_id
        QTimer.singleShot(SNIP_HIDE_SETTLE_MS, lambda: self._capture_if_job_unchanged(job_at_selection))

    def _capture_if_job_unchanged(self, job_id: int):
        if job_id == self.job_id:
            self._trigger_capture_pipeline(check_static=False)

    def _track_foreground_window(self) -> None:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or hwnd == self._last_external_hwnd:
            return
        try:
            _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return
        if pid != os.getpid():
            self._last_external_hwnd = hwnd

    def _screen_of_last_external_window(self) -> Optional[QScreen]:
        """Монитор окна, с которым пользователь работал до щелчка по панели или трею."""
        hwnd = self._last_external_hwnd
        try:
            if not hwnd or not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
                return None
            if win32gui.GetClassName(hwnd) in SHELL_WINDOW_CLASSES:
                return None
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return None
        return screen_at_native_point(QApplication.screens(), (left + right) // 2, (top + bottom) // 2)

    def capture_full_screen(self):
        # Панель стоит на своём мониторе, а игра может быть на соседнем: курсор при щелчке
        # всегда над панелью, поэтому монитор берётся по последнему активному чужому окну.
        screen = (
            self._screen_of_last_external_window()
            or QApplication.screenAt(QCursor.pos())
            or QApplication.primaryScreen()
        )
        if screen is None:
            return
        self._cancel_snipping()
        self._cancel_active_job()
        self.target_screen = screen
        self.region_rect = None
        self.show_region_border = False
        self.prev_ocr_signature = ""
        self.clear_all_plaques()
        log_event(f"Весь экран: монитор {screen.name()}")
        self._trigger_capture_pipeline(check_static=False)

    def on_auto_monitor_tick(self):
        if self.monitor_interval_ms <= 0 or self.is_hidden:
            return
        check_static = getattr(self.font_cfg, "timer_scan_mode", "smart_grid") != "forced_full"
        self._trigger_capture_pipeline(check_static=check_static)

    def _arm_watchdog(self) -> None:
        """Следит за областью захвата или прямоугольником вокруг плашек: смена картинки там значит, что перевод устарел."""
        self.watchdog.disarm()
        # В игровом режиме плашки попадают в снимок, и watchdog видел бы их вместо картинки под ними.
        if (
            self.monitor_interval_ms <= 0
            or self.font_cfg.game_mode
            or self.is_hidden
            or self.pipeline_busy
            or self.snip_overlays
            or not self.overlay_blocks
            or self._frame_bgra is None
            or self._frame_region is None
            or self.target_screen is None
        ):
            return
        screen, capture_rect = self._capture_target()
        if self.region_rect is not None:
            watch_rect = QRect(self.region_rect).intersected(capture_rect)
        else:
            union = QRect()
            for block in self.overlay_blocks:
                union = union.united(block.rect)
            pad = WATCHDOG_PADDING_PX
            v_pad = WATCHDOG_CHAT_VERT_PAD_PX
            watch_rect = union.adjusted(-pad, -v_pad, pad, v_pad).intersected(capture_rect)
        if watch_rect.isEmpty():
            return
        region = native_capture_region(screen.geometry(), self._last_capture_dpr, watch_rect)
        crop = crop_to_region(self._frame_bgra, self._frame_region, region)
        if crop is None:
            return
        self.watchdog.arm(region, compute_small_gray_numpy(crop), self.job_id)

    def _on_watchdog_screen_changed(self, diff: float, token: int) -> None:
        if (
            token != self.job_id
            or self.monitor_interval_ms <= 0
            or self.is_hidden
            or self.pipeline_busy
            or self.snip_overlays
            or not self.overlay_blocks
        ):
            return
        log_event(f"Watchdog: картинка под плашками сменилась (diff={diff:.2f}), пересканирование")
        self.prev_ocr_signature = ""
        self.clear_all_plaques()
        self._trigger_capture_pipeline(check_static=False)

    def _merge_with_persistent_blocks(self, new_blocks: List[OverlayBlock]) -> List[OverlayBlock]:
        if not self.overlay_blocks:
            return new_blocks

        for nb in new_blocks:
            if not nb.is_pending:
                continue
            nb_stripped = nb.orig_text.strip()
            for ob in self.overlay_blocks:
                if ob.is_pending or ob.is_fallback:
                    continue
                if (
                    abs(nb.rect.x() - ob.rect.x()) <= 28
                    and abs(nb.rect.y() - ob.rect.y()) <= 22
                    and nb_stripped == ob.orig_text.strip()
                ):
                    nb.trans_text = ob.trans_text
                    nb.is_pending = False
                    self.lru_cache.put(nb.orig_text, ob.trans_text)
                    break
        return new_blocks

    # --------------------------------------------------------------------------
    # КОНВЕЙЕР: СНИМОК -> OCR -> ПЕРЕВОД
    # --------------------------------------------------------------------------
    def _trigger_capture_pipeline(self, check_static: bool = False):
        if self.is_hidden:
            return
        if self.snip_overlays:
            self._schedule_next_monitor_tick()
            return
        if self._grab_scheduled:
            # Ручной запрос во время ожидания снимка отменяет проверку «экран не изменился».
            self._grab_check_static = self._grab_check_static and check_static
            return
        if self.pipeline_busy or (self.ocr_thread is not None and self.ocr_thread.isRunning()):
            self.pending_rescan = True
            return

        screen, _local_rect = self._capture_target()
        if screen is None:
            return
        if self.target_screen is not screen:
            self.target_screen = screen
            self._refresh_overlays()

        if not self.font_cfg.game_mode:
            self._grab_and_start(check_static)
            return
        self._grab_scheduled = True
        self._grab_check_static = check_static
        self.capture_veiled = True
        self._refresh_overlays()
        generation = self._grab_generation
        QTimer.singleShot(CAPTURE_VEIL_SETTLE_MS, lambda: self._grab_after_veil(generation))

    def _abort_scheduled_grab(self) -> None:
        self._grab_generation += 1
        self._grab_scheduled = False
        if self.capture_veiled:
            self.capture_veiled = False
            self._refresh_overlays()

    def _grab_after_veil(self, generation: int) -> None:
        if generation != self._grab_generation or not self._grab_scheduled:
            return
        self._grab_scheduled = False
        busy = self.pipeline_busy or (self.ocr_thread is not None and self.ocr_thread.isRunning())
        if self.is_hidden or self.snip_overlays or busy:
            self.capture_veiled = False
            self._refresh_overlays()
            if busy:
                self.pending_rescan = True
            else:
                self._schedule_next_monitor_tick()
            return
        self._grab_and_start(self._grab_check_static)

    def _grab_own_screen_frame(self, region: Optional[Dict[str, int]]) -> Optional[np.ndarray]:
        """Снимок без собственных плашек: в игровом режиме они погашены, панель и попап закрашиваются."""
        img_bgra = self.safe_grab_screen(region)
        if not self.capture_veiled:
            return img_bgra
        self.capture_veiled = False
        self._refresh_overlays()
        if img_bgra is not None and region is not None:
            panels = [w for w in (self.toolbar, self.font_popup, self.log_dialog) if w.isVisible()]
            mask_native_rects(img_bgra, region, [native_window_rect(w) for w in panels])
        return img_bgra

    def _grab_and_start(self, check_static: bool) -> None:
        screen, local_rect = self._capture_target()
        region = self._active_capture_mss_region()
        img_bgra = self._grab_own_screen_frame(region)
        if screen is None or img_bgra is None:
            self._schedule_next_monitor_tick()
            return

        small_gray = compute_small_gray_numpy(img_bgra)

        if (
            check_static
            and self.prev_small_gray is not None
            and small_gray.shape == self.prev_small_gray.shape
        ):
            diff = max_grid_diff_numpy(small_gray, self.prev_small_gray)
            if diff < PIXEL_DIFF_THRESHOLD:
                self._schedule_next_monitor_tick()
                return

        self.pipeline_busy = True
        self.pending_rescan = False
        self.watchdog.disarm()
        self.prev_small_gray = small_gray
        self._frame_bgra = img_bgra
        self._frame_region = region
        self._check_seq_on_complete = check_static

        self.job_id += 1
        current_job = self.job_id
        self.toolbar.set_stop_active(True)

        self.ocr_thread = OcrWorkerThread(
            self.ocr_engine,
            self.ocr_backend,
            img_bgra,
            self.lru_cache,
            job_id=current_job,
            dpi_scale=self._last_capture_dpr,
            offset_x=local_rect.x(),
            offset_y=local_rect.y(),
        )
        self.ocr_thread.blocks_ready.connect(self._on_ocr_blocks_ready)
        self.ocr_thread.finished.connect(self._on_ocr_thread_finished)
        self._track_thread(self.ocr_thread)
        self.ocr_thread.start()

    def _on_ocr_thread_finished(self):
        if self.ocr_thread is not None:
            self.ocr_thread.wait()
        if self.pending_rescan and not self.pipeline_busy and not self.is_hidden:
            self.pending_rescan = False
            self._trigger_capture_pipeline(check_static=False)

    def _finish_pipeline_cycle(self):
        self.pipeline_busy = False
        if self.monitor_interval_ms == 0:
            self.watchdog.disarm()
            self.toolbar.set_stop_active(False)
        else:
            self._arm_watchdog()
            self._schedule_next_monitor_tick()

        if self.pending_rescan and not self.is_hidden:
            self.pending_rescan = False
            QTimer.singleShot(40, lambda: self._trigger_capture_pipeline(check_static=False))
        elif self._retranslate_when_idle:
            self._retranslate_fallback_blocks()

    def _on_ocr_blocks_ready(self, blocks: List[OverlayBlock], signature: str, job_id: int):
        if job_id != self.job_id:
            return

        if not blocks:
            self.clear_all_plaques()
            self._finish_pipeline_cycle()
            return

        if self._check_seq_on_complete and self.prev_ocr_signature:
            if signature == self.prev_ocr_signature:
                self._finish_pipeline_cycle()
                return

        self.prev_ocr_signature = signature
        self.overlay_blocks = self._merge_with_persistent_blocks(blocks)
        self._refresh_overlays()
        if self.log_dialog.isVisible():
            self.log_dialog.refresh_view()

        pending_map: Dict[int, str] = {}
        for idx, b in enumerate(self.overlay_blocks):
            if b.is_pending:
                pending_map[idx] = b.orig_text

        if not pending_map:
            self._finish_pipeline_cycle()
            return

        self._start_translation(pending_map)

    def _start_translation(self, pending_map: Dict[int, str]) -> None:
        if self.trans_thread is not None and self.trans_thread.isRunning():
            self.trans_thread.stop()

        worker = NativeCT2TranslationWorker(pending_map, job_id=self.job_id)
        worker.batch_translated.connect(self._on_batch_translated)
        worker.batch_finished.connect(self._on_batch_finished)
        self._track_thread(worker)
        self.trans_thread = worker
        worker.start()

    def _on_model_loaded(self, ok: bool):
        if not ok:
            return
        self._retranslate_when_idle = True
        if not self.pipeline_busy:
            self._retranslate_fallback_blocks()

    def _retranslate_fallback_blocks(self):
        """Блоки, показанные без перевода, пока модель грузилась, переводятся заново."""
        self._retranslate_when_idle = False
        pending_map = {idx: b.orig_text for idx, b in enumerate(self.overlay_blocks) if b.is_fallback}
        if not pending_map:
            return
        log_event(f"Модель перевода готова: повторный перевод {len(pending_map)} блоков")
        self.pipeline_busy = True
        self._start_translation(pending_map)

    def _on_batch_translated(self, pairs: List[Tuple[int, str, str, bool]], job_id: int):
        if job_id != self.job_id:
            return
        for idx, orig_text, trans_text, is_final in pairs:
            if is_final:
                self.lru_cache.put(orig_text, trans_text)
            if 0 <= idx < len(self.overlay_blocks) and self.overlay_blocks[idx].orig_text == orig_text:
                block = self.overlay_blocks[idx]
                block.trans_text = trans_text
                block.is_pending = False
                block.is_fallback = not is_final
        self._refresh_overlays()

    def _on_batch_finished(self, job_id: int):
        if job_id == self.job_id:
            self._finish_pipeline_cycle()
        if self.log_dialog.isVisible():
            self.log_dialog.refresh_view()

    # --------------------------------------------------------------------------
    # ГЛОБАЛЬНЫЕ КЛАВИШИ: RegisterHotKey, ЗАПАСНОЙ ОПРОС GetAsyncKeyState 25 мс
    # --------------------------------------------------------------------------
    def _register_global_hotkeys(self):
        """Один канал на клавишу. RegisterHotKey и опрос вместе прячут окно и сразу открывают его снова."""
        self._hotkeys_registered = False
        hwnd = int(self.winId())
        pairs = ((HOTKEY_ID_TOGGLE, self.hotkey_toggle), (HOTKEY_ID_SNIP, self.hotkey_snip))
        names = f"{self.hotkey_toggle.text} и {self.hotkey_snip.text}"
        try:
            ok = [bool(user32.RegisterHotKey(hwnd, hk_id, hk.modifiers | MOD_NOREPEAT, hk.vk)) for hk_id, hk in pairs]
            if all(ok):
                self._hotkeys_registered = True
                log_event(f"Глобальные {names} зарегистрированы через RegisterHotKey")
                return
            for (hk_id, _hk), registered in zip(pairs, ok):
                if registered:
                    user32.UnregisterHotKey(hwnd, hk_id)
            log_event(
                f"RegisterHotKey {names} недоступен: сочетание занято другой программой. Работает опрос клавиатуры",
                "WARN",
            )
        except Exception as exc:
            log_event(f"RegisterHotKey {names}: {exc}. Работает опрос клавиатуры", "WARN")

    def _unregister_global_hotkeys(self):
        if not self._hotkeys_registered:
            return
        hwnd = int(self.winId())
        user32.UnregisterHotKey(hwnd, HOTKEY_ID_TOGGLE)
        user32.UnregisterHotKey(hwnd, HOTKEY_ID_SNIP)
        self._hotkeys_registered = False

    def _set_hotkeys_suspended(self, suspended: bool):
        """Пока поле в настройках записывает сочетание, нажатие не должно прятать окна."""
        if suspended == self._hotkeys_suspended:
            return
        self._hotkeys_suspended = suspended
        if suspended:
            self._unregister_global_hotkeys()
            return
        self._register_global_hotkeys()
        if not self._hotkeys_registered:
            self.font_popup.show_hotkey_error(
                "Сочетание занято другой программой. Оно всё равно работает через опрос клавиатуры, "
                "но нажатие получит и активное окно."
            )

    def _on_hotkeys_changed(self):
        self.hotkey_toggle = parse_hotkey(self.font_cfg.hotkey_toggle)
        self.hotkey_snip = parse_hotkey(self.font_cfg.hotkey_snip)
        self._apply_hotkey_labels()
        if not self._hotkeys_suspended:
            self._unregister_global_hotkeys()
            self._register_global_hotkeys()
        log_event(f"Глобальные клавиши изменены: {self.hotkey_toggle.text} — скрыть, {self.hotkey_snip.text} — область")

    def nativeEvent(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    if msg.wParam == HOTKEY_ID_TOGGLE:
                        self.toggle_visibility()
                        return True, 0
                    elif msg.wParam == HOTKEY_ID_SNIP:
                        self.start_snipping_mode()
                        return True, 0
        except Exception:
            pass
        # ВАЖНО: не вызываем super().nativeEvent() — в PyQt6/Qt 6.11 базовый
        # QWidget::nativeEvent возвращает значение, на котором падает QtCore
        # (0xC000041D access violation в QtCore.pyd при показе окна).
        return False, 0

    def _init_win32_input_poller(self):
        self._prev_toggle_down = False
        self._prev_snip_down = False
        self._prev_esc_down = False

        self.input_poller = QTimer(self)
        self.input_poller.setInterval(25)
        self.input_poller.timeout.connect(self._poll_win32_input)
        self.input_poller.start()

    def _poll_win32_input(self):
        self._track_foreground_window()
        toggle_down = is_hotkey_down(self.hotkey_toggle, _key_down)
        snip_down = is_hotkey_down(self.hotkey_snip, _key_down)
        esc_down = _key_down(VK_ESCAPE)

        # Клавиши через опрос только если RegisterHotKey их не занял.
        # Иначе то же нажатие приходит и сообщением WM_HOTKEY, и опросом: окно прячется и сразу возвращается.
        if not self._hotkeys_registered and not self._hotkeys_suspended:
            if toggle_down and not self._prev_toggle_down:
                self.toggle_visibility()
            elif snip_down and not self._prev_snip_down:
                self.start_snipping_mode()

        # Esc отменяет выделение, даже если окно выделения не получило фокус клавиатуры.
        if esc_down and not self._prev_esc_down and self.snip_overlays:
            self._on_snip_cancelled()

        self._prev_toggle_down = toggle_down
        self._prev_snip_down = snip_down
        self._prev_esc_down = esc_down

    def emergency_shutdown(self):
        log_event(f"Полное завершение работы GhostTranslate v{APP_VERSION} (Кнопка [X])")
        if self.font_cfg.sound_enabled:
            play_shutdown_sound_sync()
        try:
            self._unregister_global_hotkeys()
            self.monitor_timer.stop()
            self.watchdog.stop()
            self.input_poller.stop()
            self._cancel_snipping()
            for overlay in self.overlays:
                overlay.hide()
            self.font_popup.hide()
            self.mini_pill.hide()
            self.tray.hide()
            if self.trans_thread and self.trans_thread.isRunning():
                self.trans_thread.stop()
            self.sct.close()
        except Exception:
            pass
        os._exit(0)
